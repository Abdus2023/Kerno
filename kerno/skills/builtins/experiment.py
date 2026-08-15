# kerno/skills/builtins/experiment.py
"""
Built-in experimentation and A/B testing skills.
"""

_EXPERIMENT_SKILLS_CODE = r'''
import numpy as np
import pandas as pd
from IPython.display import display as _display, HTML as _HTML


def power_analysis(baseline_rate: float, mde: float, alpha: float = 0.05,
                   power: float = 0.80) -> dict:
    """
    Sample-size calculation for a two-proportion A/B test.
    """
    from scipy.stats import norm

    z_alpha = norm.ppf(1 - alpha / 2)
    z_beta = norm.ppf(power)
    p1 = baseline_rate
    p2 = baseline_rate + mde
    n = ((z_alpha * np.sqrt(2 * p1 * (1 - p1))
          + z_beta * np.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2) / (p2 - p1) ** 2
    result = {
        "baseline_rate": baseline_rate,
        "mde": mde,
        "required_n_per_variant": int(np.ceil(n)),
        "total_required_n": int(np.ceil(2 * n)),
    }
    _display(pd.DataFrame([result]).T)
    return result


def ab_test(control, variant, metric_type: str = "continuous") -> dict:
    """
    Run Welch's t-test or two-proportion z-test.
    """
    from scipy import stats

    control = pd.Series(control).dropna()
    variant = pd.Series(variant).dropna()
    if metric_type == "continuous":
        stat, p_value = stats.ttest_ind(variant, control, equal_var=False)
        test_name = "Welch's t-test"
        absolute_effect = float(variant.mean() - control.mean())
        relative_effect = absolute_effect / control.mean() if control.mean() != 0 else float("nan")
    elif metric_type == "binary":
        p1, p2 = float(control.mean()), float(variant.mean())
        n1, n2 = len(control), len(variant)
        p_pool = (control.sum() + variant.sum()) / (n1 + n2)
        se = np.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
        stat = (p2 - p1) / se if se > 0 else 0.0
        p_value = 2 * (1 - stats.norm.cdf(abs(stat)))
        test_name = "Two-proportion z-test"
        absolute_effect = p2 - p1
        relative_effect = (p2 - p1) / p1 if p1 else float("nan")
    else:
        raise ValueError("metric_type must be 'continuous' or 'binary'")

    result = {
        "test": test_name,
        "control_mean": float(control.mean()),
        "variant_mean": float(variant.mean()),
        "absolute_effect": float(absolute_effect),
        "relative_effect_pct": f"{relative_effect * 100:.2f}%",
        "statistic": float(stat),
        "p_value": float(p_value),
        "significant_at_0.05": bool(p_value < 0.05),
    }
    _display(pd.DataFrame([result]).T)
    return result
'''


def get_code() -> str:
    return _EXPERIMENT_SKILLS_CODE
