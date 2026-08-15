# kerno/skills/builtins/features.py
"""
Built-in feature engineering skills.

Automates the most common transformations with intelligent defaults:
encoding, date features, interactions, aggregations, lags, and feature selection.
"""

_FEATURES_SKILLS_CODE = r'''
import pandas as pd
import numpy as np
from IPython.display import display as _display, HTML as _HTML


def auto_encode(
    df: pd.DataFrame,
    target: str = None,
    max_cardinality: int = 10,
) -> tuple:
    """
    Automatically encode categorical columns.

    Low-cardinality columns are one-hot encoded; higher-cardinality columns
    are label encoded (pandas category codes).

    Returns:
        (X, y, report) where y is the target Series (or None).
    """
    X = df.drop(columns=[target]) if target in df.columns else df.copy()
    y = df[target] if target in df.columns else None
    report = {"one_hot": [], "label_encoded": [], "dropped": []}

    try:
        cat_cols = X.select_dtypes(include=["object", "string", "category"]).columns.tolist()
    except TypeError:  # older pandas
        cat_cols = X.select_dtypes(include=["object", "category"]).columns.tolist()
    for col in cat_cols:
        n_unique = X[col].nunique(dropna=True)
        if n_unique <= max_cardinality:
            dummies = pd.get_dummies(X[col], prefix=col, drop_first=True)
            X = pd.concat([X.drop(columns=[col]), dummies], axis=1)
            report["one_hot"].append(f"{col} ({n_unique} categories)")
        else:
            X[col] = X[col].astype("category").cat.codes
            report["label_encoded"].append(f"{col} ({n_unique} categories)")

    print("✓ Encoding complete:")
    print(f"  One-hot:       {len(report['one_hot'])} columns")
    print(f"  Label encoded: {len(report['label_encoded'])} columns")
    print(f"  Final shape:   {X.shape}")
    return X, y, report


def add_date_features(
    df: pd.DataFrame,
    date_col: str,
    drop_original: bool = True,
) -> pd.DataFrame:
    """
    Extract rich date features from a datetime column.

    Adds year, month, day, dayofweek, quarter, is_weekend, week, and hour
    (when timestamps contain a non-zero hour component).
    """
    if date_col not in df.columns:
        raise KeyError(f"Column '{date_col}' not found")

    out = df.copy()
    dt  = pd.to_datetime(out[date_col], errors="coerce")

    out[f"{date_col}_year"]       = dt.dt.year
    out[f"{date_col}_month"]      = dt.dt.month
    out[f"{date_col}_day"]        = dt.dt.day
    out[f"{date_col}_dayofweek"]  = dt.dt.dayofweek
    out[f"{date_col}_quarter"]    = dt.dt.quarter
    out[f"{date_col}_is_weekend"] = (dt.dt.dayofweek >= 5).astype("Int64")
    out[f"{date_col}_week"]       = dt.dt.isocalendar().week.astype("Int64")

    if dt.dt.hour.notna().any() and (dt.dt.hour.fillna(0) != 0).any():
        out[f"{date_col}_hour"] = dt.dt.hour

    if drop_original:
        out = out.drop(columns=[date_col])

    added = [c for c in out.columns if c.startswith(f"{date_col}_")]
    print(f"✓ Added {len(added)} date features from '{date_col}'")
    return out


def add_interaction_features(
    df: pd.DataFrame,
    columns: list,
    degree: int = 2,
) -> pd.DataFrame:
    """
    Add polynomial/interaction features.

    For degree >= 2, adds squared terms (col_sq) and pairwise products
    (a_x_b) for the supplied numeric columns.
    """
    out  = df.copy()
    cols = [c for c in columns if c in out.columns]
    missing = [c for c in columns if c not in out.columns]
    if missing:
        print(f"⚠️  Ignoring missing columns: {missing}")

    if degree >= 2:
        for col in cols:
            out[f"{col}_sq"] = pd.to_numeric(out[col], errors="coerce") ** 2

    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            out[f"{cols[i]}_x_{cols[j]}"] = (
                pd.to_numeric(out[cols[i]], errors="coerce")
                * pd.to_numeric(out[cols[j]], errors="coerce")
            )

    print(f"✓ Added interaction features → shape: {out.shape}")
    return out


def add_aggregation_features(
    df: pd.DataFrame,
    group_col: str,
    agg_col: str,
    aggs: list = None,
) -> pd.DataFrame:
    """
    Add group-level aggregation features (target-encoding style).

    For each aggregation in ``aggs`` (default mean, std, count), a column
    named ``{agg_col}_{agg}_by_{group_col}`` is added via transform().
    """
    if aggs is None:
        aggs = ["mean", "std", "count"]
    if group_col not in df.columns or agg_col not in df.columns:
        raise KeyError(f"Need both '{group_col}' and '{agg_col}' in DataFrame")

    out     = df.copy()
    grouped = out.groupby(group_col, dropna=False)[agg_col]
    for agg in aggs:
        out[f"{agg_col}_{agg}_by_{group_col}"] = grouped.transform(agg)

    print(f"✓ Added {len(aggs)} aggregation features: {aggs}")
    return out


def add_lag_features(
    df: pd.DataFrame,
    value_col: str,
    lags: list = None,
    sort_col: str = None,
) -> pd.DataFrame:
    """
    Add lag and rolling features for sequential/time-series data.

    Creates value_col_lag_{lag} for each requested lag, plus
    7-period rolling mean and standard deviation.
    """
    if lags is None:
        lags = [1, 7, 30]
    if value_col not in df.columns:
        raise KeyError(f"Column '{value_col}' not found")

    out = df.copy()
    if sort_col:
        out = out.sort_values(sort_col).reset_index(drop=True)

    for lag in lags:
        out[f"{value_col}_lag_{lag}"] = out[value_col].shift(lag)

    out[f"{value_col}_rolling_mean_7"] = out[value_col].rolling(7).mean()
    out[f"{value_col}_rolling_std_7"]  = out[value_col].rolling(7).std()

    print(f"✓ Added {len(lags)} lag features + rolling features")
    return out


def select_features(
    X,
    y,
    method:    str   = "importance",
    top_k:     int   = 15,
    threshold: float = 0.01,
) -> tuple:
    """
    Select top features using one of several methods.

    method:
      - "importance":    RandomForest feature importances
      - "correlation":   absolute correlation with y
      - "variance":      low variance filtering

    Returns:
        (X_selected, selected_names, scores)
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if method == "correlation":
        if isinstance(X, pd.DataFrame):
            scores = X.apply(
                lambda c: pd.Series(c).corr(pd.Series(y))
            ).abs().sort_values(ascending=False)
        else:
            X_arr = np.asarray(X)
            y_arr = np.asarray(y)
            scores = pd.Series(
                [abs(np.corrcoef(X_arr[:, i], y_arr)[0, 1]) for i in range(X_arr.shape[1])],
                index=[f"f{i}" for i in range(X_arr.shape[1])],
            ).sort_values(ascending=False)
        selected = scores.head(top_k).index.tolist()

    elif method == "variance":
        if isinstance(X, pd.DataFrame):
            scores = X.var(numeric_only=True).sort_values(ascending=False)
        else:
            scores = pd.Series(np.asarray(X).var(axis=0))
        selected = scores[scores > threshold].head(top_k).index.tolist()

    else:  # importance
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

        y_arr = np.asarray(y)
        n_unique = len(pd.unique(y_arr.ravel()))
        if n_unique <= 20:
            model = RandomForestClassifier(n_estimators=50, random_state=42, n_jobs=-1)
        else:
            model = RandomForestRegressor(n_estimators=50, random_state=42, n_jobs=-1)
        model.fit(X, y_arr)

        index = X.columns if isinstance(X, pd.DataFrame) else range(np.asarray(X).shape[1])
        scores = pd.Series(model.feature_importances_, index=index).sort_values(ascending=False)
        selected = scores.head(top_k).index.tolist()

    plot_scores = scores.head(top_k)
    if len(plot_scores) > 0:
        fig, ax = plt.subplots(figsize=(10, max(4, len(plot_scores) * 0.35)))
        ax.barh(range(len(plot_scores)), plot_scores.values[::-1], color="#0072B2")
        ax.set_yticks(range(len(plot_scores)))
        ax.set_yticklabels(plot_scores.index[::-1])
        ax.set_xlabel("Score")
        ax.set_title(f"Top {len(plot_scores)} Features ({method})")
        fig.tight_layout()
        _display(fig)
        plt.close(fig)

    X_selected = X[selected] if isinstance(X, pd.DataFrame) else np.asarray(X)[:, selected]
    print(f"✓ Selected {len(selected)} features ({method})")
    return X_selected, selected, scores
'''


def get_code() -> str:
    """Return the source code string for these skills."""
    return _FEATURES_SKILLS_CODE
