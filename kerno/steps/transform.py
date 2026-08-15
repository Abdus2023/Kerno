# kerno/steps/transform.py
"""
TransformCodeStep: apply middleware to generated code before execution.

Transformers are composable — apply as many as needed.
Each transformer sees the code and can modify it.
"""

from __future__ import annotations

import re
from kerno.interfaces import AgentState, CellTransformer, TransformContext


class TransformCodeStep:
    """
    Apply a sequence of CellTransformers to the generated code.
    Transformers run in order; each sees the output of the previous.
    """

    def __init__(self, transformers: list[CellTransformer]):
        self.transformers = transformers

    def run(self, state: AgentState) -> AgentState:
        code = state.metadata.get("last_code", "")
        if not code:
            return state

        ctx = TransformContext(
            cell_num   = len(state.history) + 1,
            session_id = state.session_id,
            namespace  = state.namespace,
            history    = state.history,
            task       = state.task,
        )

        for transformer in self.transformers:
            code = transformer.transform(code, ctx)

        state.metadata["last_code"] = code
        return state


# ── Built-in transformers ─────────────────────────────────────────────────────

class AutoCheckpointTransformer:
    """
    Appends a checkpoint call after any cell that creates a DataFrame or model.
    """

    def transform(self, code: str, ctx: TransformContext) -> str:
        has_df    = re.search(r'\b\w+\s*=\s*\w*[Dd]ata[Ff]rame\b', code)
        has_fit   = re.search(r'\.fit\s*\(', code)

        if has_df or has_fit:
            code += (
                "\n\n# Auto-checkpoint\n"
                "try:\n"
                "    checkpoint(locals().get('df') or locals().get('model'), "
                "name='auto')\n"
                "except Exception:\n"
                "    pass\n"
            )
        return code


class TimingTransformer:
    """Wraps the cell in timing code that prints execution duration."""

    def transform(self, code: str, ctx: TransformContext) -> str:
        return (
            "import time as _t; _t0 = _t.monotonic()\n"
            "{}\n"
            "print(f'[timing] Cell {}: "
            "{{(_t.monotonic() - _t0)*1000:.0f}}ms')".format(code, ctx.cell_num)
        )


class AllowListTransformer:
    """Rejects code that violates the allowlist before it reaches the kernel."""

    def __init__(self, allowlist):
        self.allowlist = allowlist

    def transform(self, code: str, ctx: TransformContext) -> str:
        from kerno.security.allowlist import AllowListViolation
        try:
            self.allowlist.check(code)
            return code
        except AllowListViolation as e:
            # Replace violating code with a safe error report
            return (
                "# AllowListViolation: {}\n"
                "# Blocked code: {}\n"
                "raise AllowListViolation(\n"
                "    'Generated code violated security policy: {}'\n"
                ")".format(e.rule, e.matched_text[:80], e.rule)
            )


class SanitizationTransformer:
    """Sanitizes data-derived values in code strings."""

    def __init__(self, sanitizer=None):
        from kerno.security.sanitizer import InputSanitizer
        self.sanitizer = sanitizer or InputSanitizer()

    def transform(self, code: str, ctx: TransformContext) -> str:
        result = self.sanitizer.sanitize(code, source="llm_generated")
        return result.sanitized


class NormalizationTransformer:
    """
    Normalizes LLM-generated code:
    - Strips markdown fences if LLM added them
    - Ensures consistent indentation
    """

    def transform(self, code: str, ctx: TransformContext) -> str:
        # Strip markdown code fences
        code = re.sub(r'^```(?:python)?\s*\n?', '', code, flags=re.MULTILINE)
        code = re.sub(r'\n?```\s*$', '', code, flags=re.MULTILINE)
        return code.strip()
