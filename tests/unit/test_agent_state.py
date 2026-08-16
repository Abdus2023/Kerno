"""
Unit tests for AgentState versioning — the formal execution model
(audit #27):  Stateₙ + Action + Observation → Stateₙ₊₁, with fork/snapshot.
"""

from kerno.interfaces import AgentState


class TestAdvance:

    def test_advance_increments_version(self):
        s0 = AgentState(task="t")
        s1 = s0.advance()
        assert s0.version == 0
        assert s1.version == 1
        assert s1.parent_version == 0

    def test_advance_records_transition_in_metadata(self):
        s0 = AgentState(task="t")
        s1 = s0.advance(action="cell 1", observation="ok")
        transitions = s1.metadata["transitions"]
        assert transitions[-1] == {
            "from_version": 0,
            "to_version":   1,
            "action":       "cell 1",
            "observation":  "ok",
        }

    def test_advance_copies_containers(self):
        s0 = AgentState(task="t")
        s0.history.append("cell")
        s0.metadata["k"] = "v"
        s0.artifact_refs.append("sha256:abc")

        s1 = s0.advance()

        # Mutating the old state must not affect the new one
        s0.history.append("more")
        s0.metadata["k"] = "changed"
        s0.artifact_refs.append("sha256:def")

        assert s1.history == ["cell"]
        assert s1.metadata == {"k": "v"}
        assert s1.artifact_refs == ["sha256:abc"]

    def test_advance_preserves_correlation_fields(self):
        s0 = AgentState(
            task="t", session_id="sess-1",
            kernel_generation=2, kernel_state_ref="k-0001/g2",
            execution_counter=7, checkpoint_id="ckpt_x",
        )
        s1 = s0.advance()
        assert s1.session_id == "sess-1"
        assert s1.kernel_generation == 2
        assert s1.kernel_state_ref == "k-0001/g2"
        assert s1.execution_counter == 7
        assert s1.checkpoint_id == "ckpt_x"


class TestFork:

    def test_fork_creates_new_branch(self):
        s0 = AgentState(task="t")
        s1 = s0.fork(branch_id="exp-a")
        assert s1.branch_id == "exp-a"
        assert s1.parent_version == s0.version
        assert s1.version == 1

    def test_fork_generates_branch_id_when_omitted(self):
        s0 = AgentState(task="t")
        s1 = s0.fork()
        assert s1.branch_id.startswith("branch-")
        assert s1.branch_id != "main"

    def test_branches_diverge_independently(self):
        base = AgentState(task="t", goals=["g1"])
        a = base.fork(branch_id="exp-a")
        b = base.fork(branch_id="exp-b")

        a.goals.append("g2-a")
        b.goals.append("g2-b")

        assert a.goals == ["g1", "g2-a"]
        assert b.goals == ["g1", "g2-b"]
        # Both share the same baseline version
        assert a.parent_version == b.parent_version == base.version


class TestSnapshot:

    def test_snapshot_is_plain_dict(self):
        s = AgentState(
            task="t", session_id="s", version=3,
            goals=["g"], artifact_refs=["sha256:x"],
        )
        snap = s.snapshot()
        assert snap["task"] == "t"
        assert snap["version"] == 3
        assert snap["history_len"] == 0
        assert snap["artifact_refs"] == ["sha256:x"]
        assert isinstance(snap, dict)

    def test_snapshot_is_detached_from_state(self):
        s = AgentState(task="t")
        snap = s.snapshot()
        s.goals.append("g")
        s.execution_counter += 1
        assert snap["goals"] == []
        assert snap["execution_counter"] == 0


class TestRecordExecution:

    def test_record_execution_updates_counter_and_provenance(self):
        s = AgentState(task="t")
        s.record_execution("exec_00000042", cell_num=7, artifacts=["sha256:abc"])
        assert s.execution_counter == 1
        assert s.provenance["exec_00000042"]["cell_num"] == 7
        assert s.provenance["exec_00000042"]["artifacts"] == ["sha256:abc"]

    def test_record_execution_defaults(self):
        s = AgentState(task="t")
        s.record_execution("exec_1")
        assert s.provenance["exec_1"] == {"cell_num": 0, "artifacts": []}
