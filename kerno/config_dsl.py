# kerno/config_dsl.py
"""
Declarative pipeline configuration via YAML.

Instead of writing Python code to build pipelines, write YAML:

    pipeline:
      steps:
        - inject_memory: {memory: simple}
        - generate: {llm: default}
        - transform: {transformers: [normalization, safety]}
        - execute: {}
        - format: {formatters: [default]}
        - compress: {threshold: 20}
        - check: {}

The PipelineCompiler turns this into a Pipeline object.

Built-in templates:
  - reactive:   observe → generate → transform → execute → format → compress → check
  - reflect:    like reactive but with ReflectAndGenerateStep
  - plan:       plan once, then execute loop with verify
  - secure_analysis: reactive + safety + allowlist
  - production: reactive + full middleware stack
"""

from __future__ import annotations

import warnings
from typing import Any, Optional

from kerno.interfaces import AgentState, Step
from kerno.pipeline import LoopStep, Pipeline


# ── PipelineCompiler ──────────────────────────────────────────────────────────

class PipelineCompiler:
    """
    Compile a YAML/dict pipeline definition into a Pipeline object.

    Usage:
        compiler = PipelineCompiler(
            llm=my_llm,
            kernel=my_kernel,
            memory=my_memory,
        )
        pipeline = compiler.from_yaml(yaml_string)
        pipeline = compiler.from_file("pipeline.yaml")
        pipeline = compiler.compile({"steps": [...]})
    """

    def __init__(
        self,
        llm:    Any = None,
        kernel: Any = None,
        memory: Any = None,
    ):
        self.llm    = llm
        self.kernel  = kernel
        self.memory  = memory

    def compile(self, spec: dict) -> Pipeline:
        """Compile a dict spec into a Pipeline."""
        # Support both {"steps": [...]} and {"pipeline": {"steps": [...]}}
        if "pipeline" in spec and "steps" not in spec:
            spec = spec["pipeline"]
        steps = self._compile_steps(spec.get("steps", []))
        return Pipeline(steps)

    def from_yaml(self, yaml_string: str) -> Pipeline:
        """Compile from a YAML string."""
        import yaml
        spec = yaml.safe_load(yaml_string)
        return self.compile(spec)

    def from_file(self, path: str) -> Pipeline:
        """Compile from a YAML file path."""
        from pathlib import Path
        return self.from_yaml(Path(path).read_text())

    # ── Step compilation ──────────────────────────────────────────────────────

    def _compile_steps(self, steps_spec: list[dict]) -> list[Step]:
        """Compile a list of step specs into Step objects."""
        steps = []
        for spec in steps_spec:
            step = self._compile_step(spec)
            if step is not None:
                steps.append(step)
        return steps

    def _compile_step(self, spec: dict) -> Optional[Step]:
        """Compile a single step spec."""
        if not spec:
            return None

        # Each spec is a dict with one key: the step type
        step_type = next(iter(spec))
        step_cfg  = spec[step_type] or {}

        builders = {
            "inject_memory":  self._compile_inject_memory,
            "generate":       self._compile_generate,
            "reflect":        self._compile_reflect,
            "execute":        self._compile_execute,
            "transform":      self._compile_transform,
            "format":         self._compile_format,
            "compress":       self._compile_compress,
            "check":          self._compile_check,
            "store_memory":   self._compile_store_memory,
            "plan":           self._compile_plan,
            "verify":         self._compile_verify,
            "loop":           self._compile_loop,
        }

        builder = builders.get(step_type)
        if builder is None:
            warnings.warn("Unknown step type: {}".format(step_type))
            return None

        return builder(step_cfg)

    # ── Step builders ─────────────────────────────────────────────────────────

    def _compile_inject_memory(self, cfg: dict) -> Step:
        from kerno.steps.memory import InjectMemoryStep
        memory = self._resolve_memory(cfg)
        return InjectMemoryStep(memory)

    def _compile_generate(self, cfg: dict) -> Step:
        from kerno.steps.generate import GenerateCodeStep
        llm = self._resolve_llm(cfg)
        return GenerateCodeStep(llm)

    def _compile_reflect(self, cfg: dict) -> Step:
        from kerno.steps.generate import ReflectAndGenerateStep
        llm = self._resolve_llm(cfg)
        return ReflectAndGenerateStep(llm)

    def _compile_execute(self, cfg: dict) -> Step:
        from kerno.steps.execute import ExecuteStep
        return ExecuteStep(self.kernel)

    def _compile_transform(self, cfg: dict) -> Step:
        from kerno.steps.transform import TransformCodeStep
        transformers = self._compile_transformer(cfg.get("transformers", []))
        return TransformCodeStep(transformers)

    def _compile_format(self, cfg: dict) -> Step:
        from kerno.steps.format import FormatOutputStep
        formatters = self._compile_formatter(cfg.get("formatters", []))
        return FormatOutputStep(formatters)

    def _compile_compress(self, cfg: dict) -> Step:
        from kerno.steps.compress import CompressHistoryStep
        llm = self._resolve_llm(cfg)
        threshold = cfg.get("threshold", 20)
        return CompressHistoryStep(llm, threshold=threshold)

    def _compile_check(self, cfg: dict) -> Step:
        from kerno.steps.compress import CompletionCheckStep
        return CompletionCheckStep()

    def _compile_store_memory(self, cfg: dict) -> Step:
        from kerno.steps.memory import StoreMemoryStep
        memory = self._resolve_memory(cfg)
        return StoreMemoryStep(memory)

    def _compile_plan(self, cfg: dict) -> Step:
        from kerno.steps.plan import PlanStep
        llm = self._resolve_llm(cfg)
        return PlanStep(llm)

    def _compile_verify(self, cfg: dict) -> Step:
        from kerno.steps.plan import VerifyStep
        llm = self._resolve_llm(cfg)
        return VerifyStep(llm)

    def _compile_loop(self, cfg: dict) -> Step:
        inner_steps = self._compile_steps(cfg.get("steps", []))
        max_iter = cfg.get("max_iterations", 50)
        from kerno.loop.factory import is_complete
        return LoopStep(
            Pipeline(inner_steps),
            done=is_complete,
            max_iterations=max_iter,
        )

    # ── Transformer / formatter compilation ───────────────────────────────────

    def _compile_transformer(self, names: list[str]) -> list:
        from kerno.steps.transform import NormalizationTransformer

        registry = {
            "normalization": NormalizationTransformer,
        }

        # Try to load safety transformer if available
        try:
            from kerno.steps.transform import AllowListTransformer
            registry["safety"] = AllowListTransformer
        except ImportError:
            pass

        transformers = []
        for name in names:
            cls = registry.get(name)
            if cls is None:
                warnings.warn("Unknown transformer: {}".format(name))
                continue
            if name == "safety":
                # Safety transformer needs an allowlist
                transformers.append(cls(self._resolve_allowlist()))
            else:
                transformers.append(cls())
        return transformers

    def _compile_formatter(self, names: list[str]) -> list:
        from kerno.steps.format import AnomalyFlagFormatter

        registry = {
            "default":    lambda: [],
            "anomaly":    AnomalyFlagFormatter,
        }

        formatters = []
        for name in names:
            cls = registry.get(name)
            if cls is None:
                warnings.warn("Unknown formatter: {}".format(name))
                continue
            if callable(cls) and not isinstance(cls, type):
                formatters.extend(cls())
            else:
                formatters.append(cls())
        return formatters

    # ── Middleware application ─────────────────────────────────────────────────

    def _apply_mw(self, step: Step, mw_names: list[str]) -> Step:
        """Apply middleware wrappers to a step."""
        from kerno.middleware import (
            TimedMiddleware, LoggedMiddleware,
            TracedMiddleware, wrap,
        )

        registry = {
            "timed":  TimedMiddleware,
            "logged": LoggedMiddleware,
            "traced": TracedMiddleware,
        }

        for name in mw_names:
            cls = registry.get(name)
            if cls is None:
                warnings.warn("Unknown middleware: {}".format(name))
                continue
            step = cls(step)
        return step

    # ── Memory / LLM resolution ───────────────────────────────────────────────

    def _build_memory(self, cfg: dict) -> Any:
        """Build a memory store from config."""
        mem_type = cfg.get("memory", "simple")
        if mem_type == "simple":
            from kerno.memory.simple import SimpleMemoryStore
            return SimpleMemoryStore()
        elif mem_type == "chroma":
            from kerno.memory.chroma import ChromaMemoryStore
            return ChromaMemoryStore()
        return self.memory

    def _resolve_memory(self, cfg: dict) -> Any:
        """Resolve memory from config or fallback to self.memory."""
        if "memory" in cfg:
            return self._build_memory(cfg)
        return self.memory

    def _resolve_llm(self, cfg: dict) -> Any:
        """Resolve LLM from config or fallback to self.llm."""
        return self.llm

    def _resolve_allowlist(self) -> Any:
        """Resolve allowlist from memory or default."""
        return None


