"""Unit tests for telemetry — no kernel required."""

import json
import time
import pytest

from kerno.telemetry.tracer  import Tracer, SpanContext
from kerno.telemetry.metrics import Metrics
from kerno.telemetry.logger  import StructuredLogger, Level


class TestTracer:

    @pytest.fixture
    def tracer(self, tmp_path):
        return Tracer(output_path=str(tmp_path / "traces.jsonl"))

    def test_span_writes_to_file(self, tracer, tmp_path):
        with tracer.span("test.operation"):
            pass

        path  = tmp_path / "traces.jsonl"
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1

        data = json.loads(lines[0])
        assert data["name"] == "test.operation"

    def test_span_records_duration(self, tracer, tmp_path):
        with tracer.span("timed.op"):
            time.sleep(0.05)

        data = json.loads((tmp_path / "traces.jsonl").read_text())
        assert data["duration_ms"] >= 40    # At least 40ms

    def test_span_captures_error_status(self, tracer, tmp_path):
        with pytest.raises(ValueError):
            with tracer.span("failing.op"):
                raise ValueError("test error")

        data = json.loads((tmp_path / "traces.jsonl").read_text())
        assert data["status"] == "error"
        assert data["attributes"]["error.type"] == "ValueError"

    def test_span_attributes_stored(self, tracer, tmp_path):
        with tracer.span("op.with.attrs", {"key": "value", "num": 42}):
            pass

        data = json.loads((tmp_path / "traces.jsonl").read_text())
        assert data["attributes"]["key"] == "value"
        assert data["attributes"]["num"]  == 42

    def test_span_set_during_execution(self, tracer, tmp_path):
        with tracer.span("dynamic.attrs") as span:
            span.set("computed", 123)

        data = json.loads((tmp_path / "traces.jsonl").read_text())
        assert data["attributes"]["computed"] == 123

    def test_start_trace_returns_context(self, tracer):
        ctx = tracer.start_trace("test.session")
        assert isinstance(ctx, SpanContext)
        assert ctx.trace_id != ""
        assert ctx.span_id  != ""


class TestMetrics:

    @pytest.fixture
    def metrics(self, tmp_path):
        return Metrics(output_path=str(tmp_path / "metrics.jsonl"))

    def test_counter_increments(self, metrics):
        metrics.counter("test.counter")
        metrics.counter("test.counter")
        metrics.counter("test.counter")

        snap = metrics.snapshot()
        assert snap["counters"]["test.counter"] == 3.0

    def test_counter_with_value(self, metrics):
        metrics.counter("bytes.sent", value=1024)
        snap = metrics.snapshot()
        assert snap["counters"]["bytes.sent"] == 1024.0

    def test_gauge_latest_value(self, metrics):
        metrics.gauge("pool.size", 3)
        metrics.gauge("pool.size", 5)

        snap = metrics.snapshot()
        assert snap["gauges"]["pool.size"] == 5.0

    def test_histogram_statistics(self, metrics):
        for v in [10, 20, 30, 40, 50]:
            metrics.histogram("response.ms", v)

        snap  = metrics.snapshot()
        histo = snap["histograms"]["response.ms"]
        assert histo["count"]  == 5
        assert histo["mean"]   == 30.0
        assert histo["min"]    == 10.0
        assert histo["max"]    == 50.0

    def test_tags_create_separate_series(self, metrics):
        metrics.counter("cells", tags={"loop": "reactive"})
        metrics.counter("cells", tags={"loop": "reflect"})

        snap     = metrics.snapshot()
        counters = snap["counters"]
        assert any("reactive" in k for k in counters)
        assert any("reflect"  in k for k in counters)

    def test_record_cell_convenience(self, metrics):
        metrics.record_cell(
            duration_ms = 150.0,
            had_error   = False,
            session_id  = "s-1",
        )
        metrics.record_cell(
            duration_ms = 200.0,
            had_error   = True,
            session_id  = "s-1",
        )
        snap = metrics.snapshot()
        assert any("kerno.cells" in k for k in snap["counters"])
        assert any("kerno.cell.duration_ms" in k for k in snap["histograms"])

    def test_writes_to_file(self, metrics, tmp_path):
        metrics.counter("written.to.disk")
        path  = tmp_path / "metrics.jsonl"
        lines = path.read_text().strip().split("\n")
        assert len(lines) >= 1
        data  = json.loads(lines[0])
        assert data["name"] == "written.to.disk"


class TestStructuredLogger:

    @pytest.fixture
    def logger(self, tmp_path):
        return StructuredLogger(
            "test",
            level     = Level.DEBUG,
            file_path = str(tmp_path / "test.log"),
        )

    def test_log_writes_json(self, logger, tmp_path):
        logger.info("test message", key="value")
        path = tmp_path / "test.log"
        data = json.loads(path.read_text().strip())
        assert data["message"] == "test message"
        assert data["key"]     == "value"
        assert data["level"]   == "INFO"
        assert data["logger"]  == "test"

    def test_debug_below_info_threshold_not_written(self, tmp_path):
        logger = StructuredLogger(
            "test",
            level     = Level.INFO,
            file_path = str(tmp_path / "info_only.log"),
        )
        logger.debug("this should not appear")
        path  = tmp_path / "info_only.log"
        lines = path.read_text().strip().split("\n") if path.exists() else []
        assert all("this should not appear" not in l for l in lines if l)

    def test_error_level_written(self, logger, tmp_path):
        logger.error("something broke", code=500)
        data = json.loads((tmp_path / "test.log").read_text().strip())
        assert data["level"] == "ERROR"
        assert data["code"]  == 500

    def test_extra_fields_serialized(self, logger, tmp_path):
        logger.info("with extras", count=42, flag=True, label="abc")
        data = json.loads((tmp_path / "test.log").read_text().strip())
        assert data["count"] == 42
        assert data["flag"]  is True
        assert data["label"] == "abc"
