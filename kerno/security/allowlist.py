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

import ast
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

        # Check imports against allowed modules (regex pass)
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

        # AST analysis (defense-in-depth against whitespace/syntax obfuscation & semantic bypasses)
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                # 1. Direct Name access to dangerous internal namespaces or blocked builtins
                if isinstance(node, ast.Name):
                    if node.id in ("__builtins__", "_builtins", "_original_import", "_orig"):
                        raise AllowListViolation(
                            "internal_namespace_access", f"access to '{node.id}' is forbidden"
                        )

                # 2. Import & ImportFrom restrictions
                if self.allowed_modules:
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            module = alias.name
                            if not any(
                                module == allowed or module.startswith(allowed + ".")
                                for allowed in self.allowed_modules
                            ):
                                raise AllowListViolation(
                                    "disallowed_import", f"import {module}"
                                )
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            module = node.module
                            if not any(
                                module == allowed or module.startswith(allowed + ".")
                                for allowed in self.allowed_modules
                            ):
                                raise AllowListViolation(
                                    "disallowed_import", f"from {module} import ..."
                                )

                # 3. Blocked builtin calls (direct: eval(...), __import__(...))
                if self.blocked_builtins and isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id in self.blocked_builtins:
                        raise AllowListViolation(
                            f"blocked_builtin:{node.func.id}", node.func.id
                        )

                # 4. Indirect getattr/hasattr bypasses: getattr(obj, "__import__"), getattr(os, "system")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("getattr", "hasattr"):
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            if arg.value in self.blocked_builtins or arg.value in ("system", "popen", "spawn", "exec", "eval"):
                                raise AllowListViolation(
                                    "getattr_bypass", f"getattr with forbidden attribute '{arg.value}'"
                                )

                # 5. Indirect subscript bypasses: __builtins__["__import__"]
                if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                    if node.slice.value in self.blocked_builtins:
                        raise AllowListViolation(
                            "subscript_bypass", f"subscript with forbidden key '{node.slice.value}'"
                        )
        except SyntaxError:
            # Non-python syntax (e.g. IPython magics/shell escapes) already handled by regex pass
            pass

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
                (r'^\s*%\w+',               "ipython_magic"),
                (r'^\s*!\S',                "shell_escape"),
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
                "dataclasses", "warnings", "io",
                # kerno built-in skills (safe wrappers)
                "load", "profile", "plot_distributions", "plot_correlation",
                "what_exists", "schema_of", "checkpoint",
            ],
            blocked_patterns=[
                (r'\bsubprocess\b',             "subprocess"),
                (r'\burllib\b',                 "urllib"),
                (r'\brequests\b',               "requests_module"),
                (r'\bsocket\b',                 "socket"),
                (r'\bopen\s*\(.*[\'"]w[\'"]',    "file_write"),
                (r'\bos\.remove\b',             "os_remove"),
                (r'\bos\.environ\b',            "env_access"),
                (r'\bshutil\b',                 "shutil"),
                (r'\bimportlib\b',              "importlib"),
                # pathlib is allowlisted, so block its write methods explicitly
                (r'\.write_text\s*\(',          "path_write"),
                (r'\.write_bytes\s*\(',         "path_write"),
                (r'\.unlink\s*\(',              "path_delete"),
                # pandas/matplotlib write methods (allowed modules, blocked effects)
                (r'\.to_csv\s*\(',              "pandas_write"),
                (r'\.to_parquet\s*\(',          "pandas_write"),
                (r'\.to_excel\s*\(',            "pandas_write"),
                (r'\.savefig\s*\(',             "plot_write"),
                # URL-backed data loading (allowed libraries reaching the network)
                (r'\.read_csv\s*\(\s*[\'"]https?://',  "url_load"),
                (r'\.read_json\s*\(\s*[\'"]https?://',  "url_load"),
                (r'\.read_excel\s*\(\s*[\'"]https?://', "url_load"),
                # IPython line magics / shell escapes — these bypass
                # Python-syntax checks entirely (audit hardening)
                (r'^\s*%\w+',               "ipython_magic"),
                (r'^\s*!\S',                "shell_escape"),
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
                (r'\bopen\s*\(',         "file_open"),
                (r'\bsubprocess\b',      "subprocess"),
                (r'\burllib\b',          "urllib"),
                (r'\brequests\b',        "requests"),
                (r'\bsocket\b',          "socket"),
                (r'\bos\.',              "os_module"),
                (r'\bshutil\b',          "shutil"),
                (r'\bpickle\b',          "pickle"),
                (r'\bimportlib\b',       "importlib"),
                # write methods on otherwise-allowlisted objects
                (r'\.write_text\s*\(',   "path_write"),
                (r'\.write_bytes\s*\(',  "path_write"),
                (r'\.unlink\s*\(',       "path_delete"),
                (r'\.to_csv\s*\(',       "pandas_write"),
                (r'\.to_parquet\s*\(',   "pandas_write"),
                (r'\.to_excel\s*\(',     "pandas_write"),
                (r'\.savefig\s*\(',      "plot_write"),
                # URL-backed data loading
                (r'\.read_csv\s*\(\s*[\'"]https?://',  "url_load"),
                (r'\.read_json\s*\(\s*[\'"]https?://',  "url_load"),
                (r'\.read_excel\s*\(\s*[\'"]https?://', "url_load"),
                # IPython line magics / shell escapes
                (r'^\s*%\w+',               "ipython_magic"),
                (r'^\s*!\S',                "shell_escape"),
            ],
            blocked_builtins=["eval", "exec", "compile", "__import__", "open"],
        )

    def to_kernel_code(self) -> str:
        """
        Generate Python code to enforce module restrictions
        inside the kernel at import time.

        Design constraints (this hook runs inside the patched kernel):
          - It must NEVER import anything through the patched __import__
            (the previous implementation re-entered itself via
            `import importlib.util` and wedged the kernel with infinite
            recursion).
          - Stdlib modules are allowed ONLY if they are not in the dangerous
            system modules list (os, subprocess, socket, ctypes, shutil, importlib, etc.).
          - Modules already loaded in sys.modules are allowed: the
            capability was already granted when they were first imported,
            and ipykernel internals lazily re-import them.
          - Everything else must be explicitly allowlisted.
          - _original_import is encapsulated in function closure and NEVER
            exposed in kernel globals() to prevent agent bypass.
        """
        if not self.allowed_modules:
            return ""

        allowed_repr = repr(self.allowed_modules)
        return f"""\
def _kerno_install_import_hook():
    import sys as _sys
    import builtins as _builtins

    _allowed = set({allowed_repr})
    _orig = _builtins.__import__
    _dangerous = frozenset({{
        "os", "subprocess", "sys", "socket", "shutil", "ctypes", "importlib",
        "posix", "nt", "signal", "multiprocessing", "threading", "asyncio",
        "pty", "commands", "pdb", "inspect", "_thread", "gc",
    }})

    def _restricted_import(name, *args, **kwargs):
        # Relative imports (level > 0) are internal machinery — always allow.
        level = kwargs.get('level', 0) or (args[3] if len(args) > 3 else 0)
        if level > 0:
            return _orig(name, *args, **kwargs)
        top_level = name.split('.')[0]
        # Block dangerous system modules unless explicitly declared in allowlist
        if top_level in _dangerous:
            if name not in _allowed and not any(a == name or a.startswith(name + ".") for a in _allowed):
                raise ImportError(f"Module '{{name}}' is restricted by security policy.")
        if top_level in _allowed:
            return _orig(name, *args, **kwargs)
        # Already-loaded modules (if not dangerous):
        if top_level in _sys.modules and top_level not in _dangerous:
            return _orig(name, *args, **kwargs)
        # Safe Standard library modules only:
        if top_level in getattr(_sys, 'stdlib_module_names', ()) and top_level not in _dangerous:
            return _orig(name, *args, **kwargs)
        raise ImportError(
            f"Module '{{name}}' is not in the kerno allowlist. "
            f"Available: {{sorted(list(_allowed))[:5]}}..."
        )

    _builtins.__import__ = _restricted_import

_kerno_install_import_hook()
del _kerno_install_import_hook
"""
