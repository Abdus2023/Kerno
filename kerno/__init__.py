# kerno/__init__.py
"""
kerno: a kernel-native agent runtime.
Connect a brain (LLM) to a body (Jupyter kernel).
"""

from __future__ import annotations

# ── Core types ────────────────────────────────────────────────────────────────

from kerno.types import (
    Cell, CellError, CellOutput,
    ErrorClass, LLMCallable,
    Message, SessionResult, SessionStatus,
)

# ── Interfaces (protocols) ────────────────────────────────────────────────────

from kerno.interfaces import (
    AgentState, Step, TransformContext,
    LLM, Executor, ContextStrategy, Memory,
    CellTransformer, OutputFormatter, Skill,
)

# ── Pipeline composition ─────────────────────────────────────────────────────

from kerno.pipeline import (
    Pipeline, IdentityStep, ConditionalStep,
    LoopStep, ParallelStep, RetryStep,
)

# ── Steps ────────────────────────────────────────────────────────────────────

from kerno.steps import (
    GenerateCodeStep, ReflectAndGenerateStep,
    ExecuteStep, DryRunExecuteStep,
    TransformCodeStep, FormatOutputStep,
    InjectMemoryStep, StoreMemoryStep, StoreInsightStep,
    ReflectStep, PlanStep, VerifyStep,
    CompressHistoryStep, CompletionCheckStep,
)

# ── Middleware ────────────────────────────────────────────────────────────────

from kerno.middleware import (
    Middleware, TimedMiddleware, LoggedMiddleware,
    TracedMiddleware, PluginMiddleware,
    GuardMiddleware, BudgetMiddleware, CheckpointMiddleware,
    wrap, apply_middleware,
)

# ── Interceptors ─────────────────────────────────────────────────────────────

from kerno.interceptors import (
    InterceptedPipeline, StateRecorder, StateSnapshot,
    InvariantChecker, InvariantViolation,
    make_monotonic_check, no_infinite_loops,
)

# ── Graph visualization ──────────────────────────────────────────────────────

from kerno.graph import (
    GraphNode, PipelineGraph,
)

# ── Config DSL ───────────────────────────────────────────────────────────────

from kerno.config_dsl import (
    PipelineCompiler, TEMPLATES,
)

# ── Cookbook recipes ─────────────────────────────────────────────────────────

from kerno.cookbook import (
    quick_analysis, deep_analysis, secure_analysis,
    resilient_analysis, production_pipeline,
    multi_agent_review, custom_pipeline,
)

# ── Loop strategies ──────────────────────────────────────────────────────────

from kerno.loop.factory import (
    make_reactive, make_reflect,
    make_plan_execute, make_custom, is_complete,
)
from kerno.loop.reactive       import ReactiveLoop
from kerno.loop.reflect        import ReflectReviseLoop
from kerno.loop.plan_execute   import PlanExecuteLoop
from kerno.loop.hierarchical   import HierarchicalLoop
from kerno.loop.multi_agent    import (
    AgentRole, MultiAgentLoop,
    analyst_role, critic_role, narrator_role,
)
from kerno.loop.debate         import DebateLoop

# ── Session builder ──────────────────────────────────────────────────────────

from kerno.compose import Session

# ── LLM wrappers ─────────────────────────────────────────────────────────────

from kerno.llm.wrappers import (
    LoggedLLM, CachedLLM, RetryLLM,
    FallbackLLM, RateLimitedLLM,
    EnsembleLLM, ModelRouter,
)

# ── LLM adapters ─────────────────────────────────────────────────────────────

from kerno.llm.adapters import anthropic_llm, openai_llm, make_llm

# ── LLM OpenRouter ───────────────────────────────────────────────────────────

from kerno.llm.openrouter import (
    openrouter_llm, openrouter_streaming_llm,
    list_models as list_openrouter_models,
    cheapest_model as cheapest_openrouter_model,
    MODELS as OPENROUTER_MODELS,
)

# ── Skill composition ────────────────────────────────────────────────────────

from kerno.skills.composer import (
    CodeSkill, FileSkill, ComposedSkill, SkillSet,
    minimal_skills, analysis_skills, ml_skills, full_stack_skills,
    nlp_skills, timeseries_stack,
)
from kerno.skills.registry     import SkillRegistry
from kerno.skills.bootstrap    import (
    bootstrap as load_default_skills,
    bootstrap_minimal, bootstrap_ml, bootstrap_nlp,
    bootstrap_timeseries, bootstrap_research, bootstrap_quant,
)

