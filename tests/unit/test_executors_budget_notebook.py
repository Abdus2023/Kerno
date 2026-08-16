"""
Unit tests for: pluggable executors (#97/#104), hierarchical budgets
(#86), environment lock + notebook-as-artifact (Phase E).
"""

import json

from kerno.artifacts import ArtifactStore
from kerno.audit.notebook import NotebookAuditTrail
from kerno.execution.budget import (
    BudgetAllocationError, BudgetAllocator, ExecutionBudget,
)
from kerno.executors import (
    EXECUTOR_KINDS, ScriptedExecutor, UnknownExecutorKind, make_executor,
)
from kerno.reproducibility import (
    EnvironmentSnapshot, export_lock, save_lock,
)
from kerno.types import Cell, CellOutput, SessionResult, SessionStatus


class TestExecutorFactory:
    """Audit #97: execution is pluggable; the loop never depends on one."""

    def test_all_kinds_registered(self):
        assert set(EXECUTOR_KINDS) == {
            "local", "docker", "dry_run", "replay", "mock", "subprocess",
        }

    def test_subprocess_kind(self):
        ex = make_executor("subprocess")
        out = ex.execute("print(40 + 2)")
        assert not out.has_error
        assert out.stdout.strip() == "42"

    def test_mock_executor(self):
        ex = make_executor("mock", scripted=[CellOutput(stdout="42")])
        out = ex.execute("print(42)")
        assert out.stdout == "42"
        assert ex.requests == ("print(42)",)

    def test_scripted_exhausts_to_echo(self):
        ex = make_executor("mock", scripted=[CellOutput(stdout="one")])
        assert ex.execute("a").stdout == "one"
        assert ex.execute("b").stdout.startswith("[mock]")

    def test_dry_run_executor(self):
        from kerno.security.allowlist import AllowList
        ex = make_executor("dry_run", allowlist=AllowList.data_analysis())
        out = ex.execute("import subprocess")
        assert out.has_error
        assert out.error.ename == "AllowListViolation"

    def test_replay_executor(self):
        recorded = [Cell(code="x = 1", output=CellOutput(stdout="1"), cell_num=1)]
        ex = make_executor("replay", recorded=recorded)
        assert ex.execute("x = 1").stdout == "1"

    def test_unknown_kind_rejected(self):
        try:
            make_executor("banana")
            assert False, "expected UnknownExecutorKind"
        except UnknownExecutorKind:
            pass

    def test_replay_requires_recorded(self):
        try:
            make_executor("replay")
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_scripted_satisfies_executor_protocol(self):
        ex = ScriptedExecutor()
        assert ex.is_alive is True
        assert ex.namespace == "{}"
        assert ex.execute_silent("x") == "[mock] x"


class TestBudgetAllocator:
    """Audit #86: child budgets can never exceed the parent's remaining."""

    def test_allocation_and_remaining(self):
        alloc = BudgetAllocator(ExecutionBudget(
            max_executions=100, max_wall_time=600.0,
        ))
        c1 = alloc.allocate(executions=30, wall_time=200.0)
        c2 = alloc.allocate(executions=40, wall_time=200.0)
        assert c1.max_executions == 30
        assert c2.max_executions == 40
        assert alloc.remaining_exec() == 30
        assert alloc.remaining_time() == 200.0

    def test_over_allocation_rejected(self):
        alloc = BudgetAllocator(ExecutionBudget(max_executions=10))
        alloc.allocate(executions=8)
        try:
            alloc.allocate(executions=5)
            assert False, "expected BudgetAllocationError"
        except BudgetAllocationError:
            pass

    def test_inherit_remaining_when_unspecified(self):
        alloc = BudgetAllocator(ExecutionBudget(max_executions=10))
        child = alloc.allocate(executions=4)
        child2 = alloc.allocate()          # inherits remaining = 6
        assert child2.max_executions == 6

    def test_unlimited_parent_stays_unlimited(self):
        alloc = BudgetAllocator(ExecutionBudget())
        child = alloc.allocate(executions=5)
        assert child.max_executions == 5
        assert alloc.remaining_exec() is None   # parent had no cap

    def test_remaining_property(self):
        alloc = BudgetAllocator(ExecutionBudget(max_executions=10))
        alloc.allocate(executions=7)
        rem = alloc.remaining
        assert rem.max_executions == 3


class TestEnvironmentLock:
    """Phase E: pinned environment for execution reproducibility."""

    def test_export_lock_pins_versions(self):
        env = EnvironmentSnapshot(
            python_version="3.11.9", platform="linux",
            kernel_spec="python3",
            packages={"pandas": "2.2.2", "numpy": "1.26.4"},
        )
        lock = export_lock(env)
        assert "pandas==2.2.2" in lock
        assert "numpy==1.26.4" in lock

    def test_export_lock_skips_versionless(self):
        env = EnvironmentSnapshot(
            python_version="3.11", platform="x", kernel_spec="python3",
            packages={"foo": "", "bar": "1.0"},
        )
        lock = export_lock(env)
        assert "foo" not in lock
        assert "bar==1.0" in lock

    def test_save_lock_writes_file(self, tmp_path):
        env = EnvironmentSnapshot(
            python_version="3.11", platform="x", kernel_spec="python3",
            packages={"pandas": "2.2.2"},
        )
        path = save_lock(env, tmp_path / "requirements.lock")
        assert path.read_text() == "pandas==2.2.2\n"


class TestNotebookAsArtifact:
    """Audit #96: the notebook is just another artifact."""

    def _result(self):
        return SessionResult(
            session_id="sess-nb", task="analyze",
            status=SessionStatus.COMPLETE,
            cells=[Cell(code="x = 1", output=CellOutput(stdout="1"), cell_num=1)],
        )

    def test_save_as_artifact_returns_path_and_ref(self, tmp_path):
        store = ArtifactStore(tmp_path / "artifacts")
        trail = NotebookAuditTrail.from_result(self._result())

        path, ref = trail.save_as_artifact(store, str(tmp_path / "sessions"))

        assert path.exists()
        assert ref.digest.startswith("sha256:")
        assert ref.media_type == "application/x-ipynb+json"
        assert store.exists(ref)
        # The stored bytes parse as a notebook
        nb = json.loads(store.read_bytes(ref))
        assert nb["cells"][0]["cell_type"] == "markdown"

    def test_storing_same_file_twice_deduplicates(self, tmp_path):
        store = ArtifactStore(tmp_path / "artifacts")
        trail = NotebookAuditTrail.from_result(self._result())
        path, r1 = trail.save_as_artifact(store, str(tmp_path / "s"))

        # Storing the SAME bytes again yields the same digest, no dupes
        r2 = store.store_file(path, media_type=r1.media_type)
        assert r1.digest == r2.digest
        assert len(store) == 1
