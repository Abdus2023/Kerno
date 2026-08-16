"""
Property-based tests for pipeline invariants.
These test mathematical properties of the composition system.

Requires: pip install hypothesis
"""

import pytest

try:
    from hypothesis            import given, settings, HealthCheck
    from hypothesis.strategies import (
        integers, lists, text, composite, just, one_of
    )
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

from kerno.pipeline   import Pipeline, LoopStep, IdentityStep

if not HAS_HYPOTHESIS:
    pytest.skip("hypothesis not installed", allow_module_level=True)
from kerno.interfaces import AgentState


def make_state(task: str = "test") -> AgentState:
    return AgentState(task=task, session_id="prop-test")


class AppendStep:
    def __init__(self, value: str):
        self.value = value
    def run(self, state: AgentState) -> AgentState:
        state.metadata.setdefault("log", []).append(self.value)
        return state


class TestPipelineAlgebra:
    """
    Test algebraic properties of Pipeline composition.
    """

    @given(lists(text(min_size=1, max_size=10), min_size=1, max_size=10))
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_pipeline_preserves_order(self, values: list[str]):
        """Pipeline executes steps in the order they are given."""
        steps    = [AppendStep(v) for v in values]
        pipeline = Pipeline(steps)
        state    = pipeline.run(make_state())
        assert state.metadata.get("log", []) == values

    @given(
        lists(text(min_size=1, max_size=5), min_size=1, max_size=5),
        lists(text(min_size=1, max_size=5), min_size=1, max_size=5),
    )
    def test_pipeline_concat_associativity(self, a: list[str], b: list[str]):
        """
        (Pipeline(A) | Pipeline(B)).run(s) == Pipeline(A + B).run(s)
        Concatenation of pipelines is equivalent to concatenation of steps.
        """
        steps_a  = [AppendStep(v) for v in a]
        steps_b  = [AppendStep(v) for v in b]

        combined_pipeline  = Pipeline(steps_a + steps_b)
        composed_pipeline  = Pipeline(steps_a).then(Pipeline(steps_b))

        state1 = combined_pipeline.run(make_state())
        state2 = composed_pipeline.run(make_state())

        assert state1.metadata.get("log", []) == state2.metadata.get("log", [])

    @given(lists(text(min_size=1, max_size=5), min_size=1, max_size=10))
    def test_identity_step_is_neutral_element(self, values: list[str]):
        """
        Pipeline([identity] + steps).run(s) == Pipeline(steps).run(s)
        IdentityStep is the neutral element of pipeline composition.
        """
        steps    = [AppendStep(v) for v in values]
        with_id  = Pipeline([IdentityStep()] + steps + [IdentityStep()])
        without  = Pipeline(steps)

        s1 = with_id.run(make_state())
        s2 = without.run(make_state())
        assert s1.metadata.get("log", []) == s2.metadata.get("log", [])

    @given(integers(min_value=1, max_value=20))
    def test_loop_executes_exactly_n_times_when_never_done(self, n: int):
        """LoopStep with always-false done runs exactly max_iterations times."""
        counter   = [0]

        class CountStep:
            def run(self, state):
                counter[0] += 1
                return state

        loop = LoopStep(
            CountStep(),
            done           = lambda s: False,
            max_iterations = n,
        )
        loop.run(make_state())
        assert counter[0] == n

    @given(integers(min_value=1, max_value=20))
    def test_loop_stops_at_first_complete(self, stop_at: int):
        """LoopStep stops as soon as done() returns True."""
        counter = [0]

        class CountAndMaybeComplete:
            def __init__(self, stop_at):
                self.stop_at = stop_at
            def run(self, state):
                counter[0] += 1
                if counter[0] >= self.stop_at:
                    state.complete = True
                return state

        loop = LoopStep(
            CountAndMaybeComplete(stop_at),
            done           = lambda s: s.complete,
            max_iterations = stop_at + 100,   # Much higher — shouldn't reach
        )
        loop.run(make_state())
        assert counter[0] == stop_at

    def test_empty_pipeline_is_identity(self):
        """An empty pipeline does nothing to the state."""
        state    = make_state()
        pipeline = Pipeline([])
        result   = pipeline.run(state)
        assert result.task      == state.task
        assert result.complete  == state.complete
        assert result.metadata  == state.metadata


