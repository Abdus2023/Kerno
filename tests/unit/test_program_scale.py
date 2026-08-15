"""
Tests for program-scale persistence modules:
  - provenance.py
  - vault.py
  - knowledge.py
  - capability.py
  - evolution.py
  - agent.py
"""

import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from kerno.provenance import ProvenanceRecord
from kerno.knowledge import KnowledgeEngine, Observation, ObservationKind
from kerno.capability import CapabilityRegistry, RegisteredSkill, SkillStatus
from kerno.evolution import CapabilityExtractor, SkillProposal
from kerno.vault import SessionVault, VaultIndex


# ── ProvenanceRecord tests ───────────────────────────────────────────────────

class TestProvenanceRecord:
    def test_creation(self):
        rec = ProvenanceRecord(
            object_id="df_sales",
            session_id="sess-001",
            cell_num=3,
            code="df = pd.read_csv('sales.csv')",
            input_ids=[],
            checksum=ProvenanceRecord.compute_checksum("DataFrame(100 rows)"),
        )
        assert rec.object_id == "df_sales"
        assert rec.session_id == "sess-001"
        assert rec.cell_num == 3
        assert rec.code == "df = pd.read_csv('sales.csv')"
        assert len(rec.checksum) == 16

    def test_compute_checksum(self):
        cs1 = ProvenanceRecord.compute_checksum("hello")
        cs2 = ProvenanceRecord.compute_checksum("hello")
        cs3 = ProvenanceRecord.compute_checksum("world")
        assert cs1 == cs2
        assert cs1 != cs3
        assert len(cs1) == 16

    def test_to_dict_roundtrip(self):
        rec = ProvenanceRecord(
            object_id="x",
            code="x = 42",
            input_ids=["y"],
            checksum="abc123",
        )
        d = rec.to_dict()
        assert d["object_id"] == "x"
        assert d["input_ids"] == ["y"]
        rec2 = ProvenanceRecord.from_dict(d)
        assert rec2.object_id == "x"
        assert rec2.code == "x = 42"
        assert rec2.input_ids == ["y"]

    def test_defaults(self):
        rec = ProvenanceRecord(object_id="test")
        assert rec.session_id == ""
        assert rec.cell_num == 0
        assert rec.code == ""
        assert rec.input_ids == []
        assert rec.checksum == ""
        assert rec.reconstruction is None


# ── VaultIndex tests ─────────────────────────────────────────────────────────

class TestVaultIndex:
    def test_init_schema(self, tmp_path):
        idx = VaultIndex(db_path=tmp_path / "test.db")
        # Should have created tables
        cur = idx._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = [row[0] for row in cur.fetchall()]
        assert "sessions" in tables
        assert "sessions_fts" in tables
        idx.close()

    def test_add_and_query(self, tmp_path):
        from kerno.types import Cell, CellOutput, SessionResult, SessionStatus
        idx = VaultIndex(db_path=tmp_path / "test.db")

        result = SessionResult(
            session_id="sess-001",
            task="Build a churn model",
            status=SessionStatus.COMPLETE,
            cells=[
                Cell(code="df = pd.read_csv('data.csv')", output=CellOutput(), cell_num=1),
                Cell(code="model = LogisticRegression()", output=CellOutput(), cell_num=2),
            ],
            summary="Built a churn model with 85% accuracy",
            started_at=time.time(),
        )
        idx.add(result)

        hits = idx.query("churn")
        assert len(hits) >= 1
        assert hits[0]["task"] == "Build a churn model"
        idx.close()


# ── SessionVault tests ───────────────────────────────────────────────────────

class TestSessionVault:
    def test_store_and_reproduce(self, tmp_path):
        from kerno.types import Cell, CellOutput, SessionResult, SessionStatus
        vault = SessionVault(directory=tmp_path / "vault")

        result = SessionResult(
            session_id="sess-001",
            task="Analyze sales trends",
            status=SessionStatus.COMPLETE,
            cells=[
                Cell(code="df = pd.read_csv('data.csv')", output=CellOutput(stdout="loaded"), cell_num=1),
            ],
            summary="Sales are trending upward",
            started_at=time.time(),
        )

        sid = vault.store(result)
        assert sid == "sess-001"

        reproduced = vault.reproduce("sess-001")
        assert reproduced is not None
        assert reproduced.task == "Analyze sales trends"
        assert reproduced.status == SessionStatus.COMPLETE

        # Non-existent session
        assert vault.reproduce("nonexistent") is None
        vault.close()

    def test_query(self, tmp_path):
        from kerno.types import Cell, CellOutput, SessionResult, SessionStatus
        vault = SessionVault(directory=tmp_path / "vault")

        result = SessionResult(
            session_id="sess-002",
            task="Build churn prediction model",
            status=SessionStatus.COMPLETE,
            cells=[Cell(code="model = fit()", output=CellOutput(), cell_num=1)],
            summary="Churn model built",
            started_at=time.time(),
        )
        vault.store(result)

        hits = vault.query("churn")
        assert len(hits) >= 1
        vault.close()


