# kerno/interfaces.py
"""
Explicit Protocol interfaces for every swappable component in kerno.

Why Protocols over ABCs?
  - Structural subtyping: any object that has the right methods works
  - No inheritance required: existing objects compose without modification
  - Runtime checkable: can verify at startup, not just at type-check time
  - The standard library, numpy, pandas — they all "implement" these
    without knowing about kerno
"""

from __future__ import annotations

from typing import Any, Iterator, Protocol, runtime_checkable


# ── The LLM boundary ──────────────────────────────────────────────────────────

@runtime_checkable
class LLM(Protocol):
    """
    Anything that takes messages and returns text is an LLM.

    This covers:
      - Anthropic, OpenAI, Cohere, local models
      - Cached wrappers
      - Test mocks
      - Logged wrappers
      - Ensembles
    """
    def __call__(self, messages: list["Message"]) -> str: ...


# ── The kernel boundary ───────────────────────────────────────────────────────

@runtime_checkable
class Executor(Protocol):
    """
    Anything that takes code and returns output is an Executor.

    This covers:
      - KernelRuntime (the real thing)
      - DryRunExecutor (prints code, doesn't execute)
      - RecordingExecutor (records and replays)
      - SandboxedExecutor (executes in a container)
      - MockExecutor (returns scripted outputs for tests)
    """
    def execute(self, code: str, **kwargs) -> "CellOutput": ...
    def execute_silent(self, code: str, **kwargs) -> str: ...
    @property
    def namespace(self) -> str: ...
    @property
    def is_alive(self) -> bool: ...


# ── The context boundary ──────────────────────────────────────────────────────

@runtime_checkable
class ContextStrategy(Protocol):
    """
    Anything that builds the message list for the LLM.

    This covers:
      - PromptBuilder (current default)
      - MinimalContextBuilder (just task + namespace)
      - RAGContextBuilder (augments with retrieved documents)
      - PersonaContextBuilder (adds role-specific framing)
    """
    def build(
        self,
        task:      str,
        history:   list["Cell"],
        namespace: str,
        summary:   str,
    ) -> list["Message"]: ...


# ── The memory boundary ───────────────────────────────────────────────────────

@runtime_checkable
class Memory(Protocol):
    """
    Anything that stores and retrieves MemoryEntry objects.
    Already defined as MemoryStore — this is the Protocol form.
    """
    def store(self, entry: "MemoryEntry") -> str: ...
    def retrieve(self, query: str, k: int, **kwargs) -> list["MemoryEntry"]: ...


# ── The cell transformer boundary ─────────────────────────────────────────────

@runtime_checkable
class CellTransformer(Protocol):
    """
    A function from (code, context) → code.
    Applied to LLM output BEFORE execution.

    This is the middleware slot between LLM and kernel.

    Transformers can:
      - Add safety checks
      - Inject timing code
      - Add checkpointing
      - Normalize formatting
      - Translate between languages
    """
    def transform(self, code: str, context: "TransformContext") -> str: ...


# ── The output formatter boundary ────────────────────────────────────────────

@runtime_checkable
class OutputFormatter(Protocol):
    """
    A function from CellOutput → str.
    Applied to kernel output BEFORE it goes to the LLM context.

    Formatters can:
      - Truncate intelligently
      - Extract structured data
      - Add anomaly flags
      - Translate errors into hints
    """
    def format(self, output: "CellOutput", **kwargs) -> str: ...


# ── The skill boundary ────────────────────────────────────────────────────────

@runtime_checkable
class Skill(Protocol):
    """
    A unit of capability that can be loaded into a kernel.
    """
    @property
    def name(self) -> str: ...

    @property
    def code(self) -> str: ...

    @property
    def dependencies(self) -> list[str]: ...


# ── The step boundary ─────────────────────────────────────────────────────────

@runtime_checkable
class Step(Protocol):
    """
    One step in a pipeline.
    Steps are composable: a Pipeline is itself a Step.

    This is the core composability primitive.
    """
    def run(self, state: "AgentState") -> "AgentState": ...


# ── Shared data types used in protocols ───────────────────────────────────────

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TransformContext:
    """Context passed to CellTransformers."""
    cell_num:   int
    session_id: str
    namespace:  str
    history:    list  # list[Cell]
    task:       str


@dataclass
class AgentState:
    """
    The complete state of an agent at one moment in time.
    Passed through a pipeline of Steps.

    This is the composability primitive:
    every Step reads and writes AgentState.
    """
    task:       str
    history:    list         = field(default_factory=list)
    namespace:  str          = "{}"
    summary:    str          = ""
    session_id: str          = ""
    complete:   bool         = False
    error:      Optional[str]= None
    metadata:   dict         = field(default_factory=dict)
