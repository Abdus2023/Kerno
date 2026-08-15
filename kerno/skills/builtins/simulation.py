# kerno/skills/builtins/simulation.py
"""
Built-in simulation and optimization skills.
"""

_SIMULATION_SKILLS_CODE = r'''
import numpy as np
import pandas as pd
from IPython.display import display as _display


def monte_carlo(sim_func: callable, n_sims: int = 10000, seed: int = 42, **kwargs) -> pd.DataFrame:
    """
    Run a user-provided simulation function many times.

    ``sim_func`` should return a dict, Series, or scalar. Results are collected
    into a DataFrame and numeric summaries/distributions are displayed.
    """
    np.random.seed(seed)
    rows = []
    step = max(1, n_sims // 10)
    for i in range(n_sims):
        try:
            result = sim_func(**kwargs)
        except TypeError:
            result = sim_func(i, **kwargs)
        if isinstance(result, pd.Series):
            result = result.to_dict()
        elif not isinstance(result, dict):
            result = {"result": result}
        rows.append(result)
        if step and i and i % step == 0:
            print(f"  Progress: {i}/{n_sims} ({100 * i / n_sims:.0f}%)")

    df = pd.DataFrame(rows)
    print(f"✓ Completed {len(df)} successful simulations")
    numeric = df.select_dtypes(include=np.number)
    if not numeric.empty:
        summary = numeric.agg(["mean", "median", "std", lambda x: x.quantile(0.025), lambda x: x.quantile(0.975)])
        summary.index = ["mean", "median", "std", "q025", "q975"]
        _display(summary.round(4))

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        col = numeric.columns[0]
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.hist(numeric[col].dropna(), bins=50, color="#0072B2", edgecolor="white", alpha=0.8)
        ax.axvline(numeric[col].mean(), color="#D55E00", linestyle="--", label="Mean")
        ax.set_title(f"Distribution of {col}")
        ax.legend()
        fig.tight_layout()
        _display(fig)
        plt.close(fig)
    return df


def linear_program(
    c: list,
    A_ub: list = None,
    b_ub: list = None,
    A_eq: list = None,
    b_eq: list = None,
    bounds: list = None,
    maximize: bool = False,
) -> dict:
    """
    Solve a linear program with scipy.optimize.linprog.
    """
    from scipy.optimize import linprog

    coefficients = np.array(c, dtype=float)
    if maximize:
        coefficients = -coefficients

    res = linprog(
        coefficients,
        A_ub=A_ub,
        b_ub=b_ub,
        A_eq=A_eq,
        b_eq=b_eq,
        bounds=bounds,
        method="highs",
    )
    result = {
        "success": bool(res.success),
        "status": str(res.message),
        "x": res.x.tolist() if res.x is not None else None,
        "fun": float(-res.fun if maximize else res.fun),
    }
    if result["success"]:
        print(f"✓ Optimization successful: objective={result['fun']:.4f}")
    else:
        print(f"✗ Optimization failed: {result['status']}")
    return result
'''


def get_code() -> str:
    return _SIMULATION_SKILLS_CODE
