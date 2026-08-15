# kerno/llm/wrappers.py
"""
LLM wrappers: composable decorators over any LLM callable.

Every wrapper implements the same interface:
  __call__(messages: list[Message]) -> str

So wrappers compose freely:
  llm = RateLimitedLLM(CachedLLM(LoggedLLM(base_llm)))
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Callable

from kerno.types import Message


class LoggedLLM:
    """
    Logs every LLM call: messages in, response out, duration.
    """

    def __init__(self, llm, logger=None):
        self.llm    = llm
        if logger is None:
            from kerno.telemetry.logger import get_logger
            self.logger = get_logger("kerno.llm")
        else:
            self.logger = logger

    def __call__(self, messages: list[Message]) -> str:
        start = time.monotonic()
        try:
            response = self.llm(messages)
            self.logger.info(
                "LLM call",
                n_messages  = len(messages),
                input_chars = sum(len(m.content) for m in messages),
                output_chars= len(response),
                duration_ms = round((time.monotonic() - start) * 1000),
            )
            return response
        except Exception as e:
            self.logger.error("LLM call failed", error=str(e))
            raise


class CachedLLM:
    """
    Caches LLM responses by message hash.
    Identical inputs always return cached output.
    Critical for testing and cost control during development.
    """

    def __init__(self, llm, persist_path: str = None):
        self.llm    = llm
        self._cache: dict[str, str] = {}
        self._lock  = threading.Lock()
        self._path  = persist_path

        if persist_path:
            self._load()

    def __call__(self, messages: list[Message]) -> str:
        key = self._hash(messages)

        with self._lock:
            if key in self._cache:
                return self._cache[key]

        response = self.llm(messages)

        with self._lock:
            self._cache[key] = response
            if self._path:
                self._save()

        return response

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    @staticmethod
    def _hash(messages: list[Message]) -> str:
        content = json.dumps(
            [{"role": m.role, "content": m.content} for m in messages],
            sort_keys=True
        )
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _save(self) -> None:
        with open(self._path, "w") as f:
            json.dump(self._cache, f)

    def _load(self) -> None:
        from pathlib import Path
        p = Path(self._path)
        if p.exists():
            self._cache = json.loads(p.read_text())


class RetryLLM:
    """
    Retries on failure with exponential backoff.
    Handles: rate limits, transient network errors.
    """

    def __init__(
        self,
        llm,
        max_retries:   int   = 3,
        base_delay:    float = 1.0,
        max_delay:     float = 60.0,
        backoff_factor: float = 2.0,
    ):
        self.llm            = llm
        self.max_retries    = max_retries
        self.base_delay     = base_delay
        self.max_delay      = max_delay
        self.backoff_factor = backoff_factor

    def __call__(self, messages: list[Message]) -> str:
        delay      = self.base_delay
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                return self.llm(messages)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    time.sleep(min(delay, self.max_delay))
                    delay *= self.backoff_factor

        raise last_error


class FallbackLLM:
    """
    Try primary LLM; fall back to alternatives on failure.

    Usage:
        llm = FallbackLLM([
            anthropic_llm("claude-opus-4-5"),   # primary
            anthropic_llm("claude-haiku-4-5"),  # fallback 1
            openai_llm("gpt-4o-mini"),           # fallback 2
        ])
    """

    def __init__(self, llms: list):
        self.llms = llms

    def __call__(self, messages: list[Message]) -> str:
        errors = []
        for llm in self.llms:
            try:
                return llm(messages)
            except Exception as e:
                errors.append("{}: {}".format(type(llm).__name__, e))
        raise RuntimeError("All LLMs failed:\n" + "\n".join(errors))


class RateLimitedLLM:
    """
    Rate limits calls to N per time_window seconds.
    Thread-safe.
    """

    def __init__(self, llm, max_calls: int = 10, time_window: float = 60.0):
        self.llm         = llm
        self.max_calls   = max_calls
        self.time_window = time_window
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    def __call__(self, messages: list[Message]) -> str:
        with self._lock:
            now = time.monotonic()
            # Remove timestamps outside the window
            self._timestamps = [t for t in self._timestamps
                                 if now - t < self.time_window]
            if len(self._timestamps) >= self.max_calls:
                sleep_time = self.time_window - (now - self._timestamps[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
                self._timestamps = self._timestamps[1:]
            self._timestamps.append(time.monotonic())

        return self.llm(messages)


class EnsembleLLM:
    """
    Calls multiple LLMs and combines their responses.
    Useful for: majority voting, best-of-N selection, cross-checking.

    combiner: function(list[str]) -> str
      Default: return the response that appears most often (majority vote).
    """

    def __init__(
        self,
        llms:     list,
        combiner: Callable[[list[str]], str] = None,
    ):
        self.llms     = llms
        self.combiner = combiner or self._majority_vote

    def __call__(self, messages: list[Message]) -> str:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(self.llms)
        ) as ex:
            futures   = [ex.submit(llm, messages) for llm in self.llms]
            responses = []
            for f in concurrent.futures.as_completed(futures):
                try:
                    responses.append(f.result())
                except Exception:
                    pass

        if not responses:
            raise RuntimeError("All ensemble members failed")

        return self.combiner(responses)

    @staticmethod
    def _majority_vote(responses: list[str]) -> str:
        """Return the response that appears most often.
        For code: return the longest unique response (heuristic)."""
        if len(responses) == 1:
            return responses[0]
        # For code generation, longest is often best
        return max(responses, key=len)


class ModelRouter:
    """
    Route to different LLMs based on message content.
    Implements cost optimization without changing application code.

    Example:
        router = ModelRouter([
            (lambda msgs: len(msgs) > 30,  expensive_llm),   # Deep context
            (lambda msgs: "plan" in str(msgs[-1]), planner),  # Planning requests
            (lambda msgs: True,            cheap_llm),        # Default
        ])
    """

    def __init__(self, routes: list[tuple[Callable, object]]):
        self.routes = routes   # [(condition, llm), ...]

    def __call__(self, messages: list[Message]) -> str:
        for condition, llm in self.routes:
            if condition(messages):
                return llm(messages)
        raise RuntimeError("No route matched")
