"""
KernoConfig: central configuration for the framework.

Design:
  - Dataclass with sensible defaults
  - Load from environment variables, JSON file, or kwargs
  - Single source of truth for all tuneable parameters
  - No global state — pass config explicitly

Usage:
    # Default config
    config = KernoConfig()

    # From environment
    config = KernoConfig.from_env()

    # From file
    config = KernoConfig.from_file(".kerno/config.json")

    # Explicit
    config = KernoConfig(
        kernel_name   = "python3",
        max_cells     = 30,
        cell_timeout  = 60.0,
    )
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class KernelConfig:
    """Kernel-specific settings."""
    name:            str   = "python3"
    startup_timeout: float = 30.0
    cell_timeout:    float = 120.0
    max_cells:       int   = 50
    compress_after:  int   = 20
    max_consecutive_errors: int = 4
    checkpoint_every: int  = 10
    pool_size:        int  = 3
    pool_overflow:    bool = True
    max_overflow:     int  = 10


@dataclass
class LLMConfig:
    """LLM-specific settings."""
    model:             str   = "claude-opus-4-5"
    max_tokens:        int   = 4096
    temperature:       float = 0.0
    planner_model:     str   = ""     # Defaults to model if empty
    executor_model:    str   = ""     # Defaults to model if empty


@dataclass
class MemoryConfig:
    """Memory settings."""
    enabled:      bool          = False
    persist_path: str           = ".kerno/memory.json"
    max_retrieve: int           = 3
    min_score:    float         = 0.1


@dataclass
class SecurityConfig:
    """Security settings."""
    profile:          str   = "permissive"   # "permissive" | "data_analysis" | "read_only"
    sanitize_inputs:  bool  = False


@dataclass
class TelemetryConfig:
    """Telemetry settings."""
    enabled:      bool  = True
    traces_path:  str   = ".kerno/traces.jsonl"
    metrics_path: str   = ".kerno/metrics.jsonl"
    log_path:     str   = ".kerno/kerno.log"
    log_level:    str   = "INFO"    # "DEBUG" | "INFO" | "WARNING" | "ERROR"


@dataclass
class OutputConfig:
    """Output settings."""
    save_notebook:  bool  = False
    notebook_dir:   str   = "sessions"
    verbose:        bool  = False


@dataclass
class KernoConfig:
    """
    Master configuration for a kerno session.
    All settings with sensible defaults.
    """
    kernel:     KernelConfig    = field(default_factory=KernelConfig)
    llm:        LLMConfig       = field(default_factory=LLMConfig)
    memory:     MemoryConfig    = field(default_factory=MemoryConfig)
    security:   SecurityConfig  = field(default_factory=SecurityConfig)
    telemetry:  TelemetryConfig = field(default_factory=TelemetryConfig)
    output:     OutputConfig    = field(default_factory=OutputConfig)

    # ── Factories ──────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "KernoConfig":
        """
        Load configuration from environment variables.

        Variables follow the pattern: KERNO_<SECTION>_<KEY>
        Examples:
          KERNO_KERNEL_NAME=python3
          KERNO_KERNEL_MAX_CELLS=50
          KERNO_LLM_MODEL=claude-opus-4-5
          KERNO_MEMORY_ENABLED=true
          KERNO_SECURITY_PROFILE=data_analysis
          KERNO_OUTPUT_VERBOSE=true
        """
        cfg = cls()

        mapping = {
            # Kernel
            "KERNO_KERNEL_NAME":                    ("kernel", "name",            str),
            "KERNO_KERNEL_STARTUP_TIMEOUT":         ("kernel", "startup_timeout", float),
            "KERNO_KERNEL_CELL_TIMEOUT":            ("kernel", "cell_timeout",    float),
            "KERNO_KERNEL_MAX_CELLS":               ("kernel", "max_cells",       int),
            "KERNO_KERNEL_COMPRESS_AFTER":          ("kernel", "compress_after",  int),
            "KERNO_KERNEL_MAX_CONSECUTIVE_ERRORS":  ("kernel", "max_consecutive_errors", int),
            "KERNO_KERNEL_POOL_SIZE":               ("kernel", "pool_size",       int),

            # LLM
            "KERNO_LLM_MODEL":                      ("llm", "model",           str),
            "KERNO_LLM_MAX_TOKENS":                 ("llm", "max_tokens",      int),
            "KERNO_LLM_TEMPERATURE":                ("llm", "temperature",     float),
            "KERNO_LLM_PLANNER_MODEL":              ("llm", "planner_model",   str),
            "KERNO_LLM_EXECUTOR_MODEL":             ("llm", "executor_model",  str),

            # Memory
            "KERNO_MEMORY_ENABLED":                 ("memory", "enabled",       _parse_bool),
            "KERNO_MEMORY_PERSIST_PATH":            ("memory", "persist_path",  str),
            "KERNO_MEMORY_MAX_RETRIEVE":            ("memory", "max_retrieve",  int),
            "KERNO_MEMORY_MIN_SCORE":               ("memory", "min_score",     float),

            # Security
            "KERNO_SECURITY_PROFILE":               ("security", "profile",         str),
            "KERNO_SECURITY_SANITIZE_INPUTS":       ("security", "sanitize_inputs", _parse_bool),

            # Telemetry
            "KERNO_TELEMETRY_ENABLED":              ("telemetry", "enabled",      _parse_bool),
            "KERNO_TELEMETRY_LOG_LEVEL":            ("telemetry", "log_level",    str),

            # Output
            "KERNO_OUTPUT_SAVE_NOTEBOOK":           ("output", "save_notebook",  _parse_bool),
            "KERNO_OUTPUT_NOTEBOOK_DIR":            ("output", "notebook_dir",   str),
            "KERNO_OUTPUT_VERBOSE":                 ("output", "verbose",        _parse_bool),
        }

        for env_var, (section, key, cast) in mapping.items():
            value = os.environ.get(env_var)
            if value is not None:
                setattr(getattr(cfg, section), key, cast(value))

        return cfg

    @classmethod
    def from_file(cls, path: str) -> "KernoConfig":
        """Load configuration from a JSON file."""
        data = json.loads(Path(path).read_text())
        cfg  = cls()

        for section_name, section_data in data.items():
            section = getattr(cfg, section_name, None)
            if section is None:
                continue
            for key, value in section_data.items():
                if hasattr(section, key):
                    setattr(section, key, value)

        return cfg

    @classmethod
    def default(cls) -> "KernoConfig":
        """Return the default configuration."""
        return cls()

    @classmethod
    def for_development(cls) -> "KernoConfig":
        """Development config: verbose, small limits, no persistence."""
        return cls(
            kernel   = KernelConfig(max_cells=20, cell_timeout=60.0),
            output   = OutputConfig(verbose=True, save_notebook=True),
            telemetry= TelemetryConfig(log_level="DEBUG"),
        )

    @classmethod
    def for_production(cls) -> "KernoConfig":
        """Production config: full telemetry, memory, security."""
        return cls(
            kernel   = KernelConfig(max_cells=100, pool_size=5),
            memory   = MemoryConfig(enabled=True),
            security = SecurityConfig(profile="data_analysis", sanitize_inputs=True),
            telemetry= TelemetryConfig(enabled=True),
            output   = OutputConfig(save_notebook=True),
        )

    # ── Serialization ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "kernel":    asdict(self.kernel),
            "llm":       asdict(self.llm),
            "memory":    asdict(self.memory),
            "security":  asdict(self.security),
            "telemetry": asdict(self.telemetry),
            "output":    asdict(self.output),
        }

    def save(self, path: str) -> None:
        """Save configuration to a JSON file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2))

    def display(self) -> None:
        """Print configuration in a readable format."""
        print("KernoConfig:")
        for section_name, section_data in self.to_dict().items():
            print(f"  {section_name}:")
            for key, value in section_data.items():
                print(f"    {key}: {value}")


def _parse_bool(value: str) -> bool:
    return value.lower() in ("true", "1", "yes", "on")