# ── Observation tests ────────────────────────────────────────────────────────

class TestObservation:
    def test_creation(self):
        obs = Observation(
            content="Column 'age' has type float64",
            kind=ObservationKind.SCHEMA,
            confidence=0.8,
            domain="health",
        )
        assert obs.content == "Column 'age' has type float64"
        assert obs.kind == ObservationKind.SCHEMA
        assert obs.confidence == 0.8

    def test_reinforce(self):
        obs = Observation(content="test", confidence=0.5)
        obs.reinforce()
        assert abs(obs.confidence - 0.55) < 0.001
        obs.reinforce()
        assert abs(obs.confidence - 0.6) < 0.001

    def test_decay(self):
        obs = Observation(content="test", confidence=1.0)
        obs.decay(0.9)
        assert abs(obs.confidence - 0.9) < 0.001

    def test_to_dict_roundtrip(self):
        obs = Observation(
            content="test obs",
            kind=ObservationKind.ERROR,
            confidence=0.7,
            domain="finance",
            tags=["error", "timeout"],
        )
        d = obs.to_dict()
        obs2 = Observation.from_dict(d)
        assert obs2.content == "test obs"
        assert obs2.kind == ObservationKind.ERROR
        assert obs2.confidence == 0.7
        assert obs2.tags == ["error", "timeout"]

    def test_confidence_bounds(self):
        obs = Observation(content="test", confidence=0.99)
        obs.reinforce()  # Should cap at 1.0
        assert obs.confidence == 1.0

        obs.decay(0.0)  # Should floor at 0.0
        assert obs.confidence == 0.0


# ── KnowledgeEngine tests ────────────────────────────────────────────────────

class TestKnowledgeEngine:
    def test_learn_from_session(self, tmp_path):
        from kerno.types import Cell, CellError, CellOutput, SessionResult, SessionStatus
        engine = KnowledgeEngine(directory=tmp_path / "knowledge")

        result = SessionResult(
            session_id="sess-001",
            task="Analyze customer data",
            status=SessionStatus.COMPLETE,
            cells=[
                Cell(code="df = pd.read_csv('data.csv')", output=CellOutput(stdout="loaded"), cell_num=1),
                Cell(
                    code="df.groupby('city').count()",
                    output=CellOutput(error=CellError(ename="KeyError", evalue="'city'")),
                    cell_num=2,
                ),
                Cell(code="df.groupby('region').count()", output=CellOutput(stdout="result"), cell_num=3),
            ],
            summary="Analyzed customer data by region",
            started_at=time.time(),
        )

        new_obs = engine.learn_from_session(result)
        assert len(new_obs) > 0

        # Should find an error observation
        error_obs = [o for o in new_obs if o.kind == ObservationKind.ERROR]
        assert len(error_obs) > 0

        # Should find a recovery observation
        recovery_obs = [o for o in new_obs if "recovery" in o.tags]
        assert len(recovery_obs) > 0

    def test_observe_schema(self, tmp_path):
        engine = KnowledgeEngine(directory=tmp_path / "knowledge")
        schema = {"age": "float64", "name": "object", "city": "category"}
        obs_list = engine.observe_schema(schema)
        assert len(obs_list) == 3

    def test_schema_context(self, tmp_path):
        engine = KnowledgeEngine(directory=tmp_path / "knowledge")
        schema = {"age": "float64", "name": "object"}
        ctx = engine.schema_context(schema)
        assert "age: float64" in ctx
        assert "name: object" in ctx

    def test_relevant_to(self, tmp_path):
        engine = KnowledgeEngine(directory=tmp_path / "knowledge")
        # Add some observations directly
        obs1 = Observation(content="Churn prediction works with logistic regression", confidence=0.8, domain="marketing")
        obs2 = Observation(content="Sales data has monthly seasonality", confidence=0.7, domain="finance")
        engine._observations[obs1.id] = obs1
        engine._observations[obs2.id] = obs2
        engine._save()

        results = engine.relevant_to("churn")
        assert len(results) > 0
        assert any("churn" in o.content.lower() for o in results)

    def test_context_for(self, tmp_path):
        engine = KnowledgeEngine(directory=tmp_path / "knowledge")
        obs = Observation(content="Customers tend to churn after 6 months", confidence=0.7)
        engine._observations[obs.id] = obs

        ctx = engine.context_for("churn model")
        assert ctx != ""
        assert "churn" in ctx.lower()

    def test_contradict(self, tmp_path):
        engine = KnowledgeEngine(directory=tmp_path / "knowledge")
        obs1 = Observation(content="Churn rate is 5%", confidence=0.8, id="obs-001")
        engine._observations[obs1.id] = obs1

        new_obs = engine.contradict("obs-001", "Churn rate is actually 15%", session_id="sess-002")
        assert new_obs.contradicts == ["obs-001"]
        assert obs1.confidence < 0.8  # Should have decreased

    def test_persistence(self, tmp_path):
        engine = KnowledgeEngine(directory=tmp_path / "knowledge")
        obs = Observation(content="test persistence", confidence=0.5)
        engine._observations[obs.id] = obs
        engine._save()

        # Load fresh
        engine2 = KnowledgeEngine(directory=tmp_path / "knowledge")
        assert len(engine2._observations) > 0
        assert any(o.content == "test persistence" for o in engine2._observations.values())


