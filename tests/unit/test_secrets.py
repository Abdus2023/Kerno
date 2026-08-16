"""
Unit tests for SecretBroker and the redaction layer (audit #67, #68).

Invariants:
    - secrets are granted explicitly, never exposed wholesale
    - recorded text (code previews, error values) is redacted before it
      reaches records/events — the engine redaction layer
"""

import time

import pytest

from kerno.execution.engine import ExecutionEngine
from kerno.security.allowlist import AllowList
from kerno.security.secrets import (
    REDACTED, SecretBroker, SecretDenied, SecretNotFound,
)
from kerno.types import CellOutput


class TestSecretBroker:

    def test_register_and_request_with_grant(self):
        broker = SecretBroker()
        broker.register("db_password", "s3cr3t!")
        broker.grant("db_password", subject="agent-1")
        assert broker.request("db_password", subject="agent-1") == "s3cr3t!"

    def test_request_unknown_raises(self):
        broker = SecretBroker()
        with pytest.raises(SecretNotFound):
            broker.request("ghost")

    def test_request_without_grant_raises(self):
        broker = SecretBroker()
        broker.register("db_password", "s3cr3t!")
        with pytest.raises(SecretDenied):
            broker.request("db_password", subject="agent-1")

    def test_grant_to_other_subject_denied(self):
        broker = SecretBroker()
        broker.register("db_password", "s3cr3t!")
        broker.grant("db_password", subject="alice")
        with pytest.raises(SecretDenied):
            broker.request("db_password", subject="bob")

    def test_anonymous_grant_serves_any_subject(self):
        broker = SecretBroker()
        broker.register("token", "tok-123")
        broker.grant("token")   # subject "" = any
        assert broker.request("token", subject="agent-9") == "tok-123"

    def test_expired_grant_denied(self):
        broker = SecretBroker()
        broker.register("token", "tok-123")
        broker.grant("token", expires_at=time.time() - 10)
        with pytest.raises(SecretDenied):
            broker.request("token")

    def test_revoke_denies(self):
        broker = SecretBroker()
        broker.register("token", "tok-123")
        broker.grant("token", subject="alice")
        broker.revoke("token", subject="alice")
        with pytest.raises(SecretDenied):
            broker.request("token", subject="alice")

    def test_revoke_all_denies_everyone(self):
        broker = SecretBroker()
        broker.register("token", "tok-123")
        broker.grant("token", subject="alice")
        broker.grant("token", subject="bob")
        broker.revoke_all("token")
        with pytest.raises(SecretDenied):
            broker.request("token", subject="alice")
        with pytest.raises(SecretDenied):
            broker.request("token", subject="bob")


class TestRedaction:

    def test_redact_replaces_secret_value(self):
        broker = SecretBroker()
        broker.register("api_key", "sk-live-abc123")
        assert broker.redact("key is sk-live-abc123 here") == \
            "key is [REDACTED] here"

    def test_redact_handles_multiple_secrets(self):
        broker = SecretBroker()
        broker.register("a", "alpha")
        broker.register("b", "beta")
        text = "alpha and beta and alpha again"
        assert broker.redact(text) == "[REDACTED] and [REDACTED] and [REDACTED] again"

    def test_redact_longest_first(self):
        broker = SecretBroker()
        broker.register("short", "abc")
        broker.register("long", "abcdef")
        # longest matches first, so no partial residue
        assert broker.redact("value=abcdef") == "value=[REDACTED]"

    def test_redact_empty_text(self):
        broker = SecretBroker()
        assert broker.redact("") == ""

    def test_redact_many(self):
        broker = SecretBroker()
        broker.register("token", "t0k3n")
        assert broker.redact_many(["token: t0k3n", "no secrets"]) == \
            ["token: [REDACTED]", "no secrets"]


class TestEngineRedaction:
    """Audit #68: Execution → Observation → Redaction → Event Store."""

    class FakeKernel:
        def execute(self, code, timeout=120.0, silent=False):
            return CellOutput(stdout="ok")

        def execute_silent(self, code, timeout=15.0):
            return "ok"

        @property
        def namespace(self):
            return "{}"

        @property
        def is_alive(self):
            return True

    def _engine_with_redactor(self, secret_value="sk-live-abc123"):
        broker = SecretBroker()
        broker.register("api_key", secret_value)
        return ExecutionEngine(
            self.FakeKernel(),
            allowlist=AllowList.data_analysis(),
            redactor=broker.redact,
        )

    def test_secret_never_enters_records(self):
        engine = self._engine_with_redactor()
        engine.execute("api_key = 'sk-live-abc123'\nprint(api_key)")

        for record in engine.records:
            assert "sk-live-abc123" not in record.code_preview

    def test_secret_never_enters_events(self):
        engine = self._engine_with_redactor()
        engine.execute("print('sk-live-abc123')")

        for event in engine.events:
            assert "sk-live-abc123" not in str(event.payload)

    def test_denied_code_fragment_is_redacted_in_error(self):
        engine = self._engine_with_redactor()
        # The policy error message embeds matched code — which contains
        # the secret — and must be redacted in the returned error too.
        out = engine.execute(
            "token = 'sk-live-abc123'\nimport subprocess"
        )
        assert out.has_error
        assert "sk-live-abc123" not in out.error.evalue
        assert "sk-live-abc123" not in out.error.ename

    def test_no_redactor_leaves_preview_untouched(self):
        engine = ExecutionEngine(self.FakeKernel())
        engine.execute("x = 'sk-live-abc123'")
        assert "sk-live-abc123" in engine.records[0].code_preview
