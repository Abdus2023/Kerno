"""
Unit tests for engine OUTPUT redaction (audit #68 completeness):
secrets printed by agent cells must never reach the LLM, notebook, or
persistence.
"""

from kerno.execution.engine import ORIGIN_AGENT, ORIGIN_RUNTIME, ExecutionEngine
from kerno.security.secrets import SecretBroker
from kerno.types import CellOutput

SECRET = "sk-live-abc123"


class PrintingKernel:
    """A kernel whose cell output contains the secret."""

    def __init__(self, stdout="", stderr="", result=None, displays=None):
        self._out = CellOutput(
            stdout   = stdout,
            stderr   = stderr,
            result   = result,
            displays = displays or [],
        )

    def execute(self, code, timeout=120.0, silent=False, **kwargs):
        return self._out

    def execute_silent(self, code, timeout=15.0, **kwargs):
        return ""

    @property
    def namespace(self):
        return "{}"

    @property
    def is_alive(self):
        return True


def make_engine(kernel=None, redact=True):
    broker = SecretBroker()
    broker.register("api_key", SECRET)
    return ExecutionEngine(
        kernel or PrintingKernel(stdout="token=" + SECRET),
        redactor=broker.redact,
        redact_outputs=redact,
    )


class TestOutputRedaction:

    def test_stdout_secret_redacted(self):
        engine = make_engine()
        out = engine.execute("print(api_key)")
        assert SECRET not in out.stdout
        assert "[REDACTED]" in out.stdout

    def test_stderr_and_result_redacted(self):
        engine = make_engine(PrintingKernel(
            stderr="err " + SECRET, result="res " + SECRET,
        ))
        out = engine.execute("x = 1")
        assert SECRET not in out.stderr
        assert SECRET not in out.result

    def test_display_html_redacted(self):
        engine = make_engine(PrintingKernel(
            displays=[{"html": "<b>" + SECRET + "</b>"}],
        ))
        out = engine.execute("display()")
        assert SECRET not in out.displays[0]["html"]
        assert "[REDACTED]" in out.displays[0]["html"]

    def test_runtime_origin_output_untouched(self):
        # Trusted host code's output is not scrubbed (comms/setup)
        engine = make_engine(PrintingKernel(stdout="setup " + SECRET))
        out = engine.execute("setup()", origin=ORIGIN_RUNTIME)
        assert SECRET in out.stdout

    def test_redact_outputs_disabled_leaves_output(self):
        engine = make_engine(redact=False)
        out = engine.execute("print(api_key)")
        assert SECRET in out.stdout

    def test_no_redactor_leaves_output(self):
        engine = ExecutionEngine(PrintingKernel(stdout="token=" + SECRET))
        out = engine.execute("print(api_key)")
        assert SECRET in out.stdout

    def test_redacted_output_still_audited(self):
        engine = make_engine()
        out = engine.execute("print(api_key)")
        # The record exists and the preview never contained the secret
        assert len(engine.records) == 1
        assert SECRET not in engine.records[0].code_preview
        # The output carries its execution id
        assert out.execution_id == "exec_00000001"

    def test_loop_sees_redacted_output(self):
        """End-to-end: the output the LOOP observes is already scrubbed."""
        engine = make_engine()
        out = engine.execute("print(api_key)")
        assert out.execution_id is not None
        assert "[REDACTED]" in out.stdout
