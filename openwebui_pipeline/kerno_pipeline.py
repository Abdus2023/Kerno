"""
Open WebUI Pipeline: Kerno Kernel Agent

Drop this file into Open WebUI's pipelines directory.
Open WebUI will auto-discover and register it.

Setup:
  1. In Open WebUI: Settings → Pipelines → Add Pipeline URL
     Or: place this file in the pipelines/ directory
  2. Configure OPENROUTER_API_KEY and KERNO_SKILLS_PATH
     in the pipeline's Valves (Open WebUI UI)
  3. Select "Kerno Agent" in the model dropdown

The pipeline turns any Open WebUI conversation into a
kernel-native agent session.
"""

from __future__ import annotations

import os
import sys
from typing import Generator, Iterator, Union

# Open WebUI pipeline interface
from pydantic import BaseModel


class Pipeline:
    """
    Open WebUI Pipeline — Kerno Kernel Agent.

    This class follows the Open WebUI pipeline specification.
    Open WebUI calls:
      - __init__      on load
      - on_startup    when the server starts
      - on_shutdown   when the server stops
      - pipe          for each message (sync or streaming)
    """

    class Valves(BaseModel):
        """
        Configurable settings exposed in Open WebUI's admin UI.
        Users set these through the pipeline's settings panel.
        """
        # LLM Configuration
        OPENROUTER_API_KEY:  str  = ""
        MODEL:               str  = "anthropic/claude-opus-4-5"
        MAX_TOKENS:          int  = 4096
        TEMPERATURE:         float = 0.0

        # Agent Configuration
        LOOP_STRATEGY:       str  = "reactive"   # reactive | reflect | plan
        MAX_CELLS:           int  = 50
        CELL_TIMEOUT:        float = 120.0

        # Skills
        SKILLS_PATH:         str  = ""            # Optional extra skills file

        # Features
        ENABLE_MEMORY:       bool = False
        MEMORY_PATH:         str  = ".kerno/memory.json"
        SHOW_CODE:           bool = True    # Show generated code in response
        SHOW_CELL_NUMBERS:   bool = True
        POOL_SIZE:           int  = 2

    def __init__(self):
        self.name   = "Kerno Kernel Agent"
        self.valves = self.Valves()
        self._pool  = None
        self._memory = None

    async def on_startup(self):
        """Called when Open WebUI starts. Initialize kernel pool."""
        print(f"[kerno] Pipeline starting: {self.name}")
        self._init_pool()

    async def on_shutdown(self):
        """Called when Open WebUI stops."""
        if self._pool:
            self._pool.shutdown()
            print("[kerno] Pool shutdown complete")

    async def on_valves_updated(self):
        """Called when admin changes valve settings."""
        # Restart pool with new configuration
        if self._pool:
            self._pool.shutdown()
        self._init_pool()
        print(f"[kerno] Valves updated, pool restarted")

    def pipe(
        self,
        user_message:    str,
        model_id:        str,
        messages:        list[dict],
        body:            dict,
    ) -> Union[str, Generator, Iterator]:
        """
        Main pipeline handler. Called for every user message.

        Open WebUI passes:
          user_message:  The latest user message
          model_id:      Which model was selected
          messages:      Full conversation history
          body:          Full request body

        Returns:
          str:       Complete response (non-streaming)
          Generator: Token stream (streaming)
        """
        # Get the task from the conversation
        task = self._build_task(user_message, messages)

        # Check if streaming requested
        stream = body.get("stream", True)

        if stream:
            return self._stream_response(task)
        else:
            return self._sync_response(task)

    # ── Private methods ───────────────────────────────────────────────────────

    def _init_pool(self):
        """Initialize the kernel pool."""
        try:
            # Add kerno to path if needed
            kerno_path = os.environ.get("KERNO_PATH", "")
            if kerno_path and kerno_path not in sys.path:
                sys.path.insert(0, kerno_path)

            from kerno.kernel.pool import KernelPool

            self._pool = KernelPool(
                size        = self.valves.POOL_SIZE,
                skills_path = self.valves.SKILLS_PATH or None,
            )
            self._pool.start()

            if self.valves.ENABLE_MEMORY:
                from kerno.memory.simple import SimpleMemoryStore
                self._memory = SimpleMemoryStore(
                    persist_path = self.valves.MEMORY_PATH
                )

            print(
                f"[kerno] Pool ready: {self.valves.POOL_SIZE} kernels, "
                f"model={self.valves.MODEL}"
            )
        except Exception as e:
            print(f"[kerno] Pool init failed: {e}")

    def _make_llm(self):
        """Create the LLM callable from current valve settings."""
        try:
            from kerno.llm.openrouter import openrouter_llm
            return openrouter_llm(
                model       = self.valves.MODEL,
                api_key     = self.valves.OPENROUTER_API_KEY or None,
                max_tokens  = self.valves.MAX_TOKENS,
                temperature = self.valves.TEMPERATURE,
            )
        except Exception as e:
            raise RuntimeError(f"LLM initialization failed: {e}")

    def _build_task(self, user_message: str, messages: list[dict]) -> str:
        """Build a Kerno task from the conversation context."""
        # Check for system message
        system = next(
            (m["content"] for m in messages if m["role"] == "system"),
            None
        )

        # Build conversation context from history
        history = [
            m for m in messages[:-1]   # Exclude current message
            if m["role"] in ("user", "assistant")
        ]

        task_parts = [user_message]

        if system:
            task_parts.append(f"\n\nContext:\n{system}")

        if len(history) > 1:
            recent = history[-4:]   # Last 2 exchanges
            ctx    = "\n".join(f"{m['role'].upper()}: {m['content'][:200]}" for m in recent)
            task_parts.append(f"\n\nPrior conversation:\n{ctx}")

        return "\n".join(task_parts)

    def _stream_response(self, task: str) -> Generator:
        """Stream execution events as text chunks."""
        if not self._pool:
            yield "❌ Kernel pool not initialized. Check pipeline settings."
            return

        task_id    = f"webui-{__import__('uuid').uuid4().hex[:8]}"
        kernel     = None

        try:
            llm    = self._make_llm()
            kernel = self._pool.acquire(task_id)

            from kerno.skills.bootstrap   import bootstrap
            from kerno.loop.factory       import make_reactive, make_reflect
            from kerno.interfaces         import AgentState
            from kerno.streaming.executor import StreamingExecutor
            from kerno.streaming.protocol import EventKind

            bootstrap(kernel)

            factory_map = {
                "reactive": make_reactive,
                "reflect":  make_reflect,
            }
            factory  = factory_map.get(self.valves.LOOP_STRATEGY, make_reactive)
            pipeline = factory(
                kernel    = kernel,
                llm       = llm,
                memory    = self._memory,
                max_cells = self.valves.MAX_CELLS,
            )

            # Use synchronous streaming (Open WebUI pipelines are sync)
            from kerno.interfaces import AgentState
            import queue, threading

            event_queue = queue.Queue()
            session_id  = str(__import__("uuid").uuid4())

            def run_pipeline():
                try:
                    executor = StreamingExecutor(pipeline, session_id=session_id)
                    events   = executor.run_sync(task)
                    for e in events:
                        event_queue.put(e)
                except Exception as ex:
                    event_queue.put(ex)
                finally:
                    event_queue.put(None)   # Sentinel

            thread = threading.Thread(target=run_pipeline, daemon=True)
            thread.start()

            while True:
                item = event_queue.get(timeout=self.valves.CELL_TIMEOUT)

                if item is None:
                    break
                if isinstance(item, Exception):
                    yield f"\n❌ Error: {item}\n"
                    break

                event = item

                if event.kind == EventKind.CELL_START:
                    if self.valves.SHOW_CODE:
                        num     = event.cell_num
                        preview = event.payload.get("code_preview", "")
                        if self.valves.SHOW_CELL_NUMBERS:
                            yield f"\n**Cell {num}**\n```python\n"
                        else:
                            yield f"\n```python\n"

                elif event.kind == EventKind.OUTPUT_STDOUT:
                    text = event.payload.get("text", "")
                    if text:
                        yield text

                elif event.kind == EventKind.CELL_COMPLETE:
                    had_error = event.payload.get("had_error", False)
                    dur_ms    = event.payload.get("duration_ms", 0)
                    if self.valves.SHOW_CODE:
                        if had_error:
                            yield f"\n```\n> ✗ Error ({dur_ms:.0f}ms)\n"
                        else:
                            yield f"\n```\n"

                elif event.kind == EventKind.OUTPUT_IMAGE:
                    yield "\n\n📊 *Plot generated*\n\n"

                elif event.kind == EventKind.ERROR_CLASSIFIED:
                    error_class = event.payload.get("error_class", "")
                    hint        = event.payload.get("recovery_hint", "")
                    yield f"\n> ⚠️ **{error_class}**: {hint}\n"

                elif event.kind == EventKind.MEMORY_STORED:
                    yield "\n💾 *Result stored in memory*\n"

                elif event.kind == EventKind.SESSION_COMPLETE:
                    status = event.payload.get("status", "COMPLETE")
                    cells  = event.payload.get("cells", 0)
                    dur    = event.payload.get("duration_s", 0)
                    icon   = "✅" if status == "COMPLETE" else "⚠️"
                    yield (
                        f"\n\n---\n"
                        f"{icon} **{status}** — "
                        f"{cells} cells in {dur:.1f}s"
                    )

        except Exception:
            # queue.Empty and other errors
            import queue as q
            if isinstance(Exception, q.Empty.__class__):
                yield f"\n\n⏱️ Timeout after {self.valves.CELL_TIMEOUT}s"
            else:
                yield f"\n\n❌ Pipeline error"
        finally:
            if kernel and self._pool:
                self._pool.release(task_id, reason="complete")

    def _sync_response(self, task: str) -> str:
        """Non-streaming: run full session, return compiled output."""
        if not self._pool:
            return "❌ Kernel pool not initialized."

        task_id = f"webui-sync-{__import__('uuid').uuid4().hex[:8]}"
        kernel  = None

        try:
            llm    = self._make_llm()
            kernel = self._pool.acquire(task_id)

            from kerno.skills.bootstrap import bootstrap
            from kerno.loop.factory     import make_reactive
            from kerno.interfaces       import AgentState

            bootstrap(kernel)

            pipeline = make_reactive(
                kernel    = kernel,
                llm       = llm,
                memory    = self._memory,
                max_cells = self.valves.MAX_CELLS,
            )

            state = AgentState(
                task       = task,
                session_id = str(__import__("uuid").uuid4()),
            )
            final = pipeline.run(state)

            # Format as markdown
            parts = []
            for cell in final.history:
                if self.valves.SHOW_CODE:
                    parts.append(f"```python\n{cell.code}\n```")
                out = cell.output.as_text(max_chars=500)
                if out and out != "[no output]":
                    parts.append(out)

            status = "✅ COMPLETE" if final.complete else "⚠️ INCOMPLETE"
            parts.append(f"\n{status} — {len(final.history)} cells")

            return "\n\n".join(parts)

        except Exception as e:
            return f"❌ Error: {e}"
        finally:
            if kernel and self._pool:
                self._pool.release(task_id, reason="complete")
