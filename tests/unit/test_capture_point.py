"""
Unit tests for host-side checkpoint capture (audit #59, K-007) — the
safe alternative to kernel-side checkpoint code.
"""

from kerno.core.capture import CapturePoint
from kerno.core.checkpoint import CheckpointStore


class FakeEngine:
    def __init__(self):
        self._seq = 0
    @property
    def event_sequence(self):
        return self._seq


class FakeKernel:
    def __init__(self):
        self.generation = 1


class TestCapturePoint:

    def test_records_checkpoint_every_cell(self):
        store = CheckpointStore()
        engine = FakeEngine()
        kernel = FakeKernel()
        cap = CapturePoint(store, "sess-1", engine=engine, kernel=kernel)

        c1 = cap.after_cell(1)
        c2 = cap.after_cell(2)

        assert c1 is not None and c2 is not None
        assert c1.session_id == "sess-1"
        assert c1.kernel_generation == 1
        assert c2.parent_checkpoint_id == c1.checkpoint_id   # lineage
        assert store.latest("sess-1").checkpoint_id == c2.checkpoint_id

    def test_cadence(self):
        store = CheckpointStore()
        cap = CapturePoint(store, "sess-1", every_n=3)
        assert cap.after_cell(1) is None
        assert cap.after_cell(2) is None
        c3 = cap.after_cell(3)
        assert c3 is not None
        assert c3.summary == "after cell 3"
        assert cap.count == 3
        assert cap.last is c3

    def test_event_sequence_bound(self):
        store = CheckpointStore()
        engine = FakeEngine()
        cap = CapturePoint(store, "sess-1", engine=engine)
        engine._seq = 42
        ckpt = cap.after_cell(1)
        # K-007: the checkpoint is bound to the event-stream position
        assert ckpt.event_sequence == 42

    def test_artifact_hashes(self):
        store = CheckpointStore()
        cap = CapturePoint(store, "sess-1")
        ckpt = cap.after_cell(1, artifact_hashes={"out.csv": "sha256:abc"})
        assert ckpt.artifact_hashes == {"out.csv": "sha256:abc"}

    def test_no_kernel_or_engine(self):
        store = CheckpointStore()
        cap = CapturePoint(store, "sess-1")
        ckpt = cap.after_cell(1)
        assert ckpt.event_sequence == 0
        assert ckpt.kernel_generation == 0
