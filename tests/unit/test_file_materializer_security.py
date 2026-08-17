"""
Security tests for file materialization (F-001 / F-002 / F-003 / F-004).

Covers:
  - F-001: FileMaterializer executes ONLY through the narrow
           MaterializationExecutor → ExecutionEngine boundary; a raw
           kernel is rejected structurally; every materialization
           execution produces an engine audit record (origin=runtime).
  - F-002: outbound URL policy — scheme allowlist, private/loopback/
           link-local/CGNAT blocking, per-redirect revalidation, connect
           and read timeouts, streaming size cap.
  - F-003: materialization bounds — pre-decode base64 size rejection,
           per-request file-count limit, total-byte budget.
  - F-004: per-instance (per-request) storage isolation + cleanup.
"""

import base64
from urllib.request import Request

import pytest

from kerno.execution.engine import ORIGIN_RUNTIME, ExecutionEngine
from kerno.server.files import (
    FileMaterializer,
    MaterializationExecutor,
    MaterializationLimitError,
    MaterializationLimits,
    UrlPolicyError,
    _download_to_file,
    _estimate_base64_size,
    _ValidatingRedirectHandler,
    validate_download_url,
)
from kerno.types import CellOutput


class RecordingKernel:
    """Satisfies the Executor protocol; records every direct execution."""

    def __init__(self):
        self.direct_calls = []

    def execute(self, code, timeout=120.0, silent=False, **kwargs):
        self.direct_calls.append(code)
        return CellOutput(stdout="ok")

    def execute_silent(self, code, timeout=15.0, **kwargs):
        return "ok"

    @property
    def namespace(self):
        return "{}"

    @property
    def is_alive(self):
        return True


class FakeResponse:
    """Minimal urllib response stand-in for download-machinery tests."""

    def __init__(self, chunks, headers=None, read_error=None):
        self._chunks = list(chunks)
        self.headers = headers or {}
        self._read_error = read_error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, amt=-1):
        if self._read_error is not None:
            raise self._read_error
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


class FakeOpener:
    def __init__(self, response):
        self._response = response

    def open(self, url, timeout=None):
        return self._response


def _build(kernel, tmp_path, limits=None):
    engine = ExecutionEngine(kernel)
    executor = MaterializationExecutor(engine)
    fm = FileMaterializer(executor, upload_dir=str(tmp_path / "uploads"), limits=limits)
    return engine, executor, fm


# ── F-001: execution boundary ─────────────────────────────────────────────────

class TestExecutionBoundary:

    def test_constructor_rejects_raw_kernel(self):
        # Structural guarantee: a raw kernel (or any object without
        # execute_load_code) cannot be handed to FileMaterializer.

        class _RawExecutor:
            def execute(self, *args, **kwargs):
                return CellOutput(stdout="ok")

        with pytest.raises(TypeError):
            FileMaterializer(RecordingKernel())
        with pytest.raises(TypeError):
            FileMaterializer(_RawExecutor())

    def test_materialization_goes_through_engine(self, tmp_path):
        kernel = RecordingKernel()
        engine, executor, fm = _build(kernel, tmp_path)

        body = {"files": [{"name": "data.csv", "type": "text/csv",
                           "data": base64.b64encode(b"a,b\n1,2\n").decode()}]}
        results = fm.process_from_context(body)

        assert len(results) == 1
        assert results[0].original_name == "data.csv"

        # The execution went through the engine: an audit record exists
        # with origin=runtime (loader code is trusted host template code).
        assert len(engine.records) == 1
        assert engine.records[0].origin == ORIGIN_RUNTIME
        assert engine.records[0].allowed
        # The materializer itself has no kernel reference and only the
        # narrow executor.
        assert not hasattr(fm, "kernel")
        assert fm._executor is executor

    def test_materialization_recorded_in_event_stream(self, tmp_path):
        kernel = RecordingKernel()
        engine, _, fm = _build(kernel, tmp_path)
        body = {"files": [{"name": "notes.txt", "type": "text/plain",
                           "data": base64.b64encode(b"hello world").decode()}]}
        fm.process_from_context(body)

        event_types = [e.event_type for e in engine.events]
        assert "EXECUTION_REQUESTED" in event_types
        assert "EXECUTION_STARTED" in event_types
        assert "EXECUTION_COMPLETED" in event_types

    def test_missing_fields_skipped_gracefully(self, tmp_path):
        _, _, fm = _build(RecordingKernel(), tmp_path)
        body = {"files": [{}]}          # no data, no url
        results = fm.process_from_context(body)
        assert results == []

    def test_malformed_file_objects_skipped(self, tmp_path):
        _, _, fm = _build(RecordingKernel(), tmp_path)
        results = fm.process([None, "not-a-dict", 42, {"name": "x.txt", "type": "text/plain"}])
        assert results == []


