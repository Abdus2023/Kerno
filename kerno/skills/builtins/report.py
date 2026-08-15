# kerno/skills/builtins/report.py
"""
Built-in reporting and output skills.

Generate structured markdown reports, executive summaries, comparison tables,
data dictionaries, and serialized result artifacts.
"""

_REPORT_SKILLS_CODE = r'''
import json
from datetime import datetime as _dt
from pathlib import Path

import pandas as pd
import numpy as np
from IPython.display import display as _display, HTML as _HTML, Markdown as _MD


def generate_report(
    title:     str,
    sections:  list,
    metadata:  dict = None,
    save_path: str  = None,
) -> str:
    """
    Generate a structured markdown report.

    Args:
        sections: list of dicts: {"heading", "content", "level" (default 2)}.
        metadata: optional author/date/etc. dictionary.
        save_path: if provided, the report is written to this file.
    Returns:
        The markdown string.
    """
    lines = [f"# {title}", ""]

    if metadata:
        lines.append(f"*Generated: {_dt.now().strftime('%Y-%m-%d %H:%M')}*")
        for k, v in metadata.items():
            lines.append(f"*{k}: {v}*")
        lines.extend(["", "---", ""])

    for section in sections:
        level   = int(section.get("level", 2))
        heading = str(section.get("heading", ""))
        content = str(section.get("content", ""))
        lines.append(f"{'#' * level} {heading}")
        lines.extend(["", content, ""])

    report = "\n".join(lines)

    if save_path:
        path = Path(save_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        print(f"✓ Report saved → {save_path}")

    _display(_MD(report[:2000]))
    return report


def summary_table(
    df: pd.DataFrame,
    metrics: dict = None,
    title: str = "Summary",
) -> pd.DataFrame:
    """
    Create a formatted summary table from a DataFrame.

    Args:
        metrics: optional {label: value} pairs appended to the default summary.
    Returns:
        A DataFrame with Metric/Value columns.
    """
    metrics = metrics or {}
    rows = [
        {"Metric": "Rows",        "Value": f"{len(df):,}"},
        {"Metric": "Columns",     "Value": f"{df.shape[1]}"},
        {"Metric": "Nulls",       "Value": f"{df.isnull().sum().sum():,}"},
        {"Metric": "Memory (MB)", "Value": f"{df.memory_usage(deep=True).sum() / 1e6:.2f}"},
    ]
    for label, value in metrics.items():
        rows.append({"Metric": label, "Value": str(value)})

    summary = pd.DataFrame(rows)
    _display(_HTML(
        f"<h4>{title}</h4>"
        + summary.to_html(index=False, classes="table table-sm", border=0, escape=False)
    ))
    return summary


def comparison_table(
    results: dict,
    metric:  str = "score",
    title:   str = "Model Comparison",
) -> pd.DataFrame:
    """
    Create a comparison table from multiple result dictionaries.

    results maps model/experiment name to {metric: value} dictionaries.
    Rows are sorted by ``metric`` descending when present.
    """
    rows = []
    for name, scores in results.items():
        row = {"Model": name}
        row.update(scores)
        rows.append(row)

    df = pd.DataFrame(rows)
    if metric in df.columns:
        df = df.sort_values(metric, ascending=False).reset_index(drop=True)
        df.insert(0, "Rank", range(1, len(df) + 1))
        cols = ["Rank", "Model"] + [c for c in df.columns if c not in ("Rank", "Model")]
        df = df[cols]

    _display(_HTML(f"<h4>{title}</h4>"))
    _display(df)
    return df


def executive_summary(
    findings: list,
    title: str = "Executive Summary",
    recommendations: list = None,
) -> str:
    """
    Generate a formatted markdown executive summary.

    Returns the markdown string and displays it in the notebook.
    """
    lines = [f"## {title}", "", "### Key Findings", ""]
    lines.extend(f"{i}. {finding}" for i, finding in enumerate(findings, 1))
    lines.append("")

    if recommendations:
        lines.extend(["### Recommendations", ""])
        lines.extend(f"{i}. {rec}" for i, rec in enumerate(recommendations, 1))
        lines.append("")

    lines.extend(["---", f"*Generated: {_dt.now().strftime('%Y-%m-%d %H:%M')}*"])

    summary = "\n".join(lines)
    _display(_MD(summary))
    return summary


def data_dictionary(
    df: pd.DataFrame,
    descriptions: dict = None,
) -> pd.DataFrame:
    """
    Generate a data dictionary documenting DataFrame columns.

    descriptions maps column name to a human-readable description.
    """
    descriptions = descriptions or {}
    rows = []
    for col in df.columns:
        non_null = df[col].dropna()
        sample = str(non_null.iloc[0])[:50] if len(non_null) > 0 else ""
        rows.append({
            "Column":      col,
            "Type":        str(df[col].dtype),
            "Nulls":       int(df[col].isnull().sum()),
            "Unique":      int(df[col].nunique(dropna=True)),
            "Sample":      sample,
            "Description": descriptions.get(col, ""),
        })

    dd = pd.DataFrame(rows)
    _display(_HTML("<h4>📖 Data Dictionary</h4>"))
    _display(dd)
    return dd


def save_results(
    results: dict,
    path:   str,
    format: str = "json",
) -> str:
    """
    Save analysis results to disk.

    format: "json", "csv", or "pickle". Returns the output path.
    """
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    if format == "json":
        with open(path_obj, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)
    elif format == "csv":
        pd.DataFrame([results]).to_csv(path_obj, index=False)
    elif format == "pickle":
        import pickle
        with open(path_obj, "wb") as f:
            pickle.dump(results, f)
    else:
        raise ValueError("format must be 'json', 'csv', or 'pickle'")

    print(f"✓ Results saved → {path} ({format})")
    return str(path_obj.resolve())
'''


def get_code() -> str:
    """Return the source code string for these skills."""
    return _REPORT_SKILLS_CODE
