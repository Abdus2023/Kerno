"""Tests covering the enriched built-in skill inventory and bootstrap wiring."""

import ast

import importlib

_bootstrap_module = importlib.import_module("kerno.skills.bootstrap")
from kerno.skills.bootstrap import (
    bootstrap,
    bootstrap_ml,
    bootstrap_nlp,
    bootstrap_timeseries,
)
from kerno.skills import composer
from kerno.skills.builtins import (
    data,
    features,
    introspect,
    ml,
    quality,
    report,
    sql,
    stats,
    synthetic,
    text,
    timeseries,
    viz,
    web,
)


EXPECTED_MODULES = {
    "data_skills":       data.get_code,
    "viz_skills":        viz.get_code,
    "introspect_skills": introspect.get_code,
    "ml_skills":         ml.get_code,
    "stats_skills":      stats.get_code,
    "text_skills":       text.get_code,
    "timeseries_skills": timeseries.get_code,
    "synthetic_skills":  synthetic.get_code,
    "features_skills":   features.get_code,
    "quality_skills":    quality.get_code,
    "report_skills":     report.get_code,
    "web_skills":        web.get_code,
    "sql_skills":        sql.get_code,
}


def test_skill_modules_are_registered():
    registered = dict(_bootstrap_module._SKILL_MODULES)
    assert set(registered) == set(EXPECTED_MODULES)
    for name, code_fn in EXPECTED_MODULES.items():
        assert registered[name] is code_fn
        ast.parse(code_fn())


def test_full_stack_composer_matches_bootstrap_modules():
    skill_set = composer.full_stack_skills()
    # The names in SkillSet differ slightly from bootstrap module suffixes,
    # but every domain should be represented exactly once.
    expected_domains = {
        "data", "viz", "introspect", "ml", "stats", "text", "timeseries",
        "synthetic", "features", "quality", "report", "web", "sql",
    }
    assert set(skill_set.names()) == expected_domains
    assert len(skill_set) == 13


def test_domain_composer_presets():
    assert composer.nlp_skills().names().count("text") == 1
    assert composer.timeseries_stack().names().count("timeseries") == 1
