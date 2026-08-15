"""
Shared fixtures and configuration for all kerno tests.
"""

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: marks tests that require a running Jupyter kernel"
    )
    config.addinivalue_line(
        "markers",
        "slow: marks tests that take > 10 seconds"
    )
    config.addinivalue_line(
        "markers",
        "llm: marks tests that require a real LLM API"
    )
    config.addinivalue_line(
        "markers",
        "property: marks property-based tests"
    )


@pytest.fixture(scope="session")
def mock_llm():
    """
    A deterministic mock LLM for testing.
    Returns TASK_COMPLETE on the 3rd call, generates code on earlier calls.
    """
    call_count = [0]
    responses  = [
        "x = 42\nprint('x =', x)",
        "y = x * 2\nprint('y =', y)",
        "# TASK_COMPLETE: computed x=42 and y=84",
    ]

    def llm(messages):
        i = call_count[0]
        call_count[0] += 1
        if i < len(responses):
            return responses[i]
        return "# TASK_COMPLETE: done"

    llm.call_count = call_count
    return llm


@pytest.fixture(scope="function")
def fresh_state():
    """A fresh AgentState for each test."""
    from kerno.interfaces import AgentState
    return AgentState(task="test task", session_id="test-session")


@pytest.fixture(scope="module")
def live_kernel():
    """
    A running KernelRuntime for integration tests.
    Shared across the module — faster than per-test startup.
    """
    from kerno.kernel.runtime import KernelRuntime
    with KernelRuntime() as kernel:
        yield kernel


@pytest.fixture(scope="module")
def bootstrapped_kernel(live_kernel):
    """A kernel with default skills loaded."""
    from kerno.skills.bootstrap import bootstrap
    bootstrap(live_kernel)
    yield live_kernel
