# kerno/skills/registry.py
"""
SkillRegistry: manages skills loaded into a kernel namespace.

A skill is any Python callable or object loaded into the kernel
to give the agent capabilities. The registry:
  - Tracks what was loaded and from where
  - Prevents accidental shadowing by LLM-generated code
  - Makes skills introspectable (the LLM can discover what it has)
  - Provides a manifest for the LLM's system prompt
"""

from __future__ import annotations

import hashlib
import inspect
import json
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from kerno.kernel.runtime import KernelRuntime


@dataclass
class SkillRecord:
    """Metadata about one registered skill."""
    name:        str
    source_file: str
    signature:   str
    docstring:   str
    code_hash:   str          # Hash of the skill's source code at registration


class SkillRegistry:
    """
    Loads skills into a kernel namespace and tracks them.

    Usage:
        registry = SkillRegistry()
        registry.load_file(kernel, "skills/data.py")
        registry.load_file(kernel, "skills/viz.py")

        # Get a manifest the LLM can read
        print(registry.manifest())

        # Verify nothing was shadowed
        violations = registry.check_integrity(kernel)
    """

    # Code injected into the kernel to intercept shadowing attempts
    _PROTECTION_CODE = textwrap.dedent("""\
        import warnings as _warnings

        _KERNO_PROTECTED = set()

        class _ProtectedNamespace(dict):
            def __setitem__(self, key, value):
                if key in _KERNO_PROTECTED:
                    _warnings.warn(
                        f"[kerno] Attempt to shadow protected skill '{key}'. "
                        f"Rename your variable. Original skill preserved.",
                        stacklevel=2,
                        category=UserWarning,
                    )
                    return   # Reject the overwrite silently
                super().__setitem__(key, value)

        try:
            _ip = get_ipython()
            _ip.user_ns.__class__ = _ProtectedNamespace
        except NameError:
            pass  # Not in IPython — protection disabled gracefully
    """)

    def __init__(self):
        self._records: dict[str, SkillRecord] = {}

    # ── Loading ────────────────────────────────────────────────────────────────

    def load_file(
        self,
        kernel:       KernelRuntime,
        path:         str,
        protect:      bool = True,
    ) -> list[str]:
        """
        Execute a Python file in the kernel and register its public callables.

        Args:
            kernel:   The target kernel
            path:     Path to the skills file
            protect:  If True, prevent LLM from overwriting these names

        Returns:
            List of names that were registered
        """
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Skills file not found: {path}")

        code      = file_path.read_text()
        code_hash = hashlib.sha256(code.encode()).hexdigest()[:12]

        # Execute the file
        output = kernel.execute(code, silent=True, timeout=60)
        if output.has_error:
            raise RuntimeError(
                f"Skills file '{path}' failed to load: "
                f"{output.error.ename}: {output.error.evalue}"
            )

        # Discover what was defined
        names = self._discover_names(kernel, code)

        for name in names:
            detail = kernel.inspect(name)
            self._records[name] = SkillRecord(
                name        = name,
                source_file = str(file_path),
                signature   = detail.get("signature", ""),
                docstring   = detail.get("doc", "")[:200],
                code_hash   = code_hash,
            )

        if protect and names:
            self._install_protection(kernel, names)

        return names

    def load_code(
        self,
        kernel:  KernelRuntime,
        code:    str,
        name:    str,
        protect: bool = True,
    ) -> list[str]:
        """
        Load a skill module from a code string.

        ``name`` is used as the registry key and source label, but every
        public top-level function/class discovered in ``code`` is also
        individually recorded and (optionally) protected. This makes both
        ``manifest()`` and namespace protection useful for code-string skills,
        matching the behavior of ``load_file()``.

        Returns:
            Public names discovered in the code string.
        """
        output = kernel.execute(code, silent=True, timeout=30)
        if output.has_error:
            raise RuntimeError(
                f"Skill '{name}' failed to load: "
                f"{output.error.ename}: {output.error.evalue}"
            )

        code_hash = hashlib.sha256(code.encode()).hexdigest()[:12]
        discovered = self._discover_names(kernel, code)

        # Preserve the module-level key for bootstrap/composer callers that
        # reason in terms of modules, but record every callable as well.
        self._records[name] = SkillRecord(
            name        = name,
            source_file = "<dynamic>",
            signature   = "",
            docstring   = f"Skill module with {len(discovered)} public callable(s)",
            code_hash   = code_hash,
        )

        for public_name in discovered:
            detail = kernel.inspect(public_name)
            self._records[public_name] = SkillRecord(
                name        = public_name,
                source_file = f"<dynamic>:{name}",
                signature   = detail.get("signature", ""),
                docstring   = detail.get("doc", "")[:200],
                code_hash   = code_hash,
            )

        protected = [name] + discovered
        if protect:
            self._install_protection(kernel, protected)
        return discovered

    # ── Integrity ─────────────────────────────────────────────────────────────

    def check_integrity(self, kernel: KernelRuntime) -> list[str]:
        """
        Verify that no registered skills have been shadowed.
        Returns list of names that were overwritten.
        """
        violations = []

        for name, record in self._records.items():
            # Re-hash the current definition
            current_hash = kernel.execute_silent(
                f"import hashlib as _h; "
                f"print(_h.sha256(str({name}).encode()).hexdigest()[:12])"
            )
            if current_hash != record.code_hash:
                violations.append(name)

        return violations

    # ── Manifest ──────────────────────────────────────────────────────────────

    def manifest(self, style: str = "compact") -> str:
        """
        Return a human/LLM-readable description of all registered skills.

        Args:
            style: "compact" (one line each) | "full" (with docstrings)
        """
        if not self._records:
            return "No skills loaded."

        lines = ["━━━ AVAILABLE SKILLS ━━━"]

        for name, record in sorted(self._records.items()):
            if style == "compact":
                sig  = record.signature
                doc  = record.docstring[:60] + "..." if len(record.docstring) > 60 else record.docstring
                line = f"  {name}({sig})  →  {doc}" if sig else f"  {name}  →  {doc}"
                lines.append(line)
            else:
                lines.append(f"\n  {name}")
                if record.signature:
                    lines.append(f"    Signature: ({record.signature})")
                if record.docstring:
                    lines.append(f"    {record.docstring}")

        return "\n".join(lines)

    def names(self) -> list[str]:
        """Return all registered skill names."""
        return list(self._records.keys())

    # ── Internals ─────────────────────────────────────────────────────────────

    def _discover_names(self, kernel: KernelRuntime, code: str) -> list[str]:
        """
        Find names that were defined at module level in the skill code.
        Uses static analysis — does not re-execute.
        """
        import ast

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []

        return [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not node.name.startswith("_")
        ]

    def _install_protection(
        self, kernel: KernelRuntime, names: list[str]
    ) -> None:
        """
        Install the namespace protection hook and register names as protected.
        Idempotent — safe to call multiple times.
        """
        # Install protection infrastructure (idempotent)
        kernel.execute(self._PROTECTION_CODE, silent=True, timeout=10)

        # Register the names
        names_repr = repr(set(names))
        kernel.execute(
            f"_KERNO_PROTECTED.update({names_repr})",
            silent=True,
            timeout=5,
        )
