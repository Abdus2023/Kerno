"""
Tests for the OpenRouter adapter and OpenAI-compatible server modules.
These are pure unit tests — no server or network required.
"""

import os
import json
import pytest
from unittest.mock import MagicMock, patch

from kerno.llm.openrouter import (
    openrouter_llm, openrouter_streaming_llm,
    list_models, cheapest_model, MODELS, OPENROUTER_BASE_URL,
)
from kerno.server.openai_compat import (
    _extract_task, _compile_output,
    HAS_FASTAPI,
)


# ── MODELS dict tests ────────────────────────────────────────────────────────

class TestModelsDict:
    def test_shorthand_resolution(self):
        assert MODELS["claude-opus"] == "anthropic/claude-opus-4-5"
        assert MODELS["gpt-4o"] == "openai/gpt-4o"
        assert MODELS["llama-3.1-70b"] == "meta-llama/llama-3.1-70b-instruct"
        assert MODELS["gemini-pro"] == "google/gemini-pro-1.5"

    def test_full_model_id_passes_through(self):
        # When no shorthand match, the full model ID is used
        resolved = MODELS.get("some-unknown-model", "some-unknown-model")
        assert resolved == "some-unknown-model"

    def test_free_tier_models(self):
        assert "free" in MODELS["llama-3-8b-free"]
        assert "free" in MODELS["mistral-7b-free"]

    def test_base_url(self):
        assert OPENROUTER_BASE_URL == "https://openrouter.ai/api/v1"


# ── openrouter_llm tests ─────────────────────────────────────────────────────

class TestOpenrouterLLM:
    def test_no_api_key_raises(self):
        """Should raise ValueError when no API key is provided."""
        # Ensure env var is not set
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OPENROUTER_API_KEY", None)
            with pytest.raises(ValueError, match="OpenRouter API key required"):
                openrouter_llm("claude-opus", api_key=None)

    def test_with_api_key_creates_callable(self):
        """Should create a callable when API key is provided."""
        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "test response"
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai.return_value = mock_client

            llm = openrouter_llm("claude-opus", api_key="test-key")

            from kerno.types import Message
            messages = [Message(role="user", content="hello")]
            result = llm(messages)
            assert result == "test response"

    def test_shorthand_resolution_in_llm(self):
        """Shorthand model names should resolve to full IDs."""
        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "response"
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai.return_value = mock_client

            llm = openrouter_llm("claude-opus", api_key="test-key")
            assert llm._model == "anthropic/claude-opus-4-5"
            assert llm._provider == "openrouter"
            assert llm.__name__ == "openrouter/anthropic/claude-opus-4-5"

    def test_custom_timeout(self):
        """Custom timeout should be passed to OpenAI client."""
        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            llm = openrouter_llm("claude-opus", api_key="test-key", timeout=60.0)
            mock_openai.assert_called_once_with(
                api_key="test-key",
                base_url=OPENROUTER_BASE_URL,
                timeout=60.0,
            )

    def test_extra_headers_included(self):
        """OpenRouter attribution headers should be in the request."""
        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "response"
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai.return_value = mock_client

            llm = openrouter_llm("claude-opus", api_key="test-key",
                                  site_url="https://myapp.com",
                                  site_name="MyApp")
            from kerno.types import Message
            llm([Message(role="user", content="test")])

            call_kwargs = mock_client.chat.completions.create.call_args.kwargs
            assert call_kwargs["extra_headers"]["HTTP-Referer"] == "https://myapp.com"
            assert call_kwargs["extra_headers"]["X-Title"] == "MyApp"


# ── _extract_task tests ──────────────────────────────────────────────────────

class TestExtractTask:
    def test_simple_user_message(self):
        """Simple user message should become the task."""
        if not HAS_FASTAPI:
            pytest.skip("FastAPI not installed")

        from kerno.server.openai_compat import ChatMessage
        messages = [ChatMessage(role="user", content="Analyze sales data")]
        task = _extract_task(messages)
        assert task == "Analyze sales data"

    def test_system_message_context(self):
        """System message should be appended as context."""
        if not HAS_FASTAPI:
            pytest.skip("FastAPI not installed")

        from kerno.server.openai_compat import ChatMessage
        messages = [
            ChatMessage(role="system", content="You are a data analyst"),
            ChatMessage(role="user", content="Analyze this dataset"),
        ]
        task = _extract_task(messages)
        assert "Analyze this dataset" in task
        assert "System context" in task
        assert "You are a data analyst" in task

    def test_conversation_history(self):
        """Prior conversation should be included when there's enough history."""
        if not HAS_FASTAPI:
            pytest.skip("FastAPI not installed")

        from kerno.server.openai_compat import ChatMessage
        messages = [
            ChatMessage(role="user", content="Load data"),
            ChatMessage(role="assistant", content="Data loaded"),
            ChatMessage(role="user", content="Now analyze it"),
        ]
        task = _extract_task(messages)
        assert "Now analyze it" in task

    def test_empty_messages(self):
        """No user messages should yield 'No task provided'."""
        if not HAS_FASTAPI:
            pytest.skip("FastAPI not installed")

        from kerno.server.openai_compat import ChatMessage
        messages = [ChatMessage(role="system", content="be helpful")]
        task = _extract_task(messages)
        assert "No task provided" in task


