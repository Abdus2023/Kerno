# kerno/plugins/registry.py
"""
PluginRegistry: manages lifecycle hooks for kerno sessions.
"""

from __future__ import annotations

from abc import ABC
from typing import Optional

from kerno.telemetry.logger import get_logger

log = get_logger("kerno.plugins")


class BasePlugin(ABC):
    """
    Base class for kerno plugins.
    Override any method you want to hook into.
    All methods have default no-op implementations.
    """
    name: str = "unnamed_plugin"

    def on_session_start(self, task: str, session_id: str) -> None:
        """Called when a session begins."""
        pass

    def on_cell_complete(self, cell) -> None:
        """Called after each cell execution (success or error)."""
        pass

    def on_error(self, cell, classified_error) -> None:
        """Called when a cell produces an error."""
        pass

    def on_session_complete(self, result) -> None:
        """Called when the session finishes."""
        pass

    def on_skill_load(self, skill_name: str) -> None:
        """Called when a skill is loaded into the kernel."""
        pass


class PluginRegistry:
    """
    Holds and dispatches to registered plugins.

    Plugins are called in registration order.
    Exceptions in plugins are caught and logged — they never interrupt the session.
    """

    def __init__(self):
        self._plugins: list[BasePlugin] = []

    def register(self, plugin: BasePlugin) -> "PluginRegistry":
        """Register a plugin. Returns self for chaining."""
        self._plugins.append(plugin)
        log.info("Plugin registered", name=plugin.name)
        return self

    def unregister(self, name: str) -> bool:
        """Remove a plugin by name. Returns True if found."""
        before = len(self._plugins)
        self._plugins = [p for p in self._plugins if p.name != name]
        return len(self._plugins) < before

    def __len__(self) -> int:
        return len(self._plugins)

    # ── Dispatch methods ──────────────────────────────────────────────────────

    def on_session_start(self, task: str, session_id: str) -> None:
        self._dispatch("on_session_start", task, session_id)

    def on_cell_complete(self, cell) -> None:
        self._dispatch("on_cell_complete", cell)

    def on_error(self, cell, classified_error) -> None:
        self._dispatch("on_error", cell, classified_error)

    def on_session_complete(self, result) -> None:
        self._dispatch("on_session_complete", result)

    def on_skill_load(self, skill_name: str) -> None:
        self._dispatch("on_skill_load", skill_name)

    def _dispatch(self, method: str, *args) -> None:
        for plugin in self._plugins:
            try:
                getattr(plugin, method)(*args)
            except Exception as e:
                log.warning(
                    "Plugin error",
                    plugin = plugin.name,
                    method = method,
                    error  = str(e),
                )


# ── Built-in plugins ──────────────────────────────────────────────────────────

class TimingPlugin(BasePlugin):
    """Records wall-clock time for each cell and the full session."""
    name = "timing"

    def __init__(self):
        import time
        self._start_times: dict = {}
        self._cell_times:  list = []
        self._session_start: float = 0.0

    def on_session_start(self, task: str, session_id: str) -> None:
        import time
        self._session_start = time.monotonic()

    def on_cell_complete(self, cell) -> None:
        self._cell_times.append(cell.output.duration)

    def on_session_complete(self, result) -> None:
        import time
        total = time.monotonic() - self._session_start
        if self._cell_times:
            avg_cell = sum(self._cell_times) / len(self._cell_times)
            slowest  = max(self._cell_times)
            print(
                "[timing] Session: {:.1f}s  "
                "Avg cell: {:.1f}s  "
                "Slowest: {:.1f}s".format(total, avg_cell, slowest)
            )


class CostEstimatorPlugin(BasePlugin):
    """
    Estimates LLM API cost based on approximate token counts.
    Very rough — use for ballpark estimates only.
    """
    name = "cost_estimator"

    # Approximate costs per 1M tokens (input/output) as of 2024
    COSTS = {
        "claude-opus-4-5":    {"input": 15.0,  "output": 75.0},
        "claude-haiku-4-5":   {"input": 0.25,  "output": 1.25},
        "gpt-4o":             {"input": 5.0,   "output": 15.0},
        "gpt-4o-mini":        {"input": 0.15,  "output": 0.60},
    }

    def __init__(self, model: str = "claude-opus-4-5"):
        self.model         = model
        self._total_input  = 0
        self._total_output = 0

    def on_cell_complete(self, cell) -> None:
        # Rough token estimate: ~4 chars per token
        self._total_input  += len(cell.code) // 4
        self._total_output += len(cell.output.stdout) // 4

    def on_session_complete(self, result) -> None:
        costs = self.COSTS.get(self.model, {"input": 10.0, "output": 30.0})
        in_cost  = self._total_input  / 1_000_000 * costs["input"]
        out_cost = self._total_output / 1_000_000 * costs["output"]
        total    = in_cost + out_cost

        print(
            "[cost] Estimated: ${:.4f}  "
            "(~{:,} in tokens, "
            "~{:,} out tokens, "
            "model: {})".format(total, self._total_input, self._total_output, self.model)
        )


class NotebookPlugin(BasePlugin):
    """
    Incrementally writes cells to a notebook as the session runs.
    Unlike NotebookAuditTrail (post-hoc), this writes in real time.
    """
    name = "notebook_writer"

    def __init__(self, path: str = "sessions/live.ipynb"):
        self._path  = path
        self._trail = None

    def on_session_start(self, task: str, session_id: str) -> None:
        from kerno.audit.notebook import NotebookAuditTrail
        self._trail = NotebookAuditTrail(task=task, session_id=session_id)
        self._trail.add_task_header(task)

    def on_cell_complete(self, cell) -> None:
        if self._trail:
            self._trail.add_cell(cell)
            self._trail.save(str(__import__("pathlib").Path(self._path).parent))

    def on_session_complete(self, result) -> None:
        if self._trail:
            self._trail.add_summary(result)
            path = self._trail.save(str(__import__("pathlib").Path(self._path).parent))
            print("[notebook] Saved → {}".format(path))
