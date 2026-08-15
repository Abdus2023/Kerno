# kerno/skills/bootstrap.py
"""
Default skill bootstrap: loads all built-in skills.
"""

from kerno.kernel.runtime          import KernelRuntime
from kerno.skills.builtins.data    import get_code as data_code
from kerno.skills.builtins.viz     import get_code as viz_code
from kerno.skills.builtins.introspect import get_code as introspect_code
from kerno.skills.builtins.web     import get_code as web_code
from kerno.skills.builtins.sql     import get_code as sql_code
from kerno.skills.builtins.ml      import get_code as ml_code
from kerno.skills.builtins.stats   import get_code as stats_code
from kerno.skills.registry         import SkillRegistry


_SKILL_MODULES = [
    ("data_skills",       data_code),
    ("viz_skills",        viz_code),
    ("introspect_skills", introspect_code),
    ("ml_skills",         ml_code),
    ("stats_skills",      stats_code),
    ("web_skills",        web_code),
    ("sql_skills",        sql_code),
]


def bootstrap(
    kernel:  KernelRuntime,
    include: list[str] = None,
    exclude: list[str] = None,
) -> SkillRegistry:
    """
    Load the full default skill set into a kernel.

    Args:
        kernel:  Target KernelRuntime
        include: Whitelist of skill modules to load (default: all)
        exclude: Blacklist of skill modules to skip

    Skill modules:
        data_skills       load, profile, clean_nulls, checkpoint
        viz_skills        plot_distributions, plot_correlation, ...
        introspect_skills what_exists, schema_of, diagnose, ...
        ml_skills         split, train_classifier, evaluate_classifier, ...
        stats_skills      ttest, anova, chi_square, bootstrap_ci, ...
        web_skills        fetch, fetch_json, extract_tables
        sql_skills        connect, query, list_tables, schema_of_table

    Returns:
        Populated SkillRegistry
    """
    registry = SkillRegistry()

    for name, code_fn in _SKILL_MODULES:
        if include and name not in include:
            continue
        if exclude and name in exclude:
            continue
        registry.load_code(kernel, code_fn(), name, protect=True)

    return registry


def bootstrap_minimal(kernel: KernelRuntime) -> SkillRegistry:
    """Load only data + introspection skills. Fast startup."""
    return bootstrap(kernel, include=["data_skills", "introspect_skills"])


def bootstrap_ml(kernel: KernelRuntime) -> SkillRegistry:
    """Load data + viz + ML + stats skills. Full data science stack."""
    return bootstrap(kernel, include=[
        "data_skills", "viz_skills", "ml_skills", "stats_skills"
    ])
