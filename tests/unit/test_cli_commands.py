"""
Unit tests for the CLI resume/fork commands (parser wiring + session
loading).
"""

import json

from kerno.types import Cell, CellOutput, SessionResult, SessionStatus


class TestCliResumeFork:

    def test_resume_parser_has_expected_args(self):
        from kerno.cli.main import main
        import sys
        old = sys.argv
        sys.argv = ["kerno", "resume", "nb.ipynb",
                    "--task", "t", "--loop", "plan",
                    "--max-cells", "7", "--security", "data_analysis"]
        try:
            code = main()
        except SystemExit as e:
            code = e.code
        finally:
            sys.argv = old
        # The parser ACCEPTED the args (no argparse SystemExit(2)); the
        # command fails later at LLM build (no API key) — that's the
        # parse-success signal.
        assert code in (0, 1)

    def test_fork_parser_requires_at_cell(self):
        import sys
        from kerno.cli.main import main
        old = sys.argv
        sys.argv = ["kerno", "fork", "nb.ipynb"]     # missing --at-cell
        try:
            main()
            assert False, "expected SystemExit(2) for missing required arg"
        except SystemExit as e:
            assert e.code == 2
        finally:
            sys.argv = old

    def test_fork_session_round_trip_through_json(self, tmp_path):
        """The fork command path: session JSON → fork_session."""
        from kerno.session import fork_session, session_from_dict, save_session
        from kerno.types import Message

        original = SessionResult(
            session_id="sess-cli", task="analyze",
            status=SessionStatus.INTERRUPTED,
            cells=[
                Cell(code="x = 21", output=CellOutput(stdout=""), cell_num=1),
            ],
        )
        path = save_session(original, str(tmp_path / "s.json"))

        def llm(messages: list[Message]) -> str:
            return "y = x * 2\nprint(y)\n# TASK_COMPLETE: done"

        data = json.loads(path.read_text())
        forked = fork_session(
            session_from_dict(data), llm, up_to_cell=1,
        )
        assert len(forked.cells) == 2
        assert forked.cells[0].code == "x = 21"
        assert "y = x * 2" in forked.cells[1].code


class TestCliDryRunFallback:
    """--dry-run works without an API key via ScriptedBrain (audit #91)."""

    def test_dry_run_uses_scripted_brain_without_key(self, monkeypatch, capsys):
        import sys
        from kerno.cli import main as cli

        # No API keys configured
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        # build_llm would return a lazy anthropic client that fails on
        # first call — simulate that
        def fake_build_llm(provider, model, config):
            from kerno.types import Message

            def llm(messages: list[Message]) -> str:
                raise RuntimeError("no api key")
            return llm

        monkeypatch.setattr(cli, "build_llm", fake_build_llm)
        # Isolate the config load (no .kerno/config.json dependency)
        monkeypatch.setattr(cli, "load_config",
                            lambda path: cli.KernoConfig if hasattr(cli, "KernoConfig")
                            else __import__("kerno.config", fromlist=["KernoConfig"]).KernoConfig())

        old = sys.argv
        sys.argv = ["kerno", "run", "validate me", "--dry-run"]
        try:
            code = cli.main()
        except SystemExit as e:
            code = e.code
        finally:
            sys.argv = old

        assert code == 0, "dry-run without an API key should succeed"
        out = capsys.readouterr().out
        assert "ScriptedBrain" in out
        assert "COMPLETE" in out

    def test_dry_run_with_key_uses_real_llm(self, monkeypatch, capsys):
        import sys
        from kerno.cli import main as cli

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        used = []
        def fake_build_llm(provider, model, config):
            used.append(provider)
            from kerno.types import Message
            def llm(messages: list[Message]) -> str:
                return "# TASK_COMPLETE: done"
            return llm

        monkeypatch.setattr(cli, "build_llm", fake_build_llm)
        monkeypatch.setattr(cli, "load_config",
                            lambda path: __import__("kerno.config", fromlist=["KernoConfig"]).KernoConfig())

        old = sys.argv
        sys.argv = ["kerno", "run", "validate me", "--dry-run"]
        try:
            code = cli.main()
        except SystemExit as e:
            code = e.code
        finally:
            sys.argv = old

        assert code == 0
        assert used == ["anthropic"]          # real LLM path taken
        out = capsys.readouterr().out
        assert "ScriptedBrain" not in out     # no fallback
