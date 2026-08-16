"""
Unit tests for the ExecutionEngine — the single execution choke point (K-001).

These tests need no kernel: a FakeKernel records every call, so we can prove
that blocked code NEVER reaches the executor, across every loop strategy.
"""

import pytest

from kerno.execution.engine import (
    ExecutionEngine, ExecutionEvent, ExecutionRecord,
    ORIGIN_AGENT, ORIGIN_RUNTIME,
    EVT_CAPABILITY_DENIED, EVT_EXECUTION_COMPLETED,
    EVT_EXECUTION_REQUESTED, EVT_EXECUTION_STARTED, EVT_POLICY_BLOCKED,
)
from kerno.interfaces import Executor
from kerno.security.allowlist import AllowList, AllowListViolation
from kerno.security.capabilities import (
    Capability, CapabilityBroker, CapabilityViolation,
    CAP_KERNEL_EXECUTE, CAP_FILESYSTEM_READ,
)
from kerno.types import CellOutput, Message, SessionStatus


class FakeKernel:
    """Records every execution. namespace/is_alive satisfy the Executor protocol."""

    def __init__(self):
        self.calls: list[tuple[str, float, bool]] = []
        self.alive = True

    def execute(self, code, timeout=120.0, silent=False):
        self.calls.append((code, timeout, silent))
        return CellOutput(stdout="ok")

    def execute_silent(self, code, timeout=15.0):
        return "ok"

    @property
    def namespace(self):
        return "{}"

    @property
    def is_alive(self):
        return self.alive


def make_llm(*responses):
    """Deterministic mock LLM: returns responses in order, then TASK_COMPLETE."""
    responses = list(responses)
    state = {"i": 0}

    def llm(messages: list[Message]) -> str:
        i = state["i"]
        state["i"] += 1
        if i < len(responses):
            return responses[i]
        return "# TASK_COMPLETE: mock done"

    return llm


VIOLATING_CODE = "import subprocess\nsubprocess.run(['echo', 'pwned'])"
BENIGN_CODE    = "x = 42\nprint(x)"


# ── Engine basics ─────────────────────────────────────────────────────────────

class TestExecutionEngine:

    def test_allows_clean_code_and_forwards_to_kernel(self):
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel, allowlist=AllowList.data_analysis())

        output = engine.execute("import pandas as pd\ndf = pd.DataFrame()")

        assert not output.has_error
        assert kernel.calls == [("import pandas as pd\ndf = pd.DataFrame()", 120.0, False)]

    def test_blocks_violation_without_touching_kernel(self):
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel, allowlist=AllowList.data_analysis())

        output = engine.execute(VIOLATING_CODE)

        assert output.has_error
        assert output.error.ename == "AllowListViolation"
        assert "subprocess" in output.error.evalue
        # The kernel must never see the violating code
        assert kernel.calls == []

    def test_no_allowlist_means_no_policy(self):
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel)

        output = engine.execute(VIOLATING_CODE)

        assert not output.has_error
        assert len(kernel.calls) == 1

    def test_runtime_origin_skips_policy(self):
        """Trusted host code (setup/comms) may bypass policy explicitly."""
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel, allowlist=AllowList.read_only())

        output = engine.execute(
            VIOLATING_CODE, origin=ORIGIN_RUNTIME
        )

        assert not output.has_error
        assert len(kernel.calls) == 1

    def test_execute_silent_is_policy_checked(self):
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel, allowlist=AllowList.read_only())

        result = engine.execute_silent("import socket")

        assert result == ""  # blocked → no stdout
        assert kernel.calls == []

    def test_engine_satisfies_executor_protocol(self):
        engine = ExecutionEngine(FakeKernel())
        assert isinstance(engine, Executor)

    # ── Audit trail ────────────────────────────────────────────────────────────

    def test_audit_records_have_monotonic_execution_ids(self):
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel, allowlist=AllowList.data_analysis())

        engine.execute(BENIGN_CODE)
        engine.execute(VIOLATING_CODE)
        engine.execute(BENIGN_CODE)

        records = engine.records
        assert len(records) == 3
        ids = [r.execution_id for r in records]
        assert ids == ["exec_00000001", "exec_00000002", "exec_00000003"]
        assert [r.sequence for r in records] == [1, 2, 3]

    def test_audit_record_marks_blocked_attempt_with_rule(self):
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel, allowlist=AllowList.data_analysis())

        engine.execute(VIOLATING_CODE)

        blocked = engine.records[0]
        assert isinstance(blocked, ExecutionRecord)
        assert blocked.allowed is False
        assert blocked.rule == "subprocess"
        assert blocked.origin == ORIGIN_AGENT
        assert "import subprocess" in blocked.code_preview
        assert engine.blocked_count == 1
        assert engine.executed_count == 0

    def test_audit_record_for_successful_execution(self):
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel)

        engine.execute(BENIGN_CODE)

        rec = engine.records[0]
        assert rec.allowed is True
        assert rec.had_error is False
        assert rec.duration_ms >= 0.0