# ── _compile_output tests ────────────────────────────────────────────────────

class TestCompileOutput:
    def test_empty_history(self):
        """Empty history should return a default message."""
        state = MagicMock()
        state.history = []
        result = _compile_output(state)
        assert "no output" in result

    def test_cells_with_output(self):
        """Cells with output should be compiled into markdown."""
        from kerno.types import Cell, CellOutput
        state = MagicMock()
        cell = Cell(
            code="x = 42",
            output=CellOutput(stdout="42"),
            cell_num=1,
        )
        state.history = [cell]
        result = _compile_output(state)
        assert "```python" in result
        assert "x = 42" in result


# ── openrouter_streaming_llm tests ───────────────────────────────────────────

class TestOpenrouterStreamingLLM:
    def test_no_api_key_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OPENROUTER_API_KEY", None)
            with pytest.raises(ValueError):
                openrouter_streaming_llm("claude-opus")

    def test_creates_callable(self):
        """Should create a streaming callable."""
        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            llm_stream = openrouter_streaming_llm("claude-opus", api_key="test-key")
            assert callable(llm_stream)


# ── OpenAI compat app creation tests ──────────────────────────────────────────

class TestOpenAICompatApp:
    @pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")
    def test_create_app(self):
        """Should create a FastAPI app with LLM callable."""
        mock_llm = MagicMock()
        mock_llm.return_value = "mock response"

        # We need to mock KernelPool to avoid starting real kernels
        with patch("kerno.kernel.pool.KernelPool") as mock_pool_class:
            mock_pool = MagicMock()
            mock_pool_class.return_value = mock_pool

            from kerno.server.openai_compat import create_openai_app
            app = create_openai_app(
                llm=mock_llm,
                pool_size=1,
                model_id="test-model",
                model_name="Test Model",
            )
            assert app is not None
            assert app.title == "Kerno OpenAI-Compatible API"

    def test_create_app_without_fastapi(self):
        """Should raise ImportError when FastAPI is not available."""
        if HAS_FASTAPI:
            pytest.skip("FastAPI is installed — test the negative case by mocking")

        with pytest.raises(ImportError):
            from kerno.server.openai_compat import create_openai_app
            create_openai_app(llm=MagicMock())


# ── Pipeline class tests ─────────────────────────────────────────────────────

class TestPipelineClass:
    def test_init(self):
        """Pipeline should initialize with name and valves."""
        # Import from the openwebui_pipeline module
        import sys
        from pathlib import Path
        pipeline_path = Path(__file__).parent.parent.parent / "openwebui_pipeline" / "kerno_pipeline.py"
        if not pipeline_path.exists():
            pytest.skip("openwebui_pipeline module not available")

        # Add to sys.path temporarily
        pipeline_dir = str(pipeline_path.parent)
        sys.path.insert(0, pipeline_dir)

        try:
            from kerno_pipeline import Pipeline
            p = Pipeline()
            assert p.name == "Kerno Kernel Agent"
            assert p.valves.MODEL == "anthropic/claude-opus-4-5"
            assert p.valves.MAX_CELLS == 50
            assert p.valves.SHOW_CODE == True
        finally:
            sys.path.pop(0)

    def test_valves_defaults(self):
        """Valves should have sensible defaults."""
        import sys
        from pathlib import Path
        pipeline_path = Path(__file__).parent.parent.parent / "openwebui_pipeline" / "kerno_pipeline.py"
        if not pipeline_path.exists():
            pytest.skip("openwebui_pipeline module not available")

        pipeline_dir = str(pipeline_path.parent)
        sys.path.insert(0, pipeline_dir)

        try:
            from kerno_pipeline import Pipeline
            valves = Pipeline.Valves()
            assert valves.OPENROUTER_API_KEY == ""
            assert valves.LOOP_STRATEGY == "reactive"
            assert valves.POOL_SIZE == 2
            assert valves.ENABLE_MEMORY == False
        finally:
            sys.path.pop(0)


# ── Server start module tests ────────────────────────────────────────────────

class TestServerStart:
    def test_module_importable(self):
        """The start module should be importable."""
        from kerno.server.start import main
        assert callable(main)

    def test_no_api_key_exits(self):
        """main() should exit with error when no API key is set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OPENROUTER_API_KEY", None)
            with pytest.raises(SystemExit):
                from kerno.server.start import main
                main()
