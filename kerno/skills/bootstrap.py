# kerno/skills/bootstrap.py
"""
Default skill bootstrap: loads all built-in skills.

The default set intentionally spans the complete analytical vocabulary:
wrangling, visualization, introspection, ML, statistics, text/NLP, time series,
synthetic data, feature engineering, quality, reporting, documents, graphs,
optimization, experimentation, meta-skills, web, and SQL.
"""

from kerno.kernel.runtime             import KernelRuntime
from kerno.skills.builtins.data       import get_code as data_code
from kerno.skills.builtins.viz        import get_code as viz_code
from kerno.skills.builtins.introspect import get_code as introspect_code
from kerno.skills.builtins.ml         import get_code as ml_code
from kerno.skills.builtins.stats      import get_code as stats_code
from kerno.skills.builtins.text       import get_code as text_code
from kerno.skills.builtins.timeseries import get_code as timeseries_code
from kerno.skills.builtins.synthetic  import get_code as synthetic_code
from kerno.skills.builtins.features   import get_code as features_code
from kerno.skills.builtins.quality    import get_code as quality_code
from kerno.skills.builtins.report     import get_code as report_code
from kerno.skills.builtins.web        import get_code as web_code
from kerno.skills.builtins.sql        import get_code as sql_code
from kerno.skills.builtins.llm_tools  import get_code as llm_tools_code
from kerno.skills.builtins.nlp        import get_code as nlp_code
from kerno.skills.builtins.network    import get_code as network_code
from kerno.skills.builtins.anomaly    import get_code as anomaly_code
from kerno.skills.builtins.docs       import get_code as docs_code
from kerno.skills.builtins.artifacts  import get_code as artifacts_code
from kerno.skills.builtins.simulation import get_code as simulation_code
from kerno.skills.builtins.finance    import get_code as finance_code
from kerno.skills.builtins.graph      import get_code as graph_code
from kerno.skills.builtins.optimization import get_code as optimization_code
from kerno.skills.builtins.experiment import get_code as experiment_code
from kerno.skills.builtins.meta       import get_code as meta_code
from kerno.skills.builtins.export     import get_code as export_code
from kerno.skills.builtins.filesystem import get_code as filesystem_code
from kerno.skills.builtins.synth      import get_code as synth_code
from kerno.skills.builtins.api        import get_code as api_code
from kerno.skills.registry            import SkillRegistry


_SKILL_MODULES = [
    ("data_skills",       data_code),
    ("viz_skills",        viz_code),
    ("introspect_skills", introspect_code),
    ("meta_skills",       meta_code),
    ("ml_skills",         ml_code),
    ("stats_skills",      stats_code),
    ("text_skills",       text_code),
    ("nlp_skills",        nlp_code),
    ("timeseries_skills", timeseries_code),
    ("synthetic_skills",  synthetic_code),
    ("features_skills",   features_code),
    ("quality_skills",    quality_code),
    ("anomaly_skills",    anomaly_code),
    ("report_skills",     report_code),
    ("artifacts_skills",  artifacts_code),
    ("export_skills",     export_code),
    ("docs_skills",       docs_code),
    ("filesystem_skills", filesystem_code),
    ("synth_skills",      synth_code),
    ("network_skills",    network_code),
    ("graph_skills",      graph_code),
    ("simulation_skills", simulation_code),
    ("optimization_skills", optimization_code),
    ("finance_skills",    finance_code),
    ("experiment_skills", experiment_code),
    ("llm_tools_skills",  llm_tools_code),
    ("api_skills",        api_code),
    ("web_skills",        web_code),
    ("sql_skills",        sql_code),
]


# ── Optional-dependency awareness (audit #16) ────────────────────────────────
# Each skill module's kernel-side requirements. Modules whose deps are
# missing in the kernel are SKIPPED with a warning (never crash the
# session) — a lean `pip install kerno` without kerno[data] still runs.
_SKILL_DEPS: dict[str, list[str]] = {
    "anomaly_skills": ['IPython', 'matplotlib', 'numpy', 'pandas', 'scipy', 'sklearn'],
    "api_skills": ['IPython', 'pandas', 'requests'],
    "artifacts_skills": ['IPython', 'pandas'],
    "data_skills": ['IPython', 'joblib', 'numpy', 'pandas'],
    "docs_skills": ['IPython', 'docx', 'pandas', 'pdfplumber'],
    "experiment_skills": ['IPython', 'numpy', 'pandas', 'scipy'],
    "export_skills": ['IPython', 'pandas'],
    "features_skills": ['IPython', 'matplotlib', 'numpy', 'pandas', 'sklearn'],
    "filesystem_skills": ['IPython', 'pandas'],
    "finance_skills": ['IPython', 'numpy', 'pandas'],
    "graph_skills": ['IPython', 'matplotlib', 'networkx', 'pandas'],
    "introspect_skills": ['IPython', 'numpy', 'pandas'],
    "llm_tools_skills": ['IPython', 'numpy', 'openai', 'pandas'],
    "meta_skills": ['IPython'],
    "ml_skills": ['IPython', 'matplotlib', 'numpy', 'pandas', 'sklearn'],
    "network_skills": ['IPython', 'matplotlib', 'networkx', 'pandas'],
    "nlp_skills": ['IPython', 'nltk', 'numpy', 'pandas', 'sklearn'],
    "optimization_skills": ['IPython', 'numpy', 'pandas', 'scipy'],
    "quality_skills": ['IPython', 'numpy', 'pandas'],
    "report_skills": ['IPython', 'numpy', 'pandas'],
    "simulation_skills": ['IPython', 'matplotlib', 'numpy', 'pandas', 'scipy'],
    "sql_skills": ['IPython', 'pandas', 'sqlalchemy'],
    "stats_skills": ['IPython', 'numpy', 'pandas', 'scipy'],
    "synth_skills": ['IPython', 'numpy', 'pandas'],
    "synthetic_skills": ['IPython', 'numpy', 'pandas', 'sklearn'],
    "text_skills": ['IPython', 'matplotlib', 'numpy', 'pandas', 'sklearn'],
    "timeseries_skills": ['IPython', 'matplotlib', 'numpy', 'pandas', 'statsmodels'],
    "viz_skills": ['IPython', 'matplotlib', 'numpy', 'pandas'],
    "web_skills": ['IPython', 'pandas'],
}


