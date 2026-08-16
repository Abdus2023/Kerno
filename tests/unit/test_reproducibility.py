"""
Unit tests for reproducibility manifests (audit #57, #14) and the
notebook projection with execution correlation (audit #56).
"""

import json

import nbformat

from kerno.audit.notebook import NotebookAuditTrail
from kerno.execution.engine import ExecutionEngine
from kerno.reproducibility import (
    EnvironmentSnapshot, ReproducibilityManifest,
    build_manifest, hash_file, hash_text, save_manifest,
)
from kerno.types import Cell, CellOutput, SessionResult, SessionStatus


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


def make_result(n_cells=2):
    cells = [
        Cell(code=f"x = {i}", output=CellOutput(stdout=str(i)),
             cell_num=i + 1, author="agent")
        for i in range(n_cells)
    ]
    return SessionResult(
        session_id="sess-repro", task="Analyze sales",
        status=SessionStatus.COMPLETE, cells=cells,
    )


class TestEnvironmentSnapshot:

    def test_capture_has_expected_fields(self):
        env = EnvironmentSnapshot.capture()
        assert env.python_version  # e.g. "3.11.x"
        assert env.platform
        assert env.kernel_spec == "python3"
        assert isinstance(env.packages, dict)
        assert "pandas" in env.packages  # kerno depends on it
        assert env.env_var_names == sorted(env.env_var_names)

    def test_env_var_names_never_values(self):
        import os
        os.environ["KERNO_TEST_SECRET"] = "super-secret-value-xyz"
        try:
            env = EnvironmentSnapshot.capture()
            assert "KERNO_TEST_SECRET" in env.env_var_names
            # The value must never be recorded — only the name
            assert "super-secret-value-xyz" not in json.dumps(env.to_dict())
        finally:
            os.environ.pop("KERNO_TEST_SECRET", None)

    def test_summary_is_light(self):
        env = EnvironmentSnapshot.capture()
        summary = env.summary()
        assert set(summary) == {"python", "platform", "kernel", "packages"}


class TestHashes:

    def test_hash_text_deterministic(self):
        assert hash_text("abc") == hash_text("abc")
        assert hash_text("abc") != hash_text("abd")
        assert len(hash_text("x")) == 64  # full sha256

    def test_hash_file(self, tmp_path):
        p = tmp_path / "data.csv"
        p.write_text("a,b\n1,2\n")
        h1 = hash_file(p)
        assert len(h1) == 64
        p.write_text("a,b\n1,3\n")
        assert hash_file(p) != h1

    def test_hash_file_missing_returns_unavailable(self, tmp_path):
        result = build_manifest(
            make_result(),
            artifact_paths=[str(tmp_path / "ghost.csv")],
        )
        assert result.artifact_hashes[str(tmp_path / "ghost.csv")] == "unavailable"


class TestManifest:

    def test_build_manifest_fields(self):
        m = build_manifest(
            make_result(),
            model_name="mock-model",
            artifact_paths=None,
            input_hashes={"data.csv": "abc123"},
            random_seeds={"np": 42},
        )
        assert m.session_id == "sess-repro"
        assert len(m.task_hash) == 64
        assert m.model_name == "mock-model"
        assert m.input_hashes == {"data.csv": "abc123"}
        assert m.random_seeds == {"np": 42}
        assert m.environment.packages

    def test_manifest_json_round_trip(self):
        m = build_manifest(make_result(), model_name="m1")
        restored = ReproducibilityManifest.from_dict(json.loads(m.to_json()))
        assert restored.session_id == m.session_id
        assert restored.task_hash == m.task_hash
        assert restored.model_name == "m1"
        assert restored.environment.python_version == m.environment.python_version

    def test_save_manifest_writes_json(self, tmp_path):
        m = build_manifest(make_result())
        path = save_manifest(m, str(tmp_path))
        assert path.name == "sess-repro.manifest.json"
        loaded = json.loads(path.read_text())
        assert loaded["session_id"] == "sess-repro"


