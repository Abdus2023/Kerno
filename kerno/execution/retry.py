# kerno/execution/retry.py
"""
RetryExecutor — action-level retry with idempotency policy (audit #50).

The dangerous case: the kernel times out AFTER an external service
accepted the request. Blindly retrying then double-applies the side
effect (charge_credit_card twice). RetryExecutor therefore consults
retry_policy(action.idempotency, idempotency_key) before every retry:

    SAFE           → retry automatically
    IDEMPOTENT     → retry, reusing the SAME idempotency key
    NON_IDEMPOTENT → retry only with explicit_allow=True
    UNKNOWN        → never retry

Policy denials (AllowListViolation, CapabilityViolation, ApprovalDenied)
are NEVER retried — they are deterministic refusals, not transient
failures.
"""

from __future__ import annotations

from typing import Optional

from kerno.action import (
    Action, Idempotency, retry_policy,
)
from kerno.types import CellOutput

# Error names that are deterministic refusals — retrying cannot help.
_NON_RETRYABLE = frozenset({
    "AllowListViolation",
    "CapabilityViolation",
    "ApprovalDenied",
})


class RetryExecutor:
    """
    Executor wrapper retrying failed executions under idempotency policy.

    Usage:
        ex = RetryExecutor(engine, max_retries=2)
        out = ex.execute(code, action=action)   # retries per policy
    """

    def __init__(
        self,
        executor:        object,
        max_retries:     int  = 2,
        explicit_allow:  bool = False,
    ):
        self._executor      = executor
        self._max_retries   = max_retries
        self._explicit_allow = explicit_allow
        self._retries: list[dict] = []

    def execute(
        self,
        code:    str,
        timeout: float = 120.0,
        silent:  bool  = False,
        action:  Optional[Action] = None,
        **kwargs,
    ) -> CellOutput:
        output = self._executor.execute(code, timeout=timeout, silent=silent, **kwargs)

        attempts = 0
        while (
            output.has_error
            and attempts < self._max_retries
            and self._should_retry(output, action)
        ):
            attempts += 1
            self._retries.append({
                "action_id": action.action_id if action else None,
                "attempt":   attempts,
                "error":     output.error.ename if output.error else "?",
            })
            output = self._executor.execute(
                code, timeout=timeout, silent=silent, **kwargs
            )
        return output

    def _should_retry(self, output: CellOutput, action: Optional[Action]) -> bool:
        """Retry only when the idempotency policy allows it."""
        if not output.has_error or output.error is None:
            return False
        if output.error.ename in _NON_RETRYABLE:
            return False
        if action is None:
            # No action → no idempotency contract → unknown → no retry
            return False
        decision = retry_policy(
            action.idempotency,
            idempotency_key = action.idempotency_key,
            explicit_allow  = self._explicit_allow,
        )
        return decision.retry

    def execute_silent(
        self,
        code:    str,
        timeout: float = 15.0,
        action:  Optional[Action] = None,
        **kwargs,
    ) -> str:
        output = self.execute(code, timeout=timeout, silent=True,
                              action=action, **kwargs)
        return output.stdout.strip()

    @property
    def namespace(self) -> str:
        return self._executor.namespace

    @property
    def is_alive(self) -> bool:
        return self._executor.is_alive

    @property
    def raw_kernel(self) -> object:
        return getattr(self._executor, "raw_kernel", None) or self._executor

    @property
    def retry_log(self) -> tuple[dict, ...]:
        """Every retry performed (audit trail)."""
        return tuple(self._retries)

    @property
    def retry_count(self) -> int:
        return len(self._retries)
