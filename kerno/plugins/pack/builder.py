"""Builder for the powerful plugin pack."""

from __future__ import annotations

from kerno.plugins.registry import (
    BasePlugin,
    CostEstimatorPlugin,
    PluginRegistry,
    TimingPlugin,
)

from .artifacts import ArtifactTrackerPlugin
from .budget import BudgetPlugin
from .guardrails import GuardrailPolicy, SafetyGuardrailPlugin
from .progress import ProgressPlugin
from .quality import SessionQualityPlugin
from .telemetry import TelemetryPlugin


def powerful_pack(
    *,
    notebook_path: str | None = None,
    telemetry_directory: str = "_kerno/telemetry",
    cost_model: str = "claude-opus-4-5",
    max_cells: int = 50,
    max_seconds: float = 600.0,
    guardrail_policy: GuardrailPolicy | None = None,
    extra_plugins: list[BasePlugin] | None = None,
) -> PluginRegistry:
    """
    Create a batteries-included plugin registry.

    Included plugins:
      - progress: readable per-cell/session updates
      - timing: average/slowest cell and total runtime
      - cost: rough token/cost estimate
      - budget: cell/time/input/output guardrails
      - safety_guardrails: static review for dangerous patterns
      - artifact_tracker: discovers created files
      - telemetry: structured JSONL lifecycle events
      - session_quality: error/recovery/display summary
      - notebook_writer: optional live notebook persistence
    """
    registry = PluginRegistry()
    for plugin in [
        ProgressPlugin(),
        TimingPlugin(),
        CostEstimatorPlugin(model=cost_model),
        BudgetPlugin(max_cells=max_cells, max_seconds=max_seconds),
        SafetyGuardrailPlugin(policy=guardrail_policy),
        ArtifactTrackerPlugin(),
        TelemetryPlugin(directory=telemetry_directory),
        SessionQualityPlugin(),
    ]:
        registry.register(plugin)

    if notebook_path:
        from kerno.plugins.registry import NotebookPlugin
        registry.register(NotebookPlugin(path=notebook_path))

    for plugin in extra_plugins or []:
        registry.register(plugin)
    return registry


__all__ = ["powerful_pack"]
