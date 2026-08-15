.PHONY: test test-unit test-integration test-property bench lint type-check

test:
	pytest tests/ -x -q --tb=short

test-unit:
	pytest tests/unit/ -x -q --tb=short

test-integration:
	pytest tests/behavioral/ -x -q --tb=short -m integration

test-property:
	pytest tests/property/ -x -q --tb=short

test-fast:
	pytest tests/unit/ -q --tb=line

bench:
	python -c "
from kerno.benchmark.suite import standard_suite
from kerno.benchmark.runner import BenchmarkRunner
from kerno.llm import anthropic_llm
runner = BenchmarkRunner(anthropic_llm('claude-haiku-4-5'), verbose=True)
report = runner.run(standard_suite())
print(report.table())
"

lint:
	ruff check kerno/ tests/

type-check:
	mypy kerno/ --ignore-missing-imports --no-strict-optional

coverage:
	pytest tests/unit/ --cov=kerno --cov-report=html --cov-report=term-missing

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -name "*.pyc" -delete
	rm -rf .coverage htmlcov/ .pytest_cache/ dist/ build/
