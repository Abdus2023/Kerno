"""
AllowList: restricts what modules and operations the agent can use.

Security threat model:
  1. Prompt injection via data: malicious data tells the LLM to execute harmful code
  2. Capability creep: agent imports modules it shouldn't
  3. Data exfiltration: agent sends data to external endpoints

The allowlist is enforced at two levels:
  - Static analysis (before execution): pattern matching on generated code
  - Runtime (during execution): module import hooks in the kernel
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class AllowListViolation(Exception):
    """Raised when generated code violates the allowlist."""

    def __init__(self, rule: str, matched_text: str):
        self.rule         = rule
        self.matched_text = matched_text
        super().__init__(f"AllowList violation [{rule}]: {matched_text[:100]}")


@dataclass
class AllowList:
    """
    Defines what a kernel-agent is permitted to do.

    Usage:
        # Restrictive: only allow data analysis
        al = AllowList.data_analysis()

        # Check code before execution
        try:
            al.check(generated_code)
        except AllowListViolation as e:
            # Reject the code, ask LLM to retry
            ...
    """

    # ── Allowlisted module prefixes ────────────────────────────────────────────
    # Code that imports ONLY these prefixes is allowed.
    # Empty list = no module restrictions.
    allowed_modules: list[str] = field(default_factory=list)

    # ── Blocklisted patterns ───────────────────────────────────────────────────
    # Code matching ANY of these patterns is rejected.
    blocked_patterns: list[tuple[str, str]] = field(
        default_factory=list
    )  # (regex_pattern, rule_name)

    # ── Blocklisted builtins ───────────────────────────────────────────────────
    blocked_builtins: list[str] = field(default_factory=list)

    def check(self, code: str) -> None:
        """
        Check generated code against the allowlist.

        Raises AllowListViolation if any rule is violated.
        Safe to call before every kernel.execute() call.
        """
        # Check blocked patterns
        for pattern, rule_name in self.blocked_patterns:
            match = re.search(pattern, code, re.MULTILINE | re.IGNORECASE)
            if match:
                raise AllowListViolation(rule_name, match.group(0))

        # Check blocked builtins
        for builtin in self.blocked_builtins:
            # Match whole-word usage
            pattern = r'\b' + re.escape(builtin) + r'\s*\('
            if re.search(pattern, code):
                raise AllowListViolation(
                    f"blocked_builtin:{builtin}", builtin
                )

        # Check imports against allowed modules
        if self.allowed_modules:
            import_pattern = re.compile(
                r'^\s*(?:import|from)\s+([\w.]+)', re.MULTILINE
            )
            for match in import_pattern.finditer(code):
                module = match.group(1)
                if not any(
                    module == allowed or module.startswith(allowed + ".")
                    for allowed in self.allowed_modules
                ):
                    raise AllowListViolation(
                        "disallowed_import", f"import {module}"
                    )

    # ── Preset profiles ───────────────────────────────────────────────────────

    @classmethod
    def permissive(cls) -> "AllowList":
        """
        Minimal restrictions. Suitable for trusted internal use.
        Blocks only the most dangerous operations.
        """
        return cls(
            blocked_patterns=[
                (r'\brm\s+-rf\b',        "shell_rm_rf"),
                (r'\bos\.system\s*\(',   "os_system"),
                (r'\beval\s*\(',         "eval_call"),
                (r'\bexec\s*\(',         "exec_call"),
                (r'__import__\s*\(\s*[\'"]subprocess', "subprocess_import"),
            ],
        )

    @classmethod
    def data_analysis(cls) -> "AllowList":
        """
        Suitable for a data analysis agent on trusted data.
        Allows: pandas, numpy, matplotlib, sklearn, statsmodels, scipy.
        Blocks: network access, file system writes outside working directory.
        """
        return cls(
            allowed_modules=[
                "pandas", "numpy", "matplotlib", "sklearn", "scipy",
                "statsmodels", "seaborn", "plotly", "IPython",
                "pathlib", "json", "re", "math", "datetime",
                "collections", "itertools", "functools", "typing",
                "dataclasses", "warnings", "io", "os.path",
                # kerno built-in skills (safe wrappers)
                "load", "profile", "plot_distributions", "plot_correlation",
                "what_exists", "schema_of", "checkpoint",
            ],
            blocked_patterns=[
                (r'\bsubprocess\b',             "subprocess"),
                (r'\burllib\.request\b',        "urllib_request"),
                (r'\brequests\b',               "requests_module"),
                (r'\bsocket\b',                 "socket"),
                (r'\bopen\s*\(.*[\'"]w[\'"]',   "file_write"),
                (r'\bos\.remove\b',             "os_remove"),
                (r'\bshutil\b',                 "shutil"),
            ],
            blocked_builtins=["eval", "exec", "compile", "__import__"],
        )

    @classmethod
    def read_only(cls) -> "AllowList":
        """
        Maximum restriction. Read-only operations only.
        Suitable for untrusted environments or public-facing agents.
        """
        return cls(
            allowed_modules=[
                "pandas", "numpy", "matplotlib",
                "IPython", "json", "re", "math", "datetime",
                "collections", "typing",
            ],
            blocked_patterns=[
                (r'\bopen\s*\(',        "file_open"),
                (r'\bsubprocess\b',     "subprocess"),
                (r'\burllib\b',         "urllib"),
                (r'\brequests\b',       "requests"),
                (r'\bsocket\b',         "socket"),
                (r'\bos\.',             "os_module"),
                (r'\bshutil\b',         "shutil"),
                (r'\bpickle\b',         "pickle"),
                (r'\bimportlib\b',      "importlib"),
            ],
            blocked_builtins=["eval", "exec", "compile", "__import__", "open"],
        )

    def to_kernel_code(self) -> str:
        """
        Generate Python code to enforce module restrictions
        inside the kernel at import time.
        """
        if not self.allowed_modules:
            return ""

        allowed_repr = repr(self.allowed_modules)
        return f"""\
import sys as _sys
import builtins as _builtins

_KERNO_ALLOWED_MODULES = {allowed_repr}

_original_import = _builtins.__import__

def _restricted_import(name, *args, **kwargs):
    top_level = name.split('.')[0]
    if top_level not in _KERNO_ALLOWED_MODULES:
        # Allow stdlib modules not explicitly listed
        try:
            import importlib.util as _ilu
            _spec = _ilu.find_spec(name)
            if _spec and _spec.origin and 'site-packages' not in (_spec.origin or ''):
                return _original_import(name, *args, **kwargs)
        except (ImportError, ValueError):
            pass
        raise ImportError(
            f"Module '{{name}}' is not in the kerno allowlist. "
            f"Available: {{_KERNO_ALLOWED_MODULES[:5]}}..."
        )
    return _original_import(name, *args, **kwargs)

_builtins.__import__ = _restricted_import
print("✓ Module allowlist active")
"""
