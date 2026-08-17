# kerno/execution/engine.py
"""
ExecutionEngine — the single choke point for code execution.

Invariant K-001 (from the deep audit):

    No agent, loop, plugin, skill, checkpoint, or subsystem may execute
    code except through ExecutionEngine.execute().

The engine wraps a KernelRuntime (or any Executor) and applies, in order:

    1. Authorization — capability broker check (K-008): the execution may
                       declare required capabilities; if the broker does
                       not hold an active grant, the execution is refused.
    2. Policy        — static allowlist check for agent-origin code
    3. Execution     — delegation to the underlying kernel executor
    4. Audit         — an immutable ExecutionRecord per attempt, keyed by
                       a monotonic execution_id (universal correlation key)
    5. Event log     — an immutable, causal event stream per attempt

Authorization/policy violations never touch the kernel: the agent loop
receives a synthetic CellOutput error (ename="AllowListViolation" or
"CapabilityViolation") and can recover, exactly like any other failed cell.

Origin model (F-008):
    ORIGIN_AGENT   — LLM-generated code. Authorization + policy enforced.
    ORIGIN_RUNTIME — trusted host code (setup, comms, plugins).
                     Skips both. Never use for LLM-generated text.

Authority boundary (F-008):
    The public execute()/stream_execute()/execute_silent() APIs accept ONLY
    ORIGIN_AGENT — an agent-facing caller can never manufacture runtime
    authority. Trusted host code obtains ORIGIN_RUNTIME semantics through
    the dedicated runtime_execute()/runtime_stream_execute() APIs, which
    are never exposed to agent code (e.g. MaterializationExecutor wraps
    runtime_execute()).
"""

from __future__ import annotations

import hashlib
import inspect
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from kerno.action import Action, ActionStateMachine, ActionStatus
from kerno.approval import ApprovalGate, ApprovalRequest, ApprovalDecision
from kerno.effects import EffectLedger, EFFECT_FILESYSTEM_WRITE
from kerno.provenance import KIND_EXECUTION, ProvenanceGraph
from kerno.security.allowlist import AllowList, AllowListViolation
from kerno.security.capabilities import (
    CAP_HUMAN_APPROVAL, CapabilityBroker, CapabilityViolation,
)
from kerno.telemetry.logger   import get_logger
from kerno.telemetry.metrics  import get_metrics
from kerno.telemetry.tracer   import get_tracer
from kerno.types import CellError, CellOutput

log = get_logger("kerno.execution")

# Origin constants
ORIGIN_AGENT   = "agent"     # LLM-generated code → policy enforced
ORIGIN_RUNTIME = "runtime"   # trusted host code → policy skipped

# Event types (the canonical event stream — audit #28, #79)
EVT_EXECUTION_REQUESTED = "EXECUTION_REQUESTED"
EVT_CAPABILITY_DENIED   = "CAPABILITY_DENIED"
EVT_POLICY_BLOCKED      = "POLICY_BLOCKED"
EVT_EXECUTION_STARTED   = "EXECUTION_STARTED"
EVT_EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
EVT_APPROVAL_DENIED     = "APPROVAL_DENIED"
EVT_EFFECT_VIOLATION    = "EFFECT_VIOLATION"


@dataclass(frozen=True)
class ExecutionRecord:
    """
    Immutable audit record for one execution attempt.

    This is the minimal form of the execution record from the audit:
    a stable identity that correlates events, telemetry, notebook cells,
    and provenance for a single execution.
    """

    execution_id:  str                 # universal correlation key
    sequence:      int                 # monotonic per-engine sequence number
    origin:        str                 # "agent" | "runtime"
    allowed:       bool                # False → blocked by policy
    code_preview:  str = ""            # first 80 chars of the code
    rule:          Optional[str] = None  # policy rule that fired (if blocked)
    capabilities:  tuple[str, ...] = ()  # capabilities required by the attempt
    action_id:     Optional[str] = None  # correlated action (audit #46)
    effects:       tuple[str, ...] = ()  # declared side effects (audit #92)
    duration_ms:   float = 0.0         # wall time inside the kernel
    had_error:     bool = False        # kernel reported an error
    timestamp:     float = field(default_factory=time.time)


