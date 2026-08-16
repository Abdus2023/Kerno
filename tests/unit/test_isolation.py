"""
Unit tests for agent isolation primitives (K-009) and the Docker
executor (audit #3/#11/#69) with a mocked docker CLI.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from kerno.isolation import (
    NamespacePartition, SharedMemory, export_code, parse_export,
)
from kerno.isolation_docker import (
    DockerExecutor, DockerUnavailable, docker_available,
)


class TestSharedMemory:

    def test_put_get_with_provenance(self):
        mem = SharedMemory()
        sv = mem.put("results_score", 42, producer="analyst")
        assert mem.get("results_score") is sv
        assert sv.producer == "analyst"
        assert sv.value == 42

    def test_producers_attribution(self):
        mem = SharedMemory()
        mem.put("results_score", 42, producer="analyst")
        mem.put("critique_flags", [], producer="critic")
        assert mem.producers() == {
            "analyst": ["results_score"],
            "critic":  ["critique_flags"],
        }

    def test_seed_code_materializes_json_copies(self):
        mem = SharedMemory()
        mem.put("results_score", 42, producer="analyst")
        mem.put("labels", ["a", "b"], producer="analyst")
        code = mem.seed_code()
        assert "results_score" in code
        assert "labels" in code
        assert "shared by analyst" in code

        # The generated code is executable and yields the values
        ns = {}
        exec(code, ns)
        assert ns["results_score"] == 42
        assert ns["labels"] == ["a", "b"]

    def test_seed_code_empty_when_nothing_shared(self):
        assert SharedMemory().seed_code() == ""

    def test_seed_is_detached_copy(self):
        mem = SharedMemory()
        mem.put("data", [1, 2], producer="analyst")
        code = mem.seed_code()
        ns = {}
        exec(code, ns)
        ns["data"].append(99)
        # The shared store is untouched by the receiving kernel
        assert mem.get("data").value == [1, 2]


class TestNamespacePartition:
    """K-009: agents may only write their declared prefixes."""

    def test_allows_prefix_matches(self):
        p = NamespacePartition()
        p.register("analyst", ["results_", "df_"])
        assert p.allows("analyst", "results_score") is True
        assert p.allows("analyst", "df_clean") is True
        assert p.allows("analyst", "critique_summary") is False

    def test_violations_report_undeclared_keys(self):
        p = NamespacePartition()
        p.register("analyst", ["results_"])
        viol = p.violations(
            "analyst",
            namespace_keys=["results_score", "secret_var", "x"],
            shared_keys=["x"],   # x is explicitly shared → allowed
        )
        assert viol == ["secret_var"]

    def test_no_prefixes_means_no_writes(self):
        p = NamespacePartition()
        p.register("critic", [])
        assert p.violations("critic", ["anything"], []) == ["anything"]


class TestExportHelpers:

    def test_export_code_filters_by_prefix(self):
        code = export_code(["results_"])
        assert "results_" in code
        assert "prefixes" not in code  # format already applied

    def test_parse_export(self):
        data = parse_export('{"a": 1, "b": "x"}')
        assert data == {"a": 1, "b": "x"}

    def test_parse_export_garbage(self):
        assert parse_export("not json") == {}
        assert parse_export("") == {}


class TestDockerExecutor:
    """Docker CLI is mocked — no docker required for these tests."""

    def _mock_run(self, returncode=0, stdout="", stderr=""):
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        result.stderr = stderr
        return result

    def test_start_builds_limits_command(self):
        ex = DockerExecutor(image="py:3.11")
        result = self._mock_run()
        with patch("kerno.isolation_docker.subprocess.run", return_value=result) as run:
            ex.start()
        cmd = run.call_args[0][0]
        assert "--cpus" in cmd and "1.0" in cmd
        assert "--memory" in cmd and "2g" in cmd
        assert "--pids-limit" in cmd and "128" in cmd
        assert "--network" in cmd and "none" in cmd
        assert "--read-only" in cmd
        assert ex.container_name in cmd
        assert cmd[-3:] == ["py:3.11", "sleep", "infinity"]

    def test_start_failure_raises(self):
        ex = DockerExecutor(image="py:3.11")
        result = self._mock_run(returncode=1, stderr="daemon down")
        with patch("kerno.isolation_docker.subprocess.run", return_value=result):
            with pytest.raises(DockerUnavailable, match="daemon down"):
                ex.start()

    def test_execute_success(self):
        ex = DockerExecutor()
        ex._started = True
        result = self._mock_run(stdout="42\n")
        with patch("kerno.isolation_docker.subprocess.run", return_value=result) as run:
            out = ex.execute("print(42)")
        assert not out.has_error
        assert out.stdout == "42\n"
        cmd = run.call_args[0][0]
        assert cmd[0] == "docker" and cmd[1] == "exec" and "-i" in cmd
        assert "python" in cmd and "-c" in cmd

    def test_execute_error_surfaces_stderr(self):
        ex = DockerExecutor()
        ex._started = True
        result = self._mock_run(returncode=1, stderr="NameError: name 'x'")
        with patch("kerno.isolation_docker.subprocess.run", return_value=result):
            out = ex.execute("print(x)")
        assert out.has_error
        assert out.error.ename == "ContainerExecutionError"
        assert "NameError" in out.error.evalue

    def test_execute_timeout(self):
        ex = DockerExecutor(timeout=5)
        ex._started = True
        with patch(
            "kerno.isolation_docker.subprocess.run",
            side_effect=subprocess_timeout(),
        ):
            out = ex.execute("while True: pass")
        assert out.has_error
        assert out.error.ename == "TimeoutError"
        assert "5s" in out.error.evalue

    def test_shutdown_removes_container(self):
        ex = DockerExecutor()
        ex._started = True
        with patch("kerno.isolation_docker.subprocess.run") as run:
            ex.shutdown()
        cmd = run.call_args[0][0]
        assert cmd[:3] == ["docker", "rm", "-f"]
        assert ex._started is False

    def test_docker_available(self):
        ok = MagicMock(returncode=0)
        with patch("kerno.isolation_docker.subprocess.run", return_value=ok):
            assert docker_available() is True
        bad = MagicMock(returncode=1)
        with patch("kerno.isolation_docker.subprocess.run", return_value=bad):
            assert docker_available() is False


def subprocess_timeout():
    import subprocess as sp

    def _raise(*a, **kw):
        raise sp.TimeoutExpired(cmd=["docker"], timeout=5)
    return _raise


class TestSharedMemoryMutationIsolation:
    """Audit P1: SharedMemory deep-copy isolation against host mutation."""

    def test_shared_memory_put_mutation_isolated(self):
        from kerno.isolation import SharedMemory

        shared = SharedMemory()
        orig = {"items": [1, 2, 3], "nested": {"val": 42}}
        shared.put("data", orig, "agent-a")

        # Mutating original object after put must not affect store
        orig["items"].append(999)
        orig["nested"]["val"] = 100

        retrieved = shared.get("data")
        assert retrieved is not None
        assert retrieved.value["items"] == [1, 2, 3]
        assert retrieved.value["nested"]["val"] == 42

    def test_shared_memory_get_mutation_isolated(self):
        from kerno.isolation import SharedMemory

        shared = SharedMemory()
        shared.put("data", {"items": [1, 2, 3]}, "agent-a")

        # Mutating retrieved object must not affect store
        r1 = shared.get("data")
        r1.value["items"].append(555)

        r2 = shared.get("data")
        assert r2.value["items"] == [1, 2, 3]
