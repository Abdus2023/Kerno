"""
KernoComm: a structured communication channel between kernel and orchestrator.

Standard kernel output (stdout/stderr) is for humans.
KernoComm is for machines — structured JSON messages on the IOPUB channel.

The kernel code emits comm messages.
The orchestrator listens on the IOPUB channel and dispatches them.

This enables:
  - Real-time progress reporting (without polluting stdout)
  - Anomaly detection signals (agent found something unexpected)
  - Decision point signals (agent needs external input)
  - Intermediate result streaming (large results sent in chunks)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from kerno.kernel.output import set_comm_handler
from kerno.kernel.runtime import KernelRuntime
from kerno.telemetry.logger import get_logger

log = get_logger("kerno.comms")


@dataclass
class CommMessage:
    """
    A structured message emitted by the kernel agent.
    """
    kind:       str            # "progress" | "anomaly" | "decision" | "result" | "custom"
    payload:    dict[str, Any]
    agent_name: str            = ""
    session_id: str            = ""
    timestamp:  float          = field(default_factory=time.time)

    @classmethod
    def progress(
        cls,
        step:       str,
        pct:        float,
        details:    dict = None,
        **kwargs,
    ) -> "CommMessage":
        return cls(
            kind    = "progress",
            payload = {"step": step, "pct": pct, "details": details or {}},
            **kwargs,
        )

    @classmethod
    def anomaly(
        cls,
        description: str,
        severity:    str,
        data:        dict = None,
        **kwargs,
    ) -> "CommMessage":
        return cls(
            kind    = "anomaly",
            payload = {
                "description": description,
                "severity":    severity,
                "data":        data or {},
            },
            **kwargs,
        )

    @classmethod
    def decision_required(
        cls,
        question: str,
        options:  list[str],
        **kwargs,
    ) -> "CommMessage":
        return cls(
            kind    = "decision",
            payload = {"question": question, "options": options},
            **kwargs,
        )


CommHandler = Callable[[CommMessage], None]


# ── Kernel-side code ──────────────────────────────────────────────────────────

_COMM_SETUP_CODE = '''
_kerno_comm_available = False

try:
    from ipykernel.comm import Comm as _Comm
    _kerno_comm = _Comm(target_name="kerno_orchestrator")
    _kerno_comm.open(data={"type": "init"})
    _kerno_comm_available = True
except Exception:
    pass   # Comm not available — messages will be no-ops


def _emit(kind: str, **payload):
    """Emit a structured comm message to the orchestrator."""
    if not _kerno_comm_available:
        return
    try:
        _kerno_comm.send({
            "kind":    kind,
            "payload": payload,
            "ts":      __import__("time").time(),
        })
    except Exception:
        pass


def progress(step: str, pct: float = 0.0, **details):
    """
    Report progress to the orchestrator.
    pct: 0.0 to 1.0

    Example:
        progress("loading data", 0.1)
        progress("model trained", 0.8, accuracy=0.92)
    """
    _emit("progress", step=step, pct=pct, **details)


def signal_anomaly(description: str, severity: str = "warning", **data):
    """
    Signal that something unexpected was found.
    severity: "info" | "warning" | "critical"

    Example:
        signal_anomaly("Negative revenue values detected", "warning", count=42)
    """
    _emit("anomaly", description=description, severity=severity, **data)


def signal_decision(question: str, options: list):
    """
    Signal that a decision is needed from the orchestrator/human.
    Execution continues without blocking.

    Example:
        signal_decision(
            "Found 3 outlier clusters. Should I investigate all?",
            ["investigate_all", "top_only", "skip"]
        )
    """
    _emit("decision", question=question, options=options)


def emit_result(name: str, value, description: str = ""):
    """
    Emit an intermediate result for streaming to the orchestrator.
    Useful for long analyses where you want partial results early.

    Example:
        emit_result("region_analysis", df_west.to_dict(), "West region complete")
    """
    import json as _json
    try:
        serialized = _json.dumps(value, default=str)[:10_000]
    except Exception:
        serialized = str(value)[:1000]
    _emit("result", name=name, value=serialized, description=description)
'''


class KernoComm:
    """
    Manages the structured communication channel between the kernel and the orchestrator.

    Usage:
        comm = KernoComm(kernel)
        comm.start()

        # Register handlers
        comm.on("progress", lambda msg: print(f"Progress: {msg.payload}"))
        comm.on("anomaly",  lambda msg: alert_team(msg))

        # Now run the agent — the kernel can call progress(), signal_anomaly(), etc.
        result = loop.run(task)

        comm.stop()
    """

    def __init__(self, kernel: KernelRuntime):
        self.kernel    = kernel
        self._handlers: dict[str, list[CommHandler]] = {}
        self._messages: list[CommMessage]            = []
        self._running   = False

    def start(self) -> "KernoComm":
        """
        Install comm infrastructure in kernel and start listening.

        Delivery model: the output collector (kerno.kernel.output) is the
        single reader of the IOPUB socket; comm_msg messages are dispatched
        to this channel inline while a cell is being collected. This avoids
        a competing reader thread stealing execution messages (including
        the terminal "idle"), which previously hung cell collection.
        """
        self.kernel.execute(_COMM_SETUP_CODE, silent=True, timeout=10)
        self._running = True
        set_comm_handler(self._on_comm_msg)
        log.info("KernoComm started")
        return self

    def stop(self) -> None:
        """Unregister the dispatcher and stop listening."""
        self._running = False
        set_comm_handler(None)
        log.info("KernoComm stopped")

    def on(self, kind: str, handler: CommHandler) -> "KernoComm":
        """
        Register a handler for a specific message kind.
        Multiple handlers can be registered for the same kind.

        Returns self for chaining:
            comm.on("progress", fn1).on("anomaly", fn2)
        """
        if kind not in self._handlers:
            self._handlers[kind] = []
        self._handlers[kind].append(handler)
        return self

    def messages(self, kind: str = None) -> list[CommMessage]:
        """Return all received messages, optionally filtered by kind."""
        if kind:
            return [m for m in self._messages if m.kind == kind]
        return list(self._messages)

    def last_progress(self) -> Optional[CommMessage]:
        """Return the most recent progress message."""
        progress_msgs = [m for m in self._messages if m.kind == "progress"]
        return progress_msgs[-1] if progress_msgs else None

    # ── Internals ─────────────────────────────────────────────────────────────

    def _on_comm_msg(self, msg: dict) -> None:
        """
        Handle a comm_msg received by the output collector.

        Called inline during cell collection (single-reader discipline).
        """
        if not self._running:
            return
        try:
            data = msg["content"].get("data", {})
            comm_msg = CommMessage(
                kind    = data.get("kind", "unknown"),
                payload = data.get("payload", {}),
            )
            self._messages.append(comm_msg)
            self._dispatch(comm_msg)
        except Exception as e:
            log.warning("Comm message parse error", error=str(e))

    def _dispatch(self, msg: CommMessage) -> None:
        """Call all registered handlers for this message kind."""
        handlers = (
            self._handlers.get(msg.kind, [])
            + self._handlers.get("*", [])    # Wildcard handlers
        )
        for handler in handlers:
            try:
                handler(msg)
            except Exception as e:
                log.warning(
                    "Comm handler error",
                    kind    = msg.kind,
                    error   = str(e),
                )
