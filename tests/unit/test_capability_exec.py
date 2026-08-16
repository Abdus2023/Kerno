"""
Unit tests for CapabilityExecutor — capability execution separated from
code execution (audit #31/#48): the LLM requests operations, the broker
performs them host-side WITHOUT Python.
"""

import pytest

from kerno.artifacts import ArtifactStore
from kerno.capability_exec import (
    CAP_ARTIFACT_READ, CapabilityError, CapabilityExecutor,
)
from kerno.security.capabilities import (
    CAP_ARTIFACT_CREATE, CAP_FILESYSTEM_READ, CAP_SECRET_READ,
    Capability, CapabilityBroker,
)
from kerno.security.secrets import SecretBroker
from kerno.types import CellOutput


class TestFileRead:
    """filesystem.read — scoped, host-side, no Python."""

    def _broker_with_read(self, scope="/workspace/**", subject="agent-1"):
        broker = CapabilityBroker()
        broker.grant(Capability(CAP_FILESYSTEM_READ, scope=scope),
                     subject=subject)
        return broker

    def test_read_within_scope(self, tmp_path):
        target = tmp_path / "data.csv"
        target.write_text("a,b\n1,2\n")
        ex = CapabilityExecutor(
            self._broker_with_read(scope=str(tmp_path) + "/**"),
            workspace_root=tmp_path,
        )
        result = ex.invoke(
            "filesystem.read",
            scope=str(target), subject="agent-1",
        )
        assert result.ok
        assert result.value == "a,b\n1,2\n"

    def test_read_outside_scope_denied(self, tmp_path):
        ex = CapabilityExecutor(
            self._broker_with_read(scope="/workspace/**"),
            workspace_root=tmp_path,
        )
        result = ex.invoke(
            "filesystem.read",
            scope="/etc/passwd", subject="agent-1",
        )
        assert result.denied
        assert "no active grant" in result.error

    def test_traversal_out_of_workspace_denied(self, tmp_path):
        secret = tmp_path / "secret.txt"
        secret.write_text("top secret")
        # Grant covers the whole tmp_path — but a '..' escape to a
        # sibling directory must be rejected by the workspace guard
        ex = CapabilityExecutor(
            self._broker_with_read(scope=str(tmp_path) + "/**"),
            workspace_root=tmp_path / "workspace",
        )
        (tmp_path / "workspace").mkdir(exist_ok=True)
        result = ex.invoke(
            "filesystem.read",
            scope=str(tmp_path / "workspace" / ".." / "secret.txt"),
            subject="agent-1",
        )
        assert not result.ok
        assert "escapes" in result.error

    def test_missing_file_error(self, tmp_path):
        ex = CapabilityExecutor(
            self._broker_with_read(scope=str(tmp_path) + "/**"),
            workspace_root=tmp_path,
        )
        result = ex.invoke(
            "filesystem.read",
            scope=str(tmp_path / "ghost.csv"), subject="agent-1",
        )
        assert not result.ok
        assert "not found" in result.error

    def test_oversized_file_rejected(self, tmp_path):
        target = tmp_path / "big.csv"
        target.write_text("x" * 1000)
        ex = CapabilityExecutor(
            self._broker_with_read(scope=str(tmp_path) + "/**"),
            workspace_root=tmp_path,
            max_read_bytes=100,
        )
        result = ex.invoke(
            "filesystem.read", scope=str(target), subject="agent-1",
        )
        assert not result.ok
        assert "too large" in result.error


class TestArtifacts:
    """artifact.create / artifact.read — content-addressed, host-side."""

    def _ex(self, tmp_path, broker=None):
        broker = broker or CapabilityBroker()
        broker.grant(Capability(CAP_ARTIFACT_CREATE, scope="*"),
                     subject="agent-1")
        broker.grant(Capability(CAP_ARTIFACT_READ, scope="*"),
                     subject="agent-1")
        return CapabilityExecutor(
            broker, artifact_store=ArtifactStore(tmp_path / "store")
        )

    def test_create_then_read_round_trip(self, tmp_path):
        ex = self._ex(tmp_path)
        created = ex.invoke(
            "artifact.create", scope="*", subject="agent-1",
            params={"data": "report body", "media_type": "text/plain"},
        )
        assert created.ok
        ref = created.value
        assert ref["digest"].startswith("sha256:")

        read = ex.invoke(
            "artifact.read", scope=ref["digest"], subject="agent-1",
        )
        assert read.ok
        assert read.value == "report body"

    def test_create_without_data_rejected(self, tmp_path):
        ex = self._ex(tmp_path)
        result = ex.invoke(
            "artifact.create", scope="*", subject="agent-1", params={},
        )
        assert not result.ok
        assert "params" in result.error

    def test_read_unknown_digest_error(self, tmp_path):
        ex = self._ex(tmp_path)
        result = ex.invoke(
            "artifact.read", scope="sha256:deadbeef", subject="agent-1",
        )
        assert not result.ok
        assert "not found" in result.error


