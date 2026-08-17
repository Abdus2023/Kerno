"""
Tests for Stack Part II modules:
  - kerno/server/files.py (FileMaterializer, MaterializedFile)
  - kerno/server/rag.py (OpenWebUIRAGBridge, RAGDocument)
  - kerno/llm/router.py (TaskAwareRouter, CostTrackingRouter, RoutingRule)
  - kerno/server/auth.py (APIKeyStore, RateLimiter)
"""

import os
import re
import time
from unittest.mock import MagicMock, patch

import pytest

from kerno.server.files import FileMaterializer, MaterializedFile
from kerno.server.rag import OpenWebUIRAGBridge, RAGDocument
from kerno.llm.router import TaskAwareRouter, CostTrackingRouter, RoutingRule
from kerno.server.auth import APIKeyStore, RateLimiter
from kerno.types import Message


# ── MaterializedFile tests ───────────────────────────────────────────────────

class TestMaterializedFile:
    def test_creation(self):
        mf = MaterializedFile(
            original_name="test.csv",
            local_path="/tmp/test.csv",
            mime_type="text/csv",
            size_bytes=1024,
            variable_name="df_test",
            load_code="df_test = pd.read_csv('/tmp/test.csv')",
        )
        assert mf.original_name == "test.csv"
        assert mf.variable_name == "df_test"
        assert mf.size_bytes == 1024


# ── FileMaterializer tests ──────────────────────────────────────────────────

class TestFileMaterializer:
    def test_supported_types(self):
        fm = FileMaterializer(MagicMock())
        assert "text/csv" in fm.SUPPORTED_TYPES
        assert fm.SUPPORTED_TYPES["text/csv"] == "dataframe"
        assert fm.SUPPORTED_TYPES["image/png"] == "image"
        assert fm.SUPPORTED_TYPES["application/pdf"] == "document"

    def test_classify_csv(self):
        result = FileMaterializer._classify("text/csv", "data.csv")
        assert result == "dataframe"

    def test_classify_image(self):
        result = FileMaterializer._classify("image/png", "photo.png")
        assert result == "image"

    def test_classify_pdf(self):
        result = FileMaterializer._classify("application/pdf", "report.pdf")
        assert result == "pdf"

    def test_classify_excel(self):
        result = FileMaterializer._classify("application/octet-stream", "data.xlsx")
        assert result == "dataframe"

    def test_classify_unknown(self):
        result = FileMaterializer._classify("text/plain", "notes.txt")
        assert result == "document"

    def test_safe_varname(self):
        assert FileMaterializer._safe_varname("sales_data.csv") == "sales_data"
        assert FileMaterializer._safe_varname("my-file (2024).xlsx") == "my_file_2024"
        assert FileMaterializer._safe_varname("123data.csv") == "file_123data"
        assert FileMaterializer._safe_varname("simple") == "simple"

    def test_normalize_content_part_image_url(self):
        part = {
            "type": "image_url",
            "image_url": {"url": "https://example.com/photo.jpg"},
        }
        result = FileMaterializer._normalize_content_part(part)
        assert result is not None
        assert result["type"] == "image/jpeg"

    def test_normalize_content_part_data_url(self):
        part = {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,abc123"},
        }
        result = FileMaterializer._normalize_content_part(part)
        assert result is not None
        assert result["type"] == "image/png"
        assert result["data"] == "abc123"

    def test_normalize_content_part_invalid(self):
        part = {"type": "text", "text": "hello"}
        result = FileMaterializer._normalize_content_part(part)
        assert result is None

    def test_build_context_message_empty(self):
        fm = FileMaterializer(MagicMock())
        assert fm.build_context_message([]) == ""

    def test_build_context_message_with_files(self):
        fm = FileMaterializer(MagicMock())
        files = [
            MaterializedFile("sales.csv", "/tmp/sales.csv", "text/csv", 1024, "df_sales", ""),
            MaterializedFile("report.pdf", "/tmp/report.pdf", "application/pdf", 5000, "doc_report", ""),
        ]
        msg = fm.build_context_message(files)
        assert "df_sales" in msg
        assert "sales.csv" in msg
        assert "already loaded" in msg

    def test_process_from_context_files_array(self):
        # F-001: FileMaterializer executes through the narrow
        # MaterializationExecutor interface, never a raw kernel.
        executor = MagicMock()
        executor.execute_load_code.return_value = MagicMock(has_error=False)

        fm = FileMaterializer(executor, upload_dir="/tmp/test_kerno")
        body = {"files": [{"name": "data.csv", "type": "text/csv", "data": "YWJj", "size": 3}]}
        # _save_file will decode base64 "YWJj" → "abc"; _process_one
        # executes the generated load code via execute_load_code.
        results = fm.process_from_context(body)
        assert len(results) == 1
        assert results[0].original_name == "data.csv"
        executor.execute_load_code.assert_called_once()

    def test_constructor_rejects_raw_kernel(self):
        # F-001 structural guard: a raw kernel / general executor is refused.
        from kerno.server.files import FileMaterializer
        import pytest

        class _RawExecutor:
            def execute(self, *args, **kwargs):
                return None

        with pytest.raises(TypeError):
            FileMaterializer(_RawExecutor())


