"""
End-to-end output redaction (audit #68): a cell that prints a registered
secret has it scrubbed from the session result — the LLM, notebook
projection, and persistence never see it.
"""

import pytest

from kerno import run
from kerno.security.allowlist import AllowList
from kerno.security.secrets import SecretBroker
from kerno.types import Message, SessionStatus

SECRET = "sk-live-e2e-xyz"


def make_llm(*responses):
    responses = list(responses)
    state = {"i": 0}

    def llm(messages: list[Message]) -> str:
        i = state["i"]
        state["i"] += 1
        if i < len(responses):
            return responses[i]
        return "# TASK_COMPLETE: done"

    return llm


@pytest.mark.integration
class TestOutputRedactionE2E:

    def test_secret_printed_by_cell_scrubbed_from_result(self):
        broker = SecretBroker()
        broker.register("api_key", SECRET)

        result = run(
            "Print the token",
            llm=make_llm(
                f"print('token={SECRET}')",
                "# TASK_COMPLETE: done",
            ),
            allowlist=AllowList.data_analysis(),
            redactor=broker.redact,
            max_cells=5,
            load_default_skills=False,
        )

        assert result.status == SessionStatus.COMPLETE
        # The cell ran; its output was scrubbed
        cell = result.cells[0]
        assert not cell.output.has_error
        assert SECRET not in cell.output.stdout
        assert "[REDACTED]" in cell.output.stdout

        # The recorded preview is scrubbed too
        assert SECRET not in result.final_namespace

    def test_secret_never_reaches_notebook(self, tmp_path):
        broker = SecretBroker()
        broker.register("api_key", SECRET)

        result = run(
            "Print the token",
            llm=make_llm(
                f"print('token={SECRET}')",
                "# TASK_COMPLETE: done",
            ),
            allowlist=AllowList.data_analysis(),
            redactor=broker.redact,
            max_cells=5,
            save_notebook=True,
            notebook_dir=str(tmp_path / "sessions"),
            load_default_skills=False,
        )

        nb_files = list((tmp_path / "sessions").glob("*.ipynb"))
        assert nb_files
        content = nb_files[0].read_text()
        assert SECRET not in content
        assert "[REDACTED]" in content

    def test_without_redactor_secret_visible(self):
        # Control: without a redactor the secret flows (documents the
        # need for the layer rather than asserting a leak is fine)
        result = run(
            "Print the token",
            llm=make_llm(
                f"print('token={SECRET}')",
                "# TASK_COMPLETE: done",
            ),
            allowlist=AllowList.data_analysis(),
            max_cells=5,
            load_default_skills=False,
        )
        assert SECRET in result.cells[0].output.stdout