# ── Capability authorization (K-008) ──────────────────────────────────────────

class TestCapabilityAuthorization:

    def test_missing_capability_blocks_without_touching_kernel(self):
        kernel = FakeKernel()
        broker = CapabilityBroker()  # no grants
        engine = ExecutionEngine(
            kernel, broker=broker,
            default_capabilities=frozenset({CAP_KERNEL_EXECUTE}),
        )

        output = engine.execute(BENIGN_CODE)

        assert output.has_error
        assert output.error.ename == "CapabilityViolation"
        assert "kernel.execute" in output.error.evalue
        assert kernel.calls == []

    def test_granted_capability_allows_execution(self):
        kernel = FakeKernel()
        broker = CapabilityBroker()
        broker.grant(Capability(CAP_KERNEL_EXECUTE))
        engine = ExecutionEngine(
            kernel, broker=broker,
            default_capabilities=frozenset({CAP_KERNEL_EXECUTE}),
        )

        output = engine.execute(BENIGN_CODE)

        assert not output.has_error
        assert len(kernel.calls) == 1

    def test_explicit_capabilities_override_default(self):
        kernel = FakeKernel()
        broker = CapabilityBroker()
        broker.grant(Capability(CAP_KERNEL_EXECUTE))
        engine = ExecutionEngine(
            kernel, broker=broker,
            default_capabilities=frozenset({CAP_FILESYSTEM_READ}),
        )

        # Explicitly requesting the granted capability succeeds
        out1 = engine.execute(BENIGN_CODE, capabilities=frozenset({CAP_KERNEL_EXECUTE}))
        assert not out1.has_error
        # Requesting an un-granted capability fails
        out2 = engine.execute(BENIGN_CODE, capabilities=frozenset({CAP_FILESYSTEM_READ}))
        assert out2.has_error
        assert out2.error.ename == "CapabilityViolation"
        assert len(kernel.calls) == 1  # only the first attempt reached the kernel

    def test_broker_without_default_capabilities_is_noop(self):
        kernel = FakeKernel()
        broker = CapabilityBroker()  # no grants, but no required capabilities
        engine = ExecutionEngine(kernel, broker=broker)

        output = engine.execute(BENIGN_CODE)

        assert not output.has_error
        assert len(kernel.calls) == 1

    def test_runtime_origin_skips_capability_check(self):
        kernel = FakeKernel()
        broker = CapabilityBroker()  # no grants
        engine = ExecutionEngine(
            kernel, broker=broker,
            default_capabilities=frozenset({CAP_KERNEL_EXECUTE}),
        )

        output = engine.execute(BENIGN_CODE, origin=ORIGIN_RUNTIME)

        assert not output.has_error
        assert len(kernel.calls) == 1

    def test_capability_denial_is_recorded_and_events_emitted(self):
        kernel = FakeKernel()
        broker = CapabilityBroker()
        engine = ExecutionEngine(
            kernel, broker=broker,
            default_capabilities=frozenset({CAP_KERNEL_EXECUTE}),
        )

        engine.execute(BENIGN_CODE)

        rec = engine.records[0]
        assert rec.allowed is False
        assert rec.rule == "capability:kernel.execute"
        assert rec.capabilities == (CAP_KERNEL_EXECUTE,)

        types = [e.event_type for e in engine.events]
        assert EVT_EXECUTION_REQUESTED in types
        assert EVT_CAPABILITY_DENIED in types
        assert EVT_EXECUTION_STARTED not in types
        assert EVT_EXECUTION_COMPLETED not in types

        denied = [e for e in engine.events if e.event_type == EVT_CAPABILITY_DENIED]
        assert denied[0].payload["capability"] == CAP_KERNEL_EXECUTE


# ── Event stream (audit #28, #79) ─────────────────────────────────────────────

