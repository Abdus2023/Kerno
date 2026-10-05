#!/usr/bin/env python3
"""Minimal fixture loader for .agent/conformance.

This harness validates fixture shape and can run only the deterministic
reference checks it explicitly implements. It never claims CI execution.
"""

from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / ".agent" / "conformance"

REQUIRED = {"suite", "version", "cases"}

def load(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = REQUIRED - data.keys()
    if missing:
        raise ValueError(f"{path}: missing {sorted(missing)}")
    if not isinstance(data["cases"], list):
        raise ValueError(f"{path}: cases must be an array")
    return data

def check_fixture(path: Path):
    data = load(path)
    ids = [c.get("id") for c in data["cases"]]
    if any(not isinstance(i, str) or not i for i in ids):
        raise ValueError(f"{path}: every case requires a non-empty id")
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate case id")
    return len(ids)

def main():
    total = 0
    for path in sorted(FIXTURES.glob("*.json")):
        count = check_fixture(path)
        total += count
        print(f"OK {path.relative_to(ROOT)} cases={count}")
    print(f"FIXTURE_SHAPE_VALID cases={total}")

if __name__ == "__main__":
    main()
