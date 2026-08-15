# kerno/skills/builtins/synth.py
"""
Built-in synthetic data and privacy skills.

This module provides compact business-oriented mock datasets and PII
anonymization helpers for demos, tests, and reproducible pipelines.
"""

_SYNTH_SKILLS_CODE = r'''
import hashlib as _hashlib

import numpy as np
import pandas as pd
from IPython.display import display as _display


def mock_sales(n_rows: int = 1000, seed: int = 42) -> pd.DataFrame:
    """
    Generate realistic e-commerce sales records.

    Columns: order_id, date, region, product_category, units, revenue, is_return.
    """
    np.random.seed(seed)
    dates = pd.date_range(end=pd.Timestamp.now().normalize(), periods=365, freq="D")
    regions = ["North", "South", "East", "West"]
    categories = ["Electronics", "Apparel", "Home", "Books"]
    base_prices = {"Electronics": 150, "Apparel": 45, "Home": 80, "Books": 20}

    df = pd.DataFrame({
        "order_id": [f"ORD-{i:05d}" for i in range(1, n_rows + 1)],
        "date": np.random.choice(dates, n_rows),
        "region": np.random.choice(regions, n_rows, p=[0.30, 0.20, 0.25, 0.25]),
        "product_category": np.random.choice(categories, n_rows, p=[0.20, 0.40, 0.30, 0.10]),
        "units": np.random.randint(1, 10, n_rows),
    })

    df["revenue"] = df.apply(
        lambda r: round(r["units"] * base_prices[r["product_category"]] * np.random.uniform(0.8, 1.2), 2),
        axis=1,
    )
    return_prob = np.where(
        (df["product_category"] == "Apparel") | (df["region"] == "West"), 0.15, 0.05
    )
    df["is_return"] = np.random.binomial(1, return_prob)
    df = df.sort_values("date").reset_index(drop=True)

    print(f"✓ Generated {n_rows:,} mock sales rows")
    _display(df.head(5))
    return df


def mock_timeseries(days: int = 365, freq: str = "D", trend: float = 0.1,
                    seasonality: bool = True, seed: int = 42) -> pd.DataFrame:
    """
    Generate a univariate time series with trend, seasonality, and noise.
    """
    np.random.seed(seed)
    dates = pd.date_range(end=pd.Timestamp.now().normalize(), periods=days, freq=freq)
    t = np.arange(days)
    values = 100 + trend * t
    if seasonality:
        period = 365 if freq.upper().startswith("D") else 24
        values += 20 * np.sin(2 * np.pi * t / period)
    values += np.random.normal(0, 5, days)

    df = pd.DataFrame({"date": dates, "value": np.round(values, 2)})
    print(f"✓ Generated {days} {freq} time-series periods")
    return df


def anonymize(df: pd.DataFrame, columns: list, method: str = "hash",
              prefix: str = "ID_") -> pd.DataFrame:
    """
    Anonymize PII columns.

    method:
      - "hash": SHA-256 prefix, stable within a session
      - "mask": j***@example.com or A***Z
      - "drop": remove the columns
    """
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            print(f"⚠️  Column not found, skipping: {col}")
            continue
        if method == "drop":
            out = out.drop(columns=[col])
        elif method == "hash":
            out[col] = out[col].astype(str).map(
                lambda x: prefix + _hashlib.sha256(x.encode()).hexdigest()[:8]
            )
        elif method == "mask":
            out[col] = out[col].map(_mask_value)
        else:
            raise ValueError("method must be 'hash', 'mask', or 'drop'")

    print(f"✓ Anonymized columns {columns} using '{method}'")
    _display(out.head(5))
    return out


def _mask_value(value) -> str:
    s = str(value)
    if "@" in s:
        name, domain = s.split("@", 1)
        if len(name) <= 1:
            return f"***@{domain}"
        return f"{name[0]}***@{domain}"
    if len(s) <= 2:
        return "***"
    return f"{s[0]}***{s[-1]}"
'''


def get_code() -> str:
    return _SYNTH_SKILLS_CODE
