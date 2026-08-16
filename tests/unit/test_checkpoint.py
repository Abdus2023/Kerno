"""
Unit tests for Checkpoint identity and the CheckpointStore (audit #59, K-007).

K-007: a checkpoint identifies EXACTLY which state and event sequence it
represents — state_version + event_sequence + kernel_generation.
"""

import json

from kerno.core.checkpoint import Checkpoint, CheckpointStore


class TestCheckpointIdentity:

    def test_capture_binds_state_and_event_sequence(self):
        ckpt = Checkpoint.capture(
            session_id="sess-1",
            state_version=7,
            event_sequence=42,
            kernel_generation=2,
            artifact_hashes={"report.csv": "sha256:f00d"},
        )
        assert ckpt.checkpoint_id.startswith("ckpt_")
        assert ckpt.session_id == "sess-1"
        assert ckpt.state_version == 7
        assert ckpt.event_sequence == 42
        assert ckpt.kernel_generation == 2
        assert ckpt.artifact_hashes["report.csv"] == "sha256:f00d"

    def test_serialization_round_trip(self):
        ckpt = Checkpoint.capture(
            session_id="sess-1", state_version=3, event_sequence=10,
            artifact_hashes={"a": "h1"},
        )
        data = json.loads(ckpt.to_json())
        restored = Checkpoint.from_dict(data)
        assert restored.checkpoint_id == ckpt.checkpoint_id
        assert restored.state_version == 3
        assert restored.event_sequence == 10
        assert restored.artifact_hashes == {"a": "h1"}


class TestCheckpointStore:

    def test_save_and_load(self):
        store = CheckpointStore()
        ckpt = Checkpoint.capture("sess-1", state_version=1, event_sequence=5)
        store.save(ckpt)
        assert store.load(ckpt.checkpoint_id) is ckpt

    def test_load_missing_returns_none(self):
        store = CheckpointStore()
        assert store.load("ckpt_ghost") is None

    def test_latest_by_event_sequence(self):
        store = CheckpointStore()
        store.save(Checkpoint.capture("sess-1", state_version=1, event_sequence=5))
        store.save(Checkpoint.capture("sess-1", state_version=2, event_sequence=9))
        store.save(Checkpoint.capture("sess-2", state_version=1, event_sequence=99))

        latest = store.latest("sess-1")
        assert latest.state_version == 2
        assert latest.event_sequence == 9

    def test_fork_preserves_lineage(self):
        store = CheckpointStore()
        parent = store.save(Checkpoint.capture(
            "sess-1", state_version=4, event_sequence=20,
            artifact_hashes={"data.csv": "sha256:abc"},
        ))

        child = store.fork(parent.checkpoint_id)

        assert child.parent_checkpoint_id == parent.checkpoint_id
        assert child.state_version == 4          # same baseline
        assert child.event_sequence == 20        # same event position
        assert child.artifact_hashes == {"data.csv": "sha256:abc"}
        assert store.load(child.checkpoint_id) is child

    def test_fork_unknown_raises(self):
        store = CheckpointStore()
        try:
            store.fork("ckpt_missing")
            assert False, "expected KeyError"
        except KeyError:
            pass


class TestPersistence:

    def test_disk_round_trip(self, tmp_path):
        store = CheckpointStore(persist_dir=str(tmp_path))
        ckpt = Checkpoint.capture("sess-1", state_version=5, event_sequence=8)
        store.save(ckpt)

        # A fresh store on the same directory reloads from disk
        store2 = CheckpointStore(persist_dir=str(tmp_path))
        loaded = store2.load(ckpt.checkpoint_id)
        assert loaded is not None
        assert loaded.state_version == 5
        assert loaded.event_sequence == 8
