"""
Distributed tracing for kerno.

Design:
  - Zero-dependency by default: built-in tracer writes to a JSON file
  - OpenTelemetry-compatible interface: drop-in replacement when needed
  - Every kernel cell execution becomes a span
  - Spans carry: code preview, duration, error state, namespace delta

The tracer is a global singleton per process.
Override it with set_tracer() to plug in OpenTelemetry.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generator, Optional


@dataclass
class SpanContext:
    """Identifies a span within a trace."""
    trace_id:  str
    span_id:   str
    parent_id: Optional[str] = None


@dataclass
class Span:
    """One unit of traced work."""
    name:       str
    trace_id:   str
    span_id:    str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    parent_id:  Optional[str]   = None
    start_time: float           = field(default_factory=time.monotonic)
    end_time:   Optional[float] = None
    attributes: dict[str, Any]  = field(default_factory=dict)
    status:     str             = "ok"      # "ok" | "error"
    events:     list[dict]      = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0

    def set(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attrs: dict = None) -> None:
        self.events.append({
            "name":       name,
            "time":       time.monotonic(),
            "attributes": attrs or {},
        })

    def end(self, status: str = "ok") -> None:
        self.end_time = time.monotonic()
        self.status   = status

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "trace_id":    self.trace_id,
            "span_id":     self.span_id,
            "parent_id":   self.parent_id,
            "start_time":  self.start_time,
            "duration_ms": self.duration_ms,
            "attributes":  self.attributes,
            "status":      self.status,
            "events":      self.events,
        }


class Tracer:
    """
    Built-in tracer. Writes spans to a JSONL file.

    To use OpenTelemetry instead:
        from opentelemetry import trace
        kerno.telemetry.set_tracer(OTelTracer(trace.get_tracer("kerno")))
    """

    def __init__(self, output_path: str = ".kerno/traces.jsonl"):
        self._output_path = Path(output_path)
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock        = threading.Lock()
        self._active:     dict[str, Span] = {}   # span_id → Span
        self._current_trace_id: Optional[str] = None

    def start_trace(self, name: str) -> SpanContext:
        """Start a new root trace (e.g., one agent session)."""
        trace_id = uuid.uuid4().hex
        span     = self._start_span(name, trace_id, parent_id=None)
        self._current_trace_id = trace_id
        return SpanContext(trace_id=trace_id, span_id=span.span_id)

    @contextmanager
    def span(
        self,
        name:       str,
        attributes: dict = None,
        trace_id:   str  = None,
        parent_id:  str  = None,
    ) -> Generator[Span, None, None]:
        """
        Context manager for a traced operation.

        with tracer.span("kernel.execute", {"cell.num": 5}) as span:
            output = kernel.execute(code)
            span.set("output.bytes", len(str(output)))
        """
        tid  = trace_id or self._current_trace_id or uuid.uuid4().hex
        span = self._start_span(name, tid, parent_id)

        if attributes:
            for k, v in attributes.items():
                span.set(k, v)

        try:
            yield span
            span.end("ok")
        except Exception as e:
            span.set("error.type",    type(e).__name__)
            span.set("error.message", str(e)[:500])
            span.end("error")
            raise
        finally:
            self._finish_span(span)

    def _start_span(
        self, name: str, trace_id: str, parent_id: Optional[str]
    ) -> Span:
        span = Span(
            name      = name,
            trace_id  = trace_id,
            parent_id = parent_id,
        )
        with self._lock:
            self._active[span.span_id] = span
        return span

    def _finish_span(self, span: Span) -> None:
        with self._lock:
            self._active.pop(span.span_id, None)
        self._write(span)

    def _write(self, span: Span) -> None:
        line = json.dumps(span.to_dict())
        with self._lock:
            with open(self._output_path, "a") as f:
                f.write(line + "\n")


# ── Global singleton ──────────────────────────────────────────────────────────

_tracer: Tracer = Tracer()


def get_tracer() -> Tracer:
    return _tracer


def set_tracer(tracer: Tracer) -> None:
    global _tracer
    _tracer = tracer
