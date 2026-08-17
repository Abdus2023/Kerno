"""
Security invariant suite (P3.16) — release gate.

Each test asserts ONE security invariant, end-to-end, without needing a
real kernel (a recording fake proves "the kernel was never touched").
These tests are deliberately compact so they can run in CI in seconds.

Invariants covered:
  I-01  no raw-kernel agent path          (K-001)
  I-02  no raw-kernel server path         (K-001, static gate)
  I-03  capability denial pre-execution   (K-008)
  I-04  allowlist denial pre-execution    (K-001)
  I-05  runtime origin not agent-selectable (F-008)
  I-06  profile cannot downgrade          (K-012 / F-005 / F-006)
  I-07  URL cannot reach private network  (F-002)
  I-08  file size is bounded              (F-003)
  I-09  uploads are isolated              (F-004)
  I-10  streaming preserves the boundary  (K-001)
  I-11  cancellation finalizes the transaction (P1 / K-005)
"""

import base64
import pathlib
import subprocess
import sys

import pytest

from kerno.execution.engine import ExecutionEngine, ORIGIN_RUNTIME
from kerno.security.allowlist import AllowList
from kerno.security.capabilities import CAP_KERNEL_EXECUTE, CapabilityBroker
from kerno.server.files import (
    FileMaterializer,
    MaterializationExecutor,
    MaterializationLimitError,
    MaterializationLimits,
    UrlPolicyError,
    validate_download_url,
)
from kerno.server.security import resolve_effective_profile
from kerno.types import CellOutput

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

VIOLATING = "import requests\nrequests.get('http://evil.com')"


class RecordingKernel:
    """Records every execution; satisfies the Executor protocol."""

    def __init__(self):
        self.calls = []

    def execute(self, code, timeout=120.0, silent=False, **kwargs):
        self.calls.append(code)
        return CellOutput(stdout="ok")

    def execute_silent(self, code, timeout=15.0, **kwargs):
        return "ok"

    @property
    def namespace(self):
        return "{}"

    @property
    def is_alive(self):
        return True


# ── I-01 / I-03 / I-04: agent code never touches the raw kernel ──────────────

class TestAgentExecutionBoundary:

    def test_allowlist_denial_never_reaches_kernel(self):
        kernel = RecordingKernel()
        engine = ExecutionEngine(kernel, allowlist=AllowList.data_analysis())
        out = engine.execute(VIOLATING)
        assert out.has_error
        assert out.error.ename == "AllowListViolation"
        assert kernel.calls == []          # I-01: nothing got through

    def test_capability_denial_never_reaches_kernel(self):
        kernel = RecordingKernel()
        broker = CapabilityBroker()        # no grants
        engine = ExecutionEngine(
            kernel, broker=broker,
            default_capabilities=frozenset({CAP_KERNEL_EXECUTE}),
        )
        out = engine.execute("x = 1")
        assert out.has_error
        assert out.error.ename == "CapabilityViolation"
        assert kernel.calls == []          # I-03: denied before execution


# ── I-02: the server layer contains no raw-kernel execution ─────────────────

class TestServerLayerBoundary:

    def test_static_raw_kernel_gate_passes(self):
        proc = subprocess.run(
            [sys.executable, "scripts/check_raw_kernel.py"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr


# ── I-05: runtime origin is not agent-selectable ─────────────────────────────

class TestOriginAuthority:

    def test_public_execute_rejects_runtime_origin(self):
        engine = ExecutionEngine(RecordingKernel())
        with pytest.raises(ValueError):
            engine.execute("x = 1", origin=ORIGIN_RUNTIME)

    def test_public_stream_rejects_runtime_origin(self):
        engine = ExecutionEngine(RecordingKernel())
        with pytest.raises(ValueError):
            list(engine.stream_execute("x = 1", origin=ORIGIN_RUNTIME))


# ── I-06: client cannot downgrade the server security profile ────────────────

class TestProfileGovernance:

    def test_weaker_requests_are_upgraded(self):
        assert resolve_effective_profile("permissive", server_default="data_analysis", allow_downgrade=False) == "data_analysis"
        assert resolve_effective_profile("none", server_default="data_analysis", allow_downgrade=False) == "data_analysis"

    def test_equal_or_stronger_requests_pass(self):
        assert resolve_effective_profile("data_analysis", server_default="data_analysis", allow_downgrade=False) == "data_analysis"
        assert resolve_effective_profile("read_only", server_default="data_analysis", allow_downgrade=False) == "read_only"


# ── I-07: outbound URL policy (SSRF) ─────────────────────────────────────────

class TestUrlPolicy:

    @pytest.mark.parametrize("url", [
        "http://127.0.0.1:8000/x",
        "http://10.0.0.1/x",
        "http://192.168.1.1/x",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/x",
        "file:///etc/passwd",
        "ftp://example.com/x",
    ])
    def test_private_and_forbidden_urls_rejected(self, url):
        with pytest.raises(UrlPolicyError):
            validate_download_url(url)


# ── I-08 / I-09: materialization bounds + isolation ──────────────────────────

class TestMaterializationBoundary:

    def _fm(self, kernel, tmp_path, limits=None):
        return FileMaterializer(
            MaterializationExecutor(ExecutionEngine(kernel)),
            upload_dir=str(tmp_path / "uploads"), limits=limits,
        )

    def test_file_size_is_bounded(self, tmp_path):
        limits = MaterializationLimits(max_file_bytes=16)
        fm = self._fm(RecordingKernel(), tmp_path, limits)
        big = base64.b64encode(b"x" * 24).decode()
        with pytest.raises(MaterializationLimitError):
            fm.process([{"name": "big.bin", "type": "application/octet-stream", "data": big}])

    def test_uploads_are_isolated(self, tmp_path):
        body = {"files": [{"name": "sales.csv", "type": "text/csv",
                           "data": base64.b64encode(b"a,b\n1,2\n").decode()}]}
        fm1 = self._fm(RecordingKernel(), tmp_path)
        fm2 = self._fm(RecordingKernel(), tmp_path)
        r1 = fm1.process_from_context(body)
        r2 = fm2.process_from_context(body)
        assert r1[0].local_path != r2[0].local_path


# ── I-10 / I-11: streaming parity + guaranteed finalization ──────────────────

class TestStreamingAndFinalization:

    def test_streaming_preserves_security_boundary(self):
        kernel = RecordingKernel()
        engine = ExecutionEngine(kernel, allowlist=AllowList.data_analysis())
        chunks = list(engine.stream_execute(VIOLATING))
        assert len(chunks) == 1
        assert chunks[0][0] == "error"
        assert "AllowListViolation" in chunks[0][1]
        assert "requests_module" in chunks[0][1]
        assert kernel.calls == []          # I-10: nothing got through

    def test_cancellation_finalizes_transaction(self):
        import threading
        kernel = RecordingKernel()
        engine = ExecutionEngine(kernel)
        cancel = threading.Event()
        cancel.set()
        out = engine.execute("x = 1", cancel_event=cancel)
        assert out.has_error
        assert out.error.ename == "KernelInterrupted"
        assert kernel.calls == []          # never started
        # The transaction was finalized: the cancellation is recorded and
        # the terminal event was emitted.
        assert engine.records
        event_types = [e.event_type for e in engine.events]
        assert "EXECUTION_CANCELLED" in event_types
