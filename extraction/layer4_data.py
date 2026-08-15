# kerno/skills/builtins/data.py
"""
Built-in data skills: the default toolkit loaded into every kernel.

Design principles (from Part III):
  - Return rich objects, not strings
  - Produce displays visible in notebook AND return data
  - Be idempotent by default
  - Fail gracefully with informative messages
"""

import json


_DATA_SKILLS_CODE = '''
import pandas as pd
import numpy as np
from pathlib import Path as _Path
from IPython.display import display as _display, HTML as _HTML


def load(path: str, **kwargs) -> pd.DataFrame:
    """
    Load a data file into a DataFrame.
    Supports: CSV, Parquet, JSON, Excel.
    Caches in namespace to avoid re-loading on repeated calls.

    Returns: DataFrame
    """
    _cache_key = f"_load_cache_{hash(path)}"
    if _cache_key in globals() and not kwargs.get('force', False):
        _df = globals()[_cache_key]
        print(f"✓ Using cached '{_Path(path).name}': {_df.shape}")
        return _df

    _p = _Path(path)
    if not _p.exists():
        raise FileNotFoundError(
            f"File not found: {path}\\n"
            f"Available files: {[str(f) for f in _Path('.').glob('*.*')][:10]}"
        )

    _suffix = _p.suffix.lower()
    _loaders = {
        '.csv':     lambda: pd.read_csv(path, **{k: v for k, v in kwargs.items() if k != 'force'}),
        '.parquet': lambda: pd.read_parquet(path),
        '.json':    lambda: pd.read_json(path),
        '.xlsx':    lambda: pd.read_excel(path),
        '.xls':     lambda: pd.read_excel(path),
    }

    _loader = _loaders.get(_suffix)
    if not _loader:
        raise ValueError(f"Unsupported file type: {_suffix}")

    df = _loader()
    globals()[_cache_key] = df
    print(f"✓ Loaded '{_p.name}': {df.shape} — {list(df.columns)[:6]}")
    return df


def profile(df: pd.DataFrame, max_cols: int = 20) -> dict:
    """
    Profile a DataFrame: shape, dtypes, null counts, numeric summary.
    Displays a rich HTML summary and returns stats as a dict.

    Returns: dict with keys: shape, dtypes, nulls, numeric_stats
    """
    _nulls    = df.isnull().sum()
    _non_zero = _nulls[_nulls > 0]
    _numeric  = df.select_dtypes(include=np.number)

    stats = {
        "shape":         list(df.shape),
        "dtypes":        df.dtypes.astype(str).to_dict(),
        "nulls":         _nulls.to_dict(),
        "null_columns":  _non_zero.to_dict(),
        "numeric_stats": _numeric.describe().to_dict() if not _numeric.empty else {},
    }

    # ── Rich display ──────────────────────────────────────────────────────────

    rows = [
        f"<tr><td><b>Shape</b></td><td>{df.shape[0]:,} rows × {df.shape[1]} cols</td></tr>",
        f"<tr><td><b>Memory</b></td><td>{df.memory_usage(deep=True).sum() / 1e6:.1f} MB</td></tr>",
    ]

    if not _non_zero.empty:
        null_summary = ", ".join(f"{c}: {v}" for c, v in _non_zero.items())
        rows.append(f"<tr><td><b>Nulls</b></td><td style='color:orange'>{null_summary}</td></tr>")
    else:
        rows.append("<tr><td><b>Nulls</b></td><td style='color:green'>None</td></tr>")

    html = (
        "<table style='font-family:monospace;font-size:13px'>"
        + "".join(rows)
        + "</table>"
    )
    _display(_HTML(html))

    # Numeric summary as DataFrame display
    if not _numeric.empty:
        _display(_numeric.describe().round(3))

    # Sample rows
    _display(df.head(5))

    return stats


def clean_nulls(df: pd.DataFrame, strategy: str = "report") -> pd.DataFrame:
    """
    Handle null values in a DataFrame.

    strategy:
      "report"  — print null summary only, no changes (default)
      "drop"    — drop rows with any null
      "fill"    — fill numeric nulls with median, string nulls with 'Unknown'

    Returns: DataFrame (modified copy for non-report strategies)
    """
    _nulls = df.isnull().sum()
    _null_cols = _nulls[_nulls > 0]

    if _null_cols.empty:
        print("✓ No null values found")
        return df

    print(f"Null columns ({len(_null_cols)}):")
    for col, count in _null_cols.items():
        pct = 100 * count / len(df)
        print(f"  {col}: {count:,} ({pct:.1f}%)")

    if strategy == "report":
        return df

    df = df.copy()

    if strategy == "drop":
        before = len(df)
        df = df.dropna()
        print(f"✓ Dropped {before - len(df):,} rows with nulls")

    elif strategy == "fill":
        for col in _null_cols.index:
            if df[col].dtype in (np.float64, np.int64, float, int):
                median = df[col].median()
                df[col] = df[col].fillna(median)
                print(f"  {col}: filled with median ({median:.3f})")
            else:
                df[col] = df[col].fillna("Unknown")
                print(f"  {col}: filled with 'Unknown'")

    return df


def checkpoint(obj, name: str = None) -> str:
    """
    Save an object to the checkpoints directory.
    Supports: DataFrame (parquet), sklearn models (joblib), dicts/lists (json).

    Returns: path where the object was saved
    """
    import joblib

    _Path("_checkpoints").mkdir(exist_ok=True)

    if name is None:
        # Find the variable name in the caller's frame
        import inspect as _inspect
        _frame = _inspect.currentframe().f_back
        name  = next(
            (k for k, v in _frame.f_locals.items() if v is obj),
            "object"
        )

    if isinstance(obj, pd.DataFrame):
        path = f"_checkpoints/{name}.parquet"
        obj.to_parquet(path)
    elif isinstance(obj, (dict, list)):
        path = f"_checkpoints/{name}.json"
        with open(path, "w") as f:
            json.dump(obj, f, default=str)
    else:
        path = f"_checkpoints/{name}.joblib"
        joblib.dump(obj, path)

    print(f"✓ Checkpointed '{name}' → {path}")
    return path
'''


def get_code() -> str:
    """Return the source code string for these skills."""
    return _DATA_SKILLS_CODE
