# kerno/skills/builtins/anomaly.py
"""
Built-in anomaly detection and data-quality auditing skills.

These skills complement ``quality.py`` with multivariate outlier detection,
visual missingness reports, and distribution-drift tests.
"""

_ANOMALY_SKILLS_CODE = r'''
import pandas as pd
import numpy as np
from IPython.display import display as _display, HTML as _HTML


def data_quality_audit(df: pd.DataFrame) -> dict:
    """
    Audit data quality issues.

    Checks high missingness, duplicates, infinite numeric values, constant
    columns, and high-cardinality categoricals.
    """
    issues = []
    rows = len(df)

    missing_pct = (df.isnull().sum() / max(rows, 1) * 100).sort_values(ascending=False)
    high_missing = missing_pct[missing_pct > 5]
    if not high_missing.empty:
        issues.append(f"High missing values (>5%): {high_missing.round(2).to_dict()}")

    duplicate_count = int(df.duplicated().sum())
    if duplicate_count:
        issues.append(f"Duplicate rows: {duplicate_count} ({duplicate_count / max(rows, 1):.1%})")

    numeric = df.select_dtypes(include=np.number)
    infinite_cols = [
        c for c in numeric.columns
        if np.isinf(numeric[c].to_numpy(dtype=float, na_value=np.nan)).any()
    ]
    if infinite_cols:
        issues.append(f"Infinite values in columns: {infinite_cols}")

    constant_cols = [c for c in numeric.columns if numeric[c].nunique(dropna=True) <= 1]
    if constant_cols:
        issues.append(f"Constant numeric columns: {constant_cols}")

    for col in df.select_dtypes(include=["object", "string", "category"]).columns:
        unique = df[col].nunique(dropna=True)
        ratio = unique / max(rows, 1)
        if ratio > 0.5 and unique > 50:
            issues.append(
                f"High cardinality in '{col}': {unique} unique values ({ratio:.1%})"
            )

    color = "red" if issues else "green"
    title = "⚠️ Issues Found" if issues else "✅ Clean"
    html = f"<h3 style='color:{color}'>Data Quality Audit: {title}</h3>"
    if issues:
        html += "<ul>" + "".join(f"<li>{item}</li>" for item in issues) + "</ul>"
    else:
        html += "<p>No critical data quality issues detected.</p>"
    _display(_HTML(html))

    return {"issues": issues, "missing_pct": missing_pct.to_dict()}


def detect_outliers_isolation_forest(
    df: pd.DataFrame,
    columns: list = None,
    contamination: float = 0.05,
) -> pd.DataFrame:
    """
    Detect multivariate outliers with Isolation Forest.

    Returns a copy of the original DataFrame with ``is_outlier`` and
    ``anomaly_score`` columns for rows with complete selected numeric values.
    """
    from sklearn.ensemble import IsolationForest

    if columns is None:
        columns = df.select_dtypes(include=np.number).columns.tolist()
    columns = [c for c in columns if c in df.columns]
    if not columns:
        raise ValueError("No numeric columns available for anomaly detection")

    X = df[columns].copy()
    # Impute only for fit/predict; retain original rows for other columns.
    X_complete = X.dropna()
    if X_complete.empty:
        raise ValueError("All selected rows contain missing values")

    model = IsolationForest(contamination=contamination, random_state=42)
    predictions = model.fit_predict(X_complete)
    scores = model.decision_function(X_complete)

    result = df.copy()
    result["is_outlier"] = pd.NA
    result["anomaly_score"] = pd.NA
    result.loc[X_complete.index, "is_outlier"] = predictions == -1
    result.loc[X_complete.index, "anomaly_score"] = scores
    result["is_outlier"] = result["is_outlier"].fillna(False).astype(bool)

    n_outliers = int(result.loc[X_complete.index, "is_outlier"].sum())
    print(f"✓ Detected {n_outliers} outliers ({n_outliers / len(X_complete):.1%})")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(scores, bins=50, color="#0072B2", edgecolor="white", alpha=0.8)
    ax.axvline(model.offset_, color="#D55E00", linestyle="--", label="Threshold")
    ax.set_title("Anomaly Score Distribution")
    ax.legend()
    fig.tight_layout()
    _display(fig)
    plt.close(fig)
    return result


def profile_missingness(df: pd.DataFrame, max_cols: int = 30) -> dict:
    """
    Visualize missing data and return missing percentages.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pct = df.isnull().mean().mul(100).sort_values(ascending=False)
    missing = pct[pct > 0].head(max_cols)
    if missing.empty:
        print("✓ No missing values found.")
        return {"status": "clean", "missing_pct": {}}

    print(f"⚠️ Missing values in {len(missing)} columns")
    _display(missing.to_frame("missing_pct"))

    sample = df.sample(min(1000, len(df)), random_state=42) if len(df) > 1000 else df
    cols = missing.index.tolist()[::-1]
    fig, ax = plt.subplots(figsize=(10, max(4, len(cols) * 0.3)))
    ax.imshow(sample[cols].isnull().values, aspect="auto", cmap="viridis", interpolation="none")
    ax.set_yticks([])
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(cols, rotation=45, ha="right")
    ax.set_title("Missing Data Matrix")
    fig.tight_layout()
    _display(fig)
    plt.close(fig)
    return {"status": "missing", "missing_pct": pct.to_dict()}


def detect_data_drift(
    df_old: pd.DataFrame,
    df_new: pd.DataFrame,
    columns: list = None,
) -> pd.DataFrame:
    """
    Compare numeric distributions between two datasets via KS tests.
    """
    from scipy.stats import ks_2samp

    if columns is None:
        columns = [
            c for c in df_old.select_dtypes(include=np.number).columns
            if c in df_new.columns
        ]

    rows = []
    for col in columns:
        old = df_old[col].dropna()
        new = df_new[col].dropna()
        if len(old) < 10 or len(new) < 10:
            continue
        stat, p_value = ks_2samp(old, new)
        rows.append({
            "column": col,
            "ks_statistic": round(float(stat), 4),
            "p_value": round(float(p_value), 6),
            "drift_detected": "Significant" if p_value < 0.05 else "None",
        })

    result = pd.DataFrame(rows).sort_values("p_value")
    print(f"✓ Drift analysis complete for {len(result)} numeric columns")
    _display(result)
    return result
'''


def get_code() -> str:
    return _ANOMALY_SKILLS_CODE
