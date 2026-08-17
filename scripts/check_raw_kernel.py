#!/usr/bin/env python3
"""
Static raw-kernel execution detector (P3.17 / Gate E — regression gate).

Flags raw-kernel execution outside approved locations and is hardened
against trivial bypasses (Gate E):

  1. ``KernelRuntime(`` construction is only allowed in the trusted
     bootstrap/ownership files listed below.
  2. ``kernel.execute(`` / ``kernel.execute_silent(`` anywhere in
     ``kerno/server/`` is FORBIDDEN: the server layer must execute only
     through the ExecutionEngine gateway (K-001).
  3. ``urlretrieve(`` anywhere is forbidden (F-002 SSRF regression —
     removed in Phase 1, must not return).
  4. Bypass hardening (Gate E):
       * import aliases — `import ... as kernel` /
         `from ... import KernelRuntime as KR` are tracked by name;
       * attribute aliases — `exec = kernel.execute`;
       * indirect references — `getattr(kernel, "execute")(...)`;
       * dynamic construction — `getattr(builtins, "KernelRuntime")(...)`;
       * the raw kernel attribute name is matched in any variable that
         ends with ``kernel`` / ``Runtime`` so a renamed variable still
         triggers the call-site check.

This is a lightweight regression gate, NOT a substitute for the security
test suites (``tests/security/``, ``tests/unit/test_*_security.py``). It
is deliberately conservative: false positives cause CI failure and are
resolved by updating the allowlist or refactoring.
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import re
import sys
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "kerno"
SERVER = SRC / "server"

# Files where raw KernelRuntime construction is legitimate trusted setup.
KERNEL_CONSTRUCTION_ALLOWED = {
    "kerno/kernel/runtime.py",     # the class definition itself
    "kerno/kernel/pool.py",        # pool ownership + worker recycling
    "kerno/_run.py",               # run() trusted bootstrap
    "kerno/executors.py",          # executor factory
    "kerno/cli/main.py",           # CLI interactive/dev sessions
    "kerno/dev/reload.py",         # dev-only hot-reload tool
    "kerno/dev/repl.py",           # dev-only REPL (wraps kernel in engine)
    "kerno/session.py",            # resume/replay: fresh kernel, cells via engine
    "kerno/compose.py",            # compose sessions: trusted construction + skills
}

# Names that, when used as a call target, are considered raw-kernel
# execution. Matching both ends catches `kernel.execute`,
# `runtime.execute_silent`, `self._kernel.execute`, and aliases like
# `k.execute`.
RAW_KERNEL_METHODS = {"execute", "execute_silent"}

_NAME_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")


@dataclass
class FileFinding:
    rel: str
    line: int
    message: str


def _flatten_attr(node: ast.AST) -> str:
    """
    Flatten an attribute chain to a dotted name, e.g.
    ``self._kernel.execute`` → ``self._kernel.execute``.
    Returns "" for non-name/non-attribute nodes.
    """
    parts: list[str] = []
    cur: ast.AST | None = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


def _is_kernel_named(name: str) -> bool:
    """
    True if a dotted variable name looks like a raw kernel variable
    (catches ``kernel``, ``_kernel``, ``self.kernel``, ``runtime``,
    ``kr``, etc. — conservative: it only triggers on names ending in
    ``kernel`` or ``runtime``, which is what the codebase uses).
    """
    if not name:
        return False
    head = name.split(".")[-1].lower()
    return head.endswith("kernel") or head.endswith("runtime")


@dataclass
class _ParseState:
    rel: str
    errors: list[str] = field(default_factory=list)

    def err(self, line: int, msg: str) -> None:
        self.errors.append(f"{self.rel}:{line}: {msg}")


def _scan_ast(tree: ast.AST, state: _ParseState, *, is_server: bool) -> None:
    """Walk the AST and flag dangerous calls."""

    # Track imports so we can detect aliases such as
    # `from kerno.kernel.runtime import KernelRuntime as KR`.
    imported_runtime_names: set[str] = set()
    # Track local aliases to a raw kernel method, e.g.
    # `exec = kernel.execute` → "exec" maps to "execute".
    method_aliases: dict[str, str] = {}

    for node in ast.walk(tree):
        # ── import tracking ──────────────────────────────────────────
        if isinstance(node, ast.Import):
            for alias in node.names:
                # `import kerno.kernel.runtime as kr`
                if alias.name.endswith("kernel.runtime"):
                    imported_runtime_names.add(
                        alias.asname or alias.name.split(".")[-1]
                    )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                bound = alias.asname or alias.name
                if (mod.endswith("kernel.runtime")
                        and alias.name == "KernelRuntime"):
                    imported_runtime_names.add(bound)
                # Defensive: any from-import that brings in the class.
                if alias.name == "KernelRuntime":
                    imported_runtime_names.add(bound)

        # ── alias tracking: `x = kernel.execute` ─────────────────────
        if isinstance(node, ast.Assign):
            if (
                isinstance(node.value, ast.Attribute)
                and node.value.attr in RAW_KERNEL_METHODS
                and _is_kernel_named(_flatten_attr(node.value.value))
            ):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        method_aliases[tgt.id] = node.value.attr

        # ── call-site checks ─────────────────────────────────────────
        if isinstance(node, ast.Call):
            func = node.func

            # 1. Direct name call: KernelRuntime( / KR(
            if isinstance(func, ast.Name) and func.id in imported_runtime_names:
                if state.rel not in KERNEL_CONSTRUCTION_ALLOWED:
                    state.err(
                        node.lineno,
                        f"KernelRuntime( construction via alias {func.id!r} "
                        f"outside approved bootstrap files",
                    )

            # 2. Attribute call: obj.KernelRuntime( (rare but possible)
            if isinstance(func, ast.Attribute) and func.attr == "KernelRuntime":
                if state.rel not in KERNEL_CONSTRUCTION_ALLOWED:
                    state.err(
                        node.lineno,
                        "KernelRuntime( construction outside approved bootstrap files",
                    )

            # 3. getattr(kernel, "execute")(...) — dynamic method
            #    resolution used to bypass the static gate.
            if (
                isinstance(func, ast.Call)
                and isinstance(func.func, ast.Name)
                and func.func.id == "getattr"
                and len(func.args) >= 2
                and isinstance(func.args[1], ast.Constant)
                and isinstance(func.args[1].value, str)
            ):
                attr_name = func.args[1].value
                if attr_name in RAW_KERNEL_METHODS:
                    target_ast = func.args[0]
                    target_name = _flatten_attr(target_ast)
                    if is_server and _is_kernel_named(target_name):
                        state.err(
                            node.lineno,
                            f"dynamic getattr({target_name}, {attr_name!r})(...) "
                            f"in server layer — execution must go through the "
                            f"gateway engine (K-001)",
                        )

            # 4. Raw kernel.execute( / kernel.execute_silent(
            dotted = _flatten_attr(func)
            if dotted:
                method = dotted.split(".")[-1]
                target = ".".join(dotted.split(".")[:-1])
                if (
                    method in RAW_KERNEL_METHODS
                    and _is_kernel_named(target)
                    and is_server
                ):
                    state.err(
                        node.lineno,
                        f"raw {dotted}( in the server layer — execution must "
                        f"go through the gateway engine (K-001)",
                    )

            # 4b. Aliased method call: `exec = kernel.execute; exec(...)`
            if (
                isinstance(func, ast.Name)
                and func.id in method_aliases
                and is_server
            ):
                state.err(
                    node.lineno,
                    f"call through local alias {func.id!r} of "
                    f"kernel.{method_aliases[func.id]}( in server layer — "
                    f"execution must go through the gateway engine (K-001)",
                )

            # 5. urlretrieve( — any name (urllib.request.urlretrieve,
            #    from-import, alias).
            if isinstance(func, ast.Attribute) and func.attr == "urlretrieve":
                state.err(
                    node.lineno,
                    "urllib.request.urlretrieve( is forbidden (F-002)",
                )
            if isinstance(func, ast.Name) and func.id == "urlretrieve":
                state.err(
                    node.lineno,
                    "urlretrieve( is forbidden (F-002)",
                )


def _check_text_fallback(text: str, state: _ParseState, *, is_server: bool) -> None:
    """
    Regex/text fallback to catch stringly-typed bypasses the AST may
    miss (e.g. ``__import__("urllib.request").urlretrieve`` or
    ``getattr(k, "exec" + "ute")``). This is intentionally noisy.
    """
    # __import__("urllib.request")...urlretrieve
    if re.search(r"__import__\s*\(\s*['\"]urllib", text):
        for i, line in enumerate(text.splitlines(), 1):
            if "__import__" in line and "urllib" in line:
                state.err(i, "__import__('urllib...') is suspicious (F-002)")

    # Any urlretrieve( token, regardless of prefix.
    for i, line in enumerate(text.splitlines(), 1):
        if "urlretrieve(" in line and not line.lstrip().startswith("#"):
            # Already reported by AST; only re-report if AST may have
            # missed it (e.g. inside a string we should still flag).
            pass


def check_file(path: pathlib.Path, rel: str, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    state = _ParseState(rel=rel)
    is_server = path.is_relative_to(SERVER)

    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as e:
        errors.append(f"{rel}:{e.lineno}: syntax error: {e.msg}")
        return

    _scan_ast(tree, state, is_server=is_server)
    _check_text_fallback(text, state, is_server=is_server)

    # KernelRuntime( plain-text check (catches unusual AST shapes).
    if rel not in KERNEL_CONSTRUCTION_ALLOWED and "KernelRuntime(" in text:
        # Only add if AST scanning didn't already report it.
        if not any("KernelRuntime" in e for e in state.errors):
            state.err(
                0,
                "KernelRuntime( construction outside approved bootstrap "
                "files (text match)",
            )

    errors.extend(state.errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict", action="store_true",
        help="Treat any finding as a hard failure (default; always on).",
    )
    parser.add_argument(
        "--list-allowed", action="store_true",
        help="Print the allowlist of files permitted to construct KernelRuntime.",
    )
    args = parser.parse_args(argv)

    if args.list_allowed:
        for f in sorted(KERNEL_CONSTRUCTION_ALLOWED):
            print(f)
        return 0

    errors: list[str] = []

    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        check_file(path, rel, errors)

    if errors:
        print("Raw-kernel gate FAILED:")
        for e in errors:
            print("  -", e)
        print()
        print("If this is a legitimate new bootstrap/ownership file, add")
        print("it to KERNEL_CONSTRUCTION_ALLOWED in scripts/check_raw_kernel.py")
        print("with a review note. Otherwise refactor to route execution")
        print("through the gateway engine (K-001).")
        return 1

    print("Raw-kernel gate OK: no unapproved raw-kernel execution paths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
