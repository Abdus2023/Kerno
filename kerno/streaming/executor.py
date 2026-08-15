# kerno/streaming/executor.py
"""
StreamingExecutor: executes a pipeline and emits events in real time.

Unlike the synchronous pipeline, StreamingExecutor:
  - Emits events for every state transition
  - Streams kernel output as it arrives (no buffering)
  - Supports async iteration: async for event in executor.stream(task)
  - Works with WebSockets, SSE, queues, or any async sink
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
import uuid
from typing import AsyncIterator, Callable, Iterator, Optional

from kerno.interfaces        import AgentState
from kerno.pipeline          import Pipeline
from kerno.streaming.protocol import EventKind, StreamEvent
from kerno.types             import Cell


class StreamingExecutor:
    """
    Executes a pipeline and streams events.

    Two modes:
      Sync:  executor.run_sync(task) -> list[StreamEvent]
      Async: async for event in executor.stream(task): ...
    """

    def __init__(
        self,
        pipeline:   Pipeline,
        session_id: str = "",
    ):
        self.pipeline   = pipeline
        self.session_id = session_id or str(uuid.uuid4())
        self._handlers: dict[EventKind, list[Callable]] = {}

    # ── Event subscription ────────────────────────────────────────────────────

    def on(
        self,
        kind:    EventKind,
        handler: Callable[[StreamEvent], None],
    ) -> "StreamingExecutor":
        """
        Register a synchronous event handler.
        Returns self for chaining.
        """
        self._handlers.setdefault(kind, []).append(handler)
        return self

    def on_any(self, handler: Callable[[StreamEvent], None]) -> "StreamingExecutor":
        """Register a handler for ALL event types."""
        for kind in EventKind:
            self._handlers.setdefault(kind, []).append(handler)
        return self

    # ── Synchronous execution ─────────────────────────────────────────────────

    def run_sync(self, task: str) -> list[StreamEvent]:
        """
        Execute the pipeline synchronously.
        Collects all events and returns them as a list.
        """
        events: list[StreamEvent] = []
        self.on_any(events.append)

        state = AgentState(task=task, session_id=self.session_id)
        self._emit(StreamEvent.session_start(self.session_id, task))

        started = time.time()

        instrumented = InstrumentedPipeline(
            self.pipeline,
            session_id = self.session_id,
            emit       = self._emit,
        )
        final = instrumented.run(state)

        status = "COMPLETE" if final.complete else "ERROR" if final.error else "MAX_CELLS"
        self._emit(StreamEvent.session_complete(
            session_id = self.session_id,
            status     = status,
            cells      = len(final.history),
            duration_s = time.time() - started,
        ))

        return events

    # ── Async execution ───────────────────────────────────────────────────────

    async def stream(self, task: str) -> AsyncIterator[StreamEvent]:
        """
        Execute the pipeline and yield events as they occur.

        Usage:
            async for event in executor.stream("Analyze data.csv"):
                if event.kind == EventKind.OUTPUT_STDOUT:
                    print(event.payload["text"], end="")
                elif event.kind == EventKind.SESSION_COMPLETE:
                    print("Done!")
                    break
        """
        event_queue: asyncio.Queue[Optional[StreamEvent]] = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def sync_emit(event: StreamEvent) -> None:
            asyncio.run_coroutine_threadsafe(
                event_queue.put(event), loop
            )

        self.on_any(sync_emit)

        # Run pipeline in a thread (it's synchronous)
        def _run():
            state = AgentState(task=task, session_id=self.session_id)
            sync_emit(StreamEvent.session_start(self.session_id, task))

            started = time.time()
            instrumented = InstrumentedPipeline(
                self.pipeline,
                session_id = self.session_id,
                emit       = sync_emit,
            )
            final = instrumented.run(state)

            status = ("COMPLETE" if final.complete
                      else "ERROR" if final.error else "MAX_CELLS")
            sync_emit(StreamEvent.session_complete(
                session_id = self.session_id,
                status     = status,
                cells      = len(final.history),
                duration_s = time.time() - started,
            ))
            asyncio.run_coroutine_threadsafe(
                event_queue.put(None), loop   # Sentinel: done
            )

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        while True:
            event = await event_queue.get()
            if event is None:
                break
            yield event

    # ── Internal ──────────────────────────────────────────────────────────────

    def _emit(self, event: StreamEvent) -> None:
        """Fire all registered handlers for this event."""
        handlers = self._handlers.get(event.kind, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                pass   # Never let handler errors break execution


class InstrumentedPipeline:
    """
    Wraps a Pipeline and emits StreamEvents at each cell boundary.
    Hooks into the kernel's IOPUB stream for real-time output.
    """

    def __init__(
        self,
        pipeline:   Pipeline,
        session_id: str,
        emit:       Callable[[StreamEvent], None],
    ):
        self.pipeline   = pipeline
        self.session_id = session_id
        self.emit       = emit

    def run(self, state: AgentState) -> AgentState:
        """
        Run the pipeline with event instrumentation.
        Patches ExecuteStep instances to emit streaming output.
        """
        # Instrument all ExecuteStep instances in the pipeline
        self._patch_execute_steps(self.pipeline)
        return self.pipeline.run(state)

    def _patch_execute_steps(self, pipeline) -> None:
        """Recursively find and patch ExecuteStep instances."""
        from kerno.pipeline import LoopStep, ConditionalStep, ParallelStep
        from kerno.steps.execute import ExecuteStep

        steps = []
        if hasattr(pipeline, "steps"):
            steps = pipeline.steps
        elif hasattr(pipeline, "step"):
            steps = [pipeline.step]

        for i, step in enumerate(steps):
            if isinstance(step, ExecuteStep):
                steps[i] = StreamingExecuteStep(
                    step, self.session_id, self.emit
                )
            elif hasattr(step, "steps") or hasattr(step, "step"):
                self._patch_execute_steps(step)


class StreamingExecuteStep:
    """
    Wraps ExecuteStep to emit streaming events for each output chunk.
    """

    def __init__(
        self,
        inner:      object,
        session_id: str,
        emit:       Callable[[StreamEvent], None],
    ):
        self.inner      = inner
        self.session_id = session_id
        self.emit       = emit

    def run(self, state: AgentState) -> AgentState:
        code     = state.metadata.get("last_code", "")
        cell_num = len(state.history) + 1

        self.emit(StreamEvent.cell_start(self.session_id, cell_num, code))

        start = time.monotonic()

        # Execute using the streaming kernel interface
        kernel = self.inner.kernel
        if hasattr(kernel, "stream_execute"):
            output_parts = {"stdout": "", "images": [], "displays": []}

            for kind, text in kernel.stream_execute(code, timeout=self.inner.timeout):
                if kind == "stdout":
                    output_parts["stdout"] += text
                    self.emit(StreamEvent.output_stdout(
                        self.session_id, cell_num, text
                    ))
                elif kind == "stderr":
                    self.emit(StreamEvent(
                        kind       = EventKind.OUTPUT_STDERR,
                        session_id = self.session_id,
                        cell_num   = cell_num,
                        payload    = {"text": text},
                    ))
                elif kind == "error":
                    self.emit(StreamEvent(
                        kind       = EventKind.CELL_ERROR,
                        session_id = self.session_id,
                        cell_num   = cell_num,
                        payload    = {"message": text},
                    ))
                elif kind == "done":
                    break

            # Reconstruct CellOutput from streamed parts
            from kerno.types import CellOutput
            output = CellOutput(stdout=output_parts["stdout"])
        else:
            output = kernel.execute(code, timeout=self.inner.timeout)

        duration_ms = (time.monotonic() - start) * 1000

        # Handle images from display_data
        for img_b64 in getattr(output, "images", []):
            self.emit(StreamEvent.output_image(self.session_id, cell_num, img_b64))

        # Emit HTML displays
        for display in getattr(output, "displays", []):
            if "html" in display:
                self.emit(StreamEvent(
                    kind       = EventKind.OUTPUT_HTML,
                    session_id = self.session_id,
                    cell_num   = cell_num,
                    payload    = {"html": display["html"][:5000]},
                ))

        # Emit result
        if getattr(output, "result", None):
            self.emit(StreamEvent(
                kind       = EventKind.OUTPUT_RESULT,
                session_id = self.session_id,
                cell_num   = cell_num,
                payload    = {"result": output.result[:500]},
            ))

        # Error classification
        if output.has_error:
            from kerno.errors.classifier import ErrorClassifier
            classified = ErrorClassifier().classify(output.error)
            self.emit(StreamEvent(
                kind       = EventKind.ERROR_CLASSIFIED,
                session_id = self.session_id,
                cell_num   = cell_num,
                payload    = {
                    "error_class":    classified.error_class.name,
                    "recovery_hint":  classified.recovery_hint,
                    "is_retryable":   classified.is_retryable,
                },
            ))

        self.emit(StreamEvent.cell_complete(
            self.session_id, cell_num, output.has_error, duration_ms
        ))

        # Delegate to inner step's state update logic
        cell = Cell(
            code     = code,
            output   = output,
            cell_num = cell_num,
            author   = "agent",
        )
        state.history.append(cell)
        state.namespace = kernel.namespace

        if output.has_error:
            from kerno.errors.classifier import ErrorClassifier
            classified = ErrorClassifier().classify(output.error)
            state.metadata["recovery_hint"] = (
                f"[{classified.error_class.name}] "
                f"{classified.recovery_hint}\n\n"
                f"Suggested recovery:\n{classified.recovery_code}"
            )
            state.metadata["consecutive_errors"] = (
                state.metadata.get("consecutive_errors", 0) + 1
            )
        else:
            state.metadata["consecutive_errors"] = 0

        return state
