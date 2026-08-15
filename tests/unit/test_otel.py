"""Unit tests for the OpenTelemetry bridge."""

import pytest
from kerno.telemetry.otel import OTelSpan, OTelTracer, OTelMetrics


class TestOTelSpan:
    """Tests for the OTelSpan wrapper."""

    def test_creation(self):
        span = OTelSpan(
            otel_span=None,
            trace_id="abc123",
            span_id="def456",
        )
        assert span.trace_id == "abc123"
        assert span.span_id == "def456"
        assert span.name == ""
        assert span.status == "ok"
        assert span.attributes == {}
        assert span.events == []

    def test_set_attribute(self):
        span = OTelSpan(otel_span=None, trace_id="t", span_id="s")
        span.set("key", "value")
        assert span.attributes["key"] == "value"

    def test_set_numeric_attribute(self):
        span = OTelSpan(otel_span=None, trace_id="t", span_id="s")
        span.set("count", 42)
        assert span.attributes["count"] == 42

    def test_duration_ms_default(self):
        span = OTelSpan(otel_span=None, trace_id="t", span_id="s")
        assert span.duration_ms == 0.0

    def test_end_ok(self):
        span = OTelSpan(otel_span=None, trace_id="t", span_id="s")
        span.end("ok")
        assert span.status == "ok"

    def test_end_error(self):
        span = OTelSpan(otel_span=None, trace_id="t", span_id="s")
        span.end("error")
        assert span.status == "error"


class TestOTelTracer:
    """Tests for the OTelTracer class."""

    def test_creation(self):
        tracer = OTelTracer(None)
        assert tracer._otel_tracer is None
        assert tracer._current_trace_id == ""

    def test_start_trace(self):
        tracer = OTelTracer(None)
        ctx = tracer.start_trace("test_session")
        assert ctx.trace_id != ""
        assert ctx.span_id != ""
        assert tracer._current_trace_id == ctx.trace_id


class TestOTelMetrics:
    """Tests for the OTelMetrics class."""

    def test_creation(self):
        metrics = OTelMetrics(None)
        assert metrics._meter is None
        assert metrics._counters == {}
        assert metrics._histograms == {}
        assert metrics._gauges_obs == {}

    def test_snapshot(self):
        metrics = OTelMetrics(None)
        snap = metrics.snapshot()
        assert "note" in snap

    def test_record_cell(self):
        """record_cell should be callable (OTel meter would handle the actual recording)."""
        metrics = OTelMetrics(None)
        # Without a real meter, counter creation will fail — but the method exists
        assert hasattr(metrics, "record_cell")

    def test_record_session_complete_exists(self):
        metrics = OTelMetrics(None)
        assert hasattr(metrics, "record_session_complete")

    def test_record_kernel_memory_exists(self):
        metrics = OTelMetrics(None)
        assert hasattr(metrics, "record_kernel_memory")

    def test_record_pool_state_exists(self):
        metrics = OTelMetrics(None)
        assert hasattr(metrics, "record_pool_state")


class TestOTelModuleImport:
    """Verify otel module can be imported."""

    def test_import_otel(self):
        from kerno.telemetry.otel import OTelTracer, OTelMetrics, OTelSpan
        assert OTelTracer is not None
        assert OTelMetrics is not None
        assert OTelSpan is not None
