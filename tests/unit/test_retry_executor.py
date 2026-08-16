"""
Unit tests for RetryExecutor — idempotency-aware action retry (audit #50).
"""

from kerno.action import Action, ActionKind, Idempotency
from kerno.execution.retry import RetryExecutor
from kerno.types import CellError, CellOutput


class FlakyKernel:
    """Fails the first `failures` calls, then succeeds."""

    def __init__(self, failures=1, error_name="TimeoutError"):
        self.failures    = failures
        self.error_name  = error_name
        self.calls       = 0

    def execute(self, code, timeout=120.0, silent=False):
        self.calls += 1
        if self.calls <= self.failures:
            return CellOutput(error=CellError(self.error_name, "boom"))
        return CellOutput(stdout="ok")

    def execute_silent(self, code, timeout=15.0):
        return self.execute(code, timeout=timeout, silent=True).stdout.strip()

    @property
    def namespace(self):
        return "{}"

    @property
    def is_alive(self):
        return True


def make_action(idempotency=Idempotency.SAFE, key=None):
    return Action.new(
        ActionKind.EXECUTE_CODE,
        payload={"code": "charge()"},
        idempotency=idempotency,
        idempotency_key=key,
    )


class TestRetryExecutor:

    def test_safe_action_retries_and_recovers(self):
        kernel = FlakyKernel(failures=2)
        ex = RetryExecutor(kernel, max_retries=3)
        out = ex.execute("charge()", action=make_action(Idempotency.SAFE))
        assert not out.has_error
        assert kernel.calls == 3
        assert ex.retry_count == 2
        assert ex.retry_log[0]["attempt"] == 1

    def test_unknown_action_never_retries(self):
        kernel = FlakyKernel(failures=5)
        ex = RetryExecutor(kernel, max_retries=3)
        out = ex.execute("x()", action=make_action(Idempotency.UNKNOWN))
        assert out.has_error          # failed once, no retry
        assert kernel.calls == 1
        assert ex.retry_count == 0

    def test_non_idempotent_requires_explicit_allow(self):
        kernel = FlakyKernel(failures=1)
        # Without explicit approval → no retry (the dangerous case)
        ex = RetryExecutor(kernel, max_retries=3)
        out = ex.execute("charge()", action=make_action(Idempotency.NON_IDEMPOTENT))
        assert out.has_error
        assert kernel.calls == 1

        # With explicit policy approval → retries
        kernel2 = FlakyKernel(failures=1)
        ex2 = RetryExecutor(kernel2, max_retries=3, explicit_allow=True)
        out2 = ex2.execute("charge()", action=make_action(Idempotency.NON_IDEMPOTENT))
        assert not out2.has_error
        assert kernel2.calls == 2

    def test_idempotent_with_key_retries(self):
        kernel = FlakyKernel(failures=1)
        ex = RetryExecutor(kernel, max_retries=3)
        out = ex.execute(
            "charge()", action=make_action(Idempotency.IDEMPOTENT, key="charge-42")
        )
        assert not out.has_error
        assert kernel.calls == 2

    def test_idempotent_without_key_never_retries(self):
        kernel = FlakyKernel(failures=1)
        ex = RetryExecutor(kernel, max_retries=3)
        out = ex.execute("charge()", action=make_action(Idempotency.IDEMPOTENT))
        assert out.has_error
        assert kernel.calls == 1

    def test_policy_denials_never_retried(self):
        # AllowListViolation is a deterministic refusal — retrying cannot help
        kernel = FlakyKernel(failures=1, error_name="AllowListViolation")
        ex = RetryExecutor(kernel, max_retries=3)
        out = ex.execute("import subprocess", action=make_action(Idempotency.SAFE))
        assert out.has_error
        assert out.error.ename == "AllowListViolation"
        assert kernel.calls == 1
        assert ex.retry_count == 0

    def test_no_action_means_no_retry(self):
        kernel = FlakyKernel(failures=1)
        ex = RetryExecutor(kernel, max_retries=3)
        out = ex.execute("x()")          # no action → no contract
        assert out.has_error
        assert kernel.calls == 1

    def test_max_retries_respected(self):
        kernel = FlakyKernel(failures=10)
        ex = RetryExecutor(kernel, max_retries=2)
        out = ex.execute("x()", action=make_action(Idempotency.SAFE))
        assert out.has_error
        assert kernel.calls == 3          # 1 original + 2 retries
        assert ex.retry_count == 2

    def test_executor_protocol_passthrough(self):
        kernel = FlakyKernel(failures=0)
        ex = RetryExecutor(kernel, max_retries=1)
        assert ex.is_alive is True
        assert ex.namespace == "{}"
        assert ex.raw_kernel is kernel
        assert ex.execute_silent("x") == "ok"
