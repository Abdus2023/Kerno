"""Unit tests for the enriched built-in skill modules (Part I).

These tests verify:
  - Each module and its code-string payload parse as valid Python
  - The expected public skill functions are defined
  - A representative sample of pure/pandas-level functions executes correctly
    without a live Jupyter kernel (display calls are monkeypatched out)
"""

import ast
import textwrap

import numpy as np
import pandas as pd
import pytest

from kerno.skills.builtins import (
    features,
    quality,
    report,
    synthetic,
    text,
    timeseries,
)


MODULES = [
    (text, "text_skills", [
        "text_stats", "word_frequencies", "clean_text", "ngrams",
        "sentiment_score", "extract_emails", "extract_hashtags", "extract_keywords",
    ]),
    (timeseries, "timeseries_skills", [
        "ts_prepare", "ts_decompose", "ts_summary", "ts_forecast_linear",
        "ts_detect_anomalies", "ts_seasonality_check",
    ]),
    (synthetic, "synthetic_skills", [
        "generate_sales", "generate_customers", "generate_classification",
        "generate_regression", "generate_timeseries", "generate_transactions",
    ]),
    (features, "features_skills", [
        "auto_encode", "add_date_features", "add_interaction_features",
        "add_aggregation_features", "add_lag_features", "select_features",
    ]),
    (quality, "quality_skills", [
        "quality_report", "detect_duplicates", "detect_outliers",
        "validate_schema", "detect_drift",
    ]),
    (report, "report_skills", [
        "generate_report", "summary_table", "comparison_table",
        "executive_summary", "data_dictionary", "save_results",
    ]),
]


@pytest.mark.parametrize("module,_name,_fns", MODULES)
def test_module_file_syntax(module, _name, _fns):
    with open(module.__file__) as f:
        ast.parse(f.read())


@pytest.mark.parametrize("module,_name,_fns", MODULES)
def test_code_string_syntax(module, _name, _fns):
    ast.parse(module.get_code())


@pytest.mark.parametrize("module,_name,fns", MODULES)
def test_expected_functions_defined(module, _name, fns):
    code = module.get_code()
    for fn in fns:
        assert f"def {fn}(" in code, f"{fn} missing from {module.__name__}"


def _exec_module(module, monkeypatch):
    """Execute a skill code string in a namespace with display/no-op rendering."""
    # Avoid opening matplotlib windows; imported skills set Agg themselves.
    ns = {"pd": pd, "np": np}
    monkeypatch.setitem(ns, "display", lambda *a, **k: None)
    monkeypatch.setitem(ns, "HTML", lambda x: x)
    monkeypatch.setitem(ns, "Markdown", lambda x: x)
    monkeypatch.setitem(ns, "_display", ns["display"])
    exec(module.get_code(), ns)  # noqa: S102 - trusted built-in skill code
    return ns


# ── Text ─────────────────────────────────────────────────────────────────────

def test_text_stats_and_sentiment(monkeypatch):
    ns = _exec_module(text, monkeypatch)
    s = pd.Series([
        "Good great amazing product",
        "Bad terrible awful experience",
        "I love this great item",
        None,
    ])
    stats = ns["text_stats"](s)
    assert stats["non_null"] == 3
    assert stats["avg_words"] > 0
    assert "great" in dict(stats["top_words"])

    sentiment = ns["sentiment_score"](s)
    assert set(sentiment["label"]).issubset({"positive", "negative", "neutral"})


def test_clean_text_and_extract_emails(monkeypatch):
    ns = _exec_module(text, monkeypatch)
    s = pd.Series(["<p>Hello  WORLD</p>", "Visit https://example.com now", None])
    cleaned = ns["clean_text"](s, remove_digits=False)
    assert "<p>" not in cleaned.iloc[0]
    assert "https" not in cleaned.iloc[1]

    emails = ns["extract_emails"](pd.Series(["reach me at a@example.com or b@test.io"]))
    assert len(emails) == 2


def test_ngrams_and_hashtags(monkeypatch):
    ns = _exec_module(text, monkeypatch)
    grams = ns["ngrams"](["new york city", "new york pizza"], n=2, top_k=5)
    assert "new york" in set(grams["ngram"])

    tags = ns["extract_hashtags"](pd.Series(["#data #ml", "#data again"]))
    row = tags[tags["hashtag"] == "#data"].iloc[0]
    assert row["count"] == 2


# ── Time series ───────────────────────────────────────────────────────────────

def test_ts_prepare_summary_forecast(monkeypatch):
    ns = _exec_module(timeseries, monkeypatch)
    df = pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=120, freq="D"),
        "value": np.arange(120) + np.sin(np.arange(120) / 7) * 5,
    })
    s = ns["ts_prepare"](df, "date", "value")
    assert isinstance(s, pd.Series)
    assert len(s) == 120

    summary = ns["ts_summary"](s)
    assert summary["trend_direction"] == "increasing"

    forecast = ns["ts_forecast_linear"](s, horizon=5, plot=False)
    assert len(forecast["forecast"]) == 5
    assert 0 <= forecast["r_squared"] <= 1.0001


def test_ts_decompose_and_anomalies(monkeypatch):
    ns = _exec_module(timeseries, monkeypatch)
    df = pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=180, freq="D"),
        "value": 100 + np.arange(180) * 0.1 + 10 * np.sin(np.arange(180) * 2 * np.pi / 7),
    })
    s = ns["ts_prepare"](df, "date", "value")
    result = ns["ts_decompose"](s, period=7)
    assert result["period"] == 7
    assert {"trend", "seasonal", "residual"} <= result.keys()

    s_with_outlier = s.copy()
    s_with_outlier.iloc[100] = s.max() + 500
    anomalies = ns["ts_detect_anomalies"](s_with_outlier, method="zscore", threshold=3)
    assert len(anomalies) >= 1


