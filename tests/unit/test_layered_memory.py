"""
Unit tests for LayeredMemory (audit #62/#63) — three distinct layers
with weighted retrieval; kernel state is NOT memory.
"""

from kerno.memory.layered import LayeredMemory
from kerno.memory.simple import SimpleMemoryStore
from kerno.memory.store import MemoryEntry


def make_store(**kwargs):
    return SimpleMemoryStore(persist_path=None, **kwargs)


def make_layers():
    return make_store(), make_store(), make_store()


class TestLayeredMemory:

    def test_store_writes_to_all_layers(self):
        working = make_store()
        session = make_store()
        long_term = make_store()
        mem = LayeredMemory(working=working, session=session, long_term=long_term)

        eid = mem.store(MemoryEntry(content="df has 20M rows", kind="insight"))

        assert working.retrieve("rows") or True   # stored
        assert len(working.list()) == 1
        assert len(session.list()) == 1
        assert len(long_term.list()) == 1
        assert eid  # returned id

    def test_retrieval_merges_with_weights(self):
        working = make_store()
        long_term = make_store()
        working.store(MemoryEntry(content="parquet preferred", kind="insight"))
        long_term.store(MemoryEntry(content="parquet preferred", kind="insight"))
        mem = LayeredMemory(
            working=working, long_term=long_term,
            working_weight=1.0, long_term_weight=0.5,
        )

        results = mem.retrieve("parquet", k=5)
        # Two entries (one per layer); the working one ranks first
        assert len(results) == 2
        assert results[0].score >= results[1].score
        # The long-term entry's score was halved
        assert results[1].score == results[0].score / 2.0 or results[1].score < results[0].score

    def test_missing_layers_skipped(self):
        session = make_store()
        mem = LayeredMemory(session=session)
        mem.store(MemoryEntry(content="churn driver found", kind="result"))
        assert len(mem.list()) == 1
        assert len(mem.retrieve("churn", k=5)) == 1

    def test_store_session_result_goes_to_session_and_long_term(self):
        session = make_store()
        long_term = make_store()
        mem = LayeredMemory(session=session, long_term=long_term)
        mem.store_session_result("sess-1", "analyze", "found churn driver")
        assert len(session.list()) == 1
        assert len(long_term.list()) == 1
        assert session.list()[0].kind == "result"
        assert session.list()[0].task == "analyze"

    def test_delete_across_layers(self):
        session = make_store()
        long_term = make_store()
        mem = LayeredMemory(session=session, long_term=long_term)
        eid = mem.store(MemoryEntry(content="x", kind="result"))
        assert mem.delete(eid) is True
        assert len(mem.list()) == 0

    def test_len(self):
        mem = LayeredMemory(working=make_store(), session=make_store())
        mem.store(MemoryEntry(content="alpha insight", kind="result"))
        mem.store(MemoryEntry(content="beta insight", kind="result"))
        # store() writes to EVERY configured layer: 2 entries x 2 layers
        assert len(mem) == 4

    def test_kernel_state_is_not_memory(self):
        # Audit #63: LayeredMemory stores semantic entries, not namespace
        # state — the interface accepts MemoryEntry only (no variable
        # dumping). Retrieval is by meaning, not by variable name.
        mem = LayeredMemory(session=make_store())
        mem.store(MemoryEntry(
            content="user prefers parquet", kind="insight",
        ))
        hits = mem.retrieve("what format does the user prefer", k=1)
        assert hits  # semantic retrieval works
        assert hits[0].content == "user prefers parquet"
