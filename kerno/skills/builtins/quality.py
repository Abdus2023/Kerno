# kerno/skills/builtins/quality.py
"""
Built-in data quality skills.

Validation, deduplication, outlier detection, schema checks, and train/test
drift detection with compact HTML/console reporting.
"""

_QUALITY_SKILLS_CODE = r'''
import pandas as pd
import numpy as np
from IPython.display import display as _display, HTML as _HTML


def quality_report(df: pd.DataFrame) -> dict:
    """
    Comprehensive data quality report.

    Checks nulls, duplicates, types, ranges, cardinality, and constant columns.
    Returns a dict containing all quality metrics.
    """
    report = {
        "shape":            list(df.shape),
        "memory_mb":        round(df.memory_usage(deep=True).sum() / 1e6, 2),
        "null_total":       int(df.isnull().sum().sum()),
        "null_pct":         round(float(df.isnull().sum().sum() / max(df.size, 1) * 100), 2),
        "null_columns":     {k: int(v) for k, v in df.isnull().sum()[df.isnull().sum() > 0].to_dict().items()},
        "duplicate_rows":   int(df.duplicated().sum()),
        "duplicate_pct":    round(float(df.duplicated().mean() * 100), 2),
        "constant_columns": [c for c in df.columns if df[c].nunique(dropna=True) <= 1],
        "high_cardinality": [c for c in df.columns if df[c].nunique(dropna=True) > 100],
        "numeric_cols":     len(df.select_dtypes(include=np.number).columns),
        "categorical_cols": len(df.select_dtypes(include=["object", "string", "category", "bool"]).columns),
        "datetime_cols":    len(df.select_dtypes(include=["datetime", "datetimetz"]).columns),
        "boolean_cols":     len(df.select_dtypes(include=["bool"]).columns),
    }

    range_issues = {}
    for col in df.select_dtypes(include=np.number).columns:
        s = df[col]
        if s.isnull().all():
            continue
        if col.lower() not in ("latitude", "longitude") and (s < 0).any():
            neg_count = int((s < 0).sum())
            if neg_count > 0:
                range_issues[col] = f"{neg_count} negative values"
        if np.isinf(s.to_numpy(dtype=float, copy=False)).any():
            range_issues[col] = "contains infinite values"
    report["range_issues"] = range_issues

    null_color = "red" if report["null_total"] > 0 else "green"
    rows = [
        f"<tr><td>Shape</td><td>{df.shape[0]:,} × {df.shape[1]}</td></tr>",
        f"<tr><td>Memory</td><td>{report['memory_mb']} MB</td></tr>",
        f"<tr><td>Nulls</td><td style='color:{null_color}'>"
        f"{report['null_total']:,} ({report['null_pct']}%)</td></tr>",
        f"<tr><td>Duplicates</td><td>{report['duplicate_rows']:,} ({report['duplicate_pct']}%)</td></tr>",
        f"<tr><td>Constant cols</td><td>{len(report['constant_columns'])}</td></tr>",
    ]
    _display(_HTML(
        "<table style='font-family:monospace;font-size:12px'>"
        "<tr><th colspan='2'>📋 Data Quality Report</th></tr>"
        + "".join(rows) + "</table>"
    ))

    if report["null_columns"]:
        print(f"  Null columns: {list(report['null_columns'].keys())}")
    if range_issues:
        print(f"  Range issues: {range_issues}")
    return report


def detect_duplicates(
    df: pd.DataFrame,
    subset: list = None,
    strategy: str = "report",
) -> pd.DataFrame:
    """
    Detect and optionally remove duplicate rows.

    strategy: "report" (default), "drop_first", "drop_last", or "drop_all".
    """
    if strategy not in {"report", "drop_first", "drop_last", "drop_all"}:
        raise ValueError(
            "strategy must be report, drop_first, drop_last, or drop_all"
        )

    mask = df.duplicated(subset=subset, keep=False)
    duplicates = df[mask]
    n_dupes    = len(duplicates)
    print(f"✓ Found {n_dupes:,} duplicate rows ({n_dupes / max(len(df), 1):.1%})")

    if strategy == "report":
        return duplicates
    if strategy == "drop_first":
        cleaned = df.drop_duplicates(subset=subset, keep="first")
    elif strategy == "drop_last":
        cleaned = df.drop_duplicates(subset=subset, keep="last")
    else:
        cleaned = df.drop_duplicates(subset=subset, keep=False)

    print(f"  Dropped {len(df) - len(cleaned):,} rows (strategy={strategy})")
    return cleaned


def detect_outliers(
    df: pd.DataFrame,
    columns: list = None,
    method: str = "iqr",
    threshold: float = None,
) -> dict:
    """
    Detect univariate outliers in numeric columns.

    method: "iqr" (Tukey fences, default multiplier 1.5) or "zscore"
    (default threshold 3.0). Pass ``threshold`` to override either default.
    Returns: {column: {count, pct, indices, bounds}}.
    """
    if threshold is None:
        threshold = 1.5 if method == "iqr" else 3.0
    if columns is None:
        columns = df.select_dtypes(include=np.number).columns.tolist()

    results = {}
    for col in columns:
        if col not in df.columns:
            continue
        s = df[col].dropna()
        if len(s) == 0:
            continue

        if method == "iqr":
            q1, q3 = s.quantile(0.25), s.quantile(0.75)
            iqr    = q3 - q1
            lower  = q1 - threshold * iqr
            upper  = q3 + threshold * iqr
            mask   = (s < lower) | (s > upper)
        elif method == "zscore":
            mean, std = s.mean(), s.std()
            z      = (s - mean) / (std + 1e-12)
            mask   = z.abs() > threshold
            lower, upper = mean - threshold * std, mean + threshold * std
        else:
            raise ValueError("method must be 'iqr' or 'zscore'")

        outlier_indices = s[mask].index.tolist()
        results[col] = {
            "count":   len(outlier_indices),
            "pct":     round(len(outlier_indices) / len(s) * 100, 2),
            "indices": outlier_indices[:20],
            "bounds":  (round(float(lower), 4), round(float(upper), 4)),
        }

    total_outliers = sum(r["count"] for r in results.values())
    print(f"✓ Outlier detection ({method}): {total_outliers:,} total outliers")
    for col, info in results.items():
        if info["count"] > 0:
            print(f"  {col}: {info['count']} ({info['pct']}%) "
                  f"bounds=[{info['bounds'][0]}, {info['bounds'][1]}]")
    return results


def validate_schema(df: pd.DataFrame, expected: dict) -> dict:
    """
    Validate a DataFrame against an expected schema.

    expected maps column name to a dtype substring (e.g. "int64", "object").
    Returns {passed, issues, actual_schema}.
    """
    issues = []
    actual = {c: str(t) for c, t in df.dtypes.items()}

    missing = set(expected) - set(actual)
    for col in sorted(missing):
        issues.append(f"Missing column: '{col}'")

    extra = set(actual) - set(expected)
    if extra:
        issues.append(f"Extra columns: {sorted(extra)}")

    for col, expected_type in expected.items():
        if col in actual and expected_type not in actual[col]:
            issues.append(
                f"Type mismatch: '{col}' expected {expected_type}, got {actual[col]}"
            )

    passed = not issues
    status = "✅ PASSED" if passed else "❌ FAILED"
    print(f"Schema validation: {status}")
    for issue in issues:
        print(f"  • {issue}")
    return {"passed": passed, "issues": issues, "actual_schema": actual}


def detect_drift(
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
    columns: list = None,
) -> dict:
    """
    Detect data drift between train and test sets.

    A column is flagged when the mean shift exceeds 0.5 train standard deviations
    or the standard deviation ratio is outside [0.5, 2.0].
    """
    if columns is None:
        columns = [
            c for c in df_train.select_dtypes(include=np.number).columns
            if c in df_test.columns
        ]

    results = {}
    for col in columns:
        train_vals = df_train[col].dropna()
        test_vals  = df_test[col].dropna()
        if len(train_vals) == 0 or len(test_vals) == 0:
            continue

        train_std = float(train_vals.std())
        mean_shift = abs(float(test_vals.mean()) - float(train_vals.mean())) / (train_std + 1e-12)
        std_ratio  = float(test_vals.std()) / (train_std + 1e-12)

        drifted = bool(mean_shift > 0.5 or std_ratio > 2 or std_ratio < 0.5)
        results[col] = {
            "mean_shift": round(float(mean_shift), 4),
            "std_ratio":  round(float(std_ratio), 4),
            "drifted":    drifted,
        }

    n_drifted = sum(1 for r in results.values() if r["drifted"])
    print(f"✓ Drift detection: {n_drifted}/{len(results)} columns drifted")
    for col, info in results.items():
        if info["drifted"]:
            print(f"  ⚠️  {col}: mean_shift={info['mean_shift']}, std_ratio={info['std_ratio']}")
    return results
'''


def get_code() -> str:
    """Return the source code string for these skills."""
    return _QUALITY_SKILLS_CODE
