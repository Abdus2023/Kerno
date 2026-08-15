# kerno/skills/bootstrap.py
"""
Default skill bootstrap: loads all built-in skills into a kernel.

This is the default skills_path for kerno.run() if none is provided.
"""

from kerno.kernel.runtime import KernelRuntime
from kerno.skills.builtins.data import get_code as data_skills
from kerno.skills.registry import SkillRegistry


def bootstrap(kernel: KernelRuntime) -> SkillRegistry:
    """
    Load the default skill set into a kernel.

    Loads:
      - Data skills: load, profile, clean_nulls, checkpoint

    Returns:
        A populated SkillRegistry
    """
    registry = SkillRegistry()
    registry.load_code(kernel, data_skills(), "data_skills", protect=True)
    return registry
