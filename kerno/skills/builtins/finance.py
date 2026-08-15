# kerno/skills/builtins/finance.py
"""
Built-in quantitative finance skills.
"""

_FINANCE_SKILLS_CODE = r'''
import numpy as np
import pandas as pd
from IPython.display import display as _display, HTML as _HTML


def calculate_returns(prices: pd.Series, method: str = "log") -> pd.Series:
    """
    Calculate simple or log returns from a price series.
    """
    if method == "simple":
        returns = prices.pct_change()
    elif method == "log":
        returns = np.log(prices / prices.shift(1))
    else:
        raise ValueError("method must be 'simple' or 'log'")
    return returns.dropna()


def rolling_metrics(returns: pd.Series, window: int = 252, risk_free_rate: float = 0.0) -> pd.DataFrame:
    """
    Compute rolling annualized return, volatility, and Sharpe ratio.
    """
    ann = 252
    rolling_return = returns.rolling(window).mean() * ann
    rolling_volatility = returns.rolling(window).std() * np.sqrt(ann)
    rolling_sharpe = (rolling_return - risk_free_rate) / rolling_volatility.replace(0, np.nan)
    metrics = pd.DataFrame({
        "rolling_return": rolling_return,
        "rolling_volatility": rolling_volatility,
        "rolling_sharpe": rolling_sharpe,
    }).dropna()
    _display(_HTML("<b>Latest rolling metrics</b>"))
    _display(metrics.tail(1).T)
    return metrics


def max_drawdown(returns: pd.Series) -> dict:
    """
    Compute current and maximum drawdown for a return series.
    """
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    idxmin = drawdown.idxmin()
    result = {
        "max_drawdown": f"{drawdown.min():.2%}",
        "max_drawdown_date": str(idxmin),
        "current_drawdown": f"{drawdown.iloc[-1]:.2%}",
    }
    _display(pd.DataFrame([result]).T)
    return result


def capm_beta(asset_returns: pd.Series, market_returns: pd.Series) -> float:
    """
    Calculate CAPM beta of an asset relative to a market benchmark.
    """
    aligned = pd.concat([asset_returns, market_returns], axis=1).dropna()
    if aligned.shape[0] < 2:
        raise ValueError("Need at least two aligned return observations")
    covariance = aligned.iloc[:, 0].cov(aligned.iloc[:, 1])
    variance = aligned.iloc[:, 1].var()
    beta = float(covariance / variance) if variance else 0.0
    _display(_HTML(f"<b>CAPM Beta:</b> {beta:.4f}"))
    return beta
'''


def get_code() -> str:
    return _FINANCE_SKILLS_CODE