# ── RAGDocument tests ────────────────────────────────────────────────────────

class TestRAGDocument:
    def test_creation(self):
        doc = RAGDocument(
            content="This is a document excerpt",
            source="report.pdf",
            score=0.9,
            metadata={"page": 5},
        )
        assert doc.content == "This is a document excerpt"
        assert doc.source == "report.pdf"
        assert doc.score == 0.9


# ── OpenWebUIRAGBridge tests ─────────────────────────────────────────────────

class TestOpenWebUIRAGBridge:
    def test_doc_pattern(self):
        content = """
Use the following context:
[DOCUMENT 1]
Source: report.pdf
Content: The company grew 15% year-over-year.
[DOCUMENT 2]
Source: data.csv
Content: Revenue was $12M in Q4.
"""
        matches = list(OpenWebUIRAGBridge.DOC_PATTERN.finditer(content))
        assert len(matches) == 2

    def test_extract_documents(self):
        kernel = MagicMock()
        bridge = OpenWebUIRAGBridge(kernel)

        messages = [
            {"role": "system", "content": """
Use the following context:
[DOCUMENT 1]
Source: annual_report.pdf
Content: Total revenue was $45M in 2024.
[DOCUMENT 2]
Source: quarterly.csv
Content: Q4 showed strong growth.
"""},
            {"role": "user", "content": "What was the revenue?"},
        ]

        docs = bridge._extract_documents(messages)
        assert len(docs) == 2
        assert docs[0].source == "annual_report.pdf"
        assert "revenue" in docs[0].content

    def test_extract_documents_no_system(self):
        kernel = MagicMock()
        bridge = OpenWebUIRAGBridge(kernel)
        messages = [{"role": "user", "content": "Hello"}]
        docs = bridge._extract_documents(messages)
        assert len(docs) == 0

    def test_build_context_note_empty(self):
        kernel = MagicMock()
        bridge = OpenWebUIRAGBridge(kernel)
        assert bridge.build_context_note([]) == ""

    def test_build_context_note_with_docs(self):
        kernel = MagicMock()
        bridge = OpenWebUIRAGBridge(kernel)
        docs = [
            RAGDocument("content 1", "source1.pdf", 0.9, {}),
            RAGDocument("content 2", "source2.pdf", 0.8, {}),
        ]
        note = bridge.build_context_note(docs)
        assert "2 document(s)" in note
        assert "search_docs" in note


# ── RoutingRule tests ────────────────────────────────────────────────────────