def _probe_missing_deps(kernel: KernelRuntime, deps: list[str]) -> set[str]:
    """Ask the KERNEL which of `deps` are importable (one batched cell).

    Returns the set of missing modules. On probe failure, assume none
    are missing so existing behavior is preserved.
    """
    deps = sorted({d for d in deps if d})
    if not deps:
        return set()
    code = (
        "import importlib.util as _ilu\n"
        f"_reqs = {deps!r}\n"
        "print([_m for _m in _reqs if _ilu.find_spec(_m) is None])\n"
    )
    out = kernel.execute(code, silent=True, timeout=30)
    if out.has_error:
        return set()
    try:
        import ast
        missing = ast.literal_eval(out.stdout.strip())
        return set(missing) if isinstance(missing, list) else set()
    except (ValueError, SyntaxError):
        return set()


def bootstrap(
    kernel:  KernelRuntime,
    include: list[str] = None,
    exclude: list[str] = None,
    skip_missing_deps: bool = True,
) -> SkillRegistry:
    """
    Load the full default skill set into a kernel.

    Args:
        kernel:  Target KernelRuntime
        include: Whitelist of skill modules to load (default: all)
        exclude: Blacklist of skill modules to skip

    Returns:
        Populated SkillRegistry
    """
    registry = SkillRegistry()

    modules = [
        (name, code_fn) for name, code_fn in _SKILL_MODULES
        if (not include or name in include)
        and (not exclude or name not in exclude)
    ]

    if skip_missing_deps:
        missing = _probe_missing_deps(kernel, [
            dep for name, _ in modules for dep in _SKILL_DEPS.get(name, [])
        ])
        if missing:
            skipped = sorted({
                name for name, _ in modules
                if any(dep in missing for dep in _SKILL_DEPS.get(name, []))
            })
            if skipped:
                import warnings
                warnings.warn(
                    "[kerno] Skipping skill modules (missing optional deps "
                    "{}): {}".format(
                        sorted(missing),
                        ", ".join(skipped),
                    )
                )
            modules = [
                (name, code_fn) for name, code_fn in modules
                if not any(
                    dep in missing for dep in _SKILL_DEPS.get(name, [])
                )
            ]

    for name, code_fn in modules:
        registry.load_code(kernel, code_fn(), name, protect=True)

    return registry


def bootstrap_minimal(kernel: KernelRuntime) -> SkillRegistry:
    """Fast startup: data + introspection only."""
    return bootstrap(kernel, include=["data_skills", "introspect_skills"])


def bootstrap_ml(kernel: KernelRuntime) -> SkillRegistry:
    """Full data science stack."""
    return bootstrap(kernel, include=[
        "data_skills", "viz_skills", "ml_skills", "stats_skills",
        "features_skills", "quality_skills", "anomaly_skills",
    ])


def bootstrap_nlp(kernel: KernelRuntime) -> SkillRegistry:
    """Text analysis stack."""
    return bootstrap(kernel, include=[
        "data_skills", "viz_skills", "text_skills", "nlp_skills",
        "quality_skills", "report_skills",
    ])


def bootstrap_timeseries(kernel: KernelRuntime) -> SkillRegistry:
    """Time series analysis stack."""
    return bootstrap(kernel, include=[
        "data_skills", "viz_skills", "timeseries_skills",
        "stats_skills", "report_skills",
    ])


def bootstrap_research(kernel: KernelRuntime) -> SkillRegistry:
    """Research stack including NLP, experiments, optimization, and self-extension."""
    return bootstrap(kernel, include=[
        "data_skills", "viz_skills", "introspect_skills", "meta_skills",
        "ml_skills", "stats_skills", "text_skills", "nlp_skills",
        "timeseries_skills", "features_skills", "quality_skills",
        "anomaly_skills", "experiment_skills", "optimization_skills",
        "report_skills", "export_skills",
    ])


def bootstrap_quant(kernel: KernelRuntime) -> SkillRegistry:
    """Quantitative finance stack."""
    return bootstrap(kernel, include=[
        "data_skills", "viz_skills", "introspect_skills",
        "stats_skills", "timeseries_skills", "finance_skills",
        "optimization_skills", "meta_skills",
    ])
