"""Unit tests for memory stores — no kernel required."""

import time
import pytest

from kerno.memory.simple import SimpleMemoryStore
from kerno.memory.store  import MemoryEntry


@pytest.fixture
def store(tmp_path):
    return SimpleMemoryStore(persist_path=str(tmp_path / "memory.json"))


@pytest.fixture
def populated_store(store):
    entries = [
        MemoryEntry(
            content    = "Analyzed Q3 sales data. Found revenue declined 12% in West region.",
            kind       = "result",
            session_id = "s-001",
            task       = "Analyze Q3 sales",
        ),
        MemoryEntry(
            content    = "Built RandomForest classifier for churn prediction. Accuracy: 0.87.",
            kind       = "result",
            session_id = "s-002",
            task       = "Predict customer churn",
        ),
        MemoryEntry(
            content    = "KeyError on 'profit' column — actual column name was 'margin'.",
            kind       = "error",
            session_id = "s-001",
            task       = "Analyze Q3 sales",
        ),
        MemoryEntry(
            content    = "West region has anomalously high return rates in Q4.",
            kind       = "insight",
            session_id = "s-003",
            task       = "Investigate returns",
        ),
    ]
    for e in entries:
        store.store(e)
    return store


class TestSimpleMemoryStore:

    def test_store_returns_entry_id(self, store):
        entry = MemoryEntry(
            content="Test content", kind="result"
        )
        entry_id = store.store(entry)
        assert entry_id == entry.entry_id
        assert len(entry_id) > 0

    def test_retrieve_by_keyword(self, populated_store):
        results = populated_store.retrieve("revenue West region")
        assert len(results) > 0
        assert any("West" in r.content for r in results)

    def test_retrieve_returns_sorted_by_score(self, populated_store):
        results = populated_store.retrieve("churn prediction accuracy")
        assert len(results) > 0
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_retrieve_filter_by_kind(self, populated_store):
        results = populated_store.retrieve("analysis", kind="error")
        assert all(r.kind == "error" for r in results)

    def test_retrieve_empty_query_returns_empty(self, store):
        results = store.retrieve("")
        assert results == []

    def test_retrieve_respects_k(self, populated_store):
        results = populated_store.retrieve("data analysis", k=2)
        assert len(results) <= 2

    def test_retrieve_min_score_filters(self, populated_store):
        results = populated_store.retrieve(
            "completely unrelated xyz123", min_score=10.0
        )
        assert len(results) == 0

    def test_list_all(self, populated_store):
        entries = populated_store.list()
        assert len(entries) == 4

    def test_list_filter_by_kind(self, populated_store):
        results = populated_store.list(kind="result")
        assert len(results) == 2
        assert all(e.kind == "result" for e in results)

    def test_list_filter_by_session(self, populated_store):
        results = populated_store.list(session_id="s-001")
        assert len(results) == 2
        assert all(e.session_id == "s-001" for e in results)

    def test_list_sorted_newest_first(self, store):
        store.store(MemoryEntry(content="first",  kind="result", created_at=1.0))
        store.store(MemoryEntry(content="second", kind="result", created_at=2.0))
        store.store(MemoryEntry(content="third",  kind="result", created_at=3.0))

        entries = store.list()
        assert entries[0].content == "third"

    def test_delete_existing_entry(self, populated_store):
        all_entries = populated_store.list()
        entry_id    = all_entries[0].entry_id

        deleted = populated_store.delete(entry_id)
        assert deleted is True
        assert all(e.entry_id != entry_id for e in populated_store.list())

    def test_delete_nonexistent_returns_false(self, store):
        assert store.delete("nonexistent-id") is False

    def test_persistence_across_instances(self, tmp_path):
        path = str(tmp_path / "persist_test.json")

        store1 = SimpleMemoryStore(persist_path=path)
        entry  = MemoryEntry(content="Persistent content", kind="insight")
        store1.store(entry)

        # New instance — should load from disk
        store2  = SimpleMemoryStore(persist_path=path)
        entries = store2.list()
        assert len(entries) == 1
        assert entries[0].content == "Persistent content"

    def test_store_session_result_convenience(self, store):
        entry_id = store.store_session_result(
            session_id = "s-999",
            task       = "Test task",
            summary    = "Successfully analyzed the data.",
            namespace  = '{"df": "DataFrame[100,5]"}',
        )
        assert entry_id != ""
        results = store.retrieve("analyzed data")
        assert len(results) > 0

    def test_no_persistence_when_path_is_none(self):
        store = SimpleMemoryStore(persist_path=None)
        entry = MemoryEntry(content="ephemeral", kind="result")
        entry_id = store.store(entry)   # Should not raise
        assert entry_id == entry.entry_id
