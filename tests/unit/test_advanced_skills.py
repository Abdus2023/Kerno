"""Unit tests for advanced enriched skill modules."""

import ast
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from kerno.skills.builtins import (
    anomaly,
    artifacts,
    docs,
    experiment,
    export,
    features,
    finance,
    graph,
    llm_tools,
    meta,
    network,
    nlp,
    optimization,
    quality,
    report,
    simulation,
    synthetic,
    text,
    timeseries,
)


MODULES = [
    llm_tools, nlp, network, anomaly, docs, artifacts, simulation,
    finance, graph, optimization, experiment, meta, export,
]


@pytest.mark.parametrize("module", MODULES)
def test_advanced_skill_code_parses(module):
    ast.parse(module.get_code())


def _ns(module, monkeypatch):
    ns = {"pd": pd, "np": np}
    monkeypatch.setitem(ns, "display", lambda *a, **k: None)
    monkeypatch.setitem(ns, "HTML", lambda x: x)
    monkeypatch.setitem(ns, "Markdown", lambda x: x)
    monkeypatch.setitem(ns, "_display", ns["display"])
    exec(module.get_code(), ns)
    return ns


def test_nlp_sentiment_fallback_and_clustering(monkeypatch):
    ns = _ns(nlp, monkeypatch)
    builtins_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == "nltk":
            raise ImportError("nltk unavailable in test")
        return builtins_import(name, *args, **kwargs)

    import builtins
    monkeypatch.setattr(builtins, "__import__", fake_import)
    df = ns["analyze_sentiment"](["This is great and excellent", "Bad terrible awful", "It is okay"])
    assert set(df["label"]) <= {"Positive", "Negative", "Neutral"}

    docs = []
    for i in range(30):
        topic = i % 3
        words = ["alpha", "beta", "gamma"]
        docs.append(" ".join([words[topic]] * 10 + [f"unique{topic}{i}"]))
    labels = ns["cluster_documents"](docs, n_clusters=3)
    assert labels.nunique() == 3


def test_network_and_graph_modules(monkeypatch):
    pytest.importorskip("networkx")
    edges = pd.DataFrame({"src": [1, 2, 3, 4], "dst": [2, 3, 4, 1], "w": [1, 2, 3, 4]})
    ns1 = _ns(network, monkeypatch)
    G = ns1["build_network"](edges, "src", "dst", weight="w")
    metrics = ns1["analyze_network"](G, top_n=3)
    assert {"degree", "pagerank", "betweenness"} <= set(metrics.columns)

    ns2 = _ns(graph, monkeypatch)
    G2 = ns2["build_graph"](edges, "src", "dst", weight_col="w")
    centrality = ns2["graph_centrality"](G2)
    assert "pagerank" in centrality.columns


def test_anomaly_audit_drift_outliers(monkeypatch):
    ns = _ns(anomaly, monkeypatch)
    df = pd.DataFrame({
        "a": np.r_[np.random.normal(0, 1, 100), [100]],
        "b": np.r_[np.random.normal(0, 1, 100), [-100]],
    })
    audit = ns["data_quality_audit"](df)
    assert isinstance(audit["issues"], list)

    outliers = ns["detect_outliers_isolation_forest"](df, contamination=0.02)
    assert outliers["is_outlier"].dtype == bool
    assert outliers["is_outlier"].sum() >= 1

    drift = ns["detect_data_drift"](
        pd.DataFrame({"x": np.random.normal(0, 1, 200)}),
        pd.DataFrame({"x": np.random.normal(5, 1, 200)}),
    )
    assert drift.iloc[0]["drift_detected"] == "Significant"


def test_docs_chunk_and_patterns(monkeypatch):
    ns = _ns(docs, monkeypatch)
    chunks = ns["chunk_text"]("one\ntwo\nthree", chunk_size=8, overlap=2, separator="\n")
    assert chunks and all(len(c) <= 8 for c in chunks)
    emails = ns["extract_patterns"]("mail a@b.com or c@d.net", "emails")
    assert emails == ["a@b.com", "c@d.net"]


def test_artifacts_excel_and_export(tmp_path, monkeypatch):
    ns = _ns(artifacts, monkeypatch)
    xlsx = tmp_path / "book.xlsx"
    path = ns["to_excel_report"](str(xlsx), {"data": pd.DataFrame({"a": [1]})})
    assert pd.read_excel(path).shape == (1, 1)

    exp_ns = _ns(export, monkeypatch)
    json_path = exp_ns["save_artifact"]({"ok": True}, "result", format="json")
    assert pd.io.common.file_exists(json_path)


def test_simulation_and_optimization(monkeypatch):
    sim_ns = _ns(simulation, monkeypatch)

    def sim():
        return {"profit": np.random.normal(10, 2)}

    df = sim_ns["monte_carlo"](sim, n_sims=100)
    assert len(df) == 100

    opt_ns = _ns(optimization, monkeypatch)
    assignment = opt_ns["solve_assignment"]([[4, 1], [2, 3]])
    assert assignment["total_cost"] == 3

    portfolios = pd.DataFrame({
        "a": np.random.normal(0.001, 0.02, 200),
        "b": np.random.normal(0.0005, 0.01, 200),
    })
    portfolio = opt_ns["optimize_portfolio"](portfolios)
    assert "weights" in portfolio


def test_finance_and_experiment(monkeypatch):
    fin_ns = _ns(finance, monkeypatch)
    prices = pd.Series(np.linspace(100, 110, 50))
    returns = fin_ns["calculate_returns"](prices)
    assert len(returns) == 49
    dd = fin_ns["max_drawdown"](returns)
    assert "max_drawdown" in dd

    exp_ns = _ns(experiment, monkeypatch)
    power = exp_ns["power_analysis"](0.10, 0.02)
    assert power["required_n_per_variant"] > 0
    binary = exp_ns["ab_test"](np.zeros(100), np.r_[np.ones(5), np.zeros(95)], metric_type="binary")
    assert binary["significant_at_0.05"] in (True, False)


def test_meta_register_and_search(monkeypatch):
    ns = _ns(meta, monkeypatch)
    code = "def custom_add(a, b):\n    'Add two numbers.'\n    return a + b\n"
    assert ns["register_skill"]("custom_add", code) is True
    assert ns["custom_add"](2, 3) == 5
    matches = ns["search_skills"]("add numbers")
    assert "custom_add" in matches


def test_llm_tools_parse_and_classify(monkeypatch):
    ns = _ns(llm_tools, monkeypatch)
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.choices[0].message.content = "spam"
    fake_client.chat.completions.create.return_value = fake_response
    monkeypatch.setitem(ns, "_get_llm_client", lambda: fake_client)

    labels = ns["classify_texts"](["buy now", "hello"], labels=["spam", "ham"])
    assert labels.iloc[0] == "spam"

    fake_response.choices[0].message.content = '{"item": "x", "amount": 3}'
    table = ns["extract_structured"](["Give me x for 3"], schema={"item": "str", "amount": "int"})
    assert list(table.columns) == ["item", "amount"]
