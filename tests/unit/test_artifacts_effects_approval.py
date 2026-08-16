"""
Unit tests for the artifact store (#94/#95), effect ledger (#92/#93),
and human approval gate (#90) — all wired through the engine.
"""

from pathlib import Path

import pytest

from kerno.approval import (
    ApprovalDecision, ApprovalRequest, AutoApprovalGate, DenyByDefaultGate,
)
from kerno.artifacts import (
    MEDIA_TYPE_CSV, MEDIA_TYPE_IPYNB, ArtifactIntegrityError,
    ArtifactRef, ArtifactStore, sha256_bytes,
)
from kerno.effects import (
    EFFECT_FILESYSTEM_WRITE, EFFECT_NETWORK_CONNECT, EFFECTS_NONE,
    EFFECTS_WRITE, EffectLedger, WorkspaceObserver,
)
from kerno.execution.engine import ExecutionEngine
from kerno.security.capabilities import CAP_HUMAN_APPROVAL
from kerno.types import CellOutput


class FakeKernel:
    def __init__(self):
        self.calls = []

    def execute(self, code, timeout=120.0, silent=False):
        self.calls.append(code)
        return CellOutput(stdout="ok")

    def execute_silent(self, code, timeout=15.0):
        return "ok"

    @property
    def namespace(self):
        return "{}"

    @property
    def is_alive(self):
        return True


# ── Artifact store ────────────────────────────────────────────────────────────

class TestArtifactStore:

    def test_store_bytes_content_addressed(self):
        store = ArtifactStore("/tmp/kerno-art-test")
        r1 = store.store_bytes(b"hello", media_type="text/plain")
        r2 = store.store_bytes(b"hello", media_type="text/plain")
        assert r1.digest == r2.digest            # dedupe by content
        assert r1.digest == sha256_bytes(b"hello")
        assert r1.size == 5
        assert store.exists(r1)

    def test_different_content_different_digest(self):
        store = ArtifactStore("/tmp/kerno-art-test")
        r1 = store.store_bytes(b"a")
        r2 = store.store_bytes(b"b")
        assert r1.digest != r2.digest

    def test_immutability(self, tmp_path):
        store = ArtifactStore(tmp_path / "store")
        ref = store.store_bytes(b"immutable")
        path = store.path_for(ref)
        path.write_bytes(b"tampered")            # hostile mutation attempt

        # The content address is verified on read → tampering is DETECTED
        with pytest.raises(ArtifactIntegrityError):
            store.read_bytes(ref)

        # Re-storing the canonical bytes self-heals the address
        ref2 = store.store_bytes(b"immutable")
        assert ref2.digest == ref.digest
        assert store.read_bytes(ref2) == b"immutable"

    def test_store_file_copies(self, tmp_path):
        src = tmp_path / "data.csv"
        src.write_text("a,b\n1,2\n")
        store = ArtifactStore(tmp_path / "store")
        ref = store.store_file(src, media_type=MEDIA_TYPE_CSV,
                               creator_execution="exec_00000001")
        assert ref.media_type == MEDIA_TYPE_CSV
        assert ref.creator_execution == "exec_00000001"
        assert store.read_text(ref) == "a,b\n1,2\n"

    def test_creator_execution_provenance(self):
        store = ArtifactStore("/tmp/kerno-art-test")
        ref = store.store_text("report", media_type=MEDIA_TYPE_IPYNB,
                               creator_execution="exec_42",
                               metadata={"task": "analyze"})
        d = ref.to_dict()
        assert d["creator_execution"] == "exec_42"
        assert d["metadata"]["task"] == "analyze"
        assert ArtifactRef.from_dict(d) == ref

    def test_len_and_contains(self, tmp_path):
        store = ArtifactStore(tmp_path / "store")
        store.store_bytes(b"x")
        store.store_bytes(b"y")
        assert len(store) == 2
        assert store.list_digests()[0].startswith("sha256:")


# ── Effect ledger ─────────────────────────────────────────────────────────────

class TestWorkspaceObserver:

    def test_snapshot_and_diff(self, tmp_path):
        obs = WorkspaceObserver(tmp_path)
        (tmp_path / "a.txt").write_text("1")
        before = obs.snapshot()
        assert "a.txt" in before

        (tmp_path / "b.csv").write_text("x")     # created
        (tmp_path / "a.txt").write_text("2")     # modified
        (tmp_path / "del.txt").write_text("d")   # created then deleted
        (tmp_path / "del.txt").unlink()

        after = obs.snapshot()
        changed = WorkspaceObserver.diff(before, after)
        assert "b.csv" in changed
        assert "a.txt" in changed
        assert "del.txt" not in changed          # net zero


