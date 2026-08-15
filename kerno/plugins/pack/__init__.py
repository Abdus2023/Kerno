"""A batteries-included plugin pack for kerno sessions.

The powerful plugin pack combines observability, safety review, artifact
discovery, telemetry, recovery, checkpointing, and session summaries into one
ready-to-use registry:

    from kerno import powerful_pack

    loop = ReactiveLoop(kernel=kernel, llm=llm, plugins=powerful_pack(kernel=kernel))

Every plugin is independently usable if you only need part of the pack.
"""

from .artifacts import ArtifactTrackerPlugin
from .budget import BudgetPlugin
from .checkpoint import CheckpointPlugin
from .guardrails import GuardrailPolicy, SafetyGuardrailPlugin
from .progress import ProgressPlugin
from .quality import SessionQualityPlugin
from .recovery import RecoveryAssistantPlugin
from .safety import BlockedExecution, HardGuardrailPlugin, SecretRedactionPlugin
from .telemetry import TelemetryPlugin
from .builder import powerful_pack

__all__ = [
    "powerful_pack",
    "ArtifactTrackerPlugin",
    "BlockedExecution",
    "BudgetPlugin",
    "CheckpointPlugin",
    "GuardrailPolicy",
    "HardGuardrailPlugin",
    "ProgressPlugin",
    "RecoveryAssistantPlugin",
    "SafetyGuardrailPlugin",
    "SecretRedactionPlugin",
    "SessionQualityPlugin",
    "TelemetryPlugin",
]
