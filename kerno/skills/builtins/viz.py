# kerno/skills/builtins/viz.py
"""
Built-in visualization skills.

Design:
  - Every function produces a plot AND returns the underlying data
  - All plots use Agg backend (no display required in headless environments)
  - Plots are self-labeling: titles, axis labels, legends always set
  - Color palettes are colorblind-safe by default
"""

_VIZ_SKILLS_CODE = '''
import pandas as pd
import numpy as np

# ── Backend setup (safe for headless environments) ────────────────────────────

import matplotlib as mpl
mpl.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gs
from IPython.display import display as _display

# Colorblind-safe palette (Wong, 2011)
_PALETTE = [
    '#0072B2', '#E69F00', '#009E73', '#CC79A7',
    '#56B4E9', '#D55E00', '#F0E442', '#000000',
]
mpl.rcParams.update({
    'figure.dpi':       120,
    'figure.facecolor': 'white',
    'axes.spines.top':  False,
    'axes.spines.right':False,
    'font.size':        11,
})


# ─────────────────────────────────────────────────────────────────────────────
# Core plot functions
# ─────────────────────────────────────────────────────────────────────────────

def plot_distributions(
    df:       pd.DataFrame,
    columns:  list = None,
    bins:     int  = 30,
    figsize:  tuple = None,
) -> dict:
    """
    Plot histogram + KDE for each numeric column.
    Anomalies (values beyond 3σ) are marked in red.

    Args:
        df:      Source DataFrame
        columns: Columns to plot (default: all numeric)
        bins:    Number of histogram bins
        figsize: Override figure size

    Returns:
        dict: {column: {"mean": float, "std": float, "skew": float,
                        "outlier_count": int}}
    """
    numeric = df.select_dtypes(include=np.number)
    if columns:
        numeric = numeric[[c for c in columns if c in numeric.columns]]

    if numeric.empty:
        print("No numeric columns to plot.")
        return {}

    n_cols    = min(3, len(numeric.columns))
    n_rows    = (len(numeric.columns) + n_cols - 1) // n_cols
    fig_w     = figsize[0] if figsize else max(5 * n_cols, 10)
    fig_h     = figsize[1] if figsize else max(4 * n_rows, 4)

    fig, axes = plt.subplots(n_rows, n_cols,
                              figsize=(fig_w, fig_h),
                              squeeze=False)
    fig.suptitle("Numeric Column Distributions", fontsize=14, y=1.02)

    stats = {}
    for idx, col in enumerate(numeric.columns):
        ax     = axes[idx // n_cols][idx % n_cols]
        series = numeric[col].dropna()

        mean, std = series.mean(), series.std()
        outliers  = series[(series < mean - 3 * std) | (series > mean + 3 * std)]

        ax.hist(series, bins=bins, color=_PALETTE[0], alpha=0.7,
                edgecolor='white', linewidth=0.5, label='values')

        if len(outliers) > 0:
            ax.hist(outliers, bins=bins, color='#D55E00', alpha=0.9,
                    edgecolor='white', linewidth=0.5,
                    label=f'outliers ({len(outliers)})')
            ax.legend(fontsize=9)

        ax.axvline(mean,       color='#0072B2', lw=2,   linestyle='--',
                   label=f'mean={mean:.2f}')
        ax.axvline(mean + std, color='#009E73', lw=1.2, linestyle=':')
        ax.axvline(mean - std, color='#009E73', lw=1.2, linestyle=':')

        ax.set_title(col, fontsize=11)
        ax.set_xlabel(col)
        ax.set_ylabel("Count")

        stats[col] = {
            "mean":          round(float(mean), 4),
            "std":           round(float(std),  4),
            "skew":          round(float(series.skew()), 4),
            "outlier_count": int(len(outliers)),
        }

    # Hide unused subplots
    for idx in range(len(numeric.columns), n_rows * n_cols):
        axes[idx // n_cols][idx % n_cols].set_visible(False)

    plt.tight_layout()
    _display(fig)
    plt.close(fig)

    return stats


def plot_correlation(
    df:      pd.DataFrame,
    method:  str  = 'pearson',
    annot:   bool = True,
    figsize: tuple = None,
) -> pd.DataFrame:
    """
    Plot a correlation heatmap for numeric columns.

    Args:
        df:     Source DataFrame
        method: 'pearson' | 'spearman' | 'kendall'
        annot:  Show correlation values on cells
        figsize: Override figure size

    Returns:
        Correlation DataFrame
    """
    numeric = df.select_dtypes(include=np.number)
    if numeric.shape[1] < 2:
        print("Need at least 2 numeric columns for correlation.")
        return pd.DataFrame()

    corr    = numeric.corr(method=method)
    n       = len(corr)
    size    = figsize or (max(6, n * 0.8), max(5, n * 0.8))

    fig, ax = plt.subplots(figsize=size)

    # Manual heatmap (avoids seaborn dependency)
    im = ax.imshow(corr.values, cmap='RdBu_r', vmin=-1, vmax=1, aspect='auto')
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(corr.columns, rotation=45, ha='right', fontsize=9)
    ax.set_yticklabels(corr.columns, fontsize=9)

    if annot:
        for i in range(n):
            for j in range(n):
                val  = corr.values[i, j]
                color = 'white' if abs(val) > 0.6 else 'black'
                ax.text(j, i, f'{val:.2f}', ha='center', va='center',
                        fontsize=8, color=color)

    ax.set_title(f"Correlation Matrix ({method.capitalize()})", fontsize=12)
    plt.tight_layout()
    _display(fig)
    plt.close(fig)

    # Report strong correlations
    strong = []
    for i in range(n):
        for j in range(i + 1, n):
            v = corr.values[i, j]
            if abs(v) > 0.7:
                strong.append(f"  {corr.columns[i]} ↔ {corr.columns[j]}: {v:.3f}")

    if strong:
        print(f"Strong correlations (|r| > 0.7):")
        print('\\n'.join(strong))

    return corr


def plot_timeseries(
    df:           pd.DataFrame,
    date_col:     str,
    value_cols:   list,
    resample:     str = None,
    figsize:      tuple = (14, 5),
) -> pd.DataFrame:
    """
    Plot one or more time series with trend line overlay.

    Args:
        df:          Source DataFrame
        date_col:    Name of the datetime column
        value_cols:  List of value column names to plot
        resample:    Pandas resample rule: 'D', 'W', 'M', 'Q', etc.
        figsize:     Figure size

    Returns:
        The (resampled) DataFrame that was plotted
    """
    plot_df = df.copy()
    plot_df[date_col] = pd.to_datetime(plot_df[date_col])
    plot_df = plot_df.set_index(date_col).sort_index()

    if resample:
        plot_df = plot_df[value_cols].resample(resample).mean()

    fig, ax = plt.subplots(figsize=figsize)

    for i, col in enumerate(value_cols):
        if col not in plot_df.columns:
            continue
        color  = _PALETTE[i % len(_PALETTE)]
        series = plot_df[col].dropna()

        ax.plot(series.index, series.values,
                color=color, linewidth=1.8, label=col, alpha=0.9)

        # Trend line (linear)
        if len(series) > 2:
            x = np.arange(len(series))
            z = np.polyfit(x, series.values, 1)
            p = np.poly1d(z)
            ax.plot(series.index, p(x),
                    color=color, linewidth=1, linestyle='--', alpha=0.5)

    ax.set_title(
        f"Time Series: {', '.join(value_cols)}"
        + (f" (resampled {resample})" if resample else ""),
        fontsize=12
    )
    ax.set_xlabel("Date")
    ax.legend(fontsize=10)
    plt.tight_layout()
    _display(fig)
    plt.close(fig)

    return plot_df


def plot_comparison(
    df:          pd.DataFrame,
    group_col:   str,
    value_col:   str,
    kind:        str = 'bar',
    top_n:       int = 15,
    figsize:     tuple = (12, 5),
) -> pd.DataFrame:
    """
    Compare a metric across groups (bar or box plot).

    Args:
        df:         Source DataFrame
        group_col:  Categorical column to group by
        value_col:  Numeric column to compare
        kind:       'bar' (mean ± std) | 'box' (distribution)
        top_n:      Show only top N groups by mean value
        figsize:    Figure size

    Returns:
        Summary DataFrame: group → {mean, std, count, median}
    """
    summary = (
        df.groupby(group_col)[value_col]
        .agg(['mean', 'std', 'count', 'median'])
        .sort_values('mean', ascending=False)
        .head(top_n)
    )

    fig, ax = plt.subplots(figsize=figsize)
    colors  = [_PALETTE[i % len(_PALETTE)] for i in range(len(summary))]

    if kind == 'bar':
        bars = ax.bar(summary.index, summary['mean'], color=colors,
                      yerr=summary['std'], capsize=3,
                      error_kw={'linewidth': 1, 'alpha': 0.7})
        ax.set_ylabel(f"Mean {value_col}")

        # Value labels
        for bar, val in zip(bars, summary['mean']):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() * 1.01,
                    f'{val:.1f}', ha='center', va='bottom', fontsize=8)

    elif kind == 'box':
        groups      = [df[df[group_col] == g][value_col].dropna()
                       for g in summary.index]
        bp          = ax.boxplot(groups, patch_artist=True, notch=False)
        for patch, color in zip(bp['boxes'], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        ax.set_xticklabels(summary.index)
        ax.set_ylabel(value_col)

    ax.set_xlabel(group_col)
    ax.set_title(f"{value_col} by {group_col} (top {top_n})", fontsize=12)
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    _display(fig)
    plt.close(fig)

    print(f"\n{group_col} summary (top {top_n} by mean {value_col}):")
    print(summary.round(3).to_string())

    return summary


def plot_scatter(
    df:         pd.DataFrame,
    x_col:      str,
    y_col:      str,
    color_col:  str = None,
    size_col:   str = None,
    trendline:  bool = True,
    figsize:    tuple = (10, 6),
) -> dict:
    """
    Scatter plot with optional color/size encoding and trend line.

    Args:
        df:        Source DataFrame
        x_col:     X axis column
        y_col:     Y axis column
        color_col: Column for color encoding (categorical)
        size_col:  Column for size encoding (numeric)
        trendline: Draw overall linear trend line
        figsize:   Figure size

    Returns:
        dict: {"r_squared": float, "n_points": int}
    """
    plot_df = df[[c for c in [x_col, y_col, color_col, size_col]
                  if c is not None]].copy().dropna()

    fig, ax = plt.subplots(figsize=figsize)

    sizes = None
    if size_col:
        s        = plot_df[size_col]
        sizes    = 20 + 200 * (s - s.min()) / (s.max() - s.min() + 1e-9)

    if color_col:
        groups = plot_df[color_col].unique()
        for i, grp in enumerate(groups[:8]):
            mask = plot_df[color_col] == grp
            s    = sizes[mask] if sizes is not None else 40
            ax.scatter(plot_df.loc[mask, x_col],
                       plot_df.loc[mask, y_col],
                       s=s, color=_PALETTE[i % len(_PALETTE)],
                       label=str(grp), alpha=0.7, edgecolors='white',
                       linewidths=0.3)
        ax.legend(title=color_col, fontsize=9)
    else:
        ax.scatter(plot_df[x_col], plot_df[y_col],
                   s=sizes if sizes is not None else 40,
                   color=_PALETTE[0], alpha=0.6,
                   edgecolors='white', linewidths=0.3)

    r_sq = 0.0
    if trendline and len(plot_df) > 2:
        z    = np.polyfit(plot_df[x_col], plot_df[y_col], 1)
        p    = np.poly1d(z)
        x_ln = np.linspace(plot_df[x_col].min(), plot_df[x_col].max(), 100)
        ax.plot(x_ln, p(x_ln), color='#D55E00', linewidth=2,
                linestyle='--', label='trend')

        ss_res = np.sum((plot_df[y_col] - p(plot_df[x_col])) ** 2)
        ss_tot = np.sum((plot_df[y_col] - plot_df[y_col].mean()) ** 2)
        r_sq   = 1 - ss_res / (ss_tot + 1e-12)
        ax.text(0.05, 0.95, f'R²={r_sq:.3f}', transform=ax.transAxes,
                fontsize=10, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    ax.set_xlabel(x_col)
    ax.set_ylabel(y_col)
    ax.set_title(f"{y_col} vs {x_col}", fontsize=12)
    plt.tight_layout()
    _display(fig)
    plt.close(fig)

    return {"r_squared": round(r_sq, 4), "n_points": len(plot_df)}
'''


def get_code() -> str:
    return _VIZ_SKILLS_CODE