class TestNotebookProjection:
    """Audit #56: notebook cells carry execution correlation metadata."""

    def test_cells_carry_execution_metadata(self):
        # Build a session through the engine so outputs carry execution ids
        engine = ExecutionEngine(FakeKernel())
        cells = []
        for i, code in enumerate(["x = 1", "print(x)"]):
            out = engine.execute(code, capabilities=frozenset())
            cells.append(Cell(code=code, output=out, cell_num=i + 1))
        result = SessionResult(
            session_id="s", task="t", status=SessionStatus.COMPLETE, cells=cells,
        )

        trail = NotebookAuditTrail.from_result(result)
        nb = trail._nb
        code_cells = [c for c in nb.cells if c.cell_type == "code"]
        assert len(code_cells) == 2

        first = code_cells[0]
        meta = first.metadata["kerno_execution"]
        assert meta["execution_id"] == "exec_00000001"
        assert len(meta["code_hash"]) == 16
        assert len(meta["output_hash"]) == 16

    def test_engine_denied_output_carries_execution_id(self):
        from kerno.security.allowlist import AllowList
        engine = ExecutionEngine(FakeKernel(), allowlist=AllowList.data_analysis())
        out = engine.execute("import subprocess", capabilities=frozenset())
        assert out.has_error
        assert out.execution_id == "exec_00000001"

    def test_save_embeds_manifest_metadata(self, tmp_path):
        result = make_result()
        trail = NotebookAuditTrail.from_result(result)
        manifest = build_manifest(result, model_name="m1").to_dict()

        trail.save(str(tmp_path), manifest=manifest)

        nb_path = list(tmp_path.glob("*.ipynb"))[0]
        nb = nbformat.read(nb_path, as_version=4)
        repro = nb.metadata["kerno"]["reproducibility"]
        assert repro["model"] == "m1"
        assert repro["task_hash"] == manifest["task_hash"]
        assert repro["environment"]["python"]

        # The full manifest is written next to the notebook
        manifest_path = tmp_path / "sess-repro.manifest.json"
        assert manifest_path.exists()
        assert json.loads(manifest_path.read_text())["model_name"] == "m1"

    def test_save_without_manifest_still_works(self, tmp_path):
        trail = NotebookAuditTrail.from_result(make_result())
        path = trail.save(str(tmp_path))
        assert path.exists()
        assert not list(tmp_path.glob("*.manifest.json"))


class TestNotebookRedaction:
    """Audit #67: secrets are never stored in the notebook — code source,
    reasoning, and error text all pass through the redactor."""

    class Redactor:
        def __init__(self):
            self.secret = "sk-nb-123"

        def __call__(self, text):
            return text.replace(self.secret, "[REDACTED]")

    def _cell(self, code, reason=None, error=None):
        out = CellOutput()
        if error:
            from kerno.types import CellError
            out.error = CellError(error[0], error[1])
        return Cell(code=code, output=out, cell_num=1, reasoning=reason)

    def test_code_source_redacted(self):
        redactor = self.Redactor()
        trail = NotebookAuditTrail("t", redactor=redactor)
        trail.add_cell(self._cell("api_key = 'sk-nb-123'"))

        code_cells = [c for c in trail._nb.cells if c.cell_type == "code"]
        assert "sk-nb-123" not in code_cells[0].source
        assert "[REDACTED]" in code_cells[0].source

    def test_reasoning_redacted(self):
        redactor = self.Redactor()
        trail = NotebookAuditTrail("t", redactor=redactor)
        trail.add_cell(self._cell("x = 1", reason="token is sk-nb-123"))

        md_cells = [c for c in trail._nb.cells if c.cell_type == "markdown"]
        all_text = " ".join(c.source for c in md_cells)
        assert "sk-nb-123" not in all_text

    def test_error_text_redacted(self):
        redactor = self.Redactor()
        trail = NotebookAuditTrail("t", redactor=redactor)
        trail.add_cell(self._cell("x = 1", error=("ValueError", "bad sk-nb-123")))

        md_cells = [c for c in trail._nb.cells if c.cell_type == "markdown"]
        all_text = " ".join(c.source for c in md_cells)
        assert "sk-nb-123" not in all_text

    def test_no_redactor_leaves_content(self):
        trail = NotebookAuditTrail("t")     # no redactor
        trail.add_cell(self._cell("api_key = 'sk-nb-123'"))
        code_cells = [c for c in trail._nb.cells if c.cell_type == "code"]
        assert "sk-nb-123" in code_cells[0].source


class TestVerifyEnvironment:
    """Audit #57: Verifying environment compatibility against recorded manifests."""

    def test_matching_environment_passes(self):
        from kerno.reproducibility import EnvironmentSnapshot, verify_environment

        env = EnvironmentSnapshot(
            python_version="3.11.2",
            platform="Linux",
            kernel_spec="python3",
            packages={"pandas": "2.0.0", "numpy": "1.24.0"},
        )
        compat, warnings = verify_environment(env, env)
        assert compat is True
        assert len(warnings) == 0

    def test_mismatched_python_version_warns(self):
        from kerno.reproducibility import EnvironmentSnapshot, verify_environment

        env1 = EnvironmentSnapshot("3.10.4", "Linux", "python3")
        env2 = EnvironmentSnapshot("3.11.2", "Linux", "python3")

        compat, warnings = verify_environment(env1, env2)
        assert compat is False
        assert any("Python version mismatch" in w for w in warnings)

    def test_strict_package_checks(self):
        from kerno.reproducibility import EnvironmentSnapshot, verify_environment

        env1 = EnvironmentSnapshot("3.11.2", "Linux", "python3", packages={"pandas": "2.0.0"})
        env2 = EnvironmentSnapshot("3.11.2", "Linux", "python3", packages={"pandas": "2.1.0"})

        # Non-strict ignores package diffs
        compat, warnings = verify_environment(env1, env2, strict_packages=False)
        assert compat is True

        # Strict catches package version diffs
        compat_strict, warnings_strict = verify_environment(env1, env2, strict_packages=True)
        assert compat_strict is False
        assert any("Package version mismatch" in w for w in warnings_strict)
