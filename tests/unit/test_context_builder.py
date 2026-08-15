# tests/unit/test_context_builder.py
"""Unit tests for PromptBuilder."""

import pytest
from kerno.context.builder import PromptBuilder
from kerno.types import Cell, CellOutput, Message


def make_cell(num: int, code: str, stdout: str = "") -> Cell:
    return Cell(
        code     = code,
        output   = CellOutput(stdout=stdout),
        cell_num = num,
    )


class TestPromptBuilder:

    @pytest.fixture
    def builder(self):
        return PromptBuilder()

    def test_returns_message_list(self, builder):
        msgs = builder.build(
            task      = "test task",
            history   = [],
            namespace = '{"df": "DataFrame[100, 5]"}',
        )
        assert isinstance(msgs, list)
        assert all(isinstance(m, Message) for m in msgs)

    def test_first_message_is_system(self, builder):
        msgs = builder.build(task="test", history=[], namespace="{}")
        assert msgs[0].role == "system"

    def test_system_contains_namespace(self, builder):
        msgs = builder.build(
            task      = "test",
            history   = [],
            namespace = '{"df": "DataFrame[100,5]"}',
        )
        assert "df" in msgs[0].content

    def test_system_contains_task(self, builder):
        msgs = builder.build(
            task      = "Analyze sales by region",
            history   = [],
            namespace = "{}",
        )
        assert "Analyze sales by region" in msgs[0].content

    def test_history_cells_appear_as_messages(self, builder):
        history = [
            make_cell(1, "df = pd.read_csv('x.csv')", "Shape: (100, 5)\n"),
            make_cell(2, "df.describe()", ""),
        ]
        msgs = builder.build(task="test", history=history, namespace="{}")

        # system + 2×(assistant + user) = 5 messages
        assert len(msgs) == 5

        roles = [m.role for m in msgs]
        assert roles == ["system", "assistant", "user", "assistant", "user"]

    def test_history_truncation(self, builder):
        history = [make_cell(i, f"x_{i} = {i}") for i in range(50)]
        msgs    = builder.build(
            task      = "test",
            history   = history,
            namespace = "{}",
            max_cells = 5,
        )
        # system + 5×2 = 11
        assert len(msgs) == 11

    def test_summary_in_system_prompt(self, builder):
        msgs = builder.build(
            task      = "test",
            history   = [],
            namespace = "{}",
            summary   = "Previously: loaded df with 1000 rows.",
        )
        assert "Previously: loaded df" in msgs[0].content

    def test_reflection_build(self, builder):
        cell = make_cell(1, "df.describe()", "count  100\nmean   42.0\n")
        msgs = builder.build_reflection(cell)

        assert len(msgs) == 1
        assert msgs[0].role == "user"
        assert "df.describe()" in msgs[0].content
        assert "42.0" in msgs[0].content
