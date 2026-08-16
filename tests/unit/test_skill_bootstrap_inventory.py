"""Tests covering the enriched built-in skill inventory and bootstrap wiring."""

import ast
import importlib

import pytest

_bootstrap_module = importlib.import_module("kerno.skills.bootstrap")
from kerno.skills import composer
from kerno.skills.builtins import (
    anomaly,
    artifacts,
    data,
    docs,
    experiment,
    export,
    features,
    filesystem,
    synth,
    api,
    finance,
    graph,
    introspect,
    llm_tools,
    meta,
    ml,
    network,
    nlp,
    optimization,
    quality,
    report,
    simulation,
    sql,
    stats,
    synthetic,
    text,
    timeseries,
    viz,
    web,
)


EXPECTED_MODULES = {
    "data_skills": data.get_code,
    "viz_skills": viz.get_code,
    "introspect_skills": introspect.get_code,
    "meta_skills": meta.get_code,
    "ml_skills": ml.get_code,
    "stats_skills": stats.get_code,
    "text_skills": text.get_code,
    "nlp_skills": nlp.get_code,
    "timeseries_skills": timeseries.get_code,
    "synthetic_skills": synthetic.get_code,
    "features_skills": features.get_code,
    "quality_skills": quality.get_code,
    "anomaly_skills": anomaly.get_code,
    "report_skills": report.get_code,
    "artifacts_skills": artifacts.get_code,
    "export_skills": export.get_code,
    "docs_skills": docs.get_code,
    "filesystem_skills": filesystem.get_code,
    "synth_skills": synth.get_code,
    "network_skills": network.get_code,
    "graph_skills": graph.get_code,
    "simulation_skills": None,
    "optimization_skills": optimization.get_code,
    "finance_skills": finance.get_code,
    "experiment_skills": experiment.get_code,
    "llm_tools_skills": llm_tools.get_code,
    "api_skills": api.get_code,
    "web_skills": web.get_code,
    "sql_skills": sql.get_code,
}


def test_skill_modules_are_registered():
    from kerno.skills.builtins import simulation
    expected = dict(EXPECTED_MODULES)
    expected["simulation_skills"] = simulation.get_code

    registered = dict(_bootstrap_module._SKILL_MODULES)
    assert set(registered) == set(expected)
    for name, code_fn in expected.items():
        assert registered[name] is code_fn
        ast.parse(code_fn())


def test_full_stack_composer_matches_bootstrap_domains():
    skill_set = composer.full_stack_skills()
    expected_domains = {
        "data", "viz", "introspect", "meta", "ml", "stats", "text", "nlp",
        "timeseries", "synthetic", "features", "quality", "anomaly", "report",
        "artifacts", "export", "docs", "filesystem", "synth", "network", "graph",
        "simulation", "optimization", "finance", "experiment", "llm_tools",
        "api", "web", "sql",
    }
    assert set(skill_set.names()) == expected_domains
    assert len(skill_set) == len(_bootstrap_module._SKILL_MODULES) == 29


@pytest.mark.parametrize("preset", [
    composer.nlp_skills,
    composer.timeseries_stack,
    composer.ml_skills,
    composer.minimal_skills,
])
def test_composer_presets(preset):
    skill_set = preset()
    assert len(skill_set) > 0


class TestOptionalPackSkipping:
    """Audit #16: skill bootstrap degrades gracefully on missing deps."""

    class ProbeKernel:
        """Captures the probe cell; returns the requested missing set."""

        def __init__(self, missing):
            self._missing = missing
            self.probe_code = ""

        def execute(self, code, timeout=120.0, silent=False, **kwargs):
            self.probe_code = code
            from kerno.types import CellOutput
            return CellOutput(stdout=repr(sorted(self._missing)) + "\n")

        def execute_silent(self, code, timeout=15.0, **kwargs):
            return ""

        @property
        def namespace(self):
            return "{}"

        @property
        def is_alive(self):
            return True

    def test_probe_sends_real_deps_not_placeholder(self):
        """Regression for the f-string bug: the probe cell must contain
        the actual dependency list, not the literal '{deps!r}'."""
        from kerno.skills.bootstrap import _probe_missing_deps
        kernel = self.ProbeKernel({"pandas"})
        result = _probe_missing_deps(kernel, ["pandas", "numpy"])
        assert result == {"pandas"}
        assert "{deps!r}" not in kernel.probe_code
        assert "['numpy', 'pandas']" in kernel.probe_code

    def test_probe_error_returns_empty(self):
        """On probe failure, preserve existing behavior (assume present)."""
        from kerno.skills.bootstrap import _probe_missing_deps

        class BrokenKernel(self.ProbeKernel):
            def execute(self, code, timeout=120.0, silent=False, **kwargs):
                from kerno.types import CellError, CellOutput
                return CellOutput(error=CellError("RuntimeError", "boom"))

        assert _probe_missing_deps(BrokenKernel({}), ["pandas"]) == set()

    def test_bootstrap_filters_modules_by_missing_deps(self, monkeypatch):
        """bootstrap() skips modules whose deps are missing — no crash."""
        import importlib
        B = importlib.import_module("kerno.skills.bootstrap")

        kernel = self.ProbeKernel({"pandas", "numpy", "matplotlib"})
        loaded = []
        monkeypatch.setattr(B.SkillRegistry, "load_code",
                            lambda self, k, code, name, protect=True:
                            loaded.append(name))

        reg = B.bootstrap(kernel, skip_missing_deps=True)

        # Data-dependent modules are skipped entirely
        assert "data_skills" not in loaded
        assert "viz_skills" not in loaded
        # Dependency-free modules still load (introspect has deps now, but
        # meta has none beyond IPython which is present)
        assert loaded, "at least the dep-free modules must load"

    def test_skip_missing_deps_false_loads_all(self, monkeypatch):
        """Explicit opt-out: skip_missing_deps=False keeps old behavior."""
        import importlib
        B = importlib.import_module("kerno.skills.bootstrap")

        kernel = self.ProbeKernel({"pandas"})
        loaded = []
        monkeypatch.setattr(B.SkillRegistry, "load_code",
                            lambda self, k, code, name, protect=True:
                            loaded.append(name))

        B.bootstrap(kernel, skip_missing_deps=False)
        assert "data_skills" in loaded   # no filtering at all
