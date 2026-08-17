#!/usr/bin/env python3
"""
Static raw-kernel execution detector (P3.17 — regression gate).

Flags raw-kernel execution outside approved locations:

  1. `KernelRuntime(` construction is only allowed in the trusted
     bootstrap/ownership files listed below (pool, _run, CLI, dev).
  2. `kernel.execute(` / `kernel.execute_silent(` anywhere in
     kerno/server/ is FORBIDDEN: the server layer must execute only
     through the ExecutionEngine gateway (K-001) — file materialization
     and RAG loading use the narrow MaterializationExecutor boundary.
  3. `urlretrieve(` anywhere is forbidden (F-002 SSRF regression —
     removed in Phase 1, must not return).

This is a lightweight regression gate, NOT a substitute for the
security test suites (tests/security/, tests/unit/test_*_security.py).
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC  = ROOT / "kerno"
SERVER = SRC / "server"

# Files where raw KernelRuntime construction is legitimate trusted setup.
# Each entry is classified: the raw kernel is used for host-side setup
# (skills, allowlist hook, pool warm-up) and agent code is always wrapped
# in the ExecutionEngine choke point (K-001).
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

_RAW_CALL = re.compile(r"kernel\.(?:execute|execute_silent)\s*\(")


def _check_file(path: pathlib.Path, rel: str, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")

    if "urlretrieve(" in text:
        errors.append(f"{rel}: urllib.request.urlretrieve( is forbidden (F-002)")

    if "KernelRuntime(" in text and rel not in KERNEL_CONSTRUCTION_ALLOWED:
        errors.append(
            f"{rel}: KernelRuntime( construction outside approved bootstrap "
            f"files ({', '.join(sorted(KERNEL_CONSTRUCTION_ALLOWED))})"
        )


def main() -> int:
    errors: list[str] = []

    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        _check_file(path, rel, errors)
        if path.is_relative_to(SERVER) and _RAW_CALL.search(text := path.read_text(encoding="utf-8")):
            errors.append(
                f"{rel}: raw kernel.execute( in the server layer — execution "
                f"must go through the gateway engine (K-001)"
            )

    if errors:
        print("Raw-kernel gate FAILED:")
        for e in errors:
            print("  -", e)
        return 1

    print("Raw-kernel gate OK: no unapproved raw-kernel execution paths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
