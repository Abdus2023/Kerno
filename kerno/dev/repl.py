# kerno/dev/repl.py
"""
KernoREPL: an interactive shell for exploring kerno.

Not a Python REPL. A kerno REPL:
  - Each input is a NATURAL LANGUAGE task
  - The agent executes it in the running kernel
  - The kernel namespace persists between tasks
  - Special commands: /namespace, /reset, /load, /help

Think of it as: a Jupyter notebook where you type tasks
instead of code, and the AI writes the code for you.
"""

from __future__ import annotations

import sys
from typing import Optional


class KernoREPL:
    """
    Interactive kerno REPL.

    Usage:
        from kerno.dev.repl import KernoREPL
        from kerno.llm import anthropic_llm

        repl = KernoREPL(llm=anthropic_llm("claude-opus-4-5"))
        repl.start()

    CLI:
        kerno repl --model claude-opus-4-5
    """

    BANNER = """
╔═══════════════════════════════════════════════════════╗
║  kerno REPL  — kernel-native agent shell              ║
║                                                       ║
║  Type a task in natural language. The agent runs it.  ║
║  The kernel state persists between tasks.             ║
║                                                       ║
║  Commands:                                            ║
║    /namespace   — show kernel namespace               ║
║    /reset       — clear kernel state                  ║
║    /load <path> — load a skills file                  ║
║    /history     — show session history                ║
║    /notebook    — save session as notebook            ║
║    /quit        — exit                                ║
╚═══════════════════════════════════════════════════════╝
"""

    def __init__(
        self,
        llm,
        loop:       str  = "reactive",
        max_cells:  int  = 20,
        verbose:    bool = True,
    ):
        self.llm       = llm
        self.loop      = loop
        self.max_cells = max_cells
        self.verbose   = verbose

        self._kernel   = None
        self._history:  list[tuple[str, str]] = []   # (task, summary)
        self._running   = False

    def start(self) -> None:
        """Start the interactive REPL."""
        from kerno.kernel.runtime  import KernelRuntime
        from kerno.skills.bootstrap import bootstrap

        print(self.BANNER)

        self._kernel = KernelRuntime()
        self._kernel.start()
        bootstrap(self._kernel)
        print("✓ Kernel ready. Default skills loaded.\n")

        self._running = True

        try:
            while self._running:
                try:
                    prompt = input("kerno> ").strip()
                except (KeyboardInterrupt, EOFError):
                    print("\nExiting.")
                    break

                if not prompt:
                    continue

                if prompt.startswith("/"):
                    self._handle_command(prompt)
                else:
                    self._handle_task(prompt)

        finally:
            if self._kernel:
                self._kernel.shutdown()

    # ── Command dispatch ──────────────────────────────────────────────────────

    def _handle_command(self, cmd: str) -> None:
        parts = cmd.split(maxsplit=1)
        name  = parts[0].lower()
        arg   = parts[1] if len(parts) > 1 else ""

        commands = {
            "/namespace": self._cmd_namespace,
            "/ns":        self._cmd_namespace,
            "/reset":     self._cmd_reset,
            "/load":      self._cmd_load,
            "/history":   self._cmd_history,
            "/notebook":  self._cmd_notebook,
            "/quit":      self._cmd_quit,
            "/exit":      self._cmd_quit,
            "/help":      self._cmd_help,
        }

        handler = commands.get(name)
        if handler:
            handler(arg)
        else:
            print("Unknown command: {}. Type /help for commands.".format(name))

    def _handle_task(self, task: str) -> None:
        """Execute a natural language task."""
        from kerno.loop.factory import make_reactive, make_reflect
        from kerno.interfaces   import AgentState

        factory = make_reflect if self.loop == "reflect" else make_reactive
        pipeline = factory(
            kernel    = self._kernel,
            llm       = self.llm,
            max_cells = self.max_cells,
        )

        print()
        state = AgentState(task=task)

        if self.verbose:
            # Inline streaming output
            from kerno.streaming.executor import StreamingExecutor
            executor = StreamingExecutor(pipeline)
            events   = executor.run_sync(task)
            final_state = None
            for event in events:
                from kerno.streaming.protocol import EventKind
                if event.kind.name == "OUTPUT_STDOUT" and event.payload.get("text"):
                    print(event.payload["text"], end="")
                elif event.kind.name == "CELL_START":
                    print("\n── Cell {} ──".format(event.cell_num))
                elif event.kind.name == "SESSION_COMPLETE":
                    final_state = event.payload
        else:
            final = pipeline.run(state)
            final_state = {
                "status": "COMPLETE" if final.complete else "INCOMPLETE",
                "cells":  len(final.history),
            }

        print("\n{}".format("─" * 40))
        if final_state:
            status = final_state.get("status", "?")
            cells  = final_state.get("cells", 0)
            print("  {}  ({} cells)".format(status, cells))

        self._history.append((task, ""))
        print()

    # ── Command implementations ────────────────────────────────────────────────

    def _cmd_namespace(self, _: str) -> None:
        import json
        ns = json.loads(self._kernel.namespace)
        if not ns:
            print("  (empty namespace)")
        else:
            for name, desc in sorted(ns.items()):
                print("  {:<25} {}".format(name, desc))
        print()

    def _cmd_reset(self, _: str) -> None:
        self._kernel.reset_namespace()
        from kerno.skills.bootstrap import bootstrap
        bootstrap(self._kernel)
        print("✓ Namespace cleared. Skills reloaded.\n")

    def _cmd_load(self, path: str) -> None:
        if not path:
            print("Usage: /load <path_to_skills.py>")
            return
        from pathlib import Path
        p = Path(path)
        if not p.exists():
            print("File not found: {}".format(path))
            return
        out = self._kernel.execute(p.read_text(), timeout=30)
        if out.has_error:
            print("✗ {}: {}".format(out.error.ename, out.error.evalue))
        else:
            print("✓ Loaded: {}\n".format(path))

    def _cmd_history(self, _: str) -> None:
        if not self._history:
            print("  (no history)")
            return
        for i, (task, summary) in enumerate(self._history, 1):
            print("  {}. {}".format(i, task[:60]))
        print()

    def _cmd_notebook(self, path: str) -> None:
        from kerno.types import SessionResult, SessionStatus

        # Build a synthetic SessionResult from history
        print("  (notebook save requires a completed session — run a task first)")
        print()

    def _cmd_quit(self, _: str) -> None:
        self._running = False
        print("Goodbye.")

    def _cmd_help(self, _: str) -> None:
        print(self.BANNER)
