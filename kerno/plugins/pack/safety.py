"""Pre-execution safety and redaction plugins."""

from __future__ import annotations

import ast
import re

from kerno.plugins.registry import BasePlugin


class BlockedExecution(Exception):
    """Raised by a pre-execution plugin to prevent a cell from running."""

    def __init__(self, reason: str, rule: str = "blocked"):
        super().__init__(reason)
        self.reason = reason
        self.rule = rule


class HardGuardrailPlugin(BasePlugin):
    """
    Block cells containing high-risk calls.

    The static SafetyGuardrailPlugin warns; this plugin is an opt-in hard stop
    for calls that are almost never appropriate for an autonomous data-analysis
    kernel: shell execution, dynamic eval, recursive deletion, and process
    termination.
    """

    name = "hard_guardrails"

    BLOCKED_CALLS = {
        "os.system", "os.popen", "subprocess.run", "subprocess.Popen",
        "subprocess.call", "subprocess.check_call", "subprocess.check_output",
        "shutil.rmtree", "os.remove", "os.unlink", "os.rmdir",
        "pathlib.Path.unlink", "pathlib.Path.rmdir",
        "eval", "exec", "compile", "__import__", "os.kill", "os._exit",
        "exit", "quit",
    }
    BLOCKED_IMPORTS = {"ctypes", "socket", "subprocess", "multiprocessing", "asyncio.subprocess"}

    def __init__(self, extra_blocked_calls: set[str] | None = None):
        self.blocked_calls = set(self.BLOCKED_CALLS)
        if extra_blocked_calls:
            self.blocked_calls.update(extra_blocked_calls)
        self.blocked: list[dict] = []

    def on_before_cell(self, code: str):
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return None

        for node in ast.walk(tree):
            dotted = self._dotted_name(getattr(node, "func", None))
            if dotted and any(dotted == blocked or dotted.endswith("." + blocked)
                             for blocked in self.blocked_calls):
                self._block(dotted, f"Blocked high-risk call: {dotted}")

            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"eval", "exec", "compile", "__import__"}:
                    self._block(node.func.id, f"Blocked high-risk builtin: {node.func.id}")

            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for module in modules:
                    if module in self.BLOCKED_IMPORTS:
                        self._block(module, f"Blocked import outside analysis sandbox: {module}")
        return None

    def _block(self, rule: str, reason: str):
        self.blocked.append({"rule": rule, "reason": reason})
        raise BlockedExecution(reason, rule=rule)

    @staticmethod
    def _dotted_name(node):
        if node is None:
            return ""
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))


class SecretRedactionPlugin(BasePlugin):
    """
    Redact likely secrets before code is sent to the kernel.

    The plugin replaces quoted string literals that look like API tokens with a
    placeholder and warns when a token-like assignment is present. It is
    intentionally conservative; secrets should be supplied via environment
    variables.
    """

    name = "secret_redaction"

    SECRET_PATTERNS = [
        re.compile(r"(?i)(sk-[A-Za-z0-9_-]{20,})"),
        re.compile(r"(?i)(api[_-]?key\s*=\s*)(['\"])([A-Za-z0-9_-]{20,})\2"),
        re.compile(r"(?i)(token\s*=\s*)(['\"])([A-Za-z0-9_-]{24,})\2"),
        re.compile(r"(?i)(password\s*=\s*)(['\"])([^'\"]{6,})\2"),
    ]
    PLACEHOLDER = "'***REDACTED_USE_ENV***'"

    def __init__(self):
        self.redactions = 0

    def on_before_cell(self, code: str):
        redacted = code
        redacted = self.SECRET_PATTERNS[0].sub("sk-***REDACTED***", redacted)
        for pattern in self.SECRET_PATTERNS[1:]:
            redacted = pattern.sub(rf"\g<1>{self.PLACEHOLDER}", redacted)
        if redacted != code:
            self.redactions += 1
            print("[secrets] Redacted a likely secret from generated code.", flush=True)
        return redacted or None
