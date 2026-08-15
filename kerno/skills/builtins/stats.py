# kerno/skills/builtins/stats.py
"""
Built-in statistical analysis skills.

Design principles:
  - Always report effect sizes alongside p-values
  - Always check assumptions before applying a test
  - Confidence intervals on everything
  - Plain-English interpretations alongside numbers
"""

_STATS_SKILLS_CODE = '''
import pandas as pd
import numpy as _np
from IPython.display import display as _display, HTML as _HTML


# ─── Descriptive ─────────────────────────────────────────────────────────────

def describe_distribution(series: pd.Series) -> dict:
    """
    Full distributional description of a numeric series.
    Includes: moments, quantiles, normality tests, outlier count.

    Returns:
        dict with all statistics
    """
    from scipy import stats as _stats

    s = series.dropna()

    # Normality tests
    _, shapiro_p = _stats.shapiro(s[:5000]) if len(s) >= 3 else (None, None)
    _, ks_p      = _stats.kstest(s, "norm",
                       args=(s.mean(), s.std())) if len(s) >= 5 else (None, None)

    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr    = q3 - q1
    n_low  = int((s < q1 - 1.5 * iqr).sum())
    n_high = int((s > q3 + 1.5 * iqr).sum())

    result = {
        "n":          len(s),
        "mean":       round(float(s.mean()),   4),
        "median":     round(float(s.median()), 4),
        "std":        round(float(s.std()),    4),
        "skewness":   round(float(s.skew()),   4),
        "kurtosis":   round(float(s.kurtosis()), 4),
        "min":        round(float(s.min()),    4),
        "q1":         round(float(q1),         4),
        "q3":         round(float(q3),         4),
        "max":        round(float(s.max()),    4),
        "iqr":        round(float(iqr),        4),
        "n_outliers": n_low + n_high,
        "shapiro_p":  round(float(shapiro_p), 4) if shapiro_p else None,
        "is_normal":  (shapiro_p > 0.05)          if shapiro_p else None,
    }

    # Interpretation
    interp = []
    if abs(result["skewness"]) > 1:
        direction = "right" if result["skewness"] > 0 else "left"
        interp.append("Heavily {}-skewed (skew={:.2f})".format(direction, result["skewness"]))
    if result.get("is_normal") is False:
        interp.append("Not normally distributed (Shapiro p < 0.05)")
    elif result.get("is_normal"):
        interp.append("Approximately normally distributed")
    if result["n_outliers"] > 0:
        pct = result["n_outliers"] / len(s) * 100
        interp.append("{} outliers ({:.1f}% of values)".format(result["n_outliers"], pct))

    result["interpretation"] = interp
    for line in interp:
        print("  → {}".format(line))

    return result


# ─── Hypothesis Testing ───────────────────────────────────────────────────────

def ttest(
    group_a:     pd.Series,
    group_b:     pd.Series,
    alpha:       float = 0.05,
    paired:      bool  = False,
    alternative: str   = "two-sided",
) -> dict:
    """
    Independent or paired t-test with effect size (Cohen's d).

    Args:
        group_a:     First group
        group_b:     Second group
        alpha:       Significance level (default: 0.05)
        paired:      If True, perform paired t-test
        alternative: "two-sided" | "less" | "greater"

    Returns:
        dict: statistic, p_value, cohens_d, significant,
              mean_diff, ci_95, interpretation
    """
    from scipy import stats as _stats

    a, b = group_a.dropna().values, group_b.dropna().values

    if paired:
        if len(a) != len(b):
            raise ValueError("Paired t-test requires equal group sizes")
        stat, p = _stats.ttest_rel(a, b, alternative=alternative)
    else:
        stat, p = _stats.ttest_ind(a, b, equal_var=False, alternative=alternative)

    # Cohen's d
    pooled_std = _np.sqrt((_np.std(a, ddof=1)**2 + _np.std(b, ddof=1)**2) / 2)
    cohens_d   = (a.mean() - b.mean()) / (pooled_std + 1e-12)

    # 95% CI on mean difference
    diff     = a.mean() - b.mean()
    se_diff  = _np.sqrt(_np.var(a, ddof=1)/len(a) + _np.var(b, ddof=1)/len(b))
    ci_margin= 1.96 * se_diff

    effect_label = (
        "negligible" if abs(cohens_d) < 0.2 else
        "small"      if abs(cohens_d) < 0.5 else
        "medium"     if abs(cohens_d) < 0.8 else
        "large"
    )

    result = {
        "test":        "paired_ttest" if paired else "independent_ttest",
        "statistic":   round(float(stat), 4),
        "p_value":     round(float(p),    6),
        "significant": bool(p < alpha),
        "alpha":       alpha,
        "cohens_d":    round(float(cohens_d), 4),
        "effect_size": effect_label,
        "mean_a":      round(float(a.mean()), 4),
        "mean_b":      round(float(b.mean()), 4),
        "mean_diff":   round(float(diff),     4),
        "ci_95":       (round(diff - ci_margin, 4), round(diff + ci_margin, 4)),
        "n_a":         len(a),
        "n_b":         len(b),
    }

    sig_str = "✓ SIGNIFICANT" if result["significant"] else "✗ not significant"
    print("t-test: t={:.3f}, p={:.4f}  {} (α={})".format(stat, p, sig_str, alpha))
    print("  Effect size: Cohen's d={:.3f} ({})".format(cohens_d, effect_label))
    print("  Mean diff: {:.4f}  95% CI: {}".format(diff, result["ci_95"]))

    result["interpretation"] = (
        "The difference between group A (mean={:.4f}) "
        "and group B (mean={:.4f}) is "
        "{} "
        "(p={:.4f}, Cohen's d={:.3f} [{} effect]).".format(
            result["mean_a"], result["mean_b"],
            "statistically significant" if result["significant"] else "not significant",
            p, cohens_d, effect_label
        )
    )
    print("  {}".format(result["interpretation"]))
    return result


def anova(*groups, alpha: float = 0.05, names: list = None) -> dict:
    """
    One-way ANOVA with post-hoc Tukey HSD.

    Args:
        *groups:  Two or more pandas Series
        alpha:    Significance level
        names:    Group names for display

    Returns:
        dict: f_statistic, p_value, eta_squared, pairwise_comparisons
    """
    from scipy import stats as _stats
    from itertools import combinations as _combos

    cleaned = [g.dropna().values for g in groups]
    names   = names or ["Group_{}".format(i+1) for i in range(len(cleaned))]

    stat, p = _stats.f_oneway(*cleaned)

    # Eta squared (effect size)
    all_vals   = _np.concatenate(cleaned)
    grand_mean = all_vals.mean()
    ss_between = sum(len(g) * (g.mean() - grand_mean)**2 for g in cleaned)
    ss_total   = sum((v - grand_mean)**2 for v in all_vals)
    eta_sq     = ss_between / (ss_total + 1e-12)

    # Pairwise post-hoc (Tukey-like approximation)
    pairwise = []
    for (i, g1), (j, g2) in _combos(enumerate(cleaned), 2):
        _, p_ij = _stats.ttest_ind(g1, g2, equal_var=False)
        # Bonferroni correction
        n_comparisons = len(list(_combos(range(len(cleaned)), 2)))
        p_corrected   = min(1.0, p_ij * n_comparisons)
        pairwise.append({
            "group_a":    names[i],
            "group_b":    names[j],
            "p_value":    round(float(p_corrected), 6),
            "significant": bool(p_corrected < alpha),
            "mean_diff":  round(float(g1.mean() - g2.mean()), 4),
        })

    result = {
        "test":        "one_way_anova",
        "f_statistic": round(float(stat), 4),
        "p_value":     round(float(p),    6),
        "significant": bool(p < alpha),
        "eta_squared": round(float(eta_sq), 4),
        "effect_size": (
            "small"  if eta_sq < 0.06 else
            "medium" if eta_sq < 0.14 else
            "large"
        ),
        "group_means": {names[i]: round(float(g.mean()), 4) for i, g in enumerate(cleaned)},
        "pairwise":    pairwise,
    }

    sig_str = "✓ SIGNIFICANT" if result["significant"] else "✗ not significant"
    print("ANOVA: F={:.3f}, p={:.4f}  {}".format(stat, p, sig_str))
    print("  Effect size: η²={:.3f} ({})".format(eta_sq, result["effect_size"]))
    sig_pairs = ["{} vs {}".format(pw["group_a"], pw["group_b"]) for pw in pairwise if pw["significant"]]
    if sig_pairs:
        print("  Significant pairs (Bonferroni): {}".format(sig_pairs))

    return result


def chi_square(
    observed:  pd.DataFrame,
    alpha:     float = 0.05,
) -> dict:
    """
    Chi-square test of independence on a contingency table.

    Args:
        observed: Contingency table (DataFrame or 2D array)
        alpha:    Significance level

    Returns:
        dict: chi2, pvalue, dof, cramers_v, significant
    """
    from scipy.stats import chi2_contingency as _chi2

    chi2, p, dof, expected = _chi2(observed)

    # Cramér's V (effect size for chi-square)
    n       = observed.values.sum()
    min_dim = min(observed.shape) - 1
    v       = _np.sqrt(chi2 / (n * min_dim)) if n * min_dim > 0 else 0

    result = {
        "test":        "chi_square",
        "chi2":        round(float(chi2), 4),
        "p_value":     round(float(p),    6),
        "dof":         int(dof),
        "significant": bool(p < alpha),
        "cramers_v":   round(float(v), 4),
        "effect_size": (
            "negligible" if v < 0.1 else
            "small"      if v < 0.3 else
            "medium"     if v < 0.5 else
            "large"
        ),
    }

    sig_str = "✓ SIGNIFICANT" if result["significant"] else "✗ not significant"
    print("χ²={:.3f}, p={:.4f}, dof={}  {}".format(chi2, p, dof, sig_str))
    print("  Cramér's V={:.3f} ({})".format(v, result["effect_size"]))
    return result


# ─── Confidence Intervals ─────────────────────────────────────────────────────

def bootstrap_ci(
    data:        pd.Series,
    statistic:   callable  = _np.mean,
    n_bootstrap: int       = 2000,
    alpha:       float     = 0.05,
    random_state: int      = 42,
) -> dict:
    """
    Bootstrap confidence interval for any statistic.

    More robust than parametric CIs for non-normal distributions.

    Args:
        data:       Data series
        statistic:  Function to compute (default: np.mean)
        n_bootstrap: Number of bootstrap samples
        alpha:      Significance level (0.05 → 95% CI)

    Returns:
        dict: point_estimate, ci_low, ci_high, ci_width, se
    """
    _np.random.seed(random_state)
    clean = data.dropna().values

    estimates = [
        statistic(_np.random.choice(clean, size=len(clean), replace=True))
        for _ in range(n_bootstrap)
    ]
    estimates = _np.array(estimates)

    point = statistic(clean)
    low   = float(_np.percentile(estimates, 100 * alpha / 2))
    high  = float(_np.percentile(estimates, 100 * (1 - alpha / 2)))

    result = {
        "point_estimate": round(float(point), 6),
        "ci_low":         round(low, 6),
        "ci_high":        round(high, 6),
        "ci_width":       round(high - low, 6),
        "se":             round(float(estimates.std()), 6),
        "confidence":     "{:.0f}%".format(100 * (1 - alpha)),
        "n_bootstrap":    n_bootstrap,
    }

    print("Bootstrap CI ({}, n={:,})".format(result["confidence"], n_bootstrap))
    print("  Estimate: {:.6f}".format(point))
    print("  CI: [{:.6f}, {:.6f}]  (width={:.6f})".format(low, high, result["ci_width"]))
    return result


# ─── Correlation ─────────────────────────────────────────────────────────────

def correlate(
    x:      pd.Series,
    y:      pd.Series,
    method: str   = "auto",
    alpha:  float = 0.05,
) -> dict:
    """
    Correlation analysis with significance test and effect size.

    Args:
        x, y:   Two numeric series (aligned by index)
        method: "pearson" | "spearman" | "kendall" | "auto"
                Auto selects spearman if either variable is non-normal
        alpha:  Significance level

    Returns:
        dict: r, p_value, n, method, significant, interpretation
    """
    from scipy import stats as _stats

    xy   = pd.DataFrame({"x": x, "y": y}).dropna()
    xv   = xy["x"].values
    yv   = xy["y"].values

    if method == "auto":
        _, px = _stats.shapiro(xv[:5000])
        _, py = _stats.shapiro(yv[:5000])
        method = "pearson" if (px > 0.05 and py > 0.05) else "spearman"

    if method == "pearson":
        r, p = _stats.pearsonr(xv, yv)
    elif method == "spearman":
        r, p = _stats.spearmanr(xv, yv)
    elif method == "kendall":
        r, p = _stats.kendalltau(xv, yv)
    else:
        raise ValueError("Unknown method: {}".format(method))

    strength = (
        "negligible" if abs(r) < 0.1 else
        "weak"       if abs(r) < 0.3 else
        "moderate"   if abs(r) < 0.5 else
        "strong"     if abs(r) < 0.7 else
        "very strong"
    )
    direction = "positive" if r > 0 else "negative"

    result = {
        "r":           round(float(r), 6),
        "p_value":     round(float(p), 6),
        "n":           len(xy),
        "method":      method,
        "significant": bool(p < alpha),
        "strength":    strength,
        "direction":   direction,
    }

    sig_str = "✓ SIGNIFICANT" if result["significant"] else "✗ not significant"
    print("{} r={:.4f}, p={:.4f}  {}".format(method.capitalize(), r, p, sig_str))
    print("  {} {} correlation (n={:,})".format(strength.capitalize(), direction, len(xy)))
    result["interpretation"] = (
        "{} {} {} correlation "
        "(r={:.4f}, p={:.4f}).".format(
            strength.capitalize(), direction, method, r, p
        )
    )
    return result
'''


def get_code() -> str:
    return _STATS_SKILLS_CODE
