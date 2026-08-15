"""Unit tests for SkillSet composition."""

import pytest

from kerno.skills.composer import SkillSet, CodeSkill


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_skill(name="test", code="x = 1", dependencies=None, version="1.0.0"):
    """Create a CodeSkill for testing."""
    return CodeSkill(
        name=name,
        code=code,
        dependencies=dependencies or [],
        version=version,
    )


# ── TestSkillSet ──────────────────────────────────────────────────────────────

class TestSkillSet:
    """Tests for SkillSet operations."""

    def test_add(self):
        ss = SkillSet()
        ss.add(make_skill("a", "a_code"))
        assert len(ss) == 1
        assert "a" in ss.names()

    def test_add_all(self):
        ss = SkillSet()
        ss.add_all([
            make_skill("a", "a_code"),
            make_skill("b", "b_code"),
        ])
        assert len(ss) == 2

    def test_add_duplicate_skipped(self):
        ss = SkillSet()
        ss.add(make_skill("a", "v1"))
        ss.add(make_skill("a", "v2"))  # Duplicate name — skipped
        assert ss._skills["a"].code == "v1"  # Original kept
        assert len(ss) == 1

    def test_remove(self):
        ss = SkillSet()
        ss.add(make_skill("a", "a_code"))
        ss.add(make_skill("b", "b_code"))
        ss.remove("a")
        assert len(ss) == 1
        assert "b" in ss.names()

    def test_remove_nonexistent(self):
        ss = SkillSet()
        ss.add(make_skill("a", "a_code"))
        ss.remove("z")  # Doesn't exist — no error
        assert len(ss) == 1

    def test_replace(self):
        ss = SkillSet()
        ss.add(make_skill("a", "v1"))
        ss.replace("a", make_skill("a", "v2"))
        assert ss._skills["a"].code == "v2"
        assert len(ss) == 1

    def test_replace_nonexistent(self):
        ss = SkillSet()
        ss.replace("z", make_skill("z", "code"))  # No effect
        assert len(ss) == 0

    def test_or_merge(self):
        s1 = SkillSet()
        s1.add(make_skill("a", "a_code"))
        s2 = SkillSet()
        s2.add(make_skill("b", "b_code"))
        merged = s1 | s2
        assert len(merged) == 2
        assert set(merged.names()) == {"a", "b"}

    def test_or_merge_override(self):
        s1 = SkillSet()
        s1.add(make_skill("a", "v1"))
        s2 = SkillSet()
        s2.add(make_skill("a", "v2"))
        merged = s1 | s2
        assert merged._skills["a"].code == "v2"

    def test_sub_remove(self):
        ss = SkillSet()
        ss.add(make_skill("a", "a_code"))
        ss.add(make_skill("b", "b_code"))
        ss.add(make_skill("c", "c_code"))
        result = ss - ["a", "c"]
        assert len(result) == 1
        assert "b" in result.names()

    def test_deduplication(self):
        ss = SkillSet()
        ss.add(make_skill("a", "v1"))
        ss.add(make_skill("b", "v1"))
        ss.add(make_skill("a", "v2"))  # Duplicate "a"
        assert len(ss) == 2  # Only a, b

    def test_len(self):
        ss = SkillSet()
        assert len(ss) == 0
        ss.add(make_skill("a", "a_code"))
        assert len(ss) == 1

    def test_dependency_ordering(self):
        ss = SkillSet()
        ss.add(make_skill("viz", "viz_code", dependencies=["data"]))
        ss.add(make_skill("data", "data_code"))
        order = ss._load_order()
        assert order.index("data") < order.index("viz")

    def test_combined_code(self):
        ss = SkillSet()
        ss.add(make_skill("a", "x = 1"))
        ss.add(make_skill("b", "y = 2"))
        combined = ss.combined_code()
        assert "x = 1" in combined
        assert "y = 2" in combined