class TestRoutingRule:
    def test_creation(self):
        rule = RoutingRule(
            name="test_rule",
            patterns=[r"train.*model"],
            model="anthropic/claude-opus-4-5",
            reason="ML tasks",
            priority=10,
        )
        assert rule.name == "test_rule"
        assert rule.priority == 10

    def test_default_priority(self):
        rule = RoutingRule(name="test", patterns=[], model="model", reason="reason")
        assert rule.priority == 0


# ── TaskAwareRouter tests ────────────────────────────────────────────────────

class TestTaskAwareRouter:
    def test_route_ml_task(self):
        with patch("kerno.llm.openrouter.openrouter_llm") as mock_llm_factory:
            mock_llm_factory.return_value = MagicMock(return_value="response")
            router = TaskAwareRouter(
                default_model="anthropic/claude-opus-4-5",
                api_key="test-key",
            )
            model, reason = router._route([
                Message(role="user", content="Train a neural network model for classification")
            ])
            assert model == "anthropic/claude-opus-4-5"
            assert "ML" in reason

    def test_route_visualization_task(self):
        with patch("kerno.llm.openrouter.openrouter_llm") as mock_llm_factory:
            mock_llm_factory.return_value = MagicMock(return_value="response")
            router = TaskAwareRouter(
                default_model="anthropic/claude-opus-4-5",
                api_key="test-key",
            )
            model, reason = router._route([
                Message(role="user", content="Plot a histogram of the data")
            ])
            assert model == "anthropic/claude-haiku-4-5"

    def test_route_default(self):
        with patch("kerno.llm.openrouter.openrouter_llm") as mock_llm_factory:
            mock_llm_factory.return_value = MagicMock(return_value="response")
            router = TaskAwareRouter(
                default_model="anthropic/claude-opus-4-5",
                api_key="test-key",
            )
            model, reason = router._route([
                Message(role="user", content="Hello, how are you?")
            ])
            assert model == "anthropic/claude-opus-4-5"
            assert reason == "default"

    def test_custom_rules(self):
        with patch("kerno.llm.openrouter.openrouter_llm") as mock_llm_factory:
            mock_llm_factory.return_value = MagicMock(return_value="response")
            custom = RoutingRule(
                name="finance",
                patterns=[r"stock.*price", r"portfolio"],
                model="anthropic/claude-opus-4-5",
                reason="Financial analysis",
                priority=15,
            )
            router = TaskAwareRouter(
                default_model="meta-llama/llama-3.1-8b-instruct",
                api_key="test-key",
                custom_rules=[custom],
            )
            model, reason = router._route([
                Message(role="user", content="Analyze stock price trends")
            ])
            assert model == "anthropic/claude-opus-4-5"
            assert reason == "Financial analysis"

    def test_routing_stats(self):
        with patch("kerno.llm.openrouter.openrouter_llm") as mock_llm_factory:
            mock_llm = MagicMock(return_value="response")
            mock_llm_factory.return_value = mock_llm

            router = TaskAwareRouter(
                default_model="anthropic/claude-opus-4-5",
                api_key="test-key",
                verbose=False,
            )

            # Make a few calls
            router([Message(role="user", content="Plot data")])
            router([Message(role="user", content="Hello")])

            stats = router.routing_stats
            assert stats["total_calls"] == 2
            assert len(stats["by_model"]) >= 1

    def test_verbose_output(self, capsys):
        with patch("kerno.llm.openrouter.openrouter_llm") as mock_llm_factory:
            mock_llm = MagicMock(return_value="response")
            mock_llm_factory.return_value = mock_llm

            router = TaskAwareRouter(
                default_model="anthropic/claude-opus-4-5",
                api_key="test-key",
                verbose=True,
            )
            router([Message(role="user", content="Train a model")])
            captured = capsys.readouterr()
            assert "[router]" in captured.out


# ── CostTrackingRouter tests ─────────────────────────────────────────────────

