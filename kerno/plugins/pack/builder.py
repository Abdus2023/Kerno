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
from .safety import HardGuardrailPlugin, SecretRedactionPlugin
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
    hard_guardrails: bool = False,
    redact_secrets: bool = True,
    guardrail_policy: GuardrailPolicy | None = None,
    extra_plugins: list[BasePlugin] | None = None,
) -> PluginRegistry:
    """
    Create a batteries-included plugin registry for production sessions.

    By default this includes secret redaction, progress/timing/cost reporting,
    static safety warnings, artifact tracking, telemetry, recovery guidance,
    and quality summaries. Set ``hard_guardrails=True`` to block shell, eval,
    and destructive filesystem calls before they reach the kernel.
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

    if redact_secrets:
        registry.register(SecretRedactionPlugin())
    if hard_guardrails:
        registry.register(HardGuardrailPlugin())

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
