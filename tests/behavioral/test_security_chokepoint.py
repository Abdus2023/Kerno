"""
Behavioral regression tests for the security choke point (K-001).

P0 from the deep audit: the allowlist guard in run() was installed only for
the reactive/reflect/plan paths — hierarchical, multi_agent and debate ran
unguarded, and run_with_pool had no guard at all.

These tests use a REAL kernel and prove that LLM-generated code violating
the allowlist is blocked in EVERY loop strategy exposed by run():
the violating code must never execute successfully (on the old code the
`import subprocess` cell would execute without error and the test fails).
"""

import pytest

from kerno import run, run_with_pool
from kerno.security.allowlist import AllowList
from kerno.security.capabilities import (
    Capability, CapabilityBroker, CAP_KERNEL_EXECUTE,
)
from kerno.types import Message, SessionStatus


VIOLATING_CODE = "import subprocess\nsubprocess.run(['echo', 'pwned'])\n"
BENIGN_CODE    = "x = 42\nprint('x =', x)"


def make_llm(*responses):
    """Deterministic mock LLM with a TASK_COMPLETE fallback."""
    responses = list(responses)
    state = {"i": 0}

    def llm(messages: list[Message]) -> str:
        i = state["i"]
        state["i"] += 1
        if i < len(responses):
            return responses[i]
        return "# TASK_COMPLETE: mock done"

    return llm


def assert_no_successful_violation(result):
    """The violating code may appear in history only as a blocked error cell."""
    for cell in result.cells:
        if "subprocess" in cell.code:
            assert cell.output.has_error, (
                "violating code executed successfully — policy bypass!"
            )
            assert cell.output.error.ename == "AllowListViolation"


@pytest.mark.integration
class TestRunPolicyChokepoint:
    """Every loop strategy of run() must enforce the allowlist."""

    @pytest.mark.parametrize("loop", ["reactive", "reflect", "plan"])
    def test_standard_loops_block_violations(self, loop):
        # plan executes a planning phase first — respond with valid plan JSON
        first = (
            '[{"id": 1, "description": "Compute x", '
            '"success_criterion": "x == 42"}]'
            if loop == "plan" else VIOLATING_CODE
        )
        result = run(
            "Analyze the data",
            llm=make_llm(first, VIOLATING_CODE),
            loop=loop,
            allowlist=AllowList.data_analysis(),
            max_cells=5,
            load_default_skills=False,   # policy enforcement is the subject
        )
        assert_no_successful_violation(result)
        assert any(
            c.output.has_error and c.output.error.ename == "AllowListViolation"
            for c in result.cells
        ), f"{loop}: expected an AllowListViolation cell"

    def test_hierarchical_loop_blocks_violations(self):
        planner = make_llm(
            '[{"id": 1, "description": "Compute x", "depends_on": []}]',
            '{"success": true, "summary": "done", "unexpected": null}',
            "Done.",
        )
        executor = make_llm(VIOLATING_CODE, "# SUBTASK_COMPLETE: computed x")
        result = run(
            "Analyze the data",
            llm=executor,
            loop="hierarchical",
            planner_llm=planner,
            allowlist=AllowList.data_analysis(),
            load_default_skills=False,   # policy enforcement is the subject
        )
        assert_no_successful_violation(result)
        assert any(
            c.output.has_error and c.output.error.ename == "AllowListViolation"
            for c in result.cells
        ), "hierarchical: expected an AllowListViolation cell"

    def test_multi_agent_loop_blocks_violations(self):
        from kerno.loop.multi_agent import AgentRole

        llm = make_llm(
            VIOLATING_CODE,
            "# TASK_COMPLETE: done",
        )
        # Custom role: yields on TASK_COMPLETE so the mock fallback ends
        # the turn after one cell instead of running to max_cells.
        role = AgentRole(
            name        = "analyst",
            llm         = llm,
            system      = "You are an analyst.",
            yield_signal = "# TASK_COMPLETE",
        )
        result = run(
            "Analyze the data",
            llm=llm,
            loop="multi_agent",
            roles=[role],
            allowlist=AllowList.data_analysis(),
            load_default_skills=False,
        )
        assert_no_successful_violation(result)
        assert any(
            c.output.has_error and c.output.error.ename == "AllowListViolation"
            for c in result.cells
        ), "multi_agent: expected an AllowListViolation cell"

    def test_debate_loop_blocks_violations(self):
        llm = make_llm(
            VIOLATING_CODE,   # proposer attempt 1 → blocked, retried
            BENIGN_CODE,      # proposer retry
            BENIGN_CODE,      # challenger
            "debate_verdict = 'ok'",
        )
        result = run(
            "Is X true?",
            llm=llm,
            loop="debate",
            position="X is true",
            n_rounds=1,
            allowlist=AllowList.data_analysis(),
            load_default_skills=False,
        )
        # Debate discards the blocked cell and retries — the invariant is
        # that the violating code never executed successfully.
        assert_no_successful_violation(result)

    def test_run_with_pool_blocks_violations(self):
        results = run_with_pool(
            ["Analyze task A"],
            llm=make_llm(VIOLATING_CODE),
            pool_size=1,
            allowlist=AllowList.data_analysis(),
            max_cells=5,
        )
        # run_with_pool always loads default skills per worker — the
        # subject is policy enforcement, so tolerate bootstrap slowness
        # by asserting only on the cells that did run.
        assert len(results) == 1
        assert_no_successful_violation(results[0])
        assert any(
            c.output.has_error and c.output.error.ename == "AllowListViolation"
            for c in results[0].cells
        ), "pool: expected an AllowListViolation cell"

    def test_trusted_setup_still_works_under_allowlist(self):
        """Skills bootstrap and allowlist injection must not break normal runs."""
        result = run(
            "Compute 2 + 2",
            llm=make_llm("print(2 + 2)", "# TASK_COMPLETE: done"),
            allowlist=AllowList.data_analysis(),
            max_cells=5,
        )
        assert result.cells_executed >= 2
        assert_no_successful_violation(result)


