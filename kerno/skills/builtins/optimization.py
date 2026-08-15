# kerno/skills/builtins/optimization.py
"""
Built-in optimization and operations-research skills.
"""

_OPTIMIZATION_SKILLS_CODE = r'''
import numpy as np
import pandas as pd
from IPython.display import display as _display


def solve_assignment(cost_matrix: list, row_names: list = None, col_names: list = None) -> dict:
    """
    Solve an assignment problem using scipy.optimize.linear_sum_assignment.
    """
    from scipy.optimize import linear_sum_assignment

    costs = np.asarray(cost_matrix, dtype=float)
    row_ind, col_ind = linear_sum_assignment(costs)
    rows = []
    total = 0.0
    for r, c in zip(row_ind, col_ind):
        value = float(costs[r, c])
        total += value
        rows.append({
            "Agent": row_names[r] if row_names else f"Row_{r}",
            "Task": col_names[c] if col_names else f"Col_{c}",
            "Cost": value,
        })
    df = pd.DataFrame(rows)
    _display(df)
    print(f"✓ Optimal assignment total cost: {total:.2f}")
    return {"total_cost": total, "assignments": df}


def optimize_portfolio(returns_df: pd.DataFrame, target_return: float = 0.1,
                       risk_free_rate: float = 0.02) -> dict:
    """
    Maximize Sharpe ratio over long-only fully-invested portfolio weights.
    """
    from scipy.optimize import minimize

    mu = returns_df.mean() * 252
    cov = returns_df.cov() * 252
    n = len(mu)

    def negative_sharpe(weights):
        port_return = float(np.dot(weights, mu))
        port_vol = float(np.sqrt(weights.T @ cov.values @ weights))
        return -(port_return - risk_free_rate) / (port_vol + 1e-12)

    result = minimize(
        negative_sharpe,
        np.repeat(1 / n, n),
        bounds=[(0, 1)] * n,
        constraints={"type": "eq", "fun": lambda w: np.sum(w) - 1},
        method="SLSQP",
    )
    if not result.success:
        print(f"✗ Optimization failed: {result.message}")
        return {}

    weights = pd.Series(result.x, index=returns_df.columns, name="Weight")
    try:
        _display(weights.to_frame().style.format("{:.2%}"))
    except Exception:
        _display(weights.to_frame())
    return {"weights": weights.to_dict(), "sharpe": -float(result.fun)}
'''


def get_code() -> str:
    return _OPTIMIZATION_SKILLS_CODE
