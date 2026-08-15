# kerno/skills/composer.py
"""
SkillComposer: build skill sets through composition.

Skills are no longer just strings of code.
They have names, dependencies, and can be combined.

Composition patterns:
  - Sequential:   A then B (B depends on A's definitions)
  - Conditional:  load B only if A is available
  - Versioned:    prefer v2, fall back to v1
  - Namespaced:   prefix all names to avoid conflicts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from kerno.interfaces import Skill


@dataclass
class CodeSkill:
    """A skill defined as a Python code string."""
    name:         str
    code:         str
    dependencies: list[str] = field(default_factory=list)
    version:      str       = "1.0.0"
    description:  str       = ""
    tags:         list[str] = field(default_factory=list)


@dataclass
class FileSkill:
    """A skill loaded from a file path."""
    name:         str
    path:         str
    dependencies: list[str] = field(default_factory=list)

    @property
    def code(self) -> str:
        from pathlib import Path
        return Path(self.path).read_text()


@dataclass
class ComposedSkill:
    """
    A skill built by composing other skills.
    The composed code is the concatenation of dependency code
    followed by the composition code.
    """
    name:         str
    components:   list[Skill]
    glue_code:    str         = ""
    dependencies: list[str]   = field(default_factory=list)

    @property
    def code(self) -> str:
        parts = [c.code for c in self.components]
        if self.glue_code:
            parts.append(self.glue_code)
        return "\n\n".join(parts)


class SkillSet:
    """
    An ordered, deduplicated collection of skills.
    Handles dependency resolution automatically.

    Usage:
        skills = (
            SkillSet()
            .add(data_skill)
            .add(viz_skill)
            .add(ml_skill, requires=["data_skill"])
            .add(custom_skill)
        )
        skills.load_into(kernel)
    """

    def __init__(self):
        self._skills:   dict[str, Skill] = {}   # name → Skill
        self._order:    list[str]        = []    # insertion order

    def add(
        self,
        skill:    Skill,
        requires: list[str] = None,
    ) -> "SkillSet":
        """
        Add a skill. Returns self for chaining.

        If requires is given, those skills must already be in this set
        (or will be checked before loading).
        """
        name = skill.name
        if name not in self._skills:
            self._skills[name] = skill
            self._order.append(name)
        return self

    def add_all(self, skills: list[Skill]) -> "SkillSet":
        for skill in skills:
            self.add(skill)
        return self

    def remove(self, name: str) -> "SkillSet":
        """Remove a skill by name."""
        self._skills.pop(name, None)
        self._order = [n for n in self._order if n != name]
        return self

    def replace(self, name: str, new_skill: Skill) -> "SkillSet":
        """Replace a skill while preserving load order."""
        if name in self._skills:
            self._skills[name] = new_skill
        return self

    def load_into(self, kernel, registry=None) -> None:
        """Load all skills into a kernel in dependency order."""
        from kerno.skills.registry import SkillRegistry

        reg = registry or SkillRegistry()
        for name in self._load_order():
            skill = self._skills[name]
            reg.load_code(kernel, skill.code, skill.name, protect=True)

    def _load_order(self) -> list[str]:
        """
        Topological sort respecting skill dependencies.
        Falls back to insertion order if no cycles detected.
        """
        visited: set[str]  = set()
        result:  list[str] = []

        def visit(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            skill = self._skills.get(name)
            if skill:
                for dep in skill.dependencies:
                    if dep in self._skills:
                        visit(dep)
            result.append(name)

        for name in self._order:
            visit(name)

        return result

    def combined_code(self) -> str:
        """Return all skill code concatenated in load order."""
        parts = []
        for name in self._load_order():
            skill = self._skills.get(name)
            if skill:
                parts.append("# === {} ===\n{}".format(skill.name, skill.code))
        return "\n\n".join(parts)

    def names(self) -> list[str]:
        return list(self._skills.keys())

    def __len__(self) -> int:
        return len(self._skills)

    def __or__(self, other: "SkillSet") -> "SkillSet":
        """Merge two skill sets. other's skills override on conflict."""
        merged = SkillSet()
        for name in self._order:
            merged.add(self._skills[name])
        for name in other._order:
            if name in merged._skills:
                merged.replace(name, other._skills[name])
            else:
                merged.add(other._skills[name])
        return merged

    def __sub__(self, names: list[str]) -> "SkillSet":
        """Remove skills by name."""
        result = SkillSet()
        for name in self._order:
            if name not in names:
                result.add(self._skills[name])
        return result


# ── Preset SkillSets ──────────────────────────────────────────────────────────

def minimal_skills() -> SkillSet:
    """Smallest useful skill set: data + introspection."""
    from kerno.skills.builtins.data      import get_code as data_code
    from kerno.skills.builtins.introspect import get_code as introspect_code

    return (
        SkillSet()
        .add(CodeSkill("data",      data_code()))
        .add(CodeSkill("introspect", introspect_code(),
                       dependencies=["data"]))
    )


def analysis_skills() -> SkillSet:
    """Standard data analysis stack."""
    from kerno.skills.builtins.data      import get_code as data_code
    from kerno.skills.builtins.viz       import get_code as viz_code
    from kerno.skills.builtins.introspect import get_code as introspect_code
    from kerno.skills.builtins.stats     import get_code as stats_code

    return (
        SkillSet()
        .add(CodeSkill("data",      data_code()))
        .add(CodeSkill("viz",       viz_code(),
                       dependencies=["data"]))
        .add(CodeSkill("introspect", introspect_code(),
                       dependencies=["data"]))
        .add(CodeSkill("stats",     stats_code(),
                       dependencies=["data"]))
    )


def ml_skills() -> SkillSet:
    """Full ML stack: analysis + sklearn models."""
    from kerno.skills.builtins.ml import get_code as ml_code
    return (
        analysis_skills()
        .add(CodeSkill("ml", ml_code(), dependencies=["data", "viz"]))
    )
