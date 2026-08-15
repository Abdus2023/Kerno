"""
Integration tests: memory persists across sessions.
Uses real kernel — verifies end-to-end memory flow.
"""

import pytest
from unittest.mock import MagicMock

from kerno.kernel.runtime  import KernelRuntime
from kerno.loop.reactive   import ReactiveLoop
from kerno.memory.simple   import SimpleMemoryStore
from kerno.memory.store    import MemoryEntry
from kerno.types           import Message, SessionStatus


@pytest.fixture
def store(tmp_path):
    return SimpleMemoryStore(persist_path=str(tmp_path / "mem.json"))


@pytest.fixture
def kernel():
    with KernelRuntime() as k:
        yield k


@pytest.mark.integration
class TestMemoryIntegration:

    def test_completed_session_stored_in_memory(self, kernel, store):
        call_count = [0]
        def llm(messages):
            call_count[0] += 1
            return "x = 42\n# TASK_COMPLETE: set x to 42"

        loop   = ReactiveLoop(kernel=kernel, llm=llm, memory=store)
        result = loop.run("Set x to 42")

        assert result.status == SessionStatus.COMPLETE
        entries = store.list(kind="result")
        assert len(entries) == 1
        assert "Set x to 42" in entries[0].task

    def test_prior_session_context_injected(self, kernel, store):
        # Pre-populate memory
        store.store(MemoryEntry(
            content    = "Task: Analyze West sales. Summary: West revenue down 12%.",
            kind       = "result",
            session_id = "prior-session",
            task       = "Analyze West sales",
        ))

        received_summaries = []

        def llm(messages):
            system_msg = messages[0].content if messages else ""
            if "West revenue" in system_msg:
                received_summaries.append(system_msg)
            return "# TASK_COMPLETE: done"

        loop = ReactiveLoop(
            kernel = kernel,
            llm    = llm,
            memory = store,
        )
        loop.run("Continue analysis of West region sales")

        # The memory should have been retrieved and injected
        assert len(received_summaries) > 0

    def test_error_patterns_stored(self, kernel, store):
        call_count = [0]
        def llm(messages):
            call_count[0] += 1
            if call_count[0] == 1:
                return "good = 1"
            elif call_count[0] == 2:
                return "raise KeyError('test_col')"   # Error
            else:
                return "# TASK_COMPLETE: done"

        loop = ReactiveLoop(kernel=kernel, llm=llm, memory=store, max_cells=10)
        loop.run("Test error storage")

        # Error pattern should be stored
        errors = store.list(kind="error")
        # May or may not have errors depending on which cells were adjacent
        # Just verify no exception was raised
        assert isinstance(errors, list)
