"""
Unit tests for the runtime config layer: KernoConfig runtime section,
env parsing, production defaults, and run_with_config forwarding.
"""

import os

from kerno.config import KernoConfig, RuntimeConfig
from kerno.runner import run_with_config


class TestRuntimeConfig:

    def test_defaults(self):
        cfg = KernoConfig()
        assert cfg.runtime.mode == "live"
        assert cfg.runtime.isolation == "shared"
        assert cfg.runtime.auto_restart is False
        assert cfg.runtime.budget_executions is None
        assert cfg.runtime.timeout_policy == "interrupt"

    def test_production_config(self):
        cfg = KernoConfig.for_production()
        assert cfg.runtime.auto_restart is True
        assert cfg.runtime.isolation == "isolated"
        assert cfg.runtime.timeout_policy == "escalate"
        assert cfg.runtime.budget_executions == 200

    def test_from_env_parses_runtime(self, monkeypatch):
        monkeypatch.setenv("KERNO_RUNTIME_MODE", "dry_run")
        monkeypatch.setenv("KERNO_RUNTIME_ISOLATION", "isolated")
        monkeypatch.setenv("KERNO_RUNTIME_AUTO_RESTART", "true")
        monkeypatch.setenv("KERNO_RUNTIME_BUDGET_EXECUTIONS", "42")
        monkeypatch.setenv("KERNO_RUNTIME_BUDGET_WALL_TIME", "30.5")
        monkeypatch.setenv("KERNO_RUNTIME_TIMEOUT_POLICY", "escalate")

        cfg = KernoConfig.from_env()

        assert cfg.runtime.mode == "dry_run"
        assert cfg.runtime.isolation == "isolated"
        assert cfg.runtime.auto_restart is True
        assert cfg.runtime.budget_executions == 42
        assert cfg.runtime.budget_wall_time == 30.5
        assert cfg.runtime.timeout_policy == "escalate"

    def test_env_none_values(self, monkeypatch):
        monkeypatch.setenv("KERNO_RUNTIME_BUDGET_EXECUTIONS", "none")
        monkeypatch.setenv("KERNO_RUNTIME_BUDGET_WALL_TIME", "")
        cfg = KernoConfig.from_env()
        assert cfg.runtime.budget_executions is None
        assert cfg.runtime.budget_wall_time is None

    def test_from_file_round_trip(self, tmp_path):
        cfg = KernoConfig()
        cfg.runtime.mode = "dry_run"
        cfg.runtime.budget_executions = 7
        path = tmp_path / "config.json"
        import json
        path.write_text(json.dumps(cfg.to_dict()))

        loaded = KernoConfig.from_file(str(path))
        assert loaded.runtime.mode == "dry_run"
        assert loaded.runtime.budget_executions == 7

    def test_runtime_config_serializable(self):
        rc = RuntimeConfig(mode="dry_run", isolation="isolated",
                           budget_executions=5)
        d = rc.__dict__.copy()
        assert d["mode"] == "dry_run"
        assert d["budget_executions"] == 5


class TestRunWithConfigForwarding:

    def _dummy_llm(self):
        from kerno.types import Message
        calls = [0]
        def llm(messages):
            calls[0] += 1
            return "# TASK_COMPLETE: done"
        return llm

    def test_dry_run_mode_never_starts_kernel(self, monkeypatch):
        cfg = KernoConfig()
        cfg.runtime.mode = "dry_run"
        started = []
        import kerno._run as run_mod

        original = run_mod.KernelRuntime.start
        def spy_start(self):
            started.append(self)
            return original(self)

        monkeypatch.setattr(run_mod.KernelRuntime, "start", spy_start)

        result = run_with_config("compute", self._dummy_llm(), cfg)

        assert started == [], "dry_run must never start a kernel"
        assert result.cells_executed >= 1

    def test_live_mode_uses_kernel(self):
        cfg = KernoConfig()
        cfg.kernel.max_cells = 3
        result = run_with_config(
            "compute", self._dummy_llm(), cfg,
        )
        assert result.cells_executed >= 1