# ── CapabilityRegistry tests ─────────────────────────────────────────────────

class TestCapabilityRegistry:
    def test_register(self, tmp_path):
        cap = CapabilityRegistry(directory=tmp_path / "caps")
        skill = cap.register(
            name="load_sales",
            code="df = pd.read_csv('sales.csv')",
            description="Loads sales data",
            session_id="sess-001",
        )
        assert skill.name == "load_sales"
        assert skill.status == SkillStatus.ACTIVE

    def test_register_supersedes(self, tmp_path):
        cap = CapabilityRegistry(directory=tmp_path / "caps")
        old = cap.register(name="load_data", code="old code", version="1.0")
        new = cap.register(name="load_data", code="new code", version="2.0")

        assert old.status == SkillStatus.SUPERSEDED
        assert old.superseded_by == new.skill_id
        assert new.status == SkillStatus.ACTIVE

    def test_record_use(self, tmp_path):
        cap = CapabilityRegistry(directory=tmp_path / "caps")
        skill = cap.register(name="analyze", code="x = 1")
        updated = cap.record_use("analyze", success=True)
        assert updated.use_count == 1
        assert updated.success_rate == 1.0
        assert updated.last_used_at is not None

        updated = cap.record_use("analyze", success=False)
        assert updated.use_count == 2
        assert abs(updated.success_rate - 0.5) < 0.001

    def test_get_by_name(self, tmp_path):
        cap = CapabilityRegistry(directory=tmp_path / "caps")
        cap.register(name="skill_a", code="a = 1")
        cap.register(name="skill_b", code="b = 2")

        found = cap.get_by_name("skill_a")
        assert found is not None
        assert found.name == "skill_a"

        not_found = cap.get_by_name("nonexistent")
        assert not_found is None

    def test_active_skills(self, tmp_path):
        cap = CapabilityRegistry(directory=tmp_path / "caps")
        cap.register(name="active_skill", code="x = 1")
        old = cap.register(name="deprecated_skill", code="y = 2")
        cap.update(old.skill_id, status=SkillStatus.DEPRECATED)

        active = cap.active_skills()
        assert len(active) == 1
        assert active[0].name == "active_skill"

    def test_to_skill_set(self, tmp_path):
        cap = CapabilityRegistry(directory=tmp_path / "caps")
        cap.register(name="load", code="load()", dependencies=[], tags=["data"])
        cap.register(name="transform", code="transform()", dependencies=["load"])

        ss = cap.to_skill_set()
        assert len(ss) == 2
        assert "load" in ss.names()
        assert "transform" in ss.names()

    def test_manifest(self, tmp_path):
        cap = CapabilityRegistry(directory=tmp_path / "caps")
        cap.register(name="skill_a", code="x = 1")

        manifest = cap.manifest()
        assert manifest["total_skills"] == 1
        assert manifest["active"] == 1

    def test_changelog(self, tmp_path):
        cap = CapabilityRegistry(directory=tmp_path / "caps")
        cap.register(name="skill_a", code="x = 1")
        cap.record_use("skill_a")

        log = cap.changelog()
        assert len(log) >= 2
        assert log[0]["action"] == "register"

    def test_persistence(self, tmp_path):
        cap = CapabilityRegistry(directory=tmp_path / "caps")
        cap.register(name="persisted_skill", code="z = 3")

        # Load fresh
        cap2 = CapabilityRegistry(directory=tmp_path / "caps")
        found = cap2.get_by_name("persisted_skill")
        assert found is not None
        assert found.name == "persisted_skill"


