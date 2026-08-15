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
    """

    def __init__(self):
        self._skills: dict[str, Skill] = {}
        self._order:  list[str]        = []

    def add(self, skill: Skill, requires: list[str] = None) -> "SkillSet":
        """Add a skill. Returns self for chaining."""
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
        self._skills.pop(name, None)
        self._order = [n for n in self._order if n != name]
        return self

    def replace(self, name: str, new_skill: Skill) -> "SkillSet":
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
        visited: set[str] = set()
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
        result = SkillSet()
        for name in self._order:
            if name not in names:
                result.add(self._skills[name])
        return result


# ── Preset SkillSets ──────────────────────────────────────────────────────────

def minimal_skills() -> SkillSet:
    """Smallest useful skill set: data + introspection."""
    from kerno.skills.builtins.data       import get_code as data_code
    from kerno.skills.builtins.introspect import get_code as introspect_code

    return (
        SkillSet()
        .add(CodeSkill("data", data_code()))
        .add(CodeSkill("introspect", introspect_code(), dependencies=["data"]))
    )


def analysis_skills() -> SkillSet:
    """Standard data analysis stack."""
    from kerno.skills.builtins.data       import get_code as data_code
    from kerno.skills.builtins.viz        import get_code as viz_code
    from kerno.skills.builtins.introspect import get_code as introspect_code
    from kerno.skills.builtins.stats      import get_code as stats_code

    return (
        SkillSet()
        .add(CodeSkill("data", data_code()))
        .add(CodeSkill("viz", viz_code(), dependencies=["data"]))
        .add(CodeSkill("introspect", introspect_code(), dependencies=["data"]))
        .add(CodeSkill("stats", stats_code(), dependencies=["data"]))
    )


def ml_skills() -> SkillSet:
    """Full ML stack: analysis + sklearn models."""
    from kerno.skills.builtins.ml import get_code as ml_code
    return (
        analysis_skills()
        .add(CodeSkill("ml", ml_code(), dependencies=["data", "viz"]))
    )


def full_stack_skills() -> SkillSet:
    """
    The complete built-in skill stack.

    This mirrors kerno.skills.bootstrap.bootstrap and includes every
    first-party module available with the package.
    """
    from kerno.skills.builtins.data       import get_code as data_code
    from kerno.skills.builtins.viz        import get_code as viz_code
    from kerno.skills.builtins.introspect import get_code as introspect_code
    from kerno.skills.builtins.ml         import get_code as ml_code
    from kerno.skills.builtins.stats      import get_code as stats_code
    from kerno.skills.builtins.text       import get_code as text_code
    from kerno.skills.builtins.nlp        import get_code as nlp_code
    from kerno.skills.builtins.timeseries import get_code as timeseries_code
    from kerno.skills.builtins.synthetic  import get_code as synthetic_code
    from kerno.skills.builtins.features   import get_code as features_code
    from kerno.skills.builtins.quality    import get_code as quality_code
    from kerno.skills.builtins.anomaly    import get_code as anomaly_code
    from kerno.skills.builtins.report     import get_code as report_code
    from kerno.skills.builtins.artifacts  import get_code as artifacts_code
    from kerno.skills.builtins.export     import get_code as export_code
    from kerno.skills.builtins.docs       import get_code as docs_code
    from kerno.skills.builtins.filesystem import get_code as filesystem_code
    from kerno.skills.builtins.synth      import get_code as synth_code
    from kerno.skills.builtins.api        import get_code as api_code
    from kerno.skills.builtins.network    import get_code as network_code
    from kerno.skills.builtins.graph      import get_code as graph_code
    from kerno.skills.builtins.simulation import get_code as simulation_code
    from kerno.skills.builtins.optimization import get_code as optimization_code
    from kerno.skills.builtins.finance    import get_code as finance_code
    from kerno.skills.builtins.experiment import get_code as experiment_code
    from kerno.skills.builtins.meta       import get_code as meta_code
    from kerno.skills.builtins.llm_tools  import get_code as llm_tools_code
    from kerno.skills.builtins.web        import get_code as web_code
    from kerno.skills.builtins.sql        import get_code as sql_code

    return (
        SkillSet()
        .add(CodeSkill("data", data_code()))
        .add(CodeSkill("viz", viz_code(), dependencies=["data"]))
        .add(CodeSkill("introspect", introspect_code(), dependencies=["data"]))
        .add(CodeSkill("meta", meta_code(), dependencies=["introspect"]))
        .add(CodeSkill("ml", ml_code(), dependencies=["data", "viz"]))
        .add(CodeSkill("stats", stats_code(), dependencies=["data"]))
        .add(CodeSkill("text", text_code(), dependencies=["data"]))
        .add(CodeSkill("nlp", nlp_code(), dependencies=["text"]))
        .add(CodeSkill("timeseries", timeseries_code(), dependencies=["data", "viz"]))
        .add(CodeSkill("synthetic", synthetic_code(), dependencies=["data"]))
        .add(CodeSkill("features", features_code(), dependencies=["data", "ml"]))
        .add(CodeSkill("quality", quality_code(), dependencies=["data"]))
        .add(CodeSkill("anomaly", anomaly_code(), dependencies=["data", "ml"]))
        .add(CodeSkill("report", report_code(), dependencies=["data"]))
        .add(CodeSkill("artifacts", artifacts_code(), dependencies=["data"]))
        .add(CodeSkill("export", export_code(), dependencies=["data"]))
        .add(CodeSkill("docs", docs_code()))
        .add(CodeSkill("filesystem", filesystem_code(), dependencies=["data"]))
        .add(CodeSkill("synth", synth_code(), dependencies=["data"]))
        .add(CodeSkill("network", network_code(), dependencies=["data"]))
        .add(CodeSkill("graph", graph_code(), dependencies=["data"]))
        .add(CodeSkill("simulation", simulation_code()))
        .add(CodeSkill("optimization", optimization_code()))
        .add(CodeSkill("finance", finance_code(), dependencies=["timeseries"]))
        .add(CodeSkill("experiment", experiment_code(), dependencies=["stats"]))
        .add(CodeSkill("llm_tools", llm_tools_code()))
        .add(CodeSkill("api", api_code()))
        .add(CodeSkill("web", web_code()))
        .add(CodeSkill("sql", sql_code()))
    )


def nlp_skills() -> SkillSet:
    """Text-oriented stack: data, viz, text, NLP, quality, and reporting."""
    from kerno.skills.builtins.text    import get_code as text_code
    from kerno.skills.builtins.nlp     import get_code as nlp_code
    from kerno.skills.builtins.quality import get_code as quality_code
    from kerno.skills.builtins.report  import get_code as report_code
    return (
        analysis_skills()
        .add(CodeSkill("text", text_code(), dependencies=["data"]))
        .add(CodeSkill("nlp", nlp_code(), dependencies=["text"]))
        .add(CodeSkill("quality", quality_code(), dependencies=["data"]))
        .add(CodeSkill("report", report_code(), dependencies=["data"]))
    )


def timeseries_stack() -> SkillSet:
    """Time-series stack with forecasting, stats, and reporting."""
    from kerno.skills.builtins.timeseries import get_code as timeseries_code
    from kerno.skills.builtins.report     import get_code as report_code
    return (
        analysis_skills()
        .add(CodeSkill("timeseries", timeseries_code(), dependencies=["data", "viz"]))
        .add(CodeSkill("report", report_code(), dependencies=["data"]))
    )
