"""
Unit tests for operational hardening: execution→metrics projection
(audit #80), config validation, and CLI session export.
"""

import json
import sys

from kerno.config import KernoConfig
from kerno.execution.engine import ExecutionEngine
from kerno.telemetry.metrics import Metrics
from kerno.types import CellOutput


class FakeKernel:
    def execute(self, code, timeout=120.0, silent=False, **kwargs):
        return CellOutput(stdout="ok")

    def execute_silent(self, code, timeout=15.0, **kwargs):
        return "ok"

    @property
    def namespace(self):
        return "{}"

    @property
    def is_alive(self):
        return True


class TestExecutionMetricsProjection:
    """Audit #80: one event source → multiple projections."""

    def test_attempts_and_blocks_projected(self, tmp_path):
        metrics = Metrics(output_path=str(tmp_path / "m.jsonl"))
        from kerno.telemetry import metrics as metrics_mod
        metrics_mod.set_metrics(metrics)

        from kerno.security.allowlist import AllowList
        engine = ExecutionEngine(FakeKernel(), allowlist=AllowList.data_analysis())
        engine.execute("x = 1")
        engine.execute("import subprocess\nsubprocess.run(['x'])")
        engine.execute("y = 2")

        snap = metrics.snapshot()
        # Counters land under the 'counters' bucket, tags embedded in keys
        counter_names = " ".join(snap["counters"].keys())
        assert "kerno.executions.attempts" in counter_names
        assert "kerno.executions.blocked" in counter_names
        assert "subprocess" in counter_names   # rule tag

    def test_capability_denial_projected(self, tmp_path):
        metrics = Metrics(output_path=str(tmp_path / "m.jsonl"))
        from kerno.telemetry import metrics as metrics_mod
        metrics_mod.set_metrics(metrics)

        from kerno.security.capabilities import CapabilityBroker
        engine = ExecutionEngine(
            FakeKernel(), broker=CapabilityBroker(),
            default_capabilities=frozenset({"kernel.execute"}),
        )
        engine.execute("x = 1")

        snap = metrics.snapshot()
        counter_names = " ".join(snap["counters"].keys())
        assert "kerno.executions.capability_denied" in counter_names

    def test_metrics_reset_after(self):
        import tempfile
        from kerno.telemetry import metrics as metrics_mod
        metrics_mod.set_metrics(Metrics(
            output_path=tempfile.mkdtemp() + "/reset.jsonl"
        ))


class TestConfigValidation:

    def test_default_config_valid(self):
        assert KernoConfig().validate() == []

    def test_production_config_valid(self):
        assert KernoConfig.for_production().validate() == []

    def test_bad_mode_reported(self):
        cfg = KernoConfig()
        cfg.runtime.mode = "simulate"
        problems = cfg.validate()
        assert any("runtime.mode" in p for p in problems)

    def test_bad_isolation_reported(self):
        cfg = KernoConfig()
        cfg.runtime.isolation = "banana"
        problems = cfg.validate()
        assert any("runtime.isolation" in p for p in problems)

    def test_bad_profile_reported(self):
        cfg = KernoConfig()
        cfg.security.profile = "everything"
        problems = cfg.validate()
        assert any("security.profile" in p for p in problems)

    def test_negative_budget_reported(self):
        cfg = KernoConfig()
        cfg.runtime.budget_executions = -5
        problems = cfg.validate()
        assert any("budget_executions" in p for p in problems)

    def test_validate_or_raise(self):
        cfg = KernoConfig()
        cfg.runtime.timeout_policy = "nuke"
        try:
            cfg.validate_or_raise()
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_valid_config_validate_or_raise_passes(self):
        cfg = KernoConfig()
        assert cfg.validate_or_raise() is cfg


class TestCliSessionExport:

    def test_export_parser_accepts_args(self):
        from kerno.cli.main import main
        old = sys.argv
        sys.argv = ["kerno", "session", "export", "sess-123", "--out", "/tmp/x.json"]
        try:
            code = main()
        except SystemExit as e:
            code = e.code
        finally:
            sys.argv = old
        # Parser accepted the args; execution fails at the missing
        # notebook (returns 1) — that's the parse-success signal.
        assert code in (0, 1)

    def test_export_requires_session_id(self):
        from kerno.cli.main import main
        old = sys.argv
        sys.argv = ["kerno", "session", "export"]
        try:
            main()
            assert False, "expected SystemExit(2)"
        except SystemExit as e:
            assert e.code == 2
        finally:
            sys.argv = old


class TestServerHealthEndpoint:
    """Regression: the OpenAI-compat /health endpoint must not 500.

    Found in deep verification: pool.stats() was called as a method but
    KernelPool.stats is a property ('dict' object is not callable).
    """

    def test_health_returns_ok(self):
        from kerno.llm.brain import ScriptedBrain
        from kerno.server.openai_compat import create_openai_app

        app = create_openai_app(
            ScriptedBrain("print(1)", "# TASK_COMPLETE: done"),
            pool_size=1,
        )
        # FastAPI TestClient (needs httpx)
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["pool_stats"]["total"] == 1
            assert data["pool_stats"]["available"] == 1
            # The models endpoint works too
            models = client.get("/v1/models").json()
            assert len(models["data"]) >= 1
