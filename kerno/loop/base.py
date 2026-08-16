"""
BaseLoop with telemetry, memory, and plugin integration.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from kerno.context.builder    import PromptBuilder
from kerno.context.compressor import HistoryCompressor
from kerno.errors.recovery    import RecoveryStrategy
from kerno.kernel.runtime     import KernelRuntime
from kerno.memory.store       import MemoryStore
from kerno.plugins.registry   import PluginRegistry
from kerno.telemetry.logger   import get_logger
from kerno.telemetry.metrics  import get_metrics
from kerno.telemetry.tracer   import get_tracer
from kerno.types import (
    Cell, CellOutput, LLMCallable, Message,
    SessionResult, SessionStatus,
)

log     = get_logger("kerno.loop")
tracer  = get_tracer()
metrics = get_metrics()

COMPLETE_SIGNAL  = "# TASK_COMPLETE"
CHECKPOINT_EVERY = 10


class StuckError(RuntimeError):
    """Raised when the agent repeats the same error class N times."""


class BaseLoop(ABC):

    def __init__(
        self,
        kernel:                 KernelRuntime,
        llm:                    LLMCallable,
        max_cells:              int   = 50,
        cell_timeout:           float = 120.0,
        compress_after:         int   = 20,
        max_consecutive_errors: int   = 4,
        memory:                 Optional[MemoryStore] = None,
        plugins:                Optional[PluginRegistry] = None,
        verbose:                bool  = False,
        auto_restart:           bool  = False,
    ):
        self.kernel                  = kernel
        self.llm                     = llm
        self.max_cells               = max_cells
        self.cell_timeout            = cell_timeout
        self.compress_after          = compress_after
        self.max_consecutive_errors  = max_consecutive_errors
        self.memory                  = memory
        self.plugins                 = plugins
        self.verbose                 = verbose
        self.auto_restart            = auto_restart

        self._builder    = PromptBuilder()
        self._compressor = HistoryCompressor(llm)
        self._recovery   = RecoveryStrategy()

        self._history:     list[Cell] = []
        self._summary:     str        = ""
        self._task:        str        = ""
        self._session_id:  str        = str(uuid.uuid4())
        self._loop_type:   str        = self.__class__.__name__

        self._consecutive_errors:   int           = 0
        self._pending_recovery_hint: Optional[str] = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(
        self,
        task:            str,
        *,
        initial_history: Optional[list] = None,
        initial_summary: str = "",
        cancel_token:    Optional[object] = None,
        capture:         Optional[object] = None,
    ) -> SessionResult:
        """
        Run the agent loop on a task.

        Args:
            task:             Natural language task description
            initial_history:  Prior executed cells to continue from
                              (session resume, audit #35/#36)
            initial_summary:  Prior context summary to seed the prompt
            cancel_token:     CancellationToken (audit #83) — checked
                              before every cell; the session ends with
                              INTERRUPTED status when cancelled.
            capture:          CapturePoint (audit #59, K-007) — after
                              each completed cell, a host-side checkpoint
                              is recorded bound to the engine's event
                              sequence + kernel generation (no kernel code).
        """
        self._task               = task
        self._history            = list(initial_history) if initial_history else []
        self._summary            = initial_summary or ""
        self._consecutive_errors = 0
        started_at               = time.time()

        Path("_checkpoints").mkdir(exist_ok=True)

        # Inject relevant memories into context (unless resuming with one)
        if self.memory and not self._summary:
            self._summary = self._retrieve_relevant_memories(task)

        ctx  = tracer.start_trace(f"session.{self._loop_type}")
        status = SessionStatus.MAX_CELLS

        log.info(
            "Session started",
            session_id = self._session_id,
            loop       = self._loop_type,
            task       = task[:100],
        )

        # Dispatch plugin lifecycle
        if self.plugins:
            self.plugins.on_session_start(task, self._session_id)

        with tracer.span(
            "session.run",
            {
                "session.id":   self._session_id,
                "loop.type":    self._loop_type,
                "task.preview": task[:80],
            },
            trace_id = ctx.trace_id,
        ):
            for cell_num in range(
                len(self._history) + 1,
                len(self._history) + self.max_cells + 1,
            ):

                # Audit #83: cancellation is checked before ANY new work
                # (kernel health check, LLM generation, execution).
                if cancel_token is not None and cancel_token.is_set():
                    status = SessionStatus.INTERRUPTED
                    break

                # Kernel health first (K-004): the prompt builder reads the
                # namespace, so a dead kernel must be handled BEFORE the
                # LLM is asked to generate anything.
                if not self.kernel.is_alive:
                    if self.auto_restart and self._restore_kernel():
                        if self.verbose:
                            print("  ♻️ Kernel died — restarted, state restored")
                        continue
                    status = SessionStatus.KERNEL_DIED
                    break

                try:
                    code = self._next_cell(cell_num)
                except Exception as e:
                    log.error("LLM generation failed", error=str(e))
                    status = SessionStatus.ERROR_UNHANDLED
                    break

                if self.verbose:
                    self._print_cell(cell_num, code)

                if self.plugins:
                    try:
                        transformed = self.plugins.on_before_cell(code)
                        if isinstance(transformed, str) and transformed:
                            code = transformed
                    except Exception as exc:
                        # Pre-execution plugins (e.g. hard guardrails) may block
                        # a cell. Convert this into a synthetic error so the loop
                        # can surface it and recover rather than terminating.
                        from kerno.types import CellError, CellOutput
                        output = CellOutput(
                            error=CellError(
                                ename=type(exc).__name__,
                                evalue=str(exc),
                            )
                        )
                        cell = Cell(code=code, output=output, cell_num=cell_num, author="system")
                        self._history.append(cell)
                        if self.verbose:
                            self._print_output(output)
                        if self.plugins:
                            self.plugins.on_cell_complete(cell)
                            self.plugins.on_error(
                                cell,
                                self._recovery._classifier.classify(output.error),
                            )
                        self._consecutive_errors += 1
                        self._on_error(cell)
                        continue

                exec_kwargs = {}
                if cancel_token is not None:
                    exec_kwargs["cancel_event"] = cancel_token
                output = self.kernel.execute(
                    code, timeout=self.cell_timeout, **exec_kwargs
                )

                if self.verbose:
                    self._print_output(output)

                cell = Cell(
                    code     = code,
                    output   = output,
                    cell_num = cell_num,
                    author   = "agent",
                )
                self._history.append(cell)
                self._on_cell_complete(cell)

                # Dispatch plugin lifecycle
                if self.plugins:
                    self.plugins.on_cell_complete(cell)
                    if cell.output.has_error:
                        classified = self._recovery._classifier.classify(cell.output.error)
                        self.plugins.on_error(cell, classified)

                if output.has_error:
                    self._consecutive_errors += 1
                    self._on_error(cell)

                    if self._consecutive_errors >= self.max_consecutive_errors:
                        if self.verbose:
                            print(f"  ⛔ Stuck after {self._consecutive_errors} errors — forcing redirect")
                        self._inject_unstick_message()
                        self._consecutive_errors = 0

                    if output.error.ename in ("SystemExit", "KeyboardInterrupt"):
                        status = SessionStatus.INTERRUPTED
                        break
                else:
                    self._consecutive_errors = 0

                if cell_num % CHECKPOINT_EVERY == 0:
                    self._auto_checkpoint()

                if self._compressor.should_compress(self._history, self.compress_after):
                    older         = self._history[:-10]
                    new_summary   = self._compressor.compress(older)
                    self._summary = (
                        f"{self._summary}\n\n{new_summary}".strip()
                        if self._summary else new_summary
                    )
                    self._history = self._history[-10:]

                # K-007: host-side checkpoint capture after a SUCCESSFUL
                # cell (the event sequence is at the completed position).
                if capture is not None and not output.has_error:
                    capture.after_cell(cell_num)

                # A completion marker only counts if the cell actually
                # SUCCEEDED — a policy-blocked or errored cell containing
                # "# TASK_COMPLETE" must not end the session as COMPLETE.
                if not output.has_error and COMPLETE_SIGNAL in code:
                    status = SessionStatus.COMPLETE
                    break

        result = SessionResult(
            session_id      = self._session_id,
            task            = task,
            status          = status,
            cells           = list(self._history),
            final_namespace = self._safe_namespace(),
            summary         = self._summary,
            started_at      = started_at,
            ended_at        = time.time(),
        )

        # Store session result in memory — NB: `is not None`, never `or`:
        # stores define __len__ so an EMPTY store is falsy.
        if self.memory is not None and status == SessionStatus.COMPLETE:
            self.memory.store_session_result(
                session_id = self._session_id,
                task       = task,
                summary    = self._summary,
                namespace  = result.final_namespace,
            )

        metrics.record_session_complete(
            status         = status.name,
            cells          = result.cells_executed,
            duration_s     = result.duration,
            error_count    = result.error_count,
            recovery_count = result.recovery_count,
            session_id     = self._session_id,
        )

        # Dispatch plugin lifecycle
        if self.plugins:
            self.plugins.on_session_complete(result)

        log.info(
            "Session complete",
            session_id     = self._session_id,
            status         = status.name,
            cells_executed = result.cells_executed,
            errors         = result.error_count,
            duration_s     = round(result.duration, 2),
        )

        return result

    # ── Abstract ───────────────────────────────────────────────────────────────

    @abstractmethod
    def _next_cell(self, cell_num: int) -> str: ...

    # ── Hooks ──────────────────────────────────────────────────────────────────

    def _on_cell_complete(self, cell: Cell) -> None:
        pass

    def _on_error(self, cell: Cell) -> None:
        hint, _ = self._recovery.suggest(cell.output.error)
        if self.verbose:
            clf = self._recovery._classifier.classify(cell.output.error)
            print(f"  🔍 {clf.error_class.name}: {clf.recovery_hint}")
        self._pending_recovery_hint = hint

        # Store successful recovery patterns
        if self.memory and len(self._history) > 1:
            prev = self._history[-2]
            if not prev.output.has_error:
                self.memory.store_error_pattern(
                    error_class = cell.output.error.ename,
                    context     = cell.code[:200],
                    recovery    = hint[:400],
                    session_id  = self._session_id,
                )

    def _inject_unstick_message(self) -> None:
        self._pending_recovery_hint = (
            "⛔ STRATEGY CHANGE REQUIRED\n\n"
            "You have made the same error repeatedly. Try a completely different approach:\n"
            "1. Inspect actual state: `what_exists()` or `print(list(globals().keys()))`\n"
            "2. Use `diagnose('variable_name')` to examine a specific object\n"
            "3. Try a simpler alternative\n"
            "4. Sample the data: `df.sample(100)` before operating on full dataset\n\n"
            "Write ONE diagnostic cell before retrying the operation."
        )

    # ── Message Building ───────────────────────────────────────────────────────

    def _build_messages(self) -> list[Message]:
        messages = self._builder.build(
            task      = self._task,
            history   = self._history,
            namespace = self.kernel.namespace,
            summary   = self._summary,
        )
        hint = self._pending_recovery_hint
        if hint:
            messages.append(Message(
                role    = "user",
                content = (
                    f"The previous cell raised an error.\n\n"
                    f"{hint}\n\n"
                    f"Write a recovery cell."
                ),
            ))
            self._pending_recovery_hint = None
        return messages

    def _call_llm(self, messages: list[Message]) -> str:
        with tracer.span("llm.generate", {"session.id": self._session_id}):
            return self.llm(messages)

    # ── Memory Integration ────────────────────────────────────────────────────

    def _retrieve_relevant_memories(self, task: str) -> str:
        if not self.memory:
            return ""
        entries = self.memory.retrieve(task, k=3, min_score=0.1)
        if not entries:
            return ""
        lines = ["Relevant context from prior sessions:"]
        for entry in entries:
            lines.append(f"  [{entry.kind}] {entry.content[:300]}")
        return "\n".join(lines)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _safe_namespace(self) -> str:
        """Namespace snapshot that never raises (dead kernel → \"{}\")."""
        try:
            return self.kernel.namespace
        except Exception:
            return "{}"

    def _restore_kernel(self) -> bool:
        """
        K-004: restart the kernel and re-execute history to restore state.

        The kernel is restarted through the underlying runtime (generation
        increments), then every recorded cell is re-executed — trusted
        infrastructure re-running already-vetted code. Returns True if the
        kernel is alive afterwards.
        """
        raw = getattr(self.kernel, "raw_kernel", None) or self.kernel
        try:
            raw.restart()
        except Exception as exc:
            log.error("Kernel restart failed", error=str(exc))
            return False
        for cell in self._history:
            # Only successful cells contributed (trusted) state. Errored
            # cells — including policy-blocked ones — are never re-run.
            if cell.output.has_error:
                continue
            try:
                raw.execute(cell.code, timeout=self.cell_timeout)
            except Exception as exc:
                log.error("State restoration failed", error=str(exc))
                return False
        return self.kernel.is_alive

    def _auto_checkpoint(self) -> None:
        code = """
import joblib as _jl, pathlib as _pl, pandas as _pd
_ckpt = _pl.Path('_checkpoints')
_ckpt.mkdir(exist_ok=True)
for _n, _o in list(globals().items()):
    if _n.startswith('_'): continue
    try:
        if isinstance(_o, _pd.DataFrame):
            _o.to_parquet(_ckpt / f'{_n}.parquet')
        elif hasattr(_o, '__sklearn_tags__'):
            _jl.dump(_o, _ckpt / f'{_n}.joblib')
    except Exception:
        pass
"""
        self.kernel.execute(code, silent=True, timeout=30)

    def _print_cell(self, num: int, code: str) -> None:
        border  = "─" * 56
        preview = code[:180] + ("…" if len(code) > 180 else "")
        print(f"\n{border}\n  Cell {num}\n{border}\n{preview}")

    def _print_output(self, output: CellOutput) -> None:
        text = output.as_text(max_chars=300)
        icon = "✗" if output.has_error else "→"
        print(f"  {icon} {text[:200]}")