# ── F-002: outbound URL policy ────────────────────────────────────────────────

class TestUrlPolicyValidation:

    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "ftp://example.com/data.csv",
        "gopher://example.com/x",
        "data:text/plain;base64,aGVsbG8=",
        "javascript:alert(1)",
        "http://",
        "",
        None,
    ])
    def test_unsupported_schemes_and_malformed_rejected(self, url):
        with pytest.raises(UrlPolicyError):
            validate_download_url(url)

    @pytest.mark.parametrize("url", [
        "http://127.0.0.1:8000/secret",
        "http://10.0.0.1/x",
        "http://172.16.0.1/x",
        "http://172.31.255.255/x",
        "http://192.168.1.1/x",
        "http://169.254.169.254/latest/meta-data",
        "http://0.0.0.0/x",
        "http://100.64.0.1/x",
        "http://[::1]/x",
        "http://[fe80::1]/x",
    ])
    def test_private_and_loopback_addresses_rejected(self, url):
        with pytest.raises(UrlPolicyError):
            validate_download_url(url)

    def test_embedded_credentials_rejected(self):
        with pytest.raises(UrlPolicyError):
            validate_download_url("http://user:pass@example.com/data.csv")

    def test_public_literal_ip_accepted(self):
        parsed = validate_download_url("http://8.8.8.8/dns")
        assert parsed.scheme == "http"
        parsed = validate_download_url("https://1.1.1.1/dns")
        assert parsed.scheme == "https"


class TestRedirectRevalidation:

    def test_redirect_to_private_target_rejected(self):
        handler = _ValidatingRedirectHandler()
        req = Request("http://example.com/start")
        with pytest.raises(UrlPolicyError):
            handler.redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1:8000/internal")

    def test_redirect_to_public_target_passes(self):
        handler = _ValidatingRedirectHandler()
        req = Request("http://example.com/start")
        new = handler.redirect_request(req, None, 302, "Found", {}, "http://8.8.8.8/next")
        assert new is not None


class TestDownloadMachinery:
    """_download_to_file with a fake opener (no network needed)."""

    def _run(self, url, dest, chunks, headers=None, max_bytes=1024, read_error=None):
        opener = FakeOpener(FakeResponse(chunks, headers=headers, read_error=read_error))
        return _download_to_file(
            url, dest, max_bytes=max_bytes,
            connect_timeout=5.0, read_timeout=5.0, overall_timeout=30.0,
            opener=opener,
        )

    def test_download_success(self, tmp_path):
        dest = tmp_path / "out.bin"
        n = self._run("http://example.com/f.bin", dest, [b"a" * 100, b"b" * 50])
        assert n == 150
        assert dest.read_bytes() == b"a" * 100 + b"b" * 50

    def test_declared_content_length_rejected_before_read(self, tmp_path):
        dest = tmp_path / "out.bin"
        with pytest.raises(MaterializationLimitError):
            self._run("http://example.com/f.bin", dest, [b"x"], headers={"Content-Length": "999999"})

    def test_streaming_size_cap(self, tmp_path):
        dest = tmp_path / "out.bin"
        chunks = [b"a" * 32768, b"b" * 32768, b"c" * 32768]
        with pytest.raises(MaterializationLimitError):
            self._run("http://example.com/f.bin", dest, chunks, max_bytes=65536)
        assert not dest.exists() or dest.stat().st_size <= 65536 + 32768

    def test_read_timeout(self, tmp_path):
        dest = tmp_path / "out.bin"
        with pytest.raises(MaterializationLimitError):
            self._run("http://example.com/f.bin", dest, [], read_error=TimeoutError("slow"))

    def test_policy_rejected_before_network(self, tmp_path):
        dest = tmp_path / "out.bin"
        with pytest.raises(UrlPolicyError):
            _download_to_file(
                "http://127.0.0.1:8000/x", dest,
                max_bytes=1024, connect_timeout=5.0, read_timeout=5.0,
                overall_timeout=30.0,
            )


