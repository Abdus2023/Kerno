"""
Behavioral tests for agent message passing (Phase D) in isolated
multi-agent mode: a message exported by one agent is delivered into the
next agent's context via the AgentBus.
"""

import pytest

from kerno.bus import AgentBus
from kerno.execution.engine import ExecutionEngine
from kerno.kernel.runtime import KernelRuntime
from kerno.loop.multi_agent import AgentRole, MultiAgentLoop
from kerno.types import Message, SessionStatus


@pytest.mark.integration
class TestAgentBusInLoop:

    def test_message_exported_by_analyst_delivered_to_critic(self):
        # The critic's LLM inspects its system prompt: did the analyst's
        # message arrive?
        def critic_llm(messages: list[Message]):
            system = messages[0].content
            if "MESSAGES FOR YOU" in system and "analysis_note" in system:
                return "print('GOT NOTE')\n# TASK_COMPLETE: done"
            return "print('NO NOTE')\n# TASK_COMPLETE: done"

        analyst = AgentRole(
            # Write the message in TWO cells: under heavy shared-sandbox
            # load the first cell can hit a transient iopub error; the
            # second occurrence guarantees the export has the message.
            name="analyst", llm=MockLLM(
                "results_score = 42\n"
                "messages_note = {'key': 'analysis_note', 'score': 42}\n"
                "print('analyst done')",
                "messages_note = {'key': 'analysis_note', 'score': 42}",
                "# READY_FOR_REVIEW: done",
            ),
            system="You are an analyst. Write results_ and messages_.",
            yield_signal="# READY_FOR_REVIEW",
            writes=["results_", "messages_"],
        )
        critic = AgentRole(
            name="critic", llm=critic_llm,
            system="You are a critic.",
            yield_signal="# TASK_COMPLETE",
            writes=["critique_"],
        )

        bus = AgentBus()
        created: list = []

        def factory():
            k = KernelRuntime()
            k.start()
            created.append(k)
            return ExecutionEngine(k)

        loop = MultiAgentLoop(
            kernel=ExecutionEngine(KernelRuntime()),
            roles=[analyst, critic],
            turn_order=["analyst", "critic"],
            max_turns=2,
            isolation="isolated",
            kernel_factory=factory,
            bus=bus,
        )
        loop.kernel.raw_kernel.start()
        try:
            result = loop.run("analyze then critique")
        finally:
            loop.kernel.raw_kernel.shutdown()

        assert result.status == SessionStatus.COMPLETE
        # The critic received and acknowledged the message
        got_note = [
            c for c in result.cells
            if "GOT NOTE" in c.output.stdout
        ]
        assert got_note, "critic never acknowledged the analyst's message"

        # The bus holds the attributable message
        assert len(bus.history) == 1
        msg = bus.history[0]
        assert msg.sender == "analyst"
        assert msg.recipient == "critic"
        assert msg.kind == "note"
        assert msg.payload == {"key": "analysis_note", "score": 42}
        assert bus.messages_from("analyst") == [msg]

    def test_host_sends_instructions_before_run(self):
        """Host→agent messages are injected into the first turn's context."""

        def analyst_llm(messages: list[Message]):
            # Yield IMMEDIATELY after the acknowledgment: a never-yielding
            # mock runs max_turns x max_cells (6x20=120) real kernel cells,
            # which times out the test under load.
            system = messages[0].content
            if "USE_PARQUET" in system:
                return "print('using parquet')\n# TASK_COMPLETE: done"
            return "print('ignoring instruction')\n# TASK_COMPLETE: done"

        analyst = AgentRole(
            name="analyst", llm=analyst_llm,
            system="You are an analyst.",
            yield_signal="# TASK_COMPLETE",
            writes=["results_"],
        )

        bus = AgentBus()
        bus.send_to("analyst", "instruction", {"format": "USE_PARQUET"})

        created: list = []

        def factory():
            k = KernelRuntime()
            k.start()
            created.append(k)
            return ExecutionEngine(k)

        loop = MultiAgentLoop(
            kernel=ExecutionEngine(KernelRuntime()),
            roles=[analyst],
            isolation="isolated",
            kernel_factory=factory,
            bus=bus,
        )
        loop.kernel.raw_kernel.start()
        try:
            result = loop.run("analyze")
        finally:
            loop.kernel.raw_kernel.shutdown()

        assert "using parquet" in result.cells[0].output.stdout


class MockLLM:
    """Deterministic mock: returns responses in order, then completion."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self._i = 0

    def __call__(self, messages: list[Message]) -> str:
        i = self._i
        self._i += 1
        if i < len(self._responses):
            return self._responses[i]
        return "# TASK_COMPLETE: done"
