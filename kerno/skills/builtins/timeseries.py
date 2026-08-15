# kerno/skills/builtins/timeseries.py
"""
Built-in time series analysis skills.

Design:
  - Decomposition, seasonality detection, forecasting, anomaly detection
  - Always visualize alongside numerical results
  - Return structured dicts/DataFrames, not just prints
  - Optional dependency on statsmodels; helpful error if missing
"""

_TIMESERIES_SKILLS_CODE = r'''
import pandas as pd
import numpy as np
from IPython.display import display as _display, HTML as _HTML

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


def ts_prepare(
    df:        pd.DataFrame,
    date_col:  str,
    value_col: str,
    freq:      str = None,
) -> pd.Series:
    """
    Prepare a time series: parse dates, set index, sort, optionally resample.

    Args:
        freq: Resample frequency ('D','W','M','Q','Y') or None.
    Returns:
        Sorted, indexed pandas Series.
    """
    if date_col not in df.columns or value_col not in df.columns:
        raise KeyError(f"Columns must include '{date_col}' and '{value_col}'")

    ts = df[[date_col, value_col]].copy()
    ts[date_col] = pd.to_datetime(ts[date_col], errors="coerce")
    ts = ts.dropna(subset=[date_col]).set_index(date_col).sort_index()
    series = pd.to_numeric(ts[value_col], errors="coerce")

    if freq:
        series = series.resample(freq).mean()
        print(f"✓ Resampled to {freq}: {len(series)} points")
    else:
        start = series.index.min()
        end   = series.index.max()
        print(f"✓ Time series: {len(series)} points, {start.date()} → {end.date()}")
    return series


def _detect_period(series: pd.Series, fallback: int = 12) -> int:
    """Heuristically choose a seasonal period from the index frequency."""
    freq = ""
    if series.index.freqstr:
        freq = series.index.freqstr
    if 'M' in freq or 'MS' in freq:
        period = 12
    elif 'Q' in freq:
        period = 4
    elif 'W' in freq:
        period = 52
    elif 'H' in freq or 'h' in freq:
        period = 24
    elif 'D' in freq:
        period = 7
    else:
        period = fallback

    # seasonal_decompose requires 2*period <= len(series)
    if 2 * period > len(series.dropna()):
        period = max(2, len(series.dropna()) // 3)
    return period


def ts_decompose(
    series: pd.Series,
    period: int = None,
    model:  str = "additive",
) -> dict:
    """
    Decompose a time series into trend, seasonal, and residual components.

    Returns:
        dict with trend, seasonal, residual (Series), period, model.
    """
    try:
        from statsmodels.tsa.seasonal import seasonal_decompose
    except ImportError as exc:
        raise ImportError(
            "statsmodels is required for ts_decompose. "
            "Install with: pip install statsmodels"
        ) from exc

    s = series.dropna()
    if period is None:
        period = _detect_period(s)
        print(f"  Auto-detected period: {period}")
    if period < 2:
        raise ValueError("period must be at least 2")
    if len(s) < 2 * period:
        raise ValueError(
            f"Need at least {2 * period} observations for period={period}, got {len(s)}"
        )

    result = seasonal_decompose(s, model=model, period=period)

    fig, axes = plt.subplots(4, 1, figsize=(14, 12), sharex=True)
    axes[0].plot(s.index, s.values, color="#0072B2")
    axes[0].set_title("Observed")
    axes[1].plot(s.index, result.trend, color="#E69F00")
    axes[1].set_title("Trend")
    axes[2].plot(s.index, result.seasonal, color="#009E73")
    axes[2].set_title(f"Seasonal (period={period})")
    axes[3].plot(s.index, result.resid, color="#CC79A7", alpha=0.75)
    axes[3].axhline(0, color="gray", linestyle="--", alpha=0.5)
    axes[3].set_title("Residual")
    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    fig.tight_layout()
    _display(fig)
    plt.close(fig)

    print(f"✓ Decomposition complete ({model}, period={period})")
    return {
        "trend":    result.trend,
        "seasonal": result.seasonal,
        "residual": result.resid,
        "period":   period,
        "model":    model,
    }


def ts_summary(series: pd.Series) -> dict:
    """
    Comprehensive time series summary statistics.

    Returns trend direction, volatility, autocorrelation, and a
    simple stationarity hint based on mean shift between halves.
    """
    s = series.dropna()
    if len(s) < 2:
        raise ValueError("Need at least 2 non-null observations")

    x = np.arange(len(s))
    slope, _intercept = np.polyfit(x, s.values, 1)
    trend_direction = ("increasing" if slope > 0
                       else "decreasing" if slope < 0
                       else "flat")

    returns    = s.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    volatility = float(returns.std()) if len(returns) > 0 else 0.0

    acf_1 = float(s.autocorr(lag=1)) if len(s) > 2 else 0.0
    if np.isnan(acf_1):
        acf_1 = 0.0

    mid      = len(s) // 2
    mean1    = s.iloc[:mid].mean() if mid > 0 else s.mean()
    mean2    = s.iloc[mid:].mean()
    mean_shift = abs(float(mean2) - float(mean1)) / (abs(float(mean1)) + 1e-12)

    result = {
        "n_points":          int(len(s)),
        "start":             str(s.index.min().date()) if hasattr(s.index.min(), 'date') else str(s.index.min()),
        "end":               str(s.index.max().date()) if hasattr(s.index.max(), 'date') else str(s.index.max()),
        "mean":              round(float(s.mean()), 4),
        "std":               round(float(s.std()), 4),
        "min":               round(float(s.min()), 4),
        "max":               round(float(s.max()), 4),
        "trend_slope":       round(float(slope), 6),
        "trend_direction":   trend_direction,
        "volatility":        round(volatility, 4),
        "autocorr_lag1":     round(acf_1, 4),
        "mean_shift_ratio":  round(mean_shift, 4),
        "likely_stationary": bool(mean_shift < 0.1),
    }

    print("Time Series Summary:")
    print(f"  Points:    {result['n_points']} ({result['start']} → {result['end']})")
    print(f"  Trend:     {result['trend_direction']} (slope={result['trend_slope']})")
    print(f"  Volatility:{result['volatility']}")
    print(f"  ACF(1):    {result['autocorr_lag1']}")
    print(f"  Stationary:{'likely' if result['likely_stationary'] else 'unlikely'}")
    return result


def ts_forecast_linear(
    series:  pd.Series,
    horizon: int = 30,
    plot:    bool = True,
) -> dict:
    """
    Simple linear forecast using a first-degree polynomial fit.

    Returns:
        dict: forecast (Series indexed by future dates), r_squared, slope, intercept.
    """
    s = series.dropna()
    if len(s) < 2:
        raise ValueError("Need at least 2 observations to forecast")

    x      = np.arange(len(s))
    coeffs = np.polyfit(x, s.values, 1)
    poly   = np.poly1d(coeffs)

    y_pred    = poly(x)
    ss_res    = float(np.sum((s.values - y_pred) ** 2))
    ss_tot    = float(np.sum((s.values - s.values.mean()) ** 2))
    r_squared = 1 - ss_res / (ss_tot + 1e-12)

    freq = pd.infer_freq(s.index) or 'D'
    future_dates = pd.date_range(
        start=s.index[-1], periods=horizon + 1, freq=freq
    )[1:]
    future_x  = np.arange(len(s), len(s) + horizon)
    forecast  = pd.Series(poly(future_x), index=future_dates, name="forecast")

    if plot:
        fig, ax = plt.subplots(figsize=(14, 5))
        ax.plot(s.index, s.values, color="#0072B2", label="Historical", alpha=0.8)
        ax.plot(s.index, y_pred, color="#E69F00", linestyle="--",
                label=f"Fit (R²={r_squared:.3f})", alpha=0.7)
        ax.plot(forecast.index, forecast.values, color="#D55E00",
                label=f"Forecast ({horizon} periods)", linewidth=2)
        ax.axvline(s.index[-1], color="gray", linestyle=":", alpha=0.5)
        ax.set_title(f"Linear Forecast (R²={r_squared:.3f})")
        ax.legend()
        fig.tight_layout()
        _display(fig)
        plt.close(fig)

    print(f"✓ Forecast: {horizon} periods, R²={r_squared:.4f}")
    return {
        "forecast":  forecast,
        "r_squared": round(r_squared, 4),
        "slope":     round(float(coeffs[0]), 6),
        "intercept": round(float(coeffs[1]), 4),
    }


def ts_detect_anomalies(
    series:    pd.Series,
    method:    str   = "zscore",
    threshold: float = 3.0,
    window:    int   = 7,
) -> pd.DataFrame:
    """
    Detect anomalies in a time series.

    method:
      - "zscore":  global z-score
      - "iqr":     Tukey fences (threshold is the IQR multiplier)
      - "rolling": rolling z-score (window controls the window size)

    Returns:
        DataFrame with columns date, value, method.
    """
    s = series.dropna()
    if method == "zscore":
        z    = (s - s.mean()) / (s.std() + 1e-12)
        mask = z.abs() > threshold
    elif method == "iqr":
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr    = q3 - q1
        lower  = q1 - threshold * iqr
        upper  = q3 + threshold * iqr
        mask   = (s < lower) | (s > upper)
    elif method == "rolling":
        roll_mean = s.rolling(window=window, center=True, min_periods=1).mean()
        roll_std  = s.rolling(window=window, center=True, min_periods=1).std()
        mask = ((s - roll_mean).abs() > threshold * roll_std.fillna(0))
    else:
        raise ValueError(f"Unknown method: {method}. Use 'zscore', 'iqr', or 'rolling'.")

    anomalies = s[mask].rename_axis("date").reset_index(name="value")
    anomalies["method"] = method

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(s.index, s.values, color="#0072B2", alpha=0.7, label="Series")
    if len(anomalies) > 0:
        ax.scatter(anomalies["date"], anomalies["value"],
                   color="#D55E00", s=60, zorder=5,
                   label=f"Anomalies ({len(anomalies)})")
    ax.set_title(f"Anomaly Detection ({method}, threshold={threshold})")
    ax.legend()
    fig.tight_layout()
    _display(fig)
    plt.close(fig)

    print(f"✓ {len(anomalies)} anomalies detected ({method}, threshold={threshold})")
    return anomalies


def ts_seasonality_check(series: pd.Series, max_period: int = 52) -> dict:
    """
    Detect the dominant seasonal period via autocorrelation.

    Returns:
        dict: best_period, acf_at_period, strength
    """
    s = series.dropna()
    if len(s) < 4:
        raise ValueError("Need at least 4 observations to check seasonality")

    max_period = min(max_period, len(s) - 2)
    acf_values = []
    for k in range(2, max_period + 1):
        val = s.autocorr(lag=k)
        acf_values.append(0.0 if pd.isna(val) else float(val))

    best_idx = int(np.argmax(acf_values))
    best_lag = best_idx + 2
    best_acf = acf_values[best_idx]
    strength = ("strong" if best_acf > 0.5
                else "moderate" if best_acf > 0.3
                else "weak")

    print("Seasonality check:")
    print(f"  Best period: {best_lag} (ACF={best_acf:.3f})")
    print(f"  Strength:    {strength}")
    return {
        "best_period":   int(best_lag),
        "acf_at_period": round(float(best_acf), 4),
        "strength":      strength,
    }
'''


def get_code() -> str:
    """Return the source code string for these skills."""
    return _TIMESERIES_SKILLS_CODE