class TestCostTrackingRouter:
    def test_tracking(self):
        base_llm = MagicMock(return_value="This is a response with some content")
        tracker = CostTrackingRouter(base_llm, model="anthropic/claude-opus-4-5")

        messages = [
            Message(role="user", content="Hello, this is a test message"),
        ]
        result = tracker(messages)
        assert result == "This is a response with some content"
        assert tracker.total_calls == 1
        assert tracker.total_cost > 0

    def test_pricing_lookup(self):
        base_llm = MagicMock(return_value="response")
        tracker = CostTrackingRouter(base_llm, model="openai/gpt-4o")
        assert "openai/gpt-4o" in tracker.PRICING
        assert tracker.PRICING["openai/gpt-4o"]["in"] == 5.00

    def test_unknown_model_pricing(self):
        base_llm = MagicMock(return_value="short")
        tracker = CostTrackingRouter(base_llm, model="unknown/model")
        tracker([Message(role="user", content="test")])
        # Uses default pricing
        assert tracker.total_cost > 0

    def test_cost_report(self):
        base_llm = MagicMock(return_value="response text here")
        tracker = CostTrackingRouter(base_llm, model="anthropic/claude-opus-4-5")
        tracker([Message(role="user", content="test message")])
        report = tracker.cost_report()
        assert "Cost report" in report
        assert "anthropic/claude-opus-4-5" in report
        assert "Total cost" in report


# ── APIKeyStore tests ────────────────────────────────────────────────────────

class TestAPIKeyStore:
    def test_add_and_validate(self):
        store = APIKeyStore()
        store.add_key("my-secret-key", "alice", "Alice's key", rate_limit=100)

        result = store.validate("my-secret-key")
        assert result is not None
        assert result["user_id"] == "alice"
        assert result["name"] == "Alice's key"

    def test_invalid_key(self):
        store = APIKeyStore()
        store.add_key("valid-key", "alice")

        result = store.validate("invalid-key")
        assert result is None

    def test_deactivated_key(self):
        store = APIKeyStore()
        store.add_key("key1", "alice")
        # Deactivate
        key_hash = store._keys.keys()
        for kh in key_hash:
            store._keys[kh]["active"] = False

        result = store.validate("key1")
        assert result is None

    def test_from_env(self):
        with patch.dict(os.environ, {"KERNO_API_KEYS": "abc123:alice:Alice,def456:bob:Bob"}):
            store = APIKeyStore()
            store.from_env()

            assert store.validate("abc123") is not None
            assert store.validate("abc123")["user_id"] == "alice"
            assert store.validate("def456")["user_id"] == "bob"

    def test_from_env_empty(self):
        with patch.dict(os.environ, {"KERNO_API_KEYS": ""}, clear=True):
            store = APIKeyStore()
            store.from_env()
            assert len(store._keys) == 0


# ── RateLimiter tests ────────────────────────────────────────────────────────

class TestRateLimiter:
    def test_within_limit(self):
        limiter = RateLimiter()
        allowed, remaining = limiter.check("alice", limit=10)
        assert allowed is True
        # remaining is computed BEFORE the current request is recorded
        assert remaining == 10  # 0 current → 10 remaining before adding this call

    def test_exceed_limit(self):
        limiter = RateLimiter()
        for i in range(10):
            limiter.check("alice", limit=10)
        allowed, remaining = limiter.check("alice", limit=10)
        assert allowed is False
        assert remaining == 0

    def test_per_user_isolation(self):
        limiter = RateLimiter()
        for i in range(5):
            limiter.check("alice", limit=10)

        # Bob should still have full allowance
        allowed, remaining = limiter.check("bob", limit=10)
        assert allowed is True
        assert remaining == 10  # Bob has no prior usage

    def test_reset(self):
        limiter = RateLimiter()
        for i in range(5):
            limiter.check("alice", limit=10)

        limiter.reset("alice")
        allowed, remaining = limiter.check("alice", limit=10)
        assert allowed is True
        assert remaining == 10  # Reset clears all prior usage


# ── Secure app import test ───────────────────────────────────────────────────

class TestSecureApp:
    def test_module_importable(self):
        from kerno.server.secure_app import create_secure_app
        assert callable(create_secure_app)
