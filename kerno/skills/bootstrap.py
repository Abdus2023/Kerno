# kerno/skills/bootstrap.py
"""
Default skill bootstrap: loads all built-in skills.

Skill modules:
    data_skills        load, profile, clean_nulls, checkpoint
    viz_skills         plot_distributions, plot_correlation, plot_timeseries,
                       plot_comparison, plot_scatter
    introspect_skills  what_exists, schema_of, dependencies_of, memory_report, diagnose
    ml_skills          split, train_classifier, train_regressor, evaluate_classifier,
                       evaluate_regressor, cross_validate_model, feature_importance, preprocess
    stats_skills       describe_distribution, ttest, anova, chi_square, bootstrap_ci, correlate
    text_skills        text_stats, word_frequencies, clean_text, ngrams,
                       sentiment_score, extract_emails, extract_hashtags, extract_keywords
    timeseries_skills  ts_prepare, ts_decompose, ts_summary, ts_forecast_linear,
                       ts_detect_anomalies, ts_seasonality_check
    synthetic_skills   generate_sales, generate_customers, generate_classification,
                       generate_regression, generate_timeseries, generate_transactions
    features_skills    auto_encode, add_date_features, add_interaction_features,
                       add_aggregation_features, add_lag_features, select_features
    quality_skills     quality_report, detect_duplicates, detect_outliers,
                       validate_schema, detect_drift
    report_skills      generate_report, summary_table, comparison_table,
                       executive_summary, data_dictionary, save_results
    web_skills         fetch, fetch_json, extract_tables, read_csv_url
    sql_skills         connect, connect_sqlite, query, list_tables,
                       schema_of_table, execute_sql, table_stats
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
from kerno.skills.registry            import SkillRegistry


_SKILL_MODULES = [
    ("data_skills",       data_code),
    ("viz_skills",        viz_code),
    ("introspect_skills", introspect_code),
    ("ml_skills",         ml_code),
    ("stats_skills",      stats_code),
    ("text_skills",       text_code),
    ("timeseries_skills", timeseries_code),
    ("synthetic_skills",  synthetic_code),
    ("features_skills",   features_code),
    ("quality_skills",    quality_code),
    ("report_skills",     report_code),
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
    """Fast startup: data + introspection only."""
    return bootstrap(kernel, include=["data_skills", "introspect_skills"])


def bootstrap_ml(kernel: KernelRuntime) -> SkillRegistry:
    """Full data science stack."""
    return bootstrap(kernel, include=[
        "data_skills", "viz_skills", "ml_skills", "stats_skills",
        "features_skills", "quality_skills",
    ])


def bootstrap_nlp(kernel: KernelRuntime) -> SkillRegistry:
    """Text analysis stack."""
    return bootstrap(kernel, include=[
        "data_skills", "viz_skills", "text_skills", "quality_skills", "report_skills",
    ])


def bootstrap_timeseries(kernel: KernelRuntime) -> SkillRegistry:
    """Time series analysis stack."""
    return bootstrap(kernel, include=[
        "data_skills", "viz_skills", "timeseries_skills",
        "stats_skills", "report_skills",
    ])
