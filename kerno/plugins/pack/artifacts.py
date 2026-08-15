"""Artifact discovery plugin.

Scans generated code for common output paths and, at session end, reports which
artifacts actually exist on disk.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from kerno.plugins.registry import BasePlugin


@dataclass
class ArtifactReference:
    cell: int
    path: str
    operation: str  # save | export | read | unknown


class ArtifactTrackerPlugin(BasePlugin):
    """Track file references mentioned in generated cells."""

    name = "artifact_tracker"

    _SAVE_METHODS = {
        "to_csv", "to_excel", "to_parquet", "to_json", "to_pickle",
        "to_html", "to_markdown", "savefig", "save", "write_text",
        "write_bytes", "dump",
    }
    _READ_METHODS = {"read_csv", "read_excel", "read_parquet", "read_json", "open"}

    def __init__(self, root: str | Path = "."):
        self.root = Path(root)
        self.references: list[ArtifactReference] = []
        self.created: list[Path] = []

    def on_cell_complete(self, cell) -> None:
        source = cell.code or ""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            method = self._method_name(node.func)
            if method not in self._SAVE_METHODS and method not in self._READ_METHODS:
                continue
            path = self._first_string_arg(node)
            if path:
                self.references.append(ArtifactReference(
                    cell=cell.cell_num,
                    path=path,
                    operation="save" if method in self._SAVE_METHODS else "read",
                ))

    def on_session_complete(self, result) -> None:
        seen: set[Path] = set()
        for ref in self.references:
            if ref.operation != "save":
                continue
            candidate = (self.root / ref.path).resolve()
            if candidate.exists() and candidate.is_file() and candidate not in seen:
                seen.add(candidate)
                self.created.append(candidate)

        if self.created:
            print("[artifacts] Created/updated files:", flush=True)
            for path in self.created:
                size = max(path.stat().st_size, 1)
                print(f"  - {path} ({size / 1024:.1f} KB)", flush=True)
        elif any(r.operation == "save" for r in self.references):
            print("[artifacts] No referenced output files were found on disk.", flush=True)

    def _method_name(self, func: ast.AST) -> str:
        if isinstance(func, ast.Attribute):
            return func.attr
        if isinstance(func, ast.Name):
            return func.id
        return ""

    def _first_string_arg(self, call: ast.Call) -> str | None:
        if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
            return call.args[0].value
        for kw in call.keywords:
            if kw.arg in {"path", "fname", "filename", "buf", "output_path", "save_path"}:
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    return kw.value.value
        return None
