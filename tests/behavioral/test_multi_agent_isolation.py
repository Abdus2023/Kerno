"""
Behavioral tests for multi-agent isolation (K-009, audit #33).

isolated mode: each agent runs in its OWN kernel; state crosses agent
boundaries ONLY through explicit SharedMemory (attributable, immutable
JSON copies). A shared-kernel test asserts the old behavior still works.
"""

import pytest

from kerno.execution.engine import ExecutionEngine
from kerno.isolation import SharedMemory
from kerno.kernel.runtime import KernelRuntime
from kerno.loop.multi_agent import AgentRole, MultiAgentLoop
from kerno.types import Message, SessionStatus


def make_llm(*responses):
    responses = list(responses)
    state = {"i": 0}

    def llm(messages: list[Message]) -> str:
        i = state["i"]
        state["i"] += 1
        if i < len(responses):
            return responses[i]
        return "# TASK_COMPLETE: done"

    return llm


@pytest.mark.integration
class TestIsolatedMultiAgent:
    """K-009: agents run in separate kernels with explicit sharing."""

    def test_isolated_turns_use_fresh_kernels_and_share_explicitly(self):
        analyst = AgentRole(
            name="analyst", llm=make_llm(
                "results_score = 42\nprint('score computed')",
                "# READY_FOR_REVIEW: done",
            ),
            system="You are an analyst. Write results_* variables.",
            yield_signal="# READY_FOR_REVIEW",
            writes=["results_"],
        )
        critic = AgentRole(
            name="critic", llm=make_llm(
                "critique_summary = f'score={results_score}'\nprint(critique_summary)",
                "# TASK_COMPLETE: done",
            ),
            system="You are a critic. Read shared values, write critique_*.",
            yield_signal="# TASK_COMPLETE",
            writes=["critique_"],
        )

        # Factory: fresh policy-wrapped kernel per turn; track creations
        created: list = []

        def factory():
            k = KernelRuntime()
            k.start()
            created.append(k)
            return ExecutionEngine(k)

        shared = SharedMemory()
        loop = MultiAgentLoop(
            kernel=ExecutionEngine(KernelRuntime()),
            roles=[analyst, critic],
            turn_order=["analyst", "critic"],
            max_turns=2,
            isolation="isolated",
            kernel_factory=factory,
            shared_memory=shared,
        )
        loop.kernel.raw_kernel.start()
        try:
            result = loop.run("analyze and critique")
        finally:
            loop.kernel.raw_kernel.shutdown()

        assert result.status == SessionStatus.COMPLETE

        # Two turns → two fresh kernels, both shut down afterwards
        assert len(created) == 2
        assert all(not k.is_alive for k in created), \
            "turn kernels must be shut down after their turn"

        # The analyst's results_score crossed the boundary ONLY via
        # shared memory, with attribution
        sv = shared.get("results_score")
        assert sv is not None
        assert sv.value == 42
        assert sv.producer == "analyst"
        # Both agents exported their declared writes, with attribution
        assert shared.producers() == {
            "analyst": ["results_score"],
            "critic":  ["critique_summary"],
        }

        # The critic READ the shared value (its cell executed without error)
        critic_cell = result.cells[-2]  # the critique cell before TASK_COMPLETE
        assert "critique_summary" in critic_cell.code
        assert not critic_cell.output.has_error
        assert "score=42" in critic_cell.output.stdout

        # No agent wrote outside its declared prefixes
        assert loop.isolation_violations == []

    def test_violation_detected_for_undeclared_write(self):
        rogue = AgentRole(
            name="rogue", llm=make_llm(
                "secret_var = 'evil'",
                "# TASK_COMPLETE: done",
            ),
            system="You are a rogue agent.",
            yield_signal="# TASK_COMPLETE",
            writes=["ok_"],   # declares ok_ but writes secret_var
        )

        created: list = []

        def factory():
            k = KernelRuntime()
            k.start()
            created.append(k)
            return ExecutionEngine(k)

        loop = MultiAgentLoop(
            kernel=ExecutionEngine(KernelRuntime()),
            roles=[rogue],
            isolation="isolated",
            kernel_factory=factory,
        )
        loop.kernel.raw_kernel.start()
        try:
            loop.run("test")
        finally:
            loop.kernel.raw_kernel.shutdown()

        # The undeclared write was flagged and never shared
        assert loop.isolation_violations
        assert loop.isolation_violations[0]["agent"] == "rogue"
        assert "secret_var" in loop.isolation_violations[0]["keys"]
        assert loop.shared.get("secret_var") is None


@pytest.mark.integration
class TestIsolationConfig:

    def test_isolated_requires_factory(self):
        from kerno.types import SessionResult
        with pytest.raises(ValueError, match="kernel_factory"):
            MultiAgentLoop(
                kernel=object(), roles=[], isolation="isolated"
            )

    def test_unknown_isolation_value_rejected(self):
        with pytest.raises(ValueError, match="isolation"):
            MultiAgentLoop(
                kernel=object(), roles=[], isolation="banana"
            )