class TestFileMaterializerUrlPath:

    def test_private_url_rejected(self, tmp_path):
        _, _, fm = _build(RecordingKernel(), tmp_path)
        with pytest.raises(UrlPolicyError):
            fm.process([{"name": "x.csv", "type": "text/csv",
                         "url": "http://127.0.0.1:8000/data.csv"}])

    def test_unsupported_scheme_rejected(self, tmp_path):
        _, _, fm = _build(RecordingKernel(), tmp_path)
        with pytest.raises(UrlPolicyError):
            fm.process([{"name": "x.txt", "type": "text/plain",
                         "url": "file:///etc/passwd"}])

    def test_url_download_runs_through_engine(self, tmp_path, monkeypatch):
        # Route around DNS + real network: policy accepts, fake opener
        # serves content; execution must still go through the engine.
        monkeypatch.setattr(
            "kerno.server.files.validate_download_url",
            lambda url, allowed_schemes=None: __import__("urllib.parse").parse.urlparse(url),
        )

        class _FakeOpener:
            def open(self, url, timeout=None):
                return FakeResponse([b"a,b\n1,2\n"], headers={})

        monkeypatch.setattr("kerno.server.files._build_download_opener", lambda: _FakeOpener())

        kernel = RecordingKernel()
        engine, _, fm = _build(kernel, tmp_path)
        results = fm.process([{"name": "remote.csv", "type": "text/csv",
                               "url": "https://example.com/remote.csv"}])

        assert len(results) == 1
        assert len(engine.records) == 1
        assert engine.records[0].origin == ORIGIN_RUNTIME
        assert not hasattr(fm, "kernel")


# ── F-003: resource limits ────────────────────────────────────────────────────

class TestMaterializationLimits:

    def test_oversized_base64_rejected_before_decode(self, tmp_path):
        limits = MaterializationLimits(max_file_bytes=16)
        _, _, fm = _build(RecordingKernel(), tmp_path, limits=limits)
        big = base64.b64encode(b"x" * 24).decode()   # estimate 32 bytes > 16
        with pytest.raises(MaterializationLimitError):
            fm.process([{"name": "big.bin", "type": "application/octet-stream", "data": big}])

    def test_too_many_files_rejected(self, tmp_path):
        limits = MaterializationLimits(max_files_per_request=2)
        _, _, fm = _build(RecordingKernel(), tmp_path, limits=limits)
        files = [
            {"name": f"f{i}.txt", "type": "text/plain", "data": base64.b64encode(b"x").decode()}
            for i in range(3)
        ]
        with pytest.raises(MaterializationLimitError):
            fm.process(files)

    def test_total_bytes_budget(self, tmp_path):
        limits = MaterializationLimits(max_total_file_bytes=10)
        _, _, fm = _build(RecordingKernel(), tmp_path, limits=limits)
        # 8 bytes fits; two 8-byte files exceed the 10-byte total budget.
        fm.process([{"name": "a.bin", "type": "application/octet-stream",
                     "data": base64.b64encode(b"a" * 8).decode()}])
        with pytest.raises(MaterializationLimitError):
            fm.process([{"name": "b.bin", "type": "application/octet-stream",
                         "data": base64.b64encode(b"b" * 8).decode()}])

    def test_estimate_base64_size(self):
        assert _estimate_base64_size("YWJj") == 3        # "abc"
        assert _estimate_base64_size("YQ==") == 1        # "a" with padding
        assert _estimate_base64_size("  YWJj  ") == 3    # whitespace ignored


# ── F-004: storage isolation + cleanup ────────────────────────────────────────

class TestStorageIsolationAndCleanup:

    def test_identical_filenames_isolated(self, tmp_path):
        _, _, fm1 = _build(RecordingKernel(), tmp_path)
        _, _, fm2 = _build(RecordingKernel(), tmp_path)

        body = {"files": [{"name": "sales.csv", "type": "text/csv",
                           "data": base64.b64encode(b"a,b\n1,2\n").decode()}]}
        r1 = fm1.process_from_context(body)
        r2 = fm2.process_from_context(body)

        assert len(r1) == 1 and len(r2) == 1
        # Different storage locations for the same original filename.
        assert r1[0].local_path != r2[0].local_path
        assert r1[0].local_path.endswith("sales.csv")
        assert r2[0].local_path.endswith("sales.csv")

    def test_cleanup_removes_session_dir(self, tmp_path):
        _, _, fm = _build(RecordingKernel(), tmp_path)
        session_dir = fm._session_dir
        assert session_dir.exists()
        fm.cleanup()
        assert not session_dir.exists()

    def test_cleanup_is_idempotent(self, tmp_path):
        _, _, fm = _build(RecordingKernel(), tmp_path)
        fm.cleanup()
        fm.cleanup()   # must not raise