# ── Synthetic ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("generator,expected_cols", [
    ("generate_sales", ["date", "region", "revenue"]),
    ("generate_customers", ["customer_id", "churn_flag"]),
    ("generate_timeseries", ["date", "value"]),
    ("generate_transactions", ["transaction_id", "is_fraud"]),
])
def test_synthetic_generators(monkeypatch, generator, expected_cols):
    ns = _exec_module(synthetic, monkeypatch)
    df = ns[generator](n=100) if generator == "generate_sales" else ns[generator]()
    for col in expected_cols:
        assert col in df.columns


def test_synthetic_ml_datasets(monkeypatch):
    ns = _exec_module(synthetic, monkeypatch)
    cls = ns["generate_classification"](n_samples=80, n_features=4, n_classes=2)
    assert cls.shape == (80, 5)
    assert set(cls["target"].unique()).issubset({0, 1})

    reg = ns["generate_regression"](n_samples=80, n_features=3)
    assert reg.shape == (80, 4)
    assert reg["target"].dtype.kind == "f"


# ── Feature engineering ───────────────────────────────────────────────────────

def test_auto_encode(monkeypatch):
    ns = _exec_module(features, monkeypatch)
    df = pd.DataFrame({
        "category": ["a", "b", "a", "c", "b"],
        "id":       ["u1", "u2", "u3", "u4", "u5"],
        "target":   [1, 0, 1, 0, 1],
    })
    X, y, report = ns["auto_encode"](df, target="target", max_cardinality=3)
    assert y.name == "target"
    assert "category_a" in X.columns or "category_b" in X.columns
    assert X["id"].dtype.kind in "i"
    assert "one_hot" in report and "label_encoded" in report


def test_date_interaction_and_aggregation(monkeypatch):
    ns = _exec_module(features, monkeypatch)
    df = pd.DataFrame({
        "ds": pd.date_range("2024-01-01", periods=5, freq="h"),
        "a":  [1, 2, 3, 4, 5],
        "b":  [2, 3, 4, 5, 6],
        "g":  ["x", "x", "y", "y", "y"],
    })
    dated = ns["add_date_features"](df, "ds")
    assert "ds_year" in dated.columns
    assert "ds_hour" in dated.columns
    assert "ds" not in dated.columns

    inter = ns["add_interaction_features"](df, ["a", "b"])
    assert "a_sq" in inter.columns and "a_x_b" in inter.columns

    agg = ns["add_aggregation_features"](df, "g", "a", aggs=["mean", "count"])
    assert "a_mean_by_g" in agg.columns


def test_lag_features(monkeypatch):
    ns = _exec_module(features, monkeypatch)
    df = pd.DataFrame({"t": range(10), "v": range(10)})
    out = ns["add_lag_features"](df, "v", lags=[1, 2], sort_col="t")
    assert "v_lag_1" in out.columns and "v_rolling_mean_7" in out.columns
    assert pd.isna(out["v_lag_1"].iloc[0])


# ── Quality ───────────────────────────────────────────────────────────────────

def test_quality_report_duplicates_and_schema(monkeypatch):
    ns = _exec_module(quality, monkeypatch)
    df = pd.DataFrame({
        "id":   [1, 2, 2, 4],
        "cat":  ["a", "b", "b", None],
        "num":  [1.0, 2.0, 2.0, -5.0],
    })
    rep = ns["quality_report"](df)
    assert rep["duplicate_rows"] == 1
    assert rep["null_total"] == 1
    assert "num" in rep["range_issues"]

    dupes = ns["detect_duplicates"](df, strategy="report")
    assert len(dupes) == 2

    schema = ns["validate_schema"](
        df, {"id": "int", "cat": "str", "num": "float"}
    )
    assert schema["passed"] is True


def test_outliers_and_drift(monkeypatch):
    ns = _exec_module(quality, monkeypatch)
    df = pd.DataFrame({"x": [1, 2, 3, 4, 5, 100]})
    outliers = ns["detect_outliers"](df, columns=["x"], method="iqr")
    assert outliers["x"]["count"] >= 1

    train = pd.DataFrame({"x": np.random.normal(0, 1, 200)})
    test  = pd.DataFrame({"x": np.random.normal(5, 1, 200)})
    drift = ns["detect_drift"](train, test, columns=["x"])
    assert drift["x"]["drifted"] is True


# ── Reporting ─────────────────────────────────────────────────────────────────

def test_generate_report_and_summary(tmp_path, monkeypatch):
    ns = _exec_module(report, monkeypatch)
    path = tmp_path / "report.md"
    md = ns["generate_report"](
        "Title",
        [{"heading": "Section", "content": "Hello"}],
        metadata={"author": "tests"},
        save_path=str(path),
    )
    assert "# Title" in md and "Hello" in md
    assert path.exists()

    summary = ns["summary_table"](pd.DataFrame({"a": range(3)}))
    assert set(summary.columns) == {"Metric", "Value"}


def test_comparison_table_and_save_results(tmp_path, monkeypatch):
    ns = _exec_module(report, monkeypatch)
    comp = ns["comparison_table"](
        {"model_a": {"score": 0.9}, "model_b": {"score": 0.8}},
        metric="score",
    )
    assert comp.iloc[0]["Model"] == "model_a"
    assert comp.iloc[0]["Rank"] == 1

    out = tmp_path / "results.json"
    returned = ns["save_results"]({"ok": True}, str(out), format="json")
    assert out.exists() and returned
