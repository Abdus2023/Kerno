"""Builder for the powerful plugin pack."""

from __future__ import annotations

from typing import Protocol

from kerno.plugins.registry import (
    BasePlugin,
    CostEstimatorPlugin,
    PluginRegistry,
    TimingPlugin,
)

from .artifacts import ArtifactTrackerPlugin
from .budget import BudgetPlugin
from .checkpoint import CheckpointPlugin
from .guardrails import GuardrailPolicy, SafetyGuardrailPlugin
from .progress import ProgressPlugin
from .quality import SessionQualityPlugin
from .recovery import RecoveryAssistantPlugin
from .telemetry import TelemetryPlugin


class _KernelLike(Protocol):
    def execute(self, code: str, timeout: float = ..., silent: bool = ...): ...


def powerful_pack(
    *,
    kernel: _KernelLike | None = None,
    notebook_path: str | None = None,
    telemetry_directory: str = "_kerno/telemetry",
    checkpoint_directory: str | None = None,
    checkpoint_every: int = 10,
    cost_model: str = "claude-opus-4-5",
    max_cells: int = 50,
    max_seconds: float = 600.0,
    guardrail_policy: GuardrailPolicy | None = None,
    extra_plugins: list[BasePlugin] | None = None,
) -> PluginRegistry:
    """
    Create a batteries-included plugin registry for production sessions.

    Included by default:
      - progress: readable per-cell/session updates
      - timing: average/slowest cell and total runtime
      - cost: rough token/cost estimate
      - budget: cell/time/input/output guardrails
      - recovery: classified error guidance
      - safety_guardrails: static review for dangerous patterns
      - artifact_tracker: discovers files created by cells
      - telemetry: structured JSONL lifecycle events
      - session_quality: error/recovery/display summary
      - checkpoint: optional periodic DataFrame/model serialization
      - notebook_writer: optional live notebook persistence
    """
    registry = PluginRegistry()
    checkpoint = None
    if checkpoint_directory:
        checkpoint = CheckpointPlugin(
            every=checkpoint_every,
            directory=checkpoint_directory,
        )
        if kernel is not None:
            checkpoint.attach(kernel)

    plugins: list[BasePlugin] = [
        ProgressPlugin(),
        TimingPlugin(),
        CostEstimatorPlugin(model=cost_model),
        BudgetPlugin(max_cells=max_cells, max_seconds=max_seconds),
        RecoveryAssistantPlugin(),
        SafetyGuardrailPlugin(policy=guardrail_policy),
        ArtifactTrackerPlugin(),
        TelemetryPlugin(directory=telemetry_directory),
        SessionQualityPlugin(),
    ]
    if checkpoint is not None:
        plugins.append(checkpoint)

    for plugin in plugins:
        registry.register(plugin)

    if notebook_path:
        from kerno.plugins.registry import NotebookPlugin
        registry.register(NotebookPlugin(path=notebook_path))

    for plugin in extra_plugins or []:
        registry.register(plugin)
    return registry


__all__ = ["powerful_pack"]
