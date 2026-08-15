# kerno/telemetry/otel.py
"""
OpenTelemetry bridge for kerno.

Replaces the built-in JSONL tracer with a real OTel exporter.
Zero changes required in application code — just call set_tracer().

Usage:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    provider = TracerProvider()
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4317"))
    )
    trace.set_tracer_provider(provider)

    from kerno.telemetry.otel import OTelTracer
    from kerno.telemetry      import set_tracer
    set_tracer(OTelTracer(trace.get_tracer("kerno")))
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator, Optional

from kerno.telemetry.tracer import Span, SpanContext, Tracer


class OTelSpan:
    """
    Wraps an OpenTelemetry span behind kerno's Span interface.
    """

    def __init__(self, otel_span, trace_id: str, span_id: str):
        self._otel  = otel_span
        self.trace_id = trace_id
        self.span_id  = span_id
        self.name     = ""
        self.status   = "ok"
        self.attributes: dict = {}
        self.events:    list  = []

    def set(self, key: str, value: Any) -> None:
        self.attributes[key] = value
        if self._otel is not None:
            self._otel.set_attribute(key, str(value) if not isinstance(value, (bool, int, float, str)) else value)

    def add_event(self, name: str, attrs: dict = None) -> None:
        self.events.append({"name": name, "attrs": attrs or {}})
        if self._otel is not None:
            self._otel.add_event(name, attributes=attrs or {})

    def end(self, status: str = "ok") -> None:
        self.status = status
        if status == "error" and self._otel is not None:
            from opentelemetry.trace import Status, StatusCode
            self._otel.set_status(Status(StatusCode.ERROR))
        if self._otel is not None:
            self._otel.end()

    @property
    def duration_ms(self) -> float:
        return 0.0   # OTel manages timing internally


class OTelTracer(Tracer):
    """
    OpenTelemetry-backed tracer for kerno.
    Implements the same interface as the built-in Tracer.

    Install:
        pip install opentelemetry-api opentelemetry-sdk
        pip install opentelemetry-exporter-otlp
    """

    def __init__(self, otel_tracer):
        """
        Args:
            otel_tracer: An opentelemetry.trace.Tracer instance
        """
        self._otel_tracer      = otel_tracer
        self._current_trace_id = ""
        # Don't call super().__init__() — we don't want JSONL output

    def start_trace(self, name: str) -> SpanContext:
        import uuid
        trace_id = uuid.uuid4().hex
        self._current_trace_id = trace_id
        return SpanContext(trace_id=trace_id, span_id=uuid.uuid4().hex[:16])

    @contextmanager
    def span(
        self,
        name:       str,
        attributes: dict = None,
        trace_id:   str  = None,
        parent_id:  str  = None,
    ) -> Generator[OTelSpan, None, None]:
        import uuid

        with self._otel_tracer.start_as_current_span(name) as otel_span:
            ctx_obj = otel_span.get_span_context()
            wrapped = OTelSpan(
                otel_span  = otel_span,
                trace_id   = format(ctx_obj.trace_id, '032x') if ctx_obj else "",
                span_id    = format(ctx_obj.span_id,  '016x') if ctx_obj else "",
            )
            wrapped.name = name

            if attributes:
                for k, v in attributes.items():
                    wrapped.set(k, v)

            try:
                yield wrapped
                wrapped.end("ok")
            except Exception as e:
                wrapped.set("error.type",    type(e).__name__)
                wrapped.set("error.message", str(e)[:500])
                wrapped.end("error")
                raise


class OTelMetrics:
    """
    OpenTelemetry-backed metrics for kerno.
    Wraps OTel's metrics API behind kerno's Metrics interface.

    Usage:
        from opentelemetry import metrics
        from kerno.telemetry.otel import OTelMetrics
        from kerno.telemetry      import set_metrics

        meter = metrics.get_meter("kerno")
        set_metrics(OTelMetrics(meter))
    """

    def __init__(self, meter):
        self._meter    = meter
        self._counters   = {}
        self._histograms = {}
        self._gauges_obs = {}

    def counter(self, name: str, value: float = 1.0, tags: dict = None) -> None:
        if name not in self._counters:
            self._counters[name] = self._meter.create_counter(
                name.replace(".", "_"),
                description="kerno counter: {}".format(name),
            )
        self._counters[name].add(int(value), attributes=tags or {})

    def histogram(self, name: str, value: float, tags: dict = None) -> None:
        if name not in self._histograms:
            self._histograms[name] = self._meter.create_histogram(
                name.replace(".", "_"),
                description="kerno histogram: {}".format(name),
            )
        self._histograms[name].record(value, attributes=tags or {})

    def gauge(self, name: str, value: float, tags: dict = None) -> None:
        # OTel uses observable gauges; we approximate with up/down counters
        if name not in self._gauges_obs:
            self._gauges_obs[name] = self._meter.create_up_down_counter(
                name.replace(".", "_"),
                description="kerno gauge: {}".format(name),
            )
        self._gauges_obs[name].add(value, attributes=tags or {})

    # Delegate convenience methods to the implementations above
    def record_cell(self, duration_ms, had_error, session_id="", loop_type=""):
        tags = {"session_id": session_id, "loop": loop_type}
        self.counter("kerno.cells.total", tags=tags)
        self.histogram("kerno.cell.duration_ms", duration_ms, tags=tags)
        if had_error:
            self.counter("kerno.cells.errors", tags=tags)

    def record_session_complete(self, status, cells, duration_s,
                                error_count, recovery_count, session_id=""):
        tags = {"status": status, "session_id": session_id}
        self.counter("kerno.sessions.total", tags=tags)
        self.histogram("kerno.session.cells",      cells,          tags=tags)
        self.histogram("kerno.session.duration_s", duration_s,     tags=tags)
        self.histogram("kerno.session.errors",     error_count,    tags=tags)
        self.histogram("kerno.session.recoveries", recovery_count, tags=tags)

    def record_kernel_memory(self, memory_mb, kernel_id=""):
        self.gauge("kerno.kernel.memory_mb", memory_mb, tags={"kernel_id": kernel_id})

    def record_pool_state(self, available, active):
        self.gauge("kerno.pool.available", available)
        self.gauge("kerno.pool.active",    active)

    def snapshot(self) -> dict:
        return {"note": "Use your OTel backend to query metrics snapshots."}
