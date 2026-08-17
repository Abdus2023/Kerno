.PHONY: test test-unit test-integration test-property ci build smoke bench lint type-check

# K-010: one command reproduces the CI gates locally (same jobs as
# .github/workflows/ci.yml — static, unit, security invariants, kernel).
# Use the project venv explicitly so `make ci` works without an
# activated environment.
PY ?= .venv/bin/python
PYTEST ?= .venv/bin/pytest

ci:
	$(PY) -m compileall -q kerno tests
	$(PY) -c "import kerno; print('kerno imports OK')"
	$(PY) scripts/check_raw_kernel.py
	$(PYTEST) tests/unit -q
	$(PYTEST) tests/security -q
	$(PYTEST) tests/unit/test_security.py tests/unit/test_execution_engine.py tests/unit/test_capability_broker.py tests/unit/test_secrets.py tests/unit/test_isolation.py tests/unit/test_invariants.py tests/unit/test_management_plane.py tests/unit/test_transport_parity.py tests/unit/test_static_gate.py -q
	$(PYTEST) tests/behavioral tests/integration tests/property -q

# Regenerate the reproducible dependency lockfile (Gate B).
# Requires pip-tools: pip install pip-tools
lock:
	pip-compile --resolver=backtracking --extra=all --extra=dev --generate-hashes -o requirements.lock.txt pyproject.toml

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

# Build the release wheel (release-readiness artifact)
build:
	pip wheel . -w dist/ --no-deps

# Smoke-test the wheel in a FRESH venv: import gate, doctor invariants,
# and a real dry-run/live/replay session — no API key required.
smoke:
	rm -rf /tmp/kerno-smoke-venv
	python3 -m venv /tmp/kerno-smoke-venv
	/tmp/kerno-smoke-venv/bin/pip install -q dist/kerno-*.whl
	/tmp/kerno-smoke-venv/bin/kerno doctor
	/tmp/kerno-smoke-venv/bin/kerno run "smoke test" --dry-run --security data_analysis
	/tmp/kerno-smoke-venv/bin/python examples/16_dry_run_and_replay.py
	rm -rf /tmp/kerno-smoke-venv

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
