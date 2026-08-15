# kerno/skills/builtins/artifacts.py
"""
Built-in artifact generation skills.

Produce standalone HTML dashboards and formatted Excel workbooks from kernel
DataFrames, text, images, and matplotlib figures.
"""

_ARTIFACTS_CODE = r'''
import base64 as _b64
from pathlib import Path as _Path

import pandas as pd
from IPython.display import display as _display, HTML as _HTML


def to_html_dashboard(title: str, blocks: list, filename: str = "dashboard.html") -> str:
    """
    Generate a standalone HTML dashboard.

    Supported block types:
      - ``text``: Markdown-ish text
      - ``df``: pandas DataFrame under optional ``title``
      - ``html``: raw HTML
      - ``image``: path or base64-like image source
      - ``figure``: matplotlib Figure
    """
    html = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>{title}</title>",
        "<style>",
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;"
        "margin:40px;color:#333;line-height:1.6}",
        "h1{border-bottom:2px solid #0072B2;padding-bottom:10px}",
        "h2{color:#0072B2;margin-top:30px}",
        "table{border-collapse:collapse;width:100%;margin:20px 0;font-size:14px}",
        "th,td{border:1px solid #ddd;padding:8px;text-align:left}",
        "th{background:#f8f9fa}", "tr:nth-child(even){background:#f9f9f9}",
        "img{max-width:100%;border:1px solid #ddd;border-radius:4px;margin:10px 0}",
        "</style></head><body>", f"<h1>{title}</h1>",
    ]

    for block in blocks:
        block_type = block.get("type", "text")
        html.append("<div class='block'>")
        if block.get("title") and block_type != "text":
            html.append(f"<h2>{block['title']}</h2>")

        if block_type == "text":
            content = str(block.get("content", "")).replace("\n", "<br>")
            html.append(f"<p>{content}</p>")
        elif block_type == "df":
            df = block.get("data")
            if isinstance(df, pd.DataFrame):
                html.append(df.head(100).to_html(border=0, escape=False))
            else:
                html.append(f"<pre>{df}</pre>")
        elif block_type == "html":
            html.append(str(block.get("content", "")))
        elif block_type == "figure":
            from io import BytesIO
            buf = BytesIO()
            block["content"].savefig(buf, format="png", bbox_inches="tight", dpi=120)
            buf.seek(0)
            encoded = _b64.b64encode(buf.read()).decode()
            html.append(f"<img src='data:image/png;base64,{encoded}'>")
        elif block_type == "image":
            path = _Path(block.get("path", ""))
            if path.exists():
                encoded = _b64.b64encode(path.read_bytes()).decode()
                html.append(f"<img src='data:image/png;base64,{encoded}'>")
            else:
                html.append(f"<p style='color:red'>Image not found: {path}</p>")
        html.append("</div>")

    html.append("</body></html>")
    output = _Path(filename)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(html), encoding="utf-8")
    print(f"✓ Dashboard generated: {output.resolve()}")
    _display(_HTML(f"<a href='{output.resolve()}' target='_blank'>📊 Open Dashboard</a>"))
    return str(output.resolve())


def to_excel_report(filename: str, sheets: dict, format_headers: bool = True) -> str:
    """
    Export multiple DataFrames to a formatted Excel workbook.
    """
    output = _Path(filename)
    output.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            if not isinstance(df, pd.DataFrame):
                df = pd.DataFrame(df)
            safe_name = str(sheet_name)[:31]
            df.to_excel(writer, sheet_name=safe_name, index=False)

            if format_headers:
                ws = writer.sheets[safe_name]
                for idx, col in enumerate(df.columns, start=1):
                    max_len = max(df[col].astype(str).map(len).max() if len(df) else 0, len(str(col))) + 2
                    ws.column_dimensions[chr(64 + idx) if idx <= 26 else "A"].width = min(max_len, 50)
                    for cell in ws[1]:
                        cell.font = cell.font.copy(bold=True)

    print(f"✓ Excel report saved: {output.resolve()} ({len(sheets)} sheets)")
    return str(output.resolve())
'''


def get_code() -> str:
    return _ARTIFACTS_CODE
