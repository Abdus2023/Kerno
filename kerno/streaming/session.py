# kerno/streaming/session.py
"""
StreamingSession: the user-facing API for streaming execution.
Wraps StreamingExecutor with the Session builder interface.
"""

from __future__ import annotations

from typing import AsyncIterator, Callable, Optional

from kerno.streaming.protocol import EventKind, StreamEvent


class StreamingSession:
    """
    Drop-in streaming replacement for Session.

    Instead of:
        result = Session().with_llm(llm)...run(task)

    Use:
        async for event in StreamingSession().with_llm(llm)...stream(task):
            handle(event)

    Or synchronously with callbacks:
        def on_output(event):
            print(event.payload["text"], end="")

        session = (
            StreamingSession()
            .with_llm(llm)
            .on(EventKind.OUTPUT_STDOUT, on_output)
            .on(EventKind.SESSION_COMPLETE, lambda e: print("Done!"))
        )
        events = session.run_sync(task)
    """

    def __init__(self):
        from kerno.compose import Session
        self._session   = Session()
        self._handlers: dict[EventKind, list[Callable]] = {}

    # ── Builder methods (delegate to Session) ─────────────────────────────────

    def with_llm(self, llm) -> "StreamingSession":
        self._session.with_llm(llm)
        return self

    def with_kernel(self, **kwargs) -> "StreamingSession":
        self._session.with_kernel(**kwargs)
        return self

    def with_skills(self, skills) -> "StreamingSession":
        self._session.with_skills(skills)
        return self

    def with_memory(self, memory) -> "StreamingSession":
        self._session.with_memory(memory)
        return self

    def with_security(self, allowlist) -> "StreamingSession":
        self._session.with_security(allowlist)
        return self

    def with_loop(self, strategy: str = "reactive", max_cells: int = 50) -> "StreamingSession":
        self._session.with_loop(strategy, max_cells)
        return self

    def verbose(self, v: bool = True) -> "StreamingSession":
        self._session.verbose(v)
        return self

    # ── Event subscription ────────────────────────────────────────────────────

    def on(
        self,
        kind:    EventKind,
        handler: Callable[[StreamEvent], None],
    ) -> "StreamingSession":
        self._handlers.setdefault(kind, []).append(handler)
        return self

    def on_output(self, handler: Callable[[str], None]) -> "StreamingSession":
        """Convenience: subscribe to text output chunks."""
        return self.on(
            EventKind.OUTPUT_STDOUT,
            lambda e: handler(e.payload.get("text", ""))
        )

    def on_cell_start(self, handler: Callable[[int, str], None]) -> "StreamingSession":
        """Convenience: subscribe to cell start events."""
        return self.on(
            EventKind.CELL_START,
            lambda e: handler(e.cell_num, e.payload.get("code_preview", ""))
        )

    def on_complete(self, handler: Callable[[dict], None]) -> "StreamingSession":
        """Convenience: subscribe to session completion."""
        return self.on(
            EventKind.SESSION_COMPLETE,
            lambda e: handler(e.payload)
        )

    def on_error(self, handler: Callable[[str, str], None]) -> "StreamingSession":
        """Convenience: subscribe to classified errors."""
        return self.on(
            EventKind.ERROR_CLASSIFIED,
            lambda e: handler(
                e.payload.get("error_class", ""),
                e.payload.get("recovery_hint", "")
            )
        )

    # ── Execution ─────────────────────────────────────────────────────────────

    def run_sync(self, task: str) -> list[StreamEvent]:
        """Execute synchronously, collecting all events."""
        from kerno.streaming.executor import StreamingExecutor

        pipeline   = self._session._build_pipeline_for_streaming()
        executor   = StreamingExecutor(pipeline)

        for kind, handlers in self._handlers.items():
            for handler in handlers:
                executor.on(kind, handler)

        return executor.run_sync(task)

    async def stream(self, task: str) -> AsyncIterator[StreamEvent]:
        """Execute asynchronously, yielding events."""
        from kerno.streaming.executor import StreamingExecutor

        pipeline = self._session._build_pipeline_for_streaming()
        executor = StreamingExecutor(pipeline)

        for kind, handlers in self._handlers.items():
            for handler in handlers:
                executor.on(kind, handler)

        async for event in executor.stream(task):
            yield event
