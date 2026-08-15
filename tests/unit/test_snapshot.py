# tests/unit/test_snapshot.py
"""Unit tests for namespace snapshot — no kernel required."""

import json
import pytest


# We test the snapshot code by executing it in-process
# using a mock globals() dict

def run_snapshot_code(fake_globals: dict) -> dict:
    """Execute the snapshot logic against a fake namespace."""
    snap = {}
    for k, v in fake_globals.items():
        if k.startswith('_'):
            continue
        try:
            t = type(v).__name__
            if hasattr(v, 'shape'):
                snap[k] = f"{t}{list(v.shape)}"
            elif hasattr(v, '__len__') and not isinstance(v, (str, bytes, type)):
                snap[k] = f"{t}(len={len(v)})"
            elif callable(v) and not isinstance(v, type):
                snap[k] = f"fn:{v.__name__}"
            elif isinstance(v, (int, float, bool)):
                snap[k] = f"{t}={v}"
            elif isinstance(v, str):
                snap[k] = f"str={repr(v[:40])}"
            else:
                snap[k] = t
        except Exception:
            pass
    return snap


class TestSnapshot:

    def test_skips_private_names(self):
        snap = run_snapshot_code({
            "_private": "hidden",
            "__dunder": "also hidden",
            "public":   "shown",
        })
        assert "_private"  not in snap
        assert "__dunder"  not in snap
        assert "public"    in snap

    def test_dataframe_shows_shape(self):
        pd = pytest.importorskip("pandas")
        df   = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        snap = run_snapshot_code({"df": df})
        assert "df" in snap
        assert "[3, 2]" in snap["df"]
        assert "DataFrame" in snap["df"]

    def test_list_shows_length(self):
        snap = run_snapshot_code({"items": [1, 2, 3, 4, 5]})
        assert "len=5" in snap["items"]

    def test_scalar_shows_value(self):
        snap = run_snapshot_code({"count": 42})
        assert "42" in snap["count"]
        assert "int" in snap["count"]

    def test_function_shows_name(self):
        def my_func(): pass
        snap = run_snapshot_code({"my_func": my_func})
        assert "fn" in snap["my_func"]

    def test_empty_namespace(self):
        snap = run_snapshot_code({})
        assert snap == {}

    def test_numpy_array(self):
        np = pytest.importorskip("numpy")
        arr  = np.zeros((10, 5))
        snap = run_snapshot_code({"arr": arr})
        assert "ndarray" in snap["arr"]
        assert "[10, 5]" in snap["arr"]
