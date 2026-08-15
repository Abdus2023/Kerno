"""Safety guardrail plugin for generated code."""

from __future__ import annotations

import ast
import fnmatch
from dataclasses import dataclass

from kerno.plugins.registry import BasePlugin


@dataclass(frozen=True)
class GuardrailViolation:
    """A single code-safety warning."""

    cell: int
    severity: str
    rule: str
    message: str
    snippet: str = ""


@dataclass
class GuardrailPolicy:
    """Declarative code-review rules."""

    blocked_calls: tuple[str, ...] = (
        "os.system", "subprocess.run", "subprocess.Popen", "subprocess.call",
        "shutil.rmtree", "os.remove", "os.unlink", "pathlib.Path.unlink",
        "eval", "exec", "compile", "__import__",
    )
    blocked_imports: tuple[str, ...] = ("ctypes", "socket")
    dangerous_builtins: tuple[str, ...] = ("eval", "exec", "compile", "__import__")
    path_glob_denylist: tuple[str, ...] = ("/etc/*", "/root/*", "/usr/*", "/boot/*")
    max_lines: int = 250


class SafetyGuardrailPlugin(BasePlugin):
    """
    Static code review for every generated cell.

    This is defense-in-depth observability: it records and prints warnings.
    It intentionally does not mutate or cancel execution; runtime policy
    enforcement belongs to allowlists or an external sandbox.
    """

    name = "safety_guardrails"

    def __init__(
        self,
        policy: GuardrailPolicy | None = None,
        block_on_violations: bool = False,
    ):
        self.policy = policy or GuardrailPolicy()
        self.block_on_violations = block_on_violations
        self.violations: list[GuardrailViolation] = []

    def on_cell_complete(self, cell) -> None:
        source = cell.code or ""
        cell_num = cell.cell_num
        new_violations: list[GuardrailViolation] = []

        line_count = len(source.splitlines())
        if line_count > self.policy.max_lines:
            new_violations.append(GuardrailViolation(
                cell_num, "warning", "cell_size",
                f"Cell has {line_count} lines (> {self.policy.max_lines}); consider splitting it.",
            ))

        try:
            tree = ast.parse(source)
        except SyntaxError:
            self._report(new_violations)
            return

        self._check_ast(tree, cell_num, new_violations)
        self._check_paths(tree, cell_num, new_violations)
        self.violations.extend(new_violations)
        self._report(new_violations)

    def _check_ast(self, tree: ast.AST, cell_num: int, out: list[GuardrailViolation]) -> None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for name in names:
                    if any(name == blocked or name.startswith(blocked + ".")
                           for blocked in self.policy.blocked_imports):
                        out.append(GuardrailViolation(
                            cell_num, "warning", "import",
                            f"Import '{name}' is outside the default safe analysis surface.",
                            name,
                        ))

            if isinstance(node, ast.Call):
                dotted = self._dotted_name(node.func)
                if dotted:
                    for blocked in self.policy.blocked_calls:
                        if dotted == blocked or dotted.endswith("." + blocked):
                            severity = "critical" if blocked in {"eval", "exec", "os.system"} else "warning"
                            out.append(GuardrailViolation(
                                cell_num, severity, "call",
                                f"Potentially unsafe call: {dotted}",
                                dotted,
                            ))
                if isinstance(node.func, ast.Name) and node.func.id in self.policy.dangerous_builtins:
                    out.append(GuardrailViolation(
                        cell_num, "critical", "builtin",
                        f"Potentially unsafe builtin: {node.func.id}",
                        node.func.id,
                    ))

    def _check_paths(self, tree: ast.AST, cell_num: int, out: list[GuardrailViolation]) -> None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            value = node.value
            for pattern in self.policy.path_glob_denylist:
                prefix = pattern.rstrip("*")
                if fnmatch.fnmatch(value, pattern) or value.startswith(prefix):
                    out.append(GuardrailViolation(
                        cell_num, "warning", "path",
                        f"Reference to sensitive path: {value}",
                        value,
                    ))
                    break

    @staticmethod
    def _dotted_name(node: ast.AST) -> str:
        parts: list[str] = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))

    def _report(self, violations: list[GuardrailViolation]) -> None:
        if not violations:
            return
        print(f"[guardrails] {len(violations)} warning(s):", flush=True)
        for v in violations:
            print(f"  - cell {v.cell} [{v.severity}/{v.rule}] {v.message}", flush=True)

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for v in self.violations:
            counts[v.severity] = counts.get(v.severity, 0) + 1
        return {"total": len(self.violations), "by_severity": counts}
