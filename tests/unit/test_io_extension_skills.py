"""Unit tests for filesystem, synth, and API extension skills."""

import ast
import sys
import types

import pandas as pd
import pytest

from kerno.skills.builtins import api, filesystem, synth


def test_code_strings_parse():
    for module in (filesystem, synth, api):
        ast.parse(module.get_code())


def _exec(module):
    ns = {"pd": pd}
    from IPython.display import display
    ns["display"] = display
    ns["_display"] = display
    exec(module.get_code(), ns)
    return ns


def test_find_merge_and_peek_files(tmp_path):
    ns = _exec(filesystem)
    (tmp_path / "a.csv").write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
    (tmp_path / "b.csv").write_text("x,y\n5,6\n7,8\n", encoding="utf-8")

    found = ns["find_files"](str(tmp_path), pattern="*.csv")
    assert len(found) == 2

    merged = ns["merge_csvs"](str(tmp_path), pattern="*.csv")
    assert len(merged) == 4
    assert set(merged["_source_file"]) == {"a.csv", "b.csv"}

    sample = ns["peek_file"](str(tmp_path / "a.csv"), head=1, tail=1)
    assert "x,y" in sample


def test_mock_data_and_anonymize():
    ns = _exec(synth)
    sales = ns["mock_sales"](100, seed=1)
    assert {"order_id", "revenue", "is_return"}.issubset(sales.columns)
    assert len(sales) == 100

    ts = ns["mock_timeseries"](30)
    assert list(ts.columns) == ["date", "value"]

    hashed = ns["anonymize"](sales, ["order_id"], method="hash")
    assert hashed["order_id"].str.startswith("ID_").all()

    masked = ns["anonymize"](
        pd.DataFrame({"email": ["jane@example.com"]}), ["email"], method="mask"
    )
    assert masked.loc[0, "email"].startswith("j")


def test_fetch_api_list_and_dataframe(monkeypatch):
    ns = _exec(api)
    fake_response = types.SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}],
    )
    fake_requests = types.SimpleNamespace(
        request=lambda *args, **kwargs: fake_response,
        exceptions=types.SimpleNamespace(RequestException=Exception),
    )
    monkeypatch.setitem(ns, "_requests", lambda: fake_requests)
    result = ns["fetch_api"]("https://example.test/items", cache=False)
    assert isinstance(result, pd.DataFrame)
    assert list(result["name"]) == ["alpha", "beta"]


def test_fetch_api_offset_pagination(monkeypatch):
    ns = _exec(api)
    pages = [
        [{"id": i} for i in range(2)],
        [{"id": i} for i in range(2, 3)],
    ]

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload
        def raise_for_status(self):
            pass
        def json(self):
            return self._payload

    calls = []
    def fake_request(method, url, params=None, **kwargs):
        calls.append(dict(params or {}))
        return FakeResponse(pages[len(calls) - 1])

    fake_requests = types.SimpleNamespace(
        request=fake_request,
        exceptions=types.SimpleNamespace(RequestException=Exception),
    )
    monkeypatch.setitem(ns, "_requests", lambda: fake_requests)

    result = ns["fetch_api"](
        "https://example.test/p",
        cache=False,
        delay=0,
        paginate={"type": "offset", "limit": 2, "param": "offset"},
        max_pages=5,
    )
    assert len(result) == 3
    assert calls[-1].get("offset") == 2


def test_download_file(monkeypatch, tmp_path):
    ns = _exec(api)
    content = b"hello-world"

    class FakeResponse:
        headers = {"content-length": str(len(content))}
        def raise_for_status(self):
            pass
        def iter_content(self, chunk_size=8192):
            yield content
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    def fake_get(url, stream=False, timeout=60):
        return FakeResponse()

    fake_requests = types.SimpleNamespace(
        get=fake_get,
        exceptions=types.SimpleNamespace(RequestException=Exception),
    )
    monkeypatch.setitem(ns, "_requests", lambda: fake_requests)
    target = tmp_path / "download.bin"
    path = ns["download_file"]("https://example.test/file.bin", str(target))
    assert target.read_bytes() == content
    assert path.endswith("download.bin")