# ── Kernel ───────────────────────────────────────────────────────────────────

from kerno.kernel.runtime import KernelRuntime
from kerno.kernel.pool    import KernelPool

# ── Memory ───────────────────────────────────────────────────────────────────

from kerno.memory.store  import MemoryEntry, MemoryStore
from kerno.memory.simple import SimpleMemoryStore

# ── Security ─────────────────────────────────────────────────────────────────

from kerno.security.allowlist import AllowList, AllowListViolation
from kerno.security.sanitizer import InputSanitizer

# ── Comms ────────────────────────────────────────────────────────────────────

from kerno.comms.channel import CommMessage, KernoComm

# ── Errors ───────────────────────────────────────────────────────────────────

from kerno.errors.classifier import ErrorClassifier
from kerno.errors.recovery   import RecoveryStrategy

# ── Audit ────────────────────────────────────────────────────────────────────

from kerno.audit.notebook import NotebookAuditTrail

# ── Notebook continuation ────────────────────────────────────────────────────

from kerno.notebook.continuation import continue_from_notebook

# ── Plugins ──────────────────────────────────────────────────────────────────

from kerno.plugins             import BasePlugin, PluginRegistry
from kerno.plugins.registry    import (
    CostEstimatorPlugin, NotebookPlugin, TimingPlugin,
)

# ── Telemetry ────────────────────────────────────────────────────────────────

from kerno.telemetry import get_logger, get_metrics, get_tracer

# ── Config ───────────────────────────────────────────────────────────────────

from kerno.config import KernoConfig

# ── Runner ───────────────────────────────────────────────────────────────────

from kerno.runner import run_with_config

# ── Streaming ────────────────────────────────────────────────────────────────

from kerno.streaming.protocol import EventKind, StreamEvent
from kerno.streaming.executor  import StreamingExecutor
from kerno.streaming.session   import StreamingSession

# ── Dev tooling ──────────────────────────────────────────────────────────────

from kerno.dev.reload  import HotReloader
from kerno.dev.repl    import KernoREPL
from kerno.dev.inspect import SessionInspector

# ── Benchmarking ─────────────────────────────────────────────────────────────

from kerno.benchmark.suite  import BenchmarkSuite, BenchmarkCase
from kerno.benchmark.runner import BenchmarkRunner
from kerno.benchmark.report import BenchmarkReport

# ── Provenance ───────────────────────────────────────────────────────────────

from kerno.provenance import ProvenanceRecord

# ── Vault ────────────────────────────────────────────────────────────────────

from kerno.vault import SessionVault, VaultIndex

# ── Knowledge ────────────────────────────────────────────────────────────────

from kerno.knowledge import KnowledgeEngine, Observation, ObservationKind

# ── Capability ───────────────────────────────────────────────────────────────

from kerno.capability import CapabilityRegistry, RegisteredSkill, SkillStatus

# ── Evolution ────────────────────────────────────────────────────────────────

from kerno.evolution import CapabilityExtractor, SkillProposal

# ── Agent ────────────────────────────────────────────────────────────────────

from kerno.agent import (
    ProgramAgent, AgentIdentity, AgentProfile,
    SessionContext, AgentStorage,
)

# ── OpenAI-compatible server ─────────────────────────────────────────────────

from kerno.server.openai_compat import create_openai_app
from kerno.server.secure_app import create_secure_app

# ── File handling ────────────────────────────────────────────────────────────

from kerno.server.files import FileMaterializer, MaterializedFile

# ── RAG ──────────────────────────────────────────────────────────────────────

from kerno.server.rag import OpenWebUIRAGBridge, RAGDocument

# ── Auth ─────────────────────────────────────────────────────────────────────

from kerno.server.auth import APIKeyStore, RateLimiter

# ── Task-aware LLM router ────────────────────────────────────────────────────

from kerno.llm.router import TaskAwareRouter, CostTrackingRouter, RoutingRule

# ── Run functions (delegated to _run.py) ─────────────────────────────────────

from kerno._run import run, run_with_pool


