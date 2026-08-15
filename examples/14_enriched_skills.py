"""
Example 14: Enriched built-in skill library.

This example demonstrates how the full composable skill set can be loaded into
a running kernel. It intentionally does not call an LLM; the same registry is
used by Session.with_skills(...) or bootstrap(kernel).
"""

from kerno.kernel.runtime import KernelRuntime
from kerno.skills.composer import full_stack_skills


def main():
    skill_set = full_stack_skills()
    print(f"Loaded {len(skill_set)} composable skill domains:")
    for name in skill_set.names():
        print(f"  - {name}")

    with KernelRuntime() as kernel:
        skill_set.load_into(kernel)

        # Synthetic data + feature engineering + quality report.
        kernel.execute("""
sales = mock_sales(250, seed=7)
sales = add_date_features(sales, 'date', drop_original=False)
quality_report(sales)
anonymized = anonymize(sales, ['order_id'], method='mask')
print(anonymized[['order_id', 'region', 'revenue']].head().to_string(index=False))
""", timeout=60)

        # A tiny Monte Carlo simulation and markdown report.
        result = kernel.execute("""
def profit_trial():
    units = max(0, np.random.normal(1000, 200))
    return {'profit': units * 25 - (5000 + units * 12)}

sim = monte_carlo(profit_trial, n_sims=500)
prob_loss = float((sim['profit'] < 0).mean())
report_md = generate_markdown_report(
    'Product Profit Simulation',
    {
        'Outcome': f'Probability of loss: {prob_loss:.1%}',
        'Summary': sim[['profit']].describe().round(2),
    },
    path='simulation-report.md',
)
print(report_md)
""", timeout=60)

        if result.has_error:
            raise RuntimeError(f"Kernel execution failed: {result.error}")

    print("\nDone. Artifacts may include simulation-report.md in the working directory.")


if __name__ == "__main__":
    main()