# ── CapabilityExtractor tests ────────────────────────────────────────────────

class TestCapabilityExtractor:
    def test_extract_load_pattern(self):
        from kerno.types import Cell, CellOutput, SessionResult, SessionStatus
        extractor = CapabilityExtractor()

        result = SessionResult(
            session_id="sess-001",
            task="Load data",
            status=SessionStatus.COMPLETE,
            cells=[
                Cell(
                    code="df = pd.read_csv('sales.csv')",
                    output=CellOutput(stdout="DataFrame loaded"),
                    cell_num=1,
                ),
            ],
            started_at=time.time(),
        )

        proposals = extractor.extract(result)
        assert len(proposals) > 0
        assert any(p.pattern_type == "load" for p in proposals)

    def test_extract_transform_pattern(self):
        from kerno.types import Cell, CellOutput, SessionResult, SessionStatus
        extractor = CapabilityExtractor()

        result = SessionResult(
            session_id="sess-002",
            task="Aggregate data",
            status=SessionStatus.COMPLETE,
            cells=[
                Cell(
                    code="result = df.groupby('region').agg({'sales': 'sum'})",
                    output=CellOutput(stdout="aggregated"),
                    cell_num=1,
                ),
            ],
            started_at=time.time(),
        )

        proposals = extractor.extract(result)
        assert len(proposals) > 0
        assert any(p.pattern_type == "transform" for p in proposals)

    def test_extract_skips_errors(self):
        from kerno.types import Cell, CellError, CellOutput, SessionResult, SessionStatus
        extractor = CapabilityExtractor()

        result = SessionResult(
            session_id="sess-003",
            task="test",
            status=SessionStatus.COMPLETE,
            cells=[
                Cell(code="bad code", output=CellOutput(error=CellError("SyntaxError", "bad")), cell_num=1),
            ],
            started_at=time.time(),
        )

        proposals = extractor.extract(result)
        assert len(proposals) == 0

    def test_extract_skips_short_cells(self):
        from kerno.types import Cell, CellOutput, SessionResult, SessionStatus
        extractor = CapabilityExtractor()

        result = SessionResult(
            session_id="sess-004",
            task="test",
            status=SessionStatus.COMPLETE,
            cells=[
                Cell(code="x = 1", output=CellOutput(stdout="1"), cell_num=1),  # Too short
            ],
            started_at=time.time(),
        )

        proposals = extractor.extract(result)
        assert len(proposals) == 0

    def test_merge_similar(self):
        from kerno.types import Cell, CellOutput, SessionResult, SessionStatus
        extractor = CapabilityExtractor()

        result = SessionResult(
            session_id="sess-005",
            task="Load and transform",
            status=SessionStatus.COMPLETE,
            cells=[
                Cell(code="df1 = pd.read_csv('a.csv')", output=CellOutput(stdout="ok"), cell_num=1),
                Cell(code="df2 = pd.read_csv('b.csv')", output=CellOutput(stdout="ok"), cell_num=2),
            ],
            started_at=time.time(),
        )

        proposals = extractor.extract(result)
        # Should merge similar load proposals
        load_proposals = [p for p in proposals if p.pattern_type == "load"]
        assert len(load_proposals) <= 2


# ── Agent dataclass tests ────────────────────────────────────────────────────