# ── Templates ─────────────────────────────────────────────────────────────────

TEMPLATES = {
    "reactive": """
pipeline:
  steps:
    - inject_memory: {memory: simple}
    - generate: {llm: default}
    - transform: {transformers: [normalization]}
    - execute: {}
    - format: {formatters: [default]}
    - compress: {threshold: 20}
    - check: {}
    - store_memory: {memory: simple}
""",
    "reflect": """
pipeline:
  steps:
    - inject_memory: {memory: simple}
    - reflect: {llm: default}
    - transform: {transformers: [normalization]}
    - execute: {}
    - format: {formatters: [default]}
    - compress: {threshold: 20}
    - check: {}
    - store_memory: {memory: simple}
""",
    "plan": """
pipeline:
  steps:
    - inject_memory: {memory: simple}
    - plan: {llm: default}
    - loop:
        max_iterations: 50
        steps:
          - generate: {llm: default}
          - transform: {transformers: [normalization]}
          - execute: {}
          - format: {formatters: [default]}
          - verify: {llm: default}
          - check: {}
    - store_memory: {memory: simple}
""",
    "secure_analysis": """
pipeline:
  steps:
    - inject_memory: {memory: simple}
    - generate: {llm: default}
    - transform: {transformers: [normalization, safety]}
    - execute: {}
    - format: {formatters: [anomaly]}
    - compress: {threshold: 20}
    - check: {}
    - store_memory: {memory: simple}
""",
    "production": """
pipeline:
  steps:
    - inject_memory: {memory: simple}
    - generate: {llm: default}
    - transform: {transformers: [normalization, safety]}
    - execute: {}
    - format: {formatters: [anomaly]}
    - compress: {threshold: 20}
    - check: {}
    - store_memory: {memory: simple}
  middleware: [timed, logged, traced]
""",
}