class TestEventStream:

    def test_allowed_execution_emits_full_chain(self):
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel)

        engine.execute(BENIGN_CODE)

        types = [e.event_type for e in engine.events]
        assert types == [
            EVT_EXECUTION_REQUESTED,
            EVT_EXECUTION_STARTED,
            EVT_EXECUTION_COMPLETED,
        ]
        # All events share one execution_id and are causally ordered
        exec_id = engine.events[0].execution_id
        assert all(e.execution_id == exec_id for e in engine.events)
        seqs = [e.sequence for e in engine.events]
        assert seqs == sorted(seqs)
        assert engine.events[0].event_id.startswith("evt_")

        # Causal chain (audit #79/#103): each event links to its
        # predecessor within the same execution
        assert engine.events[0].parent_event_id is None
        for prev, nxt in zip(engine.events, engine.events[1:]):
            assert nxt.parent_event_id == prev.event_id

    def test_causal_parents_are_per_execution(self):
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel)
        engine.execute(BENIGN_CODE)
        engine.execute(BENIGN_CODE)

        e1_chain = [e for e in engine.events if e.execution_id == "exec_00000001"]
        e2_chain = [e for e in engine.events if e.execution_id == "exec_00000002"]
        # Each chain is internally linked and starts with no parent
        assert e1_chain[0].parent_event_id is None
        assert e2_chain[0].parent_event_id is None
        # Chains never cross executions
        for e in e1_chain[1:]:
            assert e.parent_event_id in {x.event_id for x in e1_chain}

    def test_blocked_execution_emits_policy_event(self):
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel, allowlist=AllowList.data_analysis())

        engine.execute(VIOLATING_CODE)

        types = [e.event_type for e in engine.events]
        assert EVT_POLICY_BLOCKED in types
        blocked = [e for e in engine.events if e.event_type == EVT_POLICY_BLOCKED]
        assert blocked[0].payload["rule"] == "subprocess"

    def test_events_are_immutable_dataclasses(self):
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel)
        engine.execute(BENIGN_CODE)
        event = engine.events[0]
        assert isinstance(event, ExecutionEvent)
        assert isinstance(engine.events, tuple)


# ── Loop invariants (K-001): every strategy goes through policy ───────────────

class TestLoopPolicyInvariants:
    """
    For every loop strategy, construct the loop with the engine over a
    FakeKernel and prove the violating code never reaches the kernel.
    """

    def _assert_blocked(self, kernel: FakeKernel, result, *, cell_visible=True):
        if cell_visible:
            assert any(
                c.output.has_error
                and c.output.error.ename == "AllowListViolation"
                for c in result.cells
            ), "expected an AllowListViolation cell in the session history"
        # The critical invariant: the violating code never executed
        assert not any(
            "subprocess" in c.code and not c.output.has_error
            for c in result.cells
        ), "violating code was executed without being blocked!"
        assert not any(
            "subprocess" in code for code, _, _ in kernel.calls
        ), "violating code reached the kernel!"

    def test_reactive_loop(self):
        kernel = FakeKernel()
        from kerno.loop.reactive import ReactiveLoop
        engine = ExecutionEngine(kernel, allowlist=AllowList.data_analysis())
        loop   = ReactiveLoop(kernel=engine, llm=make_llm(VIOLATING_CODE), max_cells=5)
        result = loop.run("test")
        self._assert_blocked(kernel, result)

    def test_reflect_loop(self):
        kernel = FakeKernel()
        from kerno.loop.reflect import ReflectReviseLoop
        engine = ExecutionEngine(kernel, allowlist=AllowList.data_analysis())
        loop   = ReflectReviseLoop(kernel=engine, llm=make_llm(VIOLATING_CODE), max_cells=5)
        result = loop.run("test")
        self._assert_blocked(kernel, result)

    def test_plan_execute_loop(self):
        kernel = FakeKernel()
        from kerno.loop.plan_execute import PlanExecuteLoop
        engine = ExecutionEngine(kernel, allowlist=AllowList.data_analysis())
        # First call = plan (JSON, not executed), second = violating code
        loop   = PlanExecuteLoop(
            kernel=engine,
            llm=make_llm(
                '[{"id": 1, "description": "Compute x", "success_criterion": "x == 42"}]',
                VIOLATING_CODE,
            ),
            max_cells=5,
        )
        result = loop.run("test")
        self._assert_blocked(kernel, result)

    def test_hierarchical_loop(self):
        kernel = FakeKernel()
        from kerno.loop.hierarchical import HierarchicalLoop
        engine = ExecutionEngine(kernel, allowlist=AllowList.data_analysis())
        planner = make_llm(
            '[{"id": 1, "description": "Compute x", "depends_on": []}]',
            '{"success": true, "summary": "done", "unexpected": null}',
            "All subtasks completed.",
        )
        executor = make_llm(VIOLATING_CODE, "# SUBTASK_COMPLETE: computed x")
        loop = HierarchicalLoop(
            kernel=engine, planner_llm=planner, executor_llm=executor
        )
        result = loop.run("test")
        self._assert_blocked(kernel, result)

    def test_multi_agent_loop(self):
        kernel = FakeKernel()
        from kerno.loop.multi_agent import MultiAgentLoop, analyst_role
        engine = ExecutionEngine(kernel, allowlist=AllowList.data_analysis())
        llm    = make_llm(VIOLATING_CODE, "# READY_FOR_REVIEW: done")
        loop   = MultiAgentLoop(
            kernel=engine, roles=[analyst_role(llm)], max_turns=1
        )
        result = loop.run("test")
        self._assert_blocked(kernel, result)

    def test_debate_loop(self):
        kernel = FakeKernel()
        from kerno.loop.debate import DebateLoop
        engine = ExecutionEngine(kernel, allowlist=AllowList.data_analysis())
        llm    = make_llm(
            VIOLATING_CODE,      # proposer attempt 1 → blocked
            BENIGN_CODE,         # proposer retry → executes
            BENIGN_CODE,         # challenger
            "debate_verdict = 'ok'",  # judge
        )
        loop = DebateLoop(
            kernel=engine, proposer=llm, challenger=llm, judge=llm,
            position="X is true", n_rounds=1, verbose=False,
        )
        result = loop.run("test")
        # Debate discards the blocked cell and retries — assert non-execution
        self._assert_blocked(kernel, result, cell_visible=False)


