# kerno/skills/builtins/filesystem.py
"""
Built-in filesystem and local-ingestion skills.

These skills provide structured views of directories, merge fragmented CSV
exports, and inspect large files without requiring heavy dependencies.
"""

_FILESYSTEM_SKILLS_CODE = r'''
from collections import deque as _deque
from datetime import datetime as _dt
from pathlib import Path as _Path

import pandas as pd
from IPython.display import display as _display


def find_files(directory: str = ".", pattern: str = "*", recursive: bool = True) -> pd.DataFrame:
    """
    Find files matching a glob pattern.

    Returns a DataFrame with path, name, suffix, size_kb, and modified columns.
    """
    root = _Path(directory)
    if not root.exists():
        print(f"⚠️  Directory not found: {directory}")
        return pd.DataFrame(columns=["path", "name", "suffix", "size_kb", "modified"])

    iterator = root.rglob(pattern) if recursive else root.glob(pattern)
    rows = []
    for path in iterator:
        if not path.is_file():
            continue
        stat = path.stat()
        rows.append({
            "path": str(path),
            "name": path.name,
            "suffix": path.suffix,
            "size_kb": round(stat.st_size / 1024, 2),
            "modified": _dt.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        })

    df = pd.DataFrame(rows).sort_values("size_kb", ascending=False).reset_index(drop=True)
    print(f"✓ Found {len(df)} file(s) matching '{pattern}' in {root.resolve()}")
    if not df.empty:
        _display(df.head(20))
    return df


def merge_csvs(directory: str, pattern: str = "*.csv", sample_rows: int = 0) -> pd.DataFrame:
    """
    Load and concatenate CSV files matching a glob pattern.

    ``sample_rows`` is useful for quickly inspecting large exports; 0 means
    read every row. A ``_source_file`` column records each row's origin.
    """
    root = _Path(directory)
    files = sorted(root.glob(pattern))
    if not files:
        print(f"⚠️  No files matching '{pattern}' in {root}")
        return pd.DataFrame()

    frames = []
    for file in files:
        try:
            df = pd.read_csv(file, nrows=sample_rows if sample_rows > 0 else None)
            df["_source_file"] = file.name
            frames.append(df)
            print(f"  + {file.name}: {df.shape[0]:,} rows × {df.shape[1] - 1} cols")
        except Exception as exc:
            print(f"  ✗ {file.name}: {exc}")

    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True, sort=False)
    print(f"✓ Merged {len(frames)} file(s) → {merged.shape[0]:,} rows × {merged.shape[1]} cols")
    _display(merged.head(5))
    return merged


def peek_file(path: str, head: int = 10, tail: int = 10) -> str:
    """
    Read the first and last lines of a file without loading it all into memory.

    Useful for inspecting large logs and CSV exports.
    """
    file_path = _Path(path)
    if not file_path.exists():
        print(f"⚠️  File not found: {path}")
        return ""

    lines = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if i >= head:
                break
            lines.append(line.rstrip("\n"))

    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        tail_lines = [line.rstrip("\n") for line in _deque(f, maxlen=tail)]

    if tail_lines:
        lines.append("\n... [middle omitted] ...\n")
        lines.extend(tail_lines)

    result = "\n".join(lines)
    print(result)
    return result
'''


def get_code() -> str:
    return _FILESYSTEM_SKILLS_CODE