@pytest.mark.integration
class TestRunIsolatedMultiAgent:
    """run(loop='multi_agent', isolation='isolated') end-to-end."""

    def test_run_isolated_pipeline(self):
        from kerno import run

        analyst = AgentRole(
            name="analyst", llm=make_llm(
                "results_score = 42\nprint('computed')",
                "# READY_FOR_REVIEW: done",
            ),
            system="You are an analyst.",
            yield_signal="# READY_FOR_REVIEW",
            writes=["results_"],
        )
        critic = AgentRole(
            name="critic", llm=make_llm(
                "critique_summary = f'score={results_score}'\nprint(critique_summary)",
                "# TASK_COMPLETE: done",
            ),
            system="You are a critic.",
            yield_signal="# TASK_COMPLETE",
            writes=["critique_"],
        )

        result = run(
            "analyze and critique",
            llm=make_llm(),          # unused: roles carry their own LLMs
            loop="multi_agent",
            roles=[analyst, critic],
            isolation="isolated",
            max_cells=10,
            load_default_skills=False,   # isolation is the subject, not skills
        )

        assert result.status == SessionStatus.COMPLETE
        # The critic's cell read the shared value exported by the analyst
        critic_cell = result.cells[-2]
        assert "critique_summary" in critic_cell.code
        assert not critic_cell.output.has_error
        assert "score=42" in critic_cell.output.stdout


@pytest.mark.integration
class TestAgentsAsSecurityPrincipals:
    """Audit #89: capability grants are scoped to the agent identity."""

    def test_broker_grant_only_to_analyst_blocks_critic(self):
        from kerno import run
        from kerno.security.capabilities import (
            CAP_KERNEL_EXECUTE, Capability, CapabilityBroker,
        )

        analyst = AgentRole(
            name="analyst", llm=make_llm(
                "results_score = 42\nprint('analyst ok')",
                "# READY_FOR_REVIEW: done",
            ),
            system="You are an analyst.",
            yield_signal="# READY_FOR_REVIEW",
            writes=["results_"],
        )
        critic = AgentRole(
            name="critic", llm=make_llm(
                "critique_summary = 'review'\nprint('critic ok')",
                "# TASK_COMPLETE: done",
            ),
            system="You are a critic.",
            yield_signal="# TASK_COMPLETE",
            writes=["critique_"],
        )

        # Grant kernel.execute ONLY to the analyst — the critic must be
        # denied at the capability layer (K-008 with subject scoping).
        broker = CapabilityBroker()
        broker.grant(Capability(CAP_KERNEL_EXECUTE), subject="analyst")

        result = run(
            "analyze then critique",
            llm=make_llm(),
            loop="multi_agent",
            roles=[analyst, critic],
            isolation="isolated",
            capability_broker=broker,
            load_default_skills=False,
            max_cells=10,
        )

        # The analyst's cell ran
        analyst_cells = [c for c in result.cells if c.author == "analyst"]
        assert analyst_cells
        assert any(
            not c.output.has_error and "analyst ok" in c.output.stdout
            for c in analyst_cells
        )

        # The critic's cell was blocked by authorization — its code
        # never executed for real
        critic_cells = [c for c in result.cells if c.author == "critic"]
        assert critic_cells
        assert any(
            c.output.has_error
            and c.output.error.ename == "CapabilityViolation"
            for c in critic_cells
        ), "critic must be denied: no grant for subject='critic'"
        assert all(
            "critic ok" not in c.output.stdout for c in critic_cells
        ), "critic's code must never have executed"


@pytest.mark.integration
class TestPerRoleBudgets:
    """Audit #86: each agent has its OWN budget; a greedy agent cannot
    consume the session's resources."""

    def test_greedy_analyst_exhausts_own_budget_only(self):
        from kerno import run
        from kerno.execution.budget import ExecutionBudget

        analyst = AgentRole(
            name="analyst", llm=make_llm(
                "x = 1\nprint('a1')",
                "x = 2\nprint('a2')",
                "x = 3\nprint('a3')",
                "x = 4\nprint('a4')",
                "# READY_FOR_REVIEW: done",
            ),
            system="You are an analyst.",
            yield_signal="# READY_FOR_REVIEW",
            writes=["results_"],
        )
        critic = AgentRole(
            name="critic", llm=make_llm(
                "critique_summary = 'ok'\nprint('critic ran')",
                "# TASK_COMPLETE: done",
            ),
            system="You are a critic.",
            yield_signal="# TASK_COMPLETE",
            writes=["critique_"],
        )

        result = run(
            "analyze then critique",
            llm=make_llm(),
            loop="multi_agent",
            roles=[analyst, critic],
            isolation="isolated",
            budget=ExecutionBudget(max_executions=3),
            load_default_skills=False,
            max_cells=10,
        )

        # The analyst's cells: 2 succeeded (a1, a2) then the budget
        # (3 per agent) refused further attempts with BudgetExceeded.
        analyst_cells = [c for c in result.cells if c.author == "analyst"]
        succeeded = [
            c for c in analyst_cells
            if not c.output.has_error
        ]
        assert len(succeeded) == 3, \
            "analyst budget must cap successful cells at 3"
        assert any(
            c.output.has_error and c.output.error.ename == "BudgetExceeded"
            for c in analyst_cells
        ), "over-budget analyst attempts must surface BudgetExceeded"

        # The critic has its OWN budget — it still ran successfully
        critic_cells = [c for c in result.cells if c.author == "critic"]
        assert any(
            not c.output.has_error and "critic ran" in c.output.stdout
            for c in critic_cells
        ), "critic must not be affected by the analyst's budget"
