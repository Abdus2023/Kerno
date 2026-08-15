# kerno/skills/builtins/synthetic.py
"""
Built-in synthetic data generation skills.

Essential for testing, demos, and benchmarking.
All generators produce realistic distributions, not uniform random noise.
"""

_SYNTHETIC_SKILLS_CODE = r'''
import pandas as pd
import numpy as np
from IPython.display import display as _display, HTML as _HTML


def generate_sales(
    n:          int  = 1000,
    start_date: str  = "2023-01-01",
    n_regions:  int  = 4,
    n_products: int  = 5,
    seed:       int  = 42,
) -> pd.DataFrame:
    """
    Generate realistic synthetic sales data with annual seasonality.

    Columns: date, region, product, revenue, units, discount_pct.
    """
    np.random.seed(seed)
    dates = pd.date_range(start=start_date, periods=n, freq="D")

    regions  = [f"Region_{chr(65 + i)}" for i in range(n_regions)]
    products = [f"Product_{chr(65 + i)}" for i in range(n_products)]

    month    = dates.month
    seasonal = 1 + 0.3 * np.sin(2 * np.pi * (month - 1) / 12)

    revenue  = np.random.exponential(1000, n) * seasonal
    units    = np.random.randint(1, 50, n)
    discount = np.round(
        np.random.choice([0, 5, 10, 15, 20], n, p=[0.5, 0.2, 0.15, 0.1, 0.05]),
        1,
    )

    df = pd.DataFrame({
        "date":         dates,
        "region":       np.random.choice(regions, n),
        "product":      np.random.choice(products, n),
        "revenue":      np.round(revenue, 2),
        "units":        units,
        "discount_pct": discount,
    })

    print(f"✓ Generated {n:,} sales records "
          f"({len(regions)} regions, {len(products)} products)")
    _display(df.head(5))
    return df


def generate_customers(
    n:          int   = 500,
    churn_rate: float = 0.15,
    seed:       int   = 42,
) -> pd.DataFrame:
    """
    Generate synthetic customer data for churn analysis.

    Columns: customer_id, age, tenure_months, monthly_spend,
             support_tickets, plan_type, churn_flag.
    """
    np.random.seed(seed)

    age     = np.clip(np.random.normal(42, 14, n), 18, 80).astype(int)
    tenure  = np.clip(np.random.exponential(24, n), 0, 120).astype(int)
    spend   = np.round(np.random.lognormal(3.5, 0.8, n), 2)
    tickets = np.random.poisson(1.5, n)
    plan    = np.random.choice(["Basic", "Standard", "Premium"], n, p=[0.4, 0.4, 0.2])

    churn_prob = (
        0.1
        + 0.02 * tickets
        - 0.001 * tenure
        + 0.0001 * spend
    )
    churn_prob = np.clip(churn_prob, 0.02, 0.6)
    churn = (np.random.random(n) < churn_prob).astype(int)

    df = pd.DataFrame({
        "customer_id":     [f"CUST_{i:05d}" for i in range(n)],
        "age":             age,
        "tenure_months":   tenure,
        "monthly_spend":   spend,
        "support_tickets": tickets,
        "plan_type":       plan,
        "churn_flag":      churn,
    })

    actual_rate = df["churn_flag"].mean()
    print(f"✓ Generated {n:,} customers (churn rate: {actual_rate:.1%})")
    _display(df.head(5))
    return df


def generate_classification(
    n_samples:  int   = 1000,
    n_features: int   = 10,
    n_classes:  int   = 2,
    noise:      float = 0.1,
    seed:       int   = 42,
) -> pd.DataFrame:
    """
    Generate a synthetic classification dataset.

    Returns a DataFrame with feature_0..feature_{n-1} plus a target column.
    """
    from sklearn.datasets import make_classification

    n_informative = max(1, min(n_features - 1, n_classes * 3))
    n_redundant   = max(0, n_features - n_informative - 1)

    X, y = make_classification(
        n_samples     = n_samples,
        n_features    = n_features,
        n_classes     = n_classes,
        n_informative = n_informative,
        n_redundant   = n_redundant,
        flip_y        = noise,
        random_state  = seed,
    )

    cols = [f"feature_{i}" for i in range(n_features)]
    df   = pd.DataFrame(X, columns=cols)
    df["target"] = y

    print(f"✓ Generated {n_samples} samples, {n_features} features, {n_classes} classes")
    print(f"  Class distribution: {df['target'].value_counts().to_dict()}")
    return df


def generate_regression(
    n_samples:  int   = 1000,
    n_features: int   = 8,
    noise:      float = 10.0,
    seed:       int   = 42,
) -> pd.DataFrame:
    """
    Generate a synthetic regression dataset.

    Returns a DataFrame with feature columns plus a numeric target column.
    """
    from sklearn.datasets import make_regression

    n_informative = max(1, min(n_features, n_features))
    X, y = make_regression(
        n_samples     = n_samples,
        n_features    = n_features,
        n_informative = n_informative,
        noise         = noise,
        random_state  = seed,
    )

    cols = [f"feature_{i}" for i in range(n_features)]
    df   = pd.DataFrame(X, columns=cols)
    df["target"] = np.round(y, 2)

    print(f"✓ Generated {n_samples} samples, {n_features} features")
    return df


def generate_timeseries(
    n_days:      int   = 730,
    trend:       float = 0.05,
    seasonality: float = 20.0,
    noise:       float = 5.0,
    start_date:  str   = "2023-01-01",
    seed:        int   = 42,
) -> pd.DataFrame:
    """
    Generate synthetic time series with trend + annual + weekly seasonality + noise.

    Columns: date, value, trend_component, seasonal_component.
    """
    np.random.seed(seed)
    dates = pd.date_range(start=start_date, periods=n_days, freq="D")
    t     = np.arange(n_days)

    trend_comp    = trend * t
    seasonal_comp = seasonality * np.sin(2 * np.pi * t / 365.25)
    weekly_comp   = (seasonality / 4) * np.sin(2 * np.pi * t / 7)
    noise_comp    = np.random.normal(0, noise, n_days)

    value = 100 + trend_comp + seasonal_comp + weekly_comp + noise_comp

    df = pd.DataFrame({
        "date":               dates,
        "value":              np.round(value, 2),
        "trend_component":    np.round(trend_comp, 2),
        "seasonal_component": np.round(seasonal_comp + weekly_comp, 2),
    })

    print(f"✓ Generated {n_days} days of time series data")
    return df


def generate_transactions(
    n:          int   = 2000,
    fraud_rate: float = 0.03,
    seed:       int   = 42,
) -> pd.DataFrame:
    """
    Generate synthetic financial transactions for fraud detection.

    Columns: transaction_id, timestamp, amount, category,
             account_age_days, hour, is_fraud.
    """
    np.random.seed(seed)

    timestamps = pd.date_range("2024-01-01", periods=n, freq="h")
    amounts    = np.round(np.random.lognormal(3, 1.5, n), 2)
    categories = np.random.choice(
        ["grocery", "electronics", "travel", "dining", "utilities", "entertainment"],
        n, p=[0.25, 0.15, 0.15, 0.2, 0.15, 0.1],
    )
    acct_age = np.random.exponential(365, n).astype(int)
    hour     = np.random.randint(0, 24, n)

    high_amount_threshold = np.quantile(amounts, 0.95)
    fraud_prob = (
        0.01
        + 0.02 * (hour < 6).astype(float)
        + 0.02 * (acct_age < 30).astype(float)
        + 0.01 * (amounts > high_amount_threshold).astype(float)
    )
    fraud_prob = np.clip(fraud_prob, 0, 0.3)
    is_fraud   = (np.random.random(n) < fraud_prob).astype(int)

    df = pd.DataFrame({
        "transaction_id":   [f"TXN_{i:06d}" for i in range(n)],
        "timestamp":        timestamps,
        "amount":           amounts,
        "category":         categories,
        "account_age_days": acct_age,
        "hour":             hour,
        "is_fraud":         is_fraud,
    })

    actual_rate = df["is_fraud"].mean()
    print(f"✓ Generated {n:,} transactions (fraud rate: {actual_rate:.1%})")
    return df
'''


def get_code() -> str:
    """Return the source code string for these skills."""
    return _SYNTHETIC_SKILLS_CODE