class TestMiddlewareAlgebra:
    """Test algebraic properties of middleware composition."""

    def test_middleware_composition_is_associative(self):
        """
        apply_middleware(step, [A, B]) is equivalent to A(B(step)).
        """
        from kerno.middleware import Middleware, apply_middleware, wrap

        execution_log = []

        class LogMiddleware(Middleware):
            def __init__(self, step, name):
                super().__init__(step)
                self.name = name
            def before(self, state):
                execution_log.append("before_{}".format(self.name))
                return state
            def after(self, state):
                execution_log.append("after_{}".format(self.name))
                return state

        class PassStep:
            def run(self, state): return state

        # Method 1: apply_middleware
        execution_log.clear()
        step = apply_middleware(PassStep(), [
            lambda s: LogMiddleware(s, "outer"),
            lambda s: LogMiddleware(s, "inner"),
        ])
        step.run(make_state())
        log1 = list(execution_log)

        # Method 2: manual wrapping (reversed order)
        execution_log.clear()
        inner = LogMiddleware(PassStep(), "inner")
        outer = LogMiddleware(inner, "outer")
        outer.run(make_state())
        log2 = list(execution_log)

        assert log1 == log2


class TestAllowListFuzzing:
    """Property-based and AST fuzzing tests for the AllowList."""

    def test_obfuscated_imports_blocked(self):
        from kerno.security.allowlist import AllowList, AllowListViolation

        al = AllowList.data_analysis()

        # Multi-line imports, spaces, comments
        disallowed_payloads = [
            "import \\\n    os",
            "import os, sys",
            "from socket import socket",
            "from urllib.request import urlopen",
            "import subprocess as sp",
            "x = 1; import os",
            "import os.environ",
            "import multiprocessing",
        ]

        for payload in disallowed_payloads:
            with pytest.raises(AllowListViolation):
                al.check(payload)

    def test_safe_data_analysis_payloads_allowed(self):
        from kerno.security.allowlist import AllowList

        al = AllowList.data_analysis()

        allowed_payloads = [
            "import pandas as pd\nimport numpy as np",
            "import matplotlib.pyplot as plt",
            "from sklearn.linear_model import LogisticRegression",
            "from scipy.stats import norm",
            "import json, math, datetime, typing",
            "import pathlib",
        ]

        for payload in allowed_payloads:
            al.check(payload)


class TestSecretRedactionAlgebra:
    """Mathematical properties of the secret redaction layer (audit #67/#68)."""

    def test_redaction_is_idempotent(self):
        from kerno.security.secrets import SecretBroker

        broker = SecretBroker()
        broker.register("api_token", "sk-proj-998877665544")
        broker.register("db_pass", "postgres_master_pass_123")

        text = "Connecting to DB with postgres_master_pass_123 and token sk-proj-998877665544"
        redacted_once = broker.redact(text)
        redacted_twice = broker.redact(redacted_once)

        # Idempotency property: R(R(x)) == R(x)
        assert redacted_once == redacted_twice
        assert "sk-proj-998877665544" not in redacted_once
        assert "postgres_master_pass_123" not in redacted_once

    def test_longest_first_redaction_preserves_boundaries(self):
        from kerno.security.secrets import SecretBroker

        broker = SecretBroker()
        broker.register("short", "secret")
        broker.register("long", "secret_with_suffix")

        text = "Key: secret_with_suffix"
        redacted = broker.redact(text)

        # Longest match takes precedence
        assert "secret_with_suffix" not in redacted
        assert "secret" not in redacted