@dataclass(frozen=True)
class ExecutionEvent:
    """
    One immutable event in the execution event stream.

    A causal chain: events carry their execution_id and a monotonic
    sequence, so the stream can be replayed and audited.
    """

    event_id:      str
    event_type:    str
    execution_id:  str
    sequence:      int
    parent_event_id: Optional[str] = None   # causal chain within the execution
    timestamp:     float = field(default_factory=time.time)
    payload:       dict  = field(default_factory=dict)


@dataclass
class _TxContext:
    allowed:            bool
    execution_id:       str
    sequence:           int
    code_preview:       str
    caps:               frozenset[str]
    declared_effects:   frozenset[str]
    action_sm:          Optional[ActionStateMachine]
    attrs:              dict
    denial_output:      Optional[CellOutput] = None
    denial_error_tuple: Optional[tuple[str, str]] = None


class ExecutionEngine:
    """
    Policy-enforcing executor that delegates to a KernelRuntime.

    Satisfies the Executor protocol (execute, execute_silent, namespace,
    is_alive), so every loop strategy can be constructed with the engine
    instead of the raw kernel — making the policy boundary universal.
    """

    def __init__(
        self,
        kernel:              object,
        allowlist:           Optional[AllowList] = None,
        broker:              Optional[CapabilityBroker] = None,
        default_capabilities: frozenset[str] = frozenset(),
        provenance:          Optional[ProvenanceGraph] = None,
        redactor:            Optional["callable"] = None,
        redact_outputs:      bool = True,
        effect_ledger:       Optional[EffectLedger] = None,
        approval_gate:       Optional[ApprovalGate] = None,
    ):
        self._kernel               = kernel
        self._allowlist            = allowlist
        self._broker               = broker
        self._default_capabilities = frozenset(default_capabilities)
        self._provenance           = provenance
        self._redactor             = redactor
        self._redact_outputs       = redact_outputs
        self._effect_ledger        = effect_ledger
        self._approval_gate        = approval_gate
        self._records:  list[ExecutionRecord] = []
        self._events:   list[ExecutionEvent]  = []
        self._sequence  = 0
        self._event_seq = 0
        self._sequence_lock = threading.Lock()
        self._event_lock    = threading.Lock()
        self._last_event: dict[str, str] = {}   # execution_id → last event_id
        self._cancel_support: Optional[bool] = None
        self._tracer    = get_tracer()
        self._metrics   = get_metrics()

    # ── Redaction (audit #68): Execution → Observation → Redaction → Store ────

    def _redact(self, text: str) -> str:
        if self._redactor is None or not text:
            return text
        return self._redactor(text)

    def _redact_output(self, output: CellOutput) -> CellOutput:
        """
        Audit #68 (completeness): a secret printed by an agent cell must
        never reach the LLM's next prompt, the notebook projection, or
        session persistence. When a redactor is configured, agent-origin
        outputs (stdout/stderr/result/display text) are scrubbed before
        the cell result is returned to the loop.
        """
        if self._redactor is None or not self._redact_outputs:
            return output
        output.stdout = self._redact(output.stdout)
        output.stderr = self._redact(output.stderr)
        if output.result:
            output.result = self._redact(output.result)
        for display in output.displays:
            if "html" in display:
                display["html"] = self._redact(display["html"])
            if "json" in display:
                display["json"] = self._redact(display["json"])
        return output

    # ── Policy ─────────────────────────────────────────────────────────────────

    def check(self, code: str) -> None:
        """
        Check code against the policy without executing it.

        Raises AllowListViolation if the code is not permitted.
        """
        if self._allowlist is not None:
            self._allowlist.check(code)

    def require_capabilities(
        self,
        capabilities: frozenset[str],
        subject:      str = "",
    ) -> None:
        """
        Check that every capability holds an active broker grant.

        Raises CapabilityViolation on the first missing grant.
        """
        if self._broker is None:
            return
        for name in capabilities:
            self._broker.require(name, subject=subject)

    # ── Execution (the choke point) ────────────────────────────────────────────

    def _prepare_transaction(
        self,
        code:                 str,
        origin:               str,
        capabilities:         Optional[frozenset[str]],
        subject:              str,
        action:               Optional[Action],
        effects:              Optional[frozenset[str]],
        approval_description: str,
        cancel_event:         Optional[object],
        silent:               bool,
    ) -> _TxContext:
        with self._sequence_lock:
            self._sequence += 1
            execution_seq   = self._sequence
            execution_id    = "exec_{:08d}".format(execution_seq)

        code_preview     = self._redact(code[:80].replace("\n", " "))
        caps             = (
            self._default_capabilities if capabilities is None
            else frozenset(capabilities)
        )
        declared_effects = frozenset(effects or ())
        action_sm        = ActionStateMachine(action) if action is not None else None
        if action_sm is not None:
            action_sm.transition(ActionStatus.AUTHORIZING, reason="engine authorization")

        attrs = {
            "execution.id":     execution_id,
            "execution.origin": origin,
            "code.preview":     code_preview,
            "cell.silent":      silent,
            "execution.caps":   ",".join(sorted(caps)) if caps else "",
            "execution.action": action.action_id if action else "",
        }

        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]
        self._record_provenance(
            execution_id = execution_id,
            origin       = origin,
            code_hash    = code_hash,
        )
        self._emit(EVT_EXECUTION_REQUESTED, execution_id, origin=origin,
                   code_hash=code_hash,
                   action_id=action.action_id if action else None,
                   capabilities=sorted(caps) if caps else [])

        # ── 1. Authorization (capability broker) ─────────────────────────
        if origin == ORIGIN_AGENT and self._broker is not None and caps:
            try:
                self._require_all(caps, subject)
            except CapabilityViolation as exc:
                denial = self._deny(
                    execution_id = execution_id,
                    origin       = origin,
                    code_preview = code_preview,
                    rule         = "capability:" + exc.name,
                    ename        = "CapabilityViolation",
                    evalue       = str(exc),
                    caps         = caps,
                    action_sm    = action_sm,
                    event_type   = EVT_CAPABILITY_DENIED,
                    event_payload = {"capability": exc.name, "subject": exc.subject},
                    subject      = subject,
                )
                return _TxContext(
                    allowed            = False,
                    execution_id       = execution_id,
                    sequence           = execution_seq,
                    code_preview       = code_preview,
                    caps               = caps,
                    declared_effects   = declared_effects,
                    action_sm          = action_sm,
                    attrs              = attrs,
                    denial_output      = denial,
                    denial_error_tuple = ("error", f"CapabilityViolation: {str(exc)}"),
                )

        # ── 1b. Human approval (audit #90) — fail closed ─────────────────
        if origin == ORIGIN_AGENT and CAP_HUMAN_APPROVAL in caps:
            if self._approval_gate is None:
                denial = self._deny(
                    execution_id = execution_id,
                    origin       = origin,
                    code_preview = code_preview,
                    rule         = "approval:no_gate",
                    ename        = "ApprovalDenied",
                    evalue       = "execution requires human.approval but no ApprovalGate is installed (fail closed)",
                    caps         = caps,
                    action_sm    = action_sm,
                    event_type   = EVT_APPROVAL_DENIED,
                    event_payload = {"reason": "no_gate"},
                    subject      = subject,
                )
                return _TxContext(
                    allowed            = False,
                    execution_id       = execution_id,
                    sequence           = execution_seq,
                    code_preview       = code_preview,
                    caps               = caps,
                    declared_effects   = declared_effects,
                    action_sm          = action_sm,
                    attrs              = attrs,
                    denial_output      = denial,
                    denial_error_tuple = ("error", "ApprovalDenied: no ApprovalGate installed"),
                )
            decision = self._approval_gate.request(ApprovalRequest(
                description  = approval_description or code_preview,
                subject      = subject,
                capabilities = caps,
                code_preview = code_preview,
                execution_id = execution_id,
            ))
            if decision is not ApprovalDecision.APPROVED:
                denial = self._deny(
                    execution_id = execution_id,
                    origin       = origin,
                    code_preview = code_preview,
                    rule         = "approval:denied",
                    ename        = "ApprovalDenied",
                    evalue       = "human approval denied",
                    caps         = caps,
                    action_sm    = action_sm,
                    event_type   = EVT_APPROVAL_DENIED,
                    event_payload = {"reason": "denied"},
                    subject      = subject,
                )
                return _TxContext(
                    allowed            = False,
                    execution_id       = execution_id,
                    sequence           = execution_seq,
                    code_preview       = code_preview,
                    caps               = caps,
                    declared_effects   = declared_effects,
                    action_sm          = action_sm,
                    attrs              = attrs,
                    denial_output      = denial,
                    denial_error_tuple = ("error", "ApprovalDenied: human approval denied"),
                )

        # ── 1c. Cancellation ─────────────────────────────────────────────
        if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
            self._record(
                execution_id = execution_id,
                sequence     = execution_seq,
                origin       = origin,
                allowed      = True,
                code_preview = code_preview,
                capabilities = caps,
                action_id    = action.action_id if action else None,
                had_error    = True,
            )
            self._emit("EXECUTION_CANCELLED", execution_id,
                       action_id=action.action_id if action else None)
            denial = CellOutput(
                error        = CellError(ename="KernelInterrupted", evalue="execution cancelled before start"),
                execution_id = execution_id,
            )
            return _TxContext(
                allowed            = False,
                execution_id       = execution_id,
                sequence           = execution_seq,
                code_preview       = code_preview,
                caps               = caps,
                declared_effects   = declared_effects,
                action_sm          = action_sm,
                attrs              = attrs,
                denial_output      = denial,
                denial_error_tuple = ("error", "KernelInterrupted: execution cancelled before start"),
            )

        # ── 2. Policy (allowlist) ─────────────────────────────────────────
        if origin == ORIGIN_AGENT and self._allowlist is not None:
            try:
                self._allowlist.check(code)
            except AllowListViolation as exc:
                denial = self._deny(
                    execution_id = execution_id,
                    origin       = origin,
                    code_preview = code_preview,
                    rule         = exc.rule,
                    ename        = "AllowListViolation",
                    evalue       = str(exc),
                    caps         = caps,
                    action_sm    = action_sm,
                    event_type   = EVT_POLICY_BLOCKED,
                    event_payload = {"rule": exc.rule},
                    subject      = subject,
                )
                return _TxContext(
                    allowed            = False,
                    execution_id       = execution_id,
                    sequence           = execution_seq,
                    code_preview       = code_preview,
                    caps               = caps,
                    declared_effects   = declared_effects,
                    action_sm          = action_sm,
                    attrs              = attrs,
                    denial_output      = denial,
                    denial_error_tuple = ("error", f"AllowListViolation: {str(exc)}"),
                )

        # ── 3. Effects: declare BEFORE execution ─────────────────────────
        if self._effect_ledger is not None:
            self._effect_ledger.declare(execution_id, declared_effects)

        # ── 4. State transition to running ───────────────────────────────
        if action_sm is not None:
            action_sm.transition(ActionStatus.QUEUED, reason="queued")
            action_sm.transition(ActionStatus.RUNNING, reason="running")
        self._emit(EVT_EXECUTION_STARTED, execution_id,
                   action_id=action.action_id if action else None)

        return _TxContext(
            allowed          = True,
            execution_id     = execution_id,
            sequence         = execution_seq,
            code_preview     = code_preview,
            caps             = caps,
            declared_effects = declared_effects,
            action_sm        = action_sm,
            attrs            = attrs,
        )

    def _finalize_transaction(
        self,
        tx:        _TxContext,
        start:     float,
        had_error: bool,
        origin:    str,
        action_id: Optional[str],
    ) -> float:
        dur_ms = (time.monotonic() - start) * 1000

        # 1. Observe side effects (resilient)
        if self._effect_ledger is not None:
            try:
                violations = self._effect_ledger.observe(tx.execution_id)
                if violations:
                    paths = sorted(p for v in violations for p in v.observed)
                    self._emit(EVT_EFFECT_VIOLATION, tx.execution_id,
                               action_id=action_id, undeclared_paths=paths)
            except Exception as exc:
                log.warning("Effect observation error", error=str(exc))

        # 2. Transition action state machine to terminal state (resilient)
        if tx.action_sm is not None:
            try:
                tx.action_sm.transition(
                    ActionStatus.SUCCESS if not had_error else ActionStatus.FAILURE,
                    reason="execution " + ("ok" if not had_error else "error"),
                )
            except Exception as exc:
                log.warning("Action state machine transition error", error=str(exc))

        # 3. Record audit trail (resilient)
        try:
            self._record(
                execution_id = tx.execution_id,
                sequence     = tx.sequence,
                origin       = origin,
                allowed      = True,
                code_preview = tx.code_preview,
                capabilities = tx.caps,
                action_id    = action_id,
                effects      = tx.declared_effects,
                duration_ms  = dur_ms,
                had_error    = had_error,
            )
        except Exception as exc:
            log.warning("Audit record error", error=str(exc))

        # 4. Emit terminal event (guaranteed)
        self._emit(EVT_EXECUTION_COMPLETED, tx.execution_id,
                   action_id=action_id, had_error=had_error, duration_ms=round(dur_ms, 2))
        return dur_ms

    def execute(
        self,
        code:                 str,
        timeout:              float = 120.0,
        silent:               bool  = False,
        origin:               str   = ORIGIN_AGENT,
        capabilities:         Optional[frozenset[str]] = None,
        subject:              str   = "",
        action:               Optional[Action] = None,
        effects:              Optional[frozenset[str]] = None,
        approval_description: str   = "",
        cancel_event:         Optional[object] = None,
    ) -> CellOutput:
        """
        Execute code through the authorization + policy boundary.

        F-008 authority boundary: ONLY ORIGIN_AGENT is selectable here.
        Trusted host code must use runtime_execute() — an agent-facing
        caller can never manufacture ORIGIN_RUNTIME through this API.
        """
        if origin != ORIGIN_AGENT:
            raise ValueError(
                "origin={!r} is not selectable through execute(); only "
                "ORIGIN_AGENT is permitted. Trusted host code must use "
                "runtime_execute().".format(origin)
            )
        return self._execute(
            code=code, timeout=timeout, silent=silent, origin=ORIGIN_AGENT,
            capabilities=capabilities, subject=subject, action=action,
            effects=effects, approval_description=approval_description,
            cancel_event=cancel_event,
        )

    def runtime_execute(
        self,
        code:                 str,
        timeout:              float = 120.0,
        silent:               bool  = False,
        capabilities:         Optional[frozenset[str]] = None,
        subject:              str   = "",
        action:               Optional[Action] = None,
        effects:              Optional[frozenset[str]] = None,
        approval_description: str   = "",
        cancel_event:         Optional[object] = None,
    ) -> CellOutput:
        """
        Trusted host-code execution (F-008) — origin=ORIGIN_RUNTIME.

        This is the ONLY way to obtain runtime authority: the transaction
        lifecycle (audit records, event stream, effects, budget,
        cancellation, finalization) still applies, but agent capability /
        allowlist policy is skipped because the caller is trusted
        infrastructure (setup, comms, materialization). This API is never
        exposed to agent code.
        """
        return self._execute(
            code=code, timeout=timeout, silent=silent, origin=ORIGIN_RUNTIME,
            capabilities=capabilities, subject=subject, action=action,
            effects=effects, approval_description=approval_description,
            cancel_event=cancel_event,
        )

    def _execute(
        self,
        code:                 str,
        timeout:              float,
        silent:               bool,
        origin:               str,
        capabilities:         Optional[frozenset[str]],
        subject:              str,
        action:               Optional[Action],
        effects:              Optional[frozenset[str]],
        approval_description: str,
        cancel_event:         Optional[object],
    ) -> CellOutput:
        tx = self._prepare_transaction(
            code=code, origin=origin, capabilities=capabilities, subject=subject,
            action=action, effects=effects, approval_description=approval_description,
            cancel_event=cancel_event, silent=silent,
        )
        if not tx.allowed:
            return tx.denial_output

        action_id = action.action_id if action else None

        with self._tracer.span("execution.attempt", tx.attrs):
            start     = time.monotonic()
            had_error = False
            try:
                exec_kwargs = {}
                if cancel_event is not None and self._supports_cancel():
                    exec_kwargs["cancel_event"] = cancel_event
                output = self._kernel.execute(
                    code, timeout=timeout, silent=silent, **exec_kwargs
                )
                output.execution_id = tx.execution_id
                if origin == ORIGIN_AGENT:
                    output = self._redact_output(output)
                had_error = output.has_error
                return output
            except Exception:
                had_error = True
                raise
            finally:
                self._finalize_transaction(tx, start, had_error, origin, action_id)

    def execute_silent(
        self,
        code:               str,
        timeout:            float = 15.0,
        origin:             str   = ORIGIN_AGENT,
        capabilities:       Optional[frozenset[str]] = None,
        subject:            str   = "",
        action:             Optional[Action] = None,
        effects:            Optional[frozenset[str]] = None,
        approval_description: str = "",
    ) -> str:
        """Policy-checked silent execution (used by loops for probes)."""
        output = self.execute(
            code, timeout=timeout, silent=True,
            origin=origin, capabilities=capabilities, subject=subject,
            action=action, effects=effects,
            approval_description=approval_description,
        )
        return output.stdout.strip()

    def stream_execute(
        self,
        code:                 str,
        timeout:              float = 300.0,
        origin:               str   = ORIGIN_AGENT,
        capabilities:         Optional[frozenset[str]] = None,
        subject:              str   = "",
        action:               Optional[Action] = None,
        effects:              Optional[frozenset[str]] = None,
        approval_description: str   = "",
        cancel_event:         Optional[object] = None,
    ):
        """
        Stream execution chunks through the full authorization + policy boundary (K-001).

        Guarantees complete lifecycle parity with execute(): capability check,
        approval gate, allowlist inspection, effect declaration/observation,
        and guaranteed finally lifecycle completion.

        F-008 authority boundary: ONLY ORIGIN_AGENT is selectable; trusted
        host code must use runtime_stream_execute().
        """
        if origin != ORIGIN_AGENT:
            raise ValueError(
                "origin={!r} is not selectable through stream_execute(); only "
                "ORIGIN_AGENT is permitted. Trusted host code must use "
                "runtime_stream_execute().".format(origin)
            )
        yield from self._stream_execute(
            code=code, timeout=timeout, origin=ORIGIN_AGENT,
            capabilities=capabilities, subject=subject, action=action,
            effects=effects, approval_description=approval_description,
            cancel_event=cancel_event,
        )

    def runtime_stream_execute(
        self,
        code:                 str,
        timeout:              float = 300.0,
        capabilities:         Optional[frozenset[str]] = None,
        subject:              str   = "",
        action:               Optional[Action] = None,
        effects:              Optional[frozenset[str]] = None,
        approval_description: str   = "",
        cancel_event:         Optional[object] = None,
    ):
        """
        Trusted host-code streaming (F-008) — origin=ORIGIN_RUNTIME.

        Streaming counterpart of runtime_execute(): full transaction
        lifecycle, agent policy skipped because the caller is trusted
        infrastructure. Never exposed to agent code.
        """
        yield from self._stream_execute(
            code=code, timeout=timeout, origin=ORIGIN_RUNTIME,
            capabilities=capabilities, subject=subject, action=action,
            effects=effects, approval_description=approval_description,
            cancel_event=cancel_event,
        )

    def _stream_execute(
        self,
        code:                 str,
        timeout:              float,
        origin:               str,
        capabilities:         Optional[frozenset[str]],
        subject:              str,
        action:               Optional[Action],
        effects:              Optional[frozenset[str]],
        approval_description: str,
        cancel_event:         Optional[object],
    ):
        tx = self._prepare_transaction(
            code=code, origin=origin, capabilities=capabilities, subject=subject,
            action=action, effects=effects, approval_description=approval_description,
            cancel_event=cancel_event, silent=False,
        )
        if not tx.allowed:
            yield tx.denial_error_tuple
            return

        action_id = action.action_id if action else None
        start     = time.monotonic()
        had_error = False

        try:
            if hasattr(self._kernel, "stream_execute"):
                for kind, text in self._kernel.stream_execute(code, timeout=timeout, cancel_event=cancel_event):
                    if kind == "error":
                        had_error = True
                    if origin == ORIGIN_AGENT and self._redact_outputs:
                        text = self._redact(text)
                    yield (kind, text)
            else:
                exec_kwargs = {}
                if cancel_event is not None and self._supports_cancel():
                    exec_kwargs["cancel_event"] = cancel_event
                out = self._kernel.execute(code, timeout=timeout, silent=False, **exec_kwargs)
                out.execution_id = tx.execution_id
                if origin == ORIGIN_AGENT:
                    out = self._redact_output(out)
                had_error = out.has_error
                if out.stdout:
                    yield ("stdout", out.stdout)
                if out.stderr:
                    yield ("stderr", out.stderr)
                if out.has_error:
                    yield ("error", f"{out.error.ename}: {out.error.evalue}")
        except Exception as exc:
            had_error = True
            yield ("error", f"StreamExecutionError: {str(exc)}")
        finally:
            self._finalize_transaction(tx, start, had_error, origin, action_id)

    # ── Internals ──────────────────────────────────────────────────────────────

    def _require_all(self, capabilities: frozenset[str], subject: str) -> None:
        for name in capabilities:
            self._broker.require(name, subject=subject)

    def _supports_cancel(self) -> bool:
        """Whether the wrapped executor accepts cancel_event (cached)."""
        if self._cancel_support is None:
            try:
                params = inspect.signature(
                    self._kernel.execute
                ).parameters.values()
                self._cancel_support = any(
                    p.name == "cancel_event"
                    or p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in params
                )
            except (TypeError, ValueError):
                self._cancel_support = False
        return self._cancel_support

    def _deny(
        self,
        execution_id: str,
        origin:       str,
        code_preview: str,
        rule:         str,
        ename:        str,
        evalue:       str,
        caps:         frozenset[str],
        event_type:   str,
        event_payload: dict,
        action_sm:    Optional[ActionStateMachine] = None,
        subject:      str = "",
    ) -> CellOutput:
        if action_sm is not None:
            action_sm.transition(ActionStatus.REJECTED, reason=rule)
        self._record(
            execution_id = execution_id,
            origin       = origin,
            allowed      = False,
            code_preview = code_preview,
            rule         = rule,
            capabilities = caps,
            action_id    = (
                action_sm.action.action_id if action_sm is not None else None
            ),
        )
        self._emit(event_type, execution_id,
                   action_id=(
                       action_sm.action.action_id
                       if action_sm is not None else None
                   ),
                   **event_payload)
        # Observability (P2.13): every security rejection identifies the
        # execution, subject, origin, capability, and decision reason.
        # Secrets are never included — code_preview is redacted upstream.
        log.warning(
            "Execution blocked by policy",
            execution_id = execution_id,
            origin       = origin,
            subject      = subject,
            capabilities = ",".join(sorted(caps)) if caps else "",
            rule         = rule,
            code_preview = code_preview,
        )
        # Redact the error value too: policy messages can embed matched
        # code fragments that contain secrets.
        return CellOutput(
            error=CellError(
                ename  = ename,
                evalue = self._redact(evalue),
            ),
            execution_id = execution_id,
        )

    def _record_provenance(
        self,
        execution_id: str,
        origin:       str,
        code_hash:    str,
    ) -> None:
        """Record an execution node in the provenance graph (if attached)."""
        if self._provenance is None:
            return
        self._provenance.add_node(
            execution_id,
            KIND_EXECUTION,
            attrs={
                "origin":    origin,
                "code_hash": code_hash,
            },
        )

    def _record(
        self,
        execution_id: str,
        origin:       str,
        allowed:      bool,
        code_preview: str,
        sequence:     Optional[int] = None,
        rule:         Optional[str] = None,
        capabilities: frozenset[str] = frozenset(),
        action_id:    Optional[str] = None,
        effects:      frozenset[str] = frozenset(),
        duration_ms:  float = 0.0,
        had_error:    bool  = False,
    ) -> None:
        seq = sequence if sequence is not None else self._sequence
        with self._sequence_lock:
            self._records.append(ExecutionRecord(
                execution_id = execution_id,
                sequence     = seq,
                origin       = origin,
                allowed      = allowed,
                code_preview = code_preview,
                rule         = rule,
                capabilities = tuple(sorted(capabilities)),
                action_id    = action_id,
                effects      = tuple(sorted(effects)),
                duration_ms  = duration_ms,
                had_error    = had_error,
            ))
        # Audit #80: project the record into the metrics stream.
        self._metrics.record_execution(
            allowed    = allowed,
            origin     = origin,
            rule       = rule or "",
        )

    def _emit(self, event_type: str, execution_id: str, **payload) -> None:
        with self._event_lock:
            self._event_seq += 1
            event_id = "evt_{:08d}".format(self._event_seq)
            # Causal chain: link each event to the previous event of the SAME
            # execution (audit #79/#103) — replay reconstructs the exact order.
            parent = self._last_event.get(execution_id)
            self._last_event[execution_id] = event_id
            self._events.append(ExecutionEvent(
                event_id        = event_id,
                event_type      = event_type,
                execution_id    = execution_id,
                sequence        = self._event_seq,
                parent_event_id = parent,
                payload         = dict(payload),
            ))

    def _next_execution_id(self) -> str:
        with self._sequence_lock:
            self._sequence += 1
            return "exec_{:08d}".format(self._sequence)

    # ── Audit / event stream views ─────────────────────────────────────────────

    @property
    def records(self) -> tuple[ExecutionRecord, ...]:
        """Immutable view of the audit trail."""
        return tuple(self._records)

    @property
    def sequence(self) -> int:
        """Highest execution sequence number (checkpoint correlation, K-007)."""
        return self._sequence

    @property
    def event_sequence(self) -> int:
        """Highest event sequence number (checkpoint correlation, K-007)."""
        return self._event_seq

    @property
    def events(self) -> tuple[ExecutionEvent, ...]:
        """Immutable view of the event stream."""
        return tuple(self._events)

    @property
    def blocked_count(self) -> int:
        return sum(1 for r in self._records if not r.allowed)

    @property
    def executed_count(self) -> int:
        return sum(1 for r in self._records if r.allowed)

    # ── Executor protocol delegation ───────────────────────────────────────────

    @property
    def namespace(self) -> str:
        return self._kernel.namespace

    @property
    def is_alive(self) -> bool:
        return self._kernel.is_alive

    @property
    def raw_kernel(self) -> object:
        """
        The underlying kernel. Intended for trusted infrastructure only
        (comms, setup) — never for agent-origin code.
        """
        return self._kernel
