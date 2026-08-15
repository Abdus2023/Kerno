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
    "network_skills": network.get_code,
    "graph_skills": graph.get_code,
    "simulation_skills": None,
    "optimization_skills": optimization.get_code,
    "finance_skills": finance.get_code,
    "experiment_skills": experiment.get_code,
    "llm_tools_skills": llm_tools.get_code,
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
        "artifacts", "export", "docs", "network", "graph", "simulation",
        "optimization", "finance", "experiment", "llm_tools", "web", "sql",
    }
    assert set(skill_set.names()) == expected_domains
    assert len(skill_set) == len(_bootstrap_module._SKILL_MODULES) == 26


@pytest.mark.parametrize("preset", [
    composer.nlp_skills,
    composer.timeseries_stack,
    composer.ml_skills,
    composer.minimal_skills,
])
def test_composer_presets(preset):
    skill_set = preset()
    assert len(skill_set) > 0