class TestAgentDataclasses:
    def test_agent_identity(self):
        from kerno.agent import AgentIdentity
        identity = AgentIdentity(name="analyst", description="Data analyst")
        assert identity.name == "analyst"
        assert len(identity.goals) == 3

        d = identity.to_dict()
        identity2 = AgentIdentity.from_dict(d)
        assert identity2.name == "analyst"

    def test_agent_profile(self):
        from kerno.agent import AgentProfile, AgentIdentity
        identity = AgentIdentity(name="test-agent")
        profile = AgentProfile(name="test-agent", identity=identity)
        assert profile.name == "test-agent"
        assert profile.total_sessions == 0

        d = profile.to_dict()
        profile2 = AgentProfile.from_dict(d)
        assert profile2.name == "test-agent"
        assert profile2.identity.name == "test-agent"

    def test_session_context(self):
        from kerno.agent import SessionContext
        ctx = SessionContext(
            task="Build churn model",
            enriched_task="Build churn model\n\nKnowledge: churn patterns",
            knowledge_context="Knowledge: churn patterns",
            domain="marketing",
        )
        prompt = ctx.as_prompt_injection()
        assert "churn" in prompt
        assert "Knowledge" in prompt

    def test_session_context_empty(self):
        from kerno.agent import SessionContext
        ctx = SessionContext(task="simple task")
        assert ctx.as_prompt_injection() == ""


# ── AgentStorage tests ───────────────────────────────────────────────────────

class TestAgentStorage:
    def test_save_and_load_profile(self, tmp_path):
        from kerno.agent import AgentStorage, AgentProfile, AgentIdentity
        storage = AgentStorage(agent_name="test", directory=tmp_path / "agent")

        identity = AgentIdentity(name="test", description="Test agent")
        profile = AgentProfile(name="test", identity=identity)
        storage.save_profile(profile)

        loaded = storage.load_profile()
        assert loaded is not None
        assert loaded.name == "test"
        assert loaded.identity.name == "test"

    def test_load_nonexistent_profile(self, tmp_path):
        from kerno.agent import AgentStorage
        storage = AgentStorage(agent_name="test", directory=tmp_path / "nonexistent")
        profile = storage.load_profile()
        assert profile is None

    def test_set_llm(self, tmp_path):
        from kerno.agent import AgentStorage
        storage = AgentStorage(agent_name="test", directory=tmp_path / "agent")
        assert storage.llm is None

        def mock_llm(messages):
            return "mock response"

        storage.set_llm(mock_llm)
        assert storage.llm is not None
        assert storage.llm([]) == "mock response"

    def test_discover(self, tmp_path):
        from kerno.agent import AgentStorage, AgentProfile
        # Create one agent directory
        agent_dir = tmp_path / "agents" / "analyst"
        agent_dir.mkdir(parents=True)
        profile_path = agent_dir / "profile.json"
        profile_path.write_text(json.dumps(AgentProfile(name="analyst").to_dict()))

        storage = AgentStorage(agent_name="analyst", directory=agent_dir)
        agents = storage.discover()
        # The discover method looks at parent directory
        # Since analyst dir has profile.json, it should be discoverable
        assert isinstance(agents, list)


# ── RegisteredSkill tests ────────────────────────────────────────────────────

class TestRegisteredSkill:
    def test_creation(self):
        skill = RegisteredSkill(
            name="load_csv",
            code="pd.read_csv('data.csv')",
            description="Load CSV data",
            version="1.0.0",
            status=SkillStatus.ACTIVE,
        )
        assert skill.name == "load_csv"
        assert skill.status == SkillStatus.ACTIVE
        assert skill.use_count == 0
        assert skill.success_rate == 1.0

    def test_to_dict_roundtrip(self):
        skill = RegisteredSkill(
            name="transform",
            code="df.groupby()",
            tags=["transform", "groupby"],
        )
        d = skill.to_dict()
        skill2 = RegisteredSkill.from_dict(d)
        assert skill2.name == "transform"
        assert skill2.tags == ["transform", "groupby"]
        assert skill2.status == SkillStatus.ACTIVE


# ── SkillProposal tests ──────────────────────────────────────────────────────

class TestSkillProposal:
    def test_creation(self):
        proposal = SkillProposal(
            name="load_sales",
            code="pd.read_csv('sales.csv')",
            pattern_type="load",
            confidence=0.7,
        )
        assert proposal.name == "load_sales"
        assert proposal.pattern_type == "load"