@pytest.mark.integration
class TestRunCapabilityAuthorization:
    """K-008: run() with a capability broker gates every agent cell."""

    def test_broker_without_grants_blocks_all_agent_cells(self):
        broker = CapabilityBroker()  # no grants → nothing authorized
        result = run(
            "Compute 2 + 2",
            llm=make_llm("print(2 + 2)", "# TASK_COMPLETE: done"),
            capability_broker=broker,
            max_cells=5,
            load_default_skills=False,   # authorization is the subject
        )
        assert result.cells_executed >= 1
        # Every executed cell was blocked by authorization
        for cell in result.cells:
            assert cell.output.has_error, (
                f"cell executed without authorization: {cell.code!r}"
            )
            assert cell.output.error.ename == "CapabilityViolation"
        # A blocked cell containing "# TASK_COMPLETE" must NOT end the
        # session as COMPLETE (regression: completion only counts when
        # the cell actually succeeded).
        assert result.status != SessionStatus.COMPLETE

    def test_broker_with_grant_allows_session(self):
        broker = CapabilityBroker()
        broker.grant(Capability(CAP_KERNEL_EXECUTE))
        result = run(
            "Compute 2 + 2",
            llm=make_llm("print(2 + 2)", "# TASK_COMPLETE: done"),
            capability_broker=broker,
            max_cells=5,
            load_default_skills=False,
        )
        assert result.cells_executed >= 2
        assert all(not c.output.has_error for c in result.cells)

    def test_broker_and_allowlist_compose(self):
        broker = CapabilityBroker()
        broker.grant(Capability(CAP_KERNEL_EXECUTE))
        result = run(
            "Compute 2 + 2",
            llm=make_llm(VIOLATING_CODE, "# TASK_COMPLETE: done"),
            allowlist=AllowList.data_analysis(),
            capability_broker=broker,
            max_cells=5,
            load_default_skills=False,
        )
        # The violating cell passed authorization but was blocked by policy
        blocked = [c for c in result.cells if "subprocess" in c.code]
        assert blocked, "expected the violating cell in history"
        assert all(c.output.has_error for c in blocked)
        assert blocked[0].output.error.ename == "AllowListViolation"