class TestSecrets:
    """secret.read — via SecretBroker with subject-scoped grants."""

    def test_secret_read_with_grant(self):
        broker = CapabilityBroker()
        broker.grant(Capability(CAP_SECRET_READ, scope="db_password"),
                     subject="agent-1")
        secrets = SecretBroker()
        secrets.register("db_password", "s3cr3t!")
        secrets.grant("db_password", subject="agent-1")

        ex = CapabilityExecutor(broker, secret_broker=secrets)
        result = ex.invoke(
            "secret.read", scope="db_password", subject="agent-1",
        )
        assert result.ok
        assert result.value == "s3cr3t!"

    def test_secret_read_without_secret_grant_denied(self):
        broker = CapabilityBroker()
        # CAP_SECRET_READ granted, but the SecretBroker has no grant
        broker.grant(Capability(CAP_SECRET_READ, scope="*"), subject="agent-1")
        secrets = SecretBroker()
        secrets.register("db_password", "s3cr3t!")

        ex = CapabilityExecutor(broker, secret_broker=secrets)
        result = ex.invoke(
            "secret.read", scope="db_password", subject="agent-1",
        )
        assert not result.ok
        assert "secret denied" in result.error


class TestKernelExecute:
    """kernel.execute — the compute path, delegated to the engine."""

    class FakeEngine:
        def __init__(self):
            self.calls = []

        def execute(self, code, timeout=120.0, subject=""):
            self.calls.append(code)
            if "boom" in code:
                from kerno.types import CellError
                return CellOutput(error=CellError("ValueError", "boom"))
            return CellOutput(stdout="ran: " + code)

    def test_delegates_to_engine(self):
        broker = CapabilityBroker()
        broker.grant(Capability("kernel.execute", scope="*"), subject="agent-1")
        engine = self.FakeEngine()
        ex = CapabilityExecutor(broker, engine=engine)

        result = ex.invoke(
            "kernel.execute", scope="*", subject="agent-1",
            params={"code": "x = 1"},
        )
        assert result.ok
        assert result.value["stdout"] == "ran: x = 1"
        assert engine.calls == ["x = 1"]

    def test_engine_error_surfaces(self):
        broker = CapabilityBroker()
        broker.grant(Capability("kernel.execute", scope="*"), subject="agent-1")
        ex = CapabilityExecutor(broker, engine=self.FakeEngine())

        result = ex.invoke(
            "kernel.execute", scope="*", subject="agent-1",
            params={"code": "boom()"},
        )
        assert not result.ok
        assert "ValueError" in result.error

    def test_no_engine_configured(self):
        broker = CapabilityBroker()
        broker.grant(Capability("kernel.execute", scope="*"), subject="a")
        ex = CapabilityExecutor(broker)          # no engine
        result = ex.invoke(
            "kernel.execute", scope="*", subject="a",
            params={"code": "x = 1"},
        )
        assert not result.ok
        assert "no compute engine" in result.error


class TestAudit:

    def test_records_every_invocation(self, tmp_path):
        broker = CapabilityBroker()
        broker.grant(Capability(CAP_FILESYSTEM_READ, scope=str(tmp_path) + "/**"),
                     subject="agent-1")
        ex = CapabilityExecutor(broker, workspace_root=tmp_path)

        (tmp_path / "a.txt").write_text("hello")
        ex.invoke("filesystem.read", scope=str(tmp_path / "a.txt"),
                  subject="agent-1")
        ex.invoke("filesystem.read", scope="/etc/passwd", subject="agent-1")

        assert len(ex.records) == 2
        assert ex.records[0].ok is True
        assert ex.records[1].ok is False
        assert ex.records[1].name == "filesystem.read"
        assert ex.records[1].subject == "agent-1"
        assert "denied" in ex.records[1].error

    def test_unknown_capability_rejected(self):
        broker = CapabilityBroker()
        broker.grant(Capability("nonsense", scope="*"), subject="a")
        ex = CapabilityExecutor(broker)
        result = ex.invoke("nonsense", subject="a")
        assert not result.ok
        assert "unknown capability" in result.error
