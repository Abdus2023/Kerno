"""Unit tests for multi-agent roles — no kernel required."""

import pytest

from kerno.loop.multi_agent import (
    AgentRole, MultiAgentLoop,
    analyst_role, critic_role, narrator_role,
    YIELD_SIGNAL, COMPLETE_SIGNAL,
)


class TestAgentRole:

    def test_analyst_role_name(self):
        role = analyst_role(lambda m: "code")
        assert role.name == "analyst"

    def test_critic_role_name(self):
        role = critic_role(lambda m: "code")
        assert role.name == "critic"

    def test_narrator_uses_complete_signal(self):
        role = narrator_role(lambda m: "code")
        assert role.yield_signal == COMPLETE_SIGNAL

    def test_analyst_yields_on_review_signal(self):
        role = analyst_role(lambda m: "code")
        assert role.yield_signal == YIELD_SIGNAL

    def test_custom_role(self):
        role = AgentRole(
            name   = "reviewer",
            llm    = lambda m: "# READY_FOR_REVIEW",
            system = "You are a code reviewer.",
            writes = ["review_"],
        )
        assert role.name   == "reviewer"
        assert role.writes == ["review_"]