@pytest.mark.integration
class TestRunLifecycle:
    """Comm resources are torn down even when the agent loop raises."""

    def test_comm_stopped_after_success(self):
        result = run(
            "Compute 2 + 2",
            llm=make_llm("print(2 + 2)", "# TASK_COMPLETE: done"),
            allowlist=AllowList.data_analysis(),
            comm_handlers={"progress": lambda msg: None},
            max_cells=5,
        )
        assert result.status.name in ("COMPLETE", "MAX_CELLS")

    def test_comm_stopped_when_agent_raises(self, monkeypatch):
        from kerno.comms.channel import KernoComm

        import kerno._run as run_module

        # Spy on stop(): record invocations AND call the real method so the
        # global comm handler is still unregistered afterwards.
        real_stop = KernoComm.stop
        stop_calls = []

        def spying_stop(self, *args, **kwargs):
            stop_calls.append(1)
            return real_stop(self, *args, **kwargs)

        monkeypatch.setattr(KernoComm, "stop", spying_stop)

        def exploding_run(self, task, **kwargs):
            raise RuntimeError("LLM provider down")

        # Make agent.run() raise (plugin hooks swallow exceptions by design,
        # so patch the loop directly). The try/finally in run() must still
        # tear down comms.
        monkeypatch.setattr(run_module.ReactiveLoop, "run", exploding_run)

        with pytest.raises(RuntimeError, match="LLM provider down"):
            run(
                "Compute 2 + 2",
                llm=make_llm("print(2 + 2)"),
                comm_handlers={"progress": lambda msg: None},
            )

        assert len(stop_calls) == 1, (
            "comm.stop() must be called even when agent.run() raises"
        )


@pytest.mark.integration
class TestRunApprovalGate:
    """Audit #90 through the run() facade: human approval, fail closed."""

    def test_run_denies_when_approval_required_and_no_gate(self):
        broker = CapabilityBroker()
        broker.grant(Capability(CAP_KERNEL_EXECUTE))
        broker.grant(Capability("human.approval"))

        result = run(
            "Risky operation",
            llm=make_llm("print('risky')", "# TASK_COMPLETE: done"),
            capability_broker=broker,
            capabilities=frozenset({CAP_KERNEL_EXECUTE, "human.approval"}),
            max_cells=5,
            load_default_skills=False,
        )
        # Capabilities are granted, but NO gate is installed → fail
        # closed at the approval layer: every cell denied
        for cell in result.cells:
            assert cell.output.has_error
            assert cell.output.error.ename == "ApprovalDenied"
        assert result.status != SessionStatus.COMPLETE

    def test_run_approval_gate_approves(self):
        from kerno.approval import AutoApprovalGate, ApprovalDecision

        broker = CapabilityBroker()
        broker.grant(Capability(CAP_KERNEL_EXECUTE))
        broker.grant(Capability("human.approval"))
        gate = AutoApprovalGate(ApprovalDecision.APPROVED)

        result = run(
            "Safe operation",
            llm=make_llm("print(2 + 2)", "# TASK_COMPLETE: done"),
            capability_broker=broker,
            capabilities=frozenset({CAP_KERNEL_EXECUTE, "human.approval"}),
            approval_gate=gate,
            max_cells=5,
            load_default_skills=False,
        )
        assert result.status == SessionStatus.COMPLETE
        assert len(gate.requests) >= 2   # every cell went through the gate

    def test_run_approval_gate_denies(self):
        from kerno.approval import AutoApprovalGate, ApprovalDecision

        broker = CapabilityBroker()
        broker.grant(Capability(CAP_KERNEL_EXECUTE))
        broker.grant(Capability("human.approval"))
        gate = AutoApprovalGate(ApprovalDecision.DENIED)

        result = run(
            "Risky operation",
            llm=make_llm("print('risky')", "# TASK_COMPLETE: done"),
            capability_broker=broker,
            capabilities=frozenset({CAP_KERNEL_EXECUTE, "human.approval"}),
            approval_gate=gate,
            max_cells=5,
            load_default_skills=False,
        )
        for cell in result.cells:
            assert cell.output.has_error
            assert cell.output.error.ename == "ApprovalDenied"
