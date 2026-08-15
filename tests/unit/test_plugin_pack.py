"""Tests for the powerful plugin pack."""

import json

from kerno import powerful_pack
from kerno.plugins.pack.artifacts import ArtifactTrackerPlugin
from kerno.plugins.pack.budget import BudgetPlugin
from kerno.plugins.pack.guardrails import GuardrailPolicy, SafetyGuardrailPlugin
from kerno.plugins.pack.progress import ProgressPlugin
from kerno.plugins.pack.quality import SessionQualityPlugin
from kerno.plugins.pack.telemetry import TelemetryPlugin
from kerno.types import Cell, CellError, CellOutput, SessionResult, SessionStatus


def _cell(code: str = "x = 1", output: str = "", cell_num: int = 1, **output_kwargs) -> Cell:
    return Cell(
        code=code,
        output=CellOutput(stdout=output, **output_kwargs),
        cell_num=cell_num,
    )


def test_powerful_pack_registers_default_plugins():
    pack = powerful_pack()
    assert len(pack) == 8
    names = [p.name for p in pack._plugins]
    assert "safety_guardrails" in names
    assert "artifact_tracker" in names
    assert "telemetry" in names


def test_progress_plugin_emits_lifecycle_messages(capsys):
    plugin = ProgressPlugin(preview_chars=20)
    plugin.on_session_start("analyze data", "session-123")
    plugin.on_cell_complete(_cell("print('hello world')", output="hello world"))
    plugin.on_session_complete(SessionResult(
        "session-123", "analyze data", SessionStatus.COMPLETE, []
    ))
    out = capsys.readouterr().out
    assert "session-12" in out
    assert "cell 1" in out
    assert "session complete" in out


def test_safety_guardrail_detects_unsafe_call_and_path():
    plugin = SafetyGuardrailPlugin(policy=GuardrailPolicy(max_lines=50))
    plugin.on_cell_complete(_cell(
        "import os\nos.system('rm -rf /')\nopen('/etc/passwd').read()",
        cell_num=3,
    ))
    rules = {(v.rule, v.severity) for v in plugin.violations}
    assert ("call", "critical") in rules
    assert ("path", "warning") in rules


def test_budget_plugin_tracks_usage_and_warns():
    plugin = BudgetPlugin(max_cells=2, max_seconds=1000)
    plugin.on_session_start("task", "sid")
    plugin.on_cell_complete(_cell("x=1", "x", cell_num=1))
    plugin.on_cell_complete(_cell("y=2", "y", cell_num=2))
    assert plugin.snapshot().budget_exceeded is True
    assert plugin.snapshot().cells == 2


def test_artifact_tracker_discovers_created_files(tmp_path):
    target = tmp_path / "out.csv"
    code = f"import pandas as pd\npd.DataFrame({{'x':[1]}}).to_csv(r'{target}', index=False)"
    exec(code, {})

    tracker = ArtifactTrackerPlugin(root=tmp_path)
    tracker.on_cell_complete(_cell(code, cell_num=1))
    tracker.on_session_complete(SessionResult(
        "sid", "task", SessionStatus.COMPLETE, []
    ))
    assert any(str(target) in str(p) for p in tracker.created)


def test_telemetry_writes_jsonl_events(tmp_path):
    plugin = TelemetryPlugin(directory=str(tmp_path))
    plugin.on_session_start("task", "sid-1")
    plugin.on_cell_complete(_cell("print(1)", "1", duration=0.2, cell_num=1))
    plugin.on_session_complete(SessionResult(
        "sid-1", "task", SessionStatus.COMPLETE, []
    ))
    path = tmp_path / "sid-1.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["event"] for r in records] == [
        "session_start", "cell_complete", "session_complete"
    ]


def test_quality_plugin_aggregates_metrics():
    plugin = SessionQualityPlugin()
    plugin.on_session_start("task", "sid")
    plugin.on_cell_complete(_cell("x=1", "1", images=["png"], displays=[{"html": "t"}]))

    class _Classified:
        error_class = type("_E", (), {"name": "SYNTAX_ERROR"})()
        recovery_hint = "fix it"

    plugin.on_error(
        _cell("bad", CellOutput(error=CellError("SyntaxError", "bad")), cell_num=2),
        _Classified(),
    )
    plugin.on_cell_complete(_cell("x=2", "2", cell_num=3))
    plugin.on_session_complete(SessionResult("sid", "task", SessionStatus.COMPLETE, []))
    assert plugin.report.cells == 3
    assert plugin.report.errors == 1
    assert plugin.report.images == 1
    assert plugin.report.displays == 1
    assert plugin.report.error_classes["SYNTAX_ERROR"] == 1
