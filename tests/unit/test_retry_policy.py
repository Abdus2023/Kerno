"""
Unit tests for action idempotency + retry policy (audit #50).
"""

from kerno.action import Action, ActionKind, Idempotency, retry_policy


class TestRetryPolicy:

    def test_safe_retries_automatically(self):
        d = retry_policy(Idempotency.SAFE)
        assert d.retry is True
        assert "safe" in d.reason

    def test_idempotent_requires_key(self):
        assert retry_policy(Idempotency.IDEMPOTENT).retry is False
        d = retry_policy(Idempotency.IDEMPOTENT, idempotency_key="charge-1")
        assert d.retry is True
        assert d.require_key is True

    def test_non_idempotent_requires_explicit_approval(self):
        assert retry_policy(Idempotency.NON_IDEMPOTENT).retry is False
        d = retry_policy(Idempotency.NON_IDEMPOTENT, explicit_allow=True)
        assert d.retry is True
        assert "explicit" in d.reason

    def test_unknown_never_retries(self):
        assert retry_policy(Idempotency.UNKNOWN).retry is False

    def test_decision_serializable(self):
        d = retry_policy(Idempotency.IDEMPOTENT, idempotency_key="k")
        assert d.to_dict() == {
            "retry": True, "reason": d.reason, "require_key": True,
        }


class TestActionIdempotency:

    def test_default_unknown(self):
        a = Action.new(ActionKind.EXECUTE_CODE)
        assert a.idempotency == Idempotency.UNKNOWN
        assert a.idempotency_key is None

    def test_explicit_idempotency(self):
        a = Action.new(
            ActionKind.EXECUTE_CODE,
            payload={"code": "charge()"},
            idempotency=Idempotency.IDEMPOTENT,
            idempotency_key="charge-42",
        )
        assert a.idempotency == Idempotency.IDEMPOTENT
        assert a.idempotency_key == "charge-42"
        # The policy for this action
        d = retry_policy(a.idempotency, idempotency_key=a.idempotency_key)
        assert d.retry is True
