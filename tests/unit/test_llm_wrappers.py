"""Unit tests for LLM wrappers: CachedLLM, RetryLLM, FallbackLLM, EnsembleLLM."""

import pytest
import tempfile
import os

from kerno.types import Message
from kerno.llm.wrappers import (
    CachedLLM, RetryLLM, FallbackLLM, EnsembleLLM,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_msgs(text="test"):
    """Create a simple message list."""
    return [Message(role="user", content=text)]


def make_llm(response="response"):
    """Create a simple LLM callable."""
    def llm(messages):
        return response
    return llm


# ── TestCachedLLM ─────────────────────────────────────────────────────────────

class TestCachedLLM:
    """Tests for CachedLLM including disk persistence."""

    def test_caches_identical_requests(self):
        call_count = [0]
        def base(messages):
            call_count[0] += 1
            return "cached_response"

        cached = CachedLLM(base)
        msgs = make_msgs("test")
        r1 = cached(msgs)
        assert r1 == "cached_response"
        assert call_count[0] == 1

        r2 = cached(msgs)
        assert r2 == "cached_response"
        assert call_count[0] == 1  # Not incremented (cached)

    def test_different_requests_not_cached(self):
        call_count = [0]
        def base(messages):
            call_count[0] += 1
            return "different_response"

        cached = CachedLLM(base)
        r1 = cached(make_msgs("query1"))
        r2 = cached(make_msgs("query2"))
        assert call_count[0] == 2  # Both calls made

    def test_clear_cache(self):
        cached = CachedLLM(make_llm("r"))
        cached(make_msgs("test"))
        assert cached.cache_size >= 1
        cached.clear()
        assert cached.cache_size == 0

    def test_disk_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache.json")

            call_count = [0]
            def base(messages):
                call_count[0] += 1
                return "persisted"

            # First instance: writes to disk
            cached1 = CachedLLM(base, persist_path=path)
            cached1(make_msgs("test"))
            assert call_count[0] == 1

            # Second instance: loads from disk
            cached2 = CachedLLM(base, persist_path=path)
            r = cached2(make_msgs("test"))
            assert r == "persisted"
            assert call_count[0] == 1  # No new call (loaded from disk)

    def test_cache_size_property(self):
        cached = CachedLLM(make_llm("r"))
        assert cached.cache_size == 0
        cached(make_msgs("a"))
        assert cached.cache_size == 1
        cached(make_msgs("b"))
        assert cached.cache_size == 2


# ── TestRetryLLM ──────────────────────────────────────────────────────────────

class TestRetryLLM:
    """Tests for RetryLLM."""

    def test_success_on_first_call(self):
        llm = make_llm("ok")
        retry = RetryLLM(llm, max_retries=3, base_delay=0.01)
        result = retry(make_msgs("test"))
        assert result == "ok"

    def test_retries_on_failure(self):
        call_count = [0]
        def failing_llm(messages):
            call_count[0] += 1
            if call_count[0] < 3:
                raise RuntimeError("transient failure")
            return "success after retries"

        retry = RetryLLM(failing_llm, max_retries=3, base_delay=0.01)
        result = retry(make_msgs("test"))
        assert result == "success after retries"
        assert call_count[0] == 3

    def test_all_retries_exhausted(self):
        def always_fail(messages):
            raise RuntimeError("permanent failure")

        retry = RetryLLM(always_fail, max_retries=2, base_delay=0.01)
        with pytest.raises(RuntimeError, match="permanent failure"):
            retry(make_msgs("test"))


# ── TestFallbackLLM ──────────────────────────────────────────────────────────

class TestFallbackLLM:
    """Tests for FallbackLLM."""

    def test_primary_works(self):
        primary = make_llm("primary")
        fallback = make_llm("fallback")
        fb = FallbackLLM([primary, fallback])
        result = fb(make_msgs("test"))
        assert result == "primary"

    def test_fallback_on_primary_failure(self):
        def fail(messages):
            raise RuntimeError("primary failed")

        fallback = make_llm("fallback")
        fb = FallbackLLM([fail, fallback])
        result = fb(make_msgs("test"))
        assert result == "fallback"

    def test_all_fail(self):
        def fail1(messages):
            raise RuntimeError("fail1")
        def fail2(messages):
            raise RuntimeError("fail2")

        fb = FallbackLLM([fail1, fail2])
        with pytest.raises(RuntimeError, match="All LLMs failed"):
            fb(make_msgs("test"))


# ── TestEnsembleLLM ──────────────────────────────────────────────────────────

class TestEnsembleLLM:
    """Tests for EnsembleLLM."""

    def test_default_combiner_picks_longest(self):
        def short(messages):
            return "short"
        def long(messages):
            return "longer response with more detail"

        ens = EnsembleLLM([short, long])
        result = ens(make_msgs("test"))
        assert "longer" in result

    def test_custom_combiner(self):
        def llm1(messages):
            return "a"
        def llm2(messages):
            return "b"

        ens = EnsembleLLM([llm1, llm2], combiner=lambda rs: rs[0])
        result = ens(make_msgs("test"))
        assert result == "a"

    def test_partial_failure(self):
        def fail(messages):
            raise RuntimeError("fail")
        def succeed(messages):
            return "success"

        ens = EnsembleLLM([fail, succeed])
        result = ens(make_msgs("test"))
        assert result == "success"

    def test_all_fail_raises(self):
        def fail(messages):
            raise RuntimeError("fail")

        ens = EnsembleLLM([fail, fail])
        with pytest.raises(RuntimeError, match="All ensemble members failed"):
            ens(make_msgs("test"))
