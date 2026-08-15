# kerno/skills/__init__.py
"""Skills subpackage: registry, bootstrap, and builtin skills."""

from kerno.skills.registry import SkillRegistry, SkillRecord
from kerno.skills.bootstrap import bootstrap

__all__ = [
    "SkillRegistry",
    "SkillRecord",
    "bootstrap",
]
