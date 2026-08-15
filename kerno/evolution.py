"""
CapabilityExtractor: extracting reusable skills from session history.

The CapabilityExtractor is the bridge between Level 3 (provenance)
and Level 5 (capability evolution).  It examines completed sessions
and extracts code patterns that can be generalised into reusable skills.

Design:
  - Extract reusable code from successful session cells
  - Identify skill candidates by pattern (data loading, transformation, etc.)
  - Propose new skills with confidence based on reuse frequency
  - Generalise specific code into parametric skills

The extractor runs after each session and feeds proposals into
the CapabilityRegistry for registration or refinement.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

from kerno.types import Cell, SessionResult


# ── SkillProposal ────────────────────────────────────────────────────────────

@dataclass
class SkillProposal:
    """
    A proposed skill extracted from a session.
    Not yet registered — awaiting review or automatic acceptance.
    """
    name:            str                = ""
    code:            str                = ""
    description:     str                = ""
    confidence:      float              = 0.5
    source_session:  str                = ""
    cell_nums:       list[int]          = field(default_factory=list)
    pattern_type:    str                = "custom"   # "load", "transform", "export", etc.
    tags:            list[str]          = field(default_factory=list)


# ── CapabilityExtractor ──────────────────────────────────────────────────────

class CapabilityExtractor:
    """
    Extract reusable skills from session history.

    Usage:
        extractor = CapabilityExtractor()
        proposals = extractor.extract(result)
        for p in proposals:
            registry.register(name=p.name, code=p.code, ...)
    """

    # Patterns that indicate a reusable skill
    SKILL_PATTERNS = {
        "load": [
            r"pd\.read_csv\(",
            r"pd\.read_parquet\(",
            r"pd\.read_excel\(",
            r"pd\.read_json\(",
            r"requests\.get\(",
            r"open\(.+read",
        ],
        "transform": [
            r"\.groupby\(",
            r"\.merge\(",
            r"\.pivot_table\(",
            r"\.apply\(",
            r"\.agg\(",
        ],
        "export": [
            r"\.to_csv\(",
            r"\.to_parquet\(",
            r"\.to_excel\(",
            r"plt\.savefig\(",
        ],
        "viz": [
            r"plt\.plot\(",
            r"plt\.bar\(",
            r"plt\.scatter\(",
            r"sns\.",
            r"\.plot\(",
        ],
        "model": [
            r"sklearn\.",
            r"fit\(",
            r"predict\(",
            r"model\.fit",
        ],
    }

    def extract(self, result: SessionResult) -> list[SkillProposal]:
        """
        Extract skill proposals from a completed session.
        Looks for cells that match known patterns and are
        successful (no errors).
        """
        proposals = []
        successful_cells = [
            c for c in result.cells
            if not c.output.has_error and len(c.code.strip()) > 20
        ]

        for cell in successful_cells:
            pattern_type = self._classify(cell.code)
            if pattern_type:
                name = self._infer_name(cell.code, pattern_type)
                description = self._infer_description(cell.code, pattern_type)
                proposal = SkillProposal(
                    name=name,
                    code=cell.code,
                    description=description,
                    confidence=0.5,
                    source_session=result.session_id,
                    cell_nums=[cell.cell_num],
                    pattern_type=pattern_type,
                    tags=[pattern_type],
                )
                proposals.append(proposal)

        # Merge similar proposals
        proposals = self._merge_similar(proposals)
        return proposals

    def _classify(self, code: str) -> Optional[str]:
        """Classify a code cell by matching against skill patterns."""
        for pattern_type, patterns in self.SKILL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, code):
                    return pattern_type
        return None

    def _infer_name(self, code: str, pattern_type: str) -> str:
        """Infer a skill name from the code and pattern type."""
        # Try to extract variable assignment
        match = re.search(r"(\w+)\s*=\s*", code)
        if match:
            var = match.group(1)
            return f"{pattern_type}_{var}"

        # Fallback: use pattern type with a counter
        return f"{pattern_type}_skill"

    def _infer_description(self, code: str, pattern_type: str) -> str:
        """Infer a skill description from the code."""
        descriptions = {
            "load": "Loads data from a source",
            "transform": "Transforms data using aggregation or reshaping",
            "export": "Exports data or plots to a file",
            "viz": "Creates a visualisation",
            "model": "Builds or applies a ML model",
        }
        base = descriptions.get(pattern_type, "Performs a reusable operation")
        # Add first line of code as context
        first_line = code.strip().split("\n")[0][:100]
        return f"{base}: {first_line}"

    def _merge_similar(self, proposals: list[SkillProposal]) -> list[SkillProposal]:
        """Merge proposals with the same inferred name."""
        merged: dict[str, SkillProposal] = {}
        for p in proposals:
            if p.name in merged:
                existing = merged[p.name]
                # Keep the longer (more detailed) code
                if len(p.code) > len(existing.code):
                    merged[p.name] = p
                # Accumulate evidence
                existing.cell_nums.extend(p.cell_nums)
                existing.confidence = min(1.0, existing.confidence + 0.1)
            else:
                merged[p.name] = p
        return list(merged.values())