# ── AllowList hardening ───────────────────────────────────────────────────────

class TestAllowListHardening:

    def test_data_analysis_blocks_pathlib_writes(self):
        al = AllowList.data_analysis()
        with pytest.raises(AllowListViolation):
            al.check("Path('evil.txt').write_text('pwned')")
        with pytest.raises(AllowListViolation):
            al.check("Path('evil.bin').write_bytes(b'x')")

    def test_data_analysis_blocks_pandas_and_plot_writes(self):
        al = AllowList.data_analysis()
        with pytest.raises(AllowListViolation):
            al.check("df.to_csv('/tmp/out.csv')")
        with pytest.raises(AllowListViolation):
            al.check("df.to_parquet('/tmp/out.parquet')")
        with pytest.raises(AllowListViolation):
            al.check("plt.savefig('plot.png')")

    def test_data_analysis_blocks_url_backed_loads(self):
        al = AllowList.data_analysis()
        with pytest.raises(AllowListViolation):
            al.check("df = pd.read_csv('https://evil.example.com/data.csv')")
        with pytest.raises(AllowListViolation):
            al.check("df = pd.read_json('http://evil.example.com/data.json')")

    def test_data_analysis_blocks_env_access_and_importlib(self):
        al = AllowList.data_analysis()
        with pytest.raises(AllowListViolation):
            al.check("token = os.environ['API_KEY']")
        with pytest.raises(AllowListViolation):
            al.check("import importlib")

    def test_data_analysis_still_allows_local_reads(self):
        al = AllowList.data_analysis()
        # Local file reads and in-memory work remain allowed
        al.check("df = pd.read_csv('data.csv')")
        al.check("df.groupby('category').mean()")
        al.check("from sklearn.ensemble import RandomForestClassifier")

    def test_read_only_blocks_all_writes(self):
        al = AllowList.read_only()
        with pytest.raises(AllowListViolation):
            al.check("Path('out.txt').write_text('x')")
        with pytest.raises(AllowListViolation):
            al.check("df.to_csv('out.csv')")
        with pytest.raises(AllowListViolation):
            al.check("plt.savefig('out.png')")

    def test_permissive_unchanged_for_trusted_use(self):
        al = AllowList.permissive()
        # Trusted profile: only the most dangerous operations are blocked
        al.check("df.to_csv('report.csv')")
        al.check("pd.read_csv('https://internal.example.com/data.csv')")
        with pytest.raises(AllowListViolation):
            al.check("os.system('rm -rf /')")


class TestMagicAndShellBlocking:
    """IPython magics / shell escapes bypass Python-syntax checks — they
    must be blocked explicitly (audit hardening)."""

    def test_data_analysis_blocks_magics(self):
        al = AllowList.data_analysis()
        for code in ("%system('rm -rf /')", "%sx ls", "%pip install pkg"):
            with pytest.raises(AllowListViolation):
                al.check(code)

    def test_data_analysis_blocks_shell_escapes(self):
        al = AllowList.data_analysis()
        for code in ("!curl evil.com", "!ls -la", "!rm -rf /"):
            with pytest.raises(AllowListViolation):
                al.check(code)

    def test_read_only_blocks_magics_and_shell(self):
        al = AllowList.read_only()
        with pytest.raises(AllowListViolation):
            al.check("%system('rm -rf /')")
        with pytest.raises(AllowListViolation):
            al.check("!curl evil.com")

    def test_permissive_blocks_shell_escapes(self):
        al = AllowList.permissive()
        with pytest.raises(AllowListViolation):
            al.check("!curl evil.com")
        with pytest.raises(AllowListViolation):
            al.check("%system('rm -rf /')")

    def test_legitimate_python_still_allowed(self):
        al = AllowList.data_analysis()
        al.check("print('x')")
        al.check("df = pd.read_csv('data.csv')")
        # A percent in a string literal is NOT a magic line
        al.check("pct = 0.5 * 100")