__all__ = [
    # Run functions
    "run", "run_with_pool", "run_with_config",
    "continue_from_notebook",

    # Interfaces
    "AgentState", "Step", "TransformContext",
    "LLM", "Executor", "ContextStrategy", "Memory",
    "CellTransformer", "OutputFormatter", "Skill",

    # Pipeline composition
    "Pipeline", "IdentityStep", "ConditionalStep",
    "LoopStep", "ParallelStep", "RetryStep",

    # Steps
    "GenerateCodeStep", "ReflectAndGenerateStep",
    "ExecuteStep", "DryRunExecuteStep",
    "TransformCodeStep", "FormatOutputStep",
    "InjectMemoryStep", "StoreMemoryStep", "StoreInsightStep",
    "ReflectStep", "PlanStep", "VerifyStep",
    "CompressHistoryStep", "CompletionCheckStep",

    # Middleware
    "Middleware", "TimedMiddleware", "LoggedMiddleware",
    "TracedMiddleware", "PluginMiddleware",
    "GuardMiddleware", "BudgetMiddleware", "CheckpointMiddleware",
    "wrap", "apply_middleware",

    # Interceptors
    "InterceptedPipeline", "StateRecorder", "StateSnapshot",
    "InvariantChecker", "InvariantViolation",
    "make_monotonic_check", "no_infinite_loops",

    # Graph visualization
    "GraphNode", "PipelineGraph",

    # Config DSL
    "PipelineCompiler", "TEMPLATES",

    # Cookbook recipes
    "quick_analysis", "deep_analysis", "secure_analysis",
    "resilient_analysis", "production_pipeline",
    "multi_agent_review", "custom_pipeline",

    # Loop strategies
    "make_reactive", "make_reflect", "make_plan_execute",
    "make_custom", "is_complete",
    "ReactiveLoop", "ReflectReviseLoop", "PlanExecuteLoop",
    "HierarchicalLoop", "MultiAgentLoop", "DebateLoop",
    "AgentRole", "analyst_role", "critic_role", "narrator_role",

    # Session builder
    "Session",

    # LLM wrappers
    "LoggedLLM", "CachedLLM", "RetryLLM",
    "FallbackLLM", "RateLimitedLLM",
    "EnsembleLLM", "ModelRouter",

    # LLM adapters
    "anthropic_llm", "openai_llm", "make_llm",

    # LLM OpenRouter
    "openrouter_llm", "openrouter_streaming_llm",
    "list_openrouter_models", "cheapest_openrouter_model",
    "OPENROUTER_MODELS",

    # Skill composition
    "CodeSkill", "FileSkill", "ComposedSkill", "SkillSet",
    "minimal_skills", "analysis_skills", "ml_skills",
    "full_stack_skills", "nlp_skills", "timeseries_stack",
    "SkillRegistry", "load_default_skills",
    "bootstrap_minimal", "bootstrap_ml", "bootstrap_nlp",
    "bootstrap_timeseries", "bootstrap_research", "bootstrap_quant",

    # Kernel
    "KernelRuntime", "KernelPool",

    # Memory
    "MemoryStore", "MemoryEntry", "SimpleMemoryStore",

    # Security
    "AllowList", "AllowListViolation", "InputSanitizer",

    # Comms
    "KernoComm", "CommMessage",

    # Errors
    "ErrorClassifier", "RecoveryStrategy",

    # Audit
    "NotebookAuditTrail",

    # Plugins
    "PluginRegistry", "BasePlugin",
    "TimingPlugin", "CostEstimatorPlugin", "NotebookPlugin",

    # Telemetry
    "get_tracer", "get_metrics", "get_logger",

    # Streaming
    "StreamingExecutor", "StreamEvent", "EventKind", "StreamingSession",

    # Dev tooling
    "HotReloader", "KernoREPL", "SessionInspector",

    # Benchmarking
    "BenchmarkSuite", "BenchmarkCase", "BenchmarkRunner", "BenchmarkReport",

    # Config
    "KernoConfig",

    # Types
    "Cell", "CellOutput", "CellError",
    "Message", "SessionResult", "SessionStatus",
    "ErrorClass", "LLMCallable",

    # Provenance
    "ProvenanceRecord",

    # Vault
    "SessionVault", "VaultIndex",

    # Knowledge
    "KnowledgeEngine", "Observation", "ObservationKind",

    # Capability
    "CapabilityRegistry", "RegisteredSkill", "SkillStatus",

    # Evolution
    "CapabilityExtractor", "SkillProposal",

    # Agent
    "ProgramAgent", "AgentIdentity", "AgentProfile",
    "SessionContext", "AgentStorage",

    # OpenAI-compatible server
    "create_openai_app",

    # Secure server
    "create_secure_app",

    # File handling
    "FileMaterializer", "MaterializedFile",

    # RAG
    "OpenWebUIRAGBridge", "RAGDocument",

    # Auth
    "APIKeyStore", "RateLimiter",

    # Task-aware LLM router
    "TaskAwareRouter", "CostTrackingRouter", "RoutingRule",
]