class TestEffectLedger:

    def test_undeclared_write_is_violation(self, tmp_path):
        ledger = EffectLedger(workspace=tmp_path)
        ledger.declare("exec_1", EFFECTS_NONE)   # no write declared

        (tmp_path / "out.csv").write_text("x")   # agent wrote a file

        violations = ledger.observe("exec_1")
        assert len(violations) == 1
        assert violations[0].execution_id == "exec_1"
        assert "out.csv" in violations[0].observed
        assert violations[0].declared == EFFECTS_NONE
        assert ledger.violations == (violations[0],)

    def test_declared_write_is_allowed(self, tmp_path):
        ledger = EffectLedger(workspace=tmp_path)
        ledger.declare("exec_1", EFFECTS_WRITE)

        (tmp_path / "out.csv").write_text("x")

        assert ledger.observe("exec_1") == []    # declared → no violation

    def test_network_effect_not_observable_host_side(self, tmp_path):
        # Documents the boundary: only filesystem is observed; network is
        # enforced by allowlist + container policy.
        ledger = EffectLedger(workspace=tmp_path)
        ledger.declare("exec_1", frozenset({EFFECT_NETWORK_CONNECT}))
        assert ledger.observe("exec_1") == []    # nothing observed → no violation

    def test_no_workspace_means_no_observation(self):
        ledger = EffectLedger()                  # no workspace
        ledger.declare("exec_1", EFFECTS_NONE)
        assert ledger.observe("exec_1") == []


class TestEngineEffects:
    """The engine records declared effects and emits violation events."""

    def test_engine_emits_effect_violation_event(self, tmp_path):
        class WritingKernel(FakeKernel):
            def execute(self, code, timeout=120.0, silent=False):
                Path(tmp_path, "leak.csv").write_text("data")
                return CellOutput(stdout="ok")

        ledger = EffectLedger(workspace=tmp_path)
        engine = ExecutionEngine(WritingKernel(), effect_ledger=ledger)

        engine.execute("write file", effects=EFFECTS_NONE)

        types = [e.event_type for e in engine.events]
        assert "EFFECT_VIOLATION" in types
        viol = [e for e in engine.events if e.event_type == "EFFECT_VIOLATION"]
        assert "leak.csv" in viol[0].payload["undeclared_paths"]
        # Record carries the declared effects
        assert engine.records[0].effects == ()

    def test_engine_declared_write_no_violation(self, tmp_path):
        class WritingKernel(FakeKernel):
            def execute(self, code, timeout=120.0, silent=False):
                Path(tmp_path, "ok.csv").write_text("data")
                return CellOutput(stdout="ok")

        ledger = EffectLedger(workspace=tmp_path)
        engine = ExecutionEngine(WritingKernel(), effect_ledger=ledger)

        engine.execute("write file", effects=EFFECTS_WRITE)

        assert not any(
            e.event_type == "EFFECT_VIOLATION" for e in engine.events
        )
        assert engine.records[0].effects == (EFFECT_FILESYSTEM_WRITE,)


# ── Human approval (audit #90) ───────────────────────────────────────────────

class TestApprovalGate:

    def test_auto_approve_allows(self):
        gate = AutoApprovalGate(ApprovalDecision.APPROVED)
        engine = ExecutionEngine(FakeKernel(), approval_gate=gate)
        out = engine.execute(
            "delete data", capabilities=frozenset({CAP_HUMAN_APPROVAL}),
            approval_description="delete production data",
        )
        assert not out.has_error
        assert len(gate.requests) == 1
        assert gate.requests[0].description == "delete production data"

    def test_auto_deny_blocks_without_touching_kernel(self):
        gate = AutoApprovalGate(ApprovalDecision.DENIED)
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel, approval_gate=gate)
        out = engine.execute(
            "delete data", capabilities=frozenset({CAP_HUMAN_APPROVAL}),
        )
        assert out.has_error
        assert out.error.ename == "ApprovalDenied"
        assert kernel.calls == []                # never reached the kernel
        assert "APPROVAL_DENIED" in [e.event_type for e in engine.events]
        assert engine.records[0].allowed is False

    def test_fail_closed_without_gate(self):
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel)          # NO gate installed
        out = engine.execute(
            "delete data", capabilities=frozenset({CAP_HUMAN_APPROVAL}),
        )
        assert out.has_error
        assert out.error.ename == "ApprovalDenied"
        assert "no ApprovalGate" in out.error.evalue
        assert kernel.calls == []

    def test_human_gate_denies_when_unanswered(self):
        gate = DenyByDefaultGate(ask=lambda req: None)
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel, approval_gate=gate)
        out = engine.execute(
            "risky", capabilities=frozenset({CAP_HUMAN_APPROVAL}),
        )
        assert out.has_error
        assert out.error.ename == "ApprovalDenied"

    def test_human_gate_approves_on_true(self):
        gate = DenyByDefaultGate(ask=lambda req: True)
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel, approval_gate=gate)
        out = engine.execute(
            "safe", capabilities=frozenset({CAP_HUMAN_APPROVAL}),
        )
        assert not out.has_error
        assert len(kernel.calls) == 1
