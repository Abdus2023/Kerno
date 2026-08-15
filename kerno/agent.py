"""
ProgramAgent: an agent that grows, learns, and persists across sessions.

The ProgramAgent is Level 5 of the persistence taxonomy — program-scale
architecture.  Unlike a single Session.run(), the ProgramAgent:

  - Has an identity (name, goals, accumulated knowledge)
  - Builds a context for each task from accumulated knowledge
  - Proposes new skills from successful sessions
  - Tracks schema knowledge from data it has seen
  - Persists its profile, capabilities, and knowledge between runs

Design:
  AgentProfile → who the agent is (identity + stats)
  AgentIdentity → name, goals, personality traits
  SessionContext → enriched task + knowledge + capabilities
  ProgramAgent → orchestrator tying all subsystems together
  AgentStorage → persistence layer for the agent's state

The agent is NOT an LLM in a loop — it's an architecture that
*uses* the LLM-loop as one component among many.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from kerno.capability import CapabilityRegistry, RegisteredSkill, SkillStatus
from kerno.evolution import CapabilityExtractor, SkillProposal
from kerno.knowledge import KnowledgeEngine, Observation, ObservationKind
from kerno.provenance import ProvenanceRecord
from kerno.skills.composer import SkillSet
from kerno.types import SessionResult, SessionStatus
from kerno.vault import SessionVault


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class AgentIdentity:
    """
    The agent's self-concept: who it is, what it's for.
    """
    name:            str   = "kerno-agent"
    description:     str   = "A data analysis agent"
    goals:           list[str] = field(default_factory=lambda: [
        "Help the user analyse data accurately",
        "Learn from past sessions",
        "Propose reusable skills",
    ])
    personality:     dict      = field(default_factory=lambda: {
        "cautious": 0.7,
        "curious":  0.5,
        "verbose":  0.3,
    })

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "description": self.description,
            "goals":       self.goals,
            "personality": self.personality,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AgentIdentity:
        return cls(**d)


@dataclass
class AgentProfile:
    """
    The agent's accumulated history and statistics.
    """
    name:            str            = "kerno-agent"
    total_sessions:  int            = 0
    total_cells:     int            = 0
    success_rate:    float          = 0.0
    first_run:       Optional[float] = None
    last_run:        Optional[float] = None
    identity:        AgentIdentity  = field(default_factory=AgentIdentity)

    def to_dict(self) -> dict:
        d = {
            "name":           self.name,
            "total_sessions": self.total_sessions,
            "total_cells":    self.total_cells,
            "success_rate":   self.success_rate,
            "first_run":      self.first_run,
            "last_run":       self.last_run,
            "identity":       self.identity.to_dict(),
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> AgentProfile:
        d = dict(d)
        d["identity"] = AgentIdentity.from_dict(d.get("identity", {}))
        return cls(**d)


@dataclass
class SessionContext:
    """
    Enriched context built for a specific task.
    Combines the raw task with relevant knowledge and capabilities.
    """
    task:                str    = ""
    enriched_task:       str    = ""
    knowledge_context:   str    = ""
    capability_context:  str    = ""
    schema_context:      str    = ""
    domain:              str    = ""

    def as_prompt_injection(self) -> str:
        """
        Build a string that can be injected into the LLM context.
        """
        parts = []
        if self.enriched_task and self.enriched_task != self.task:
            parts.append(f"## Enriched task:\n{self.enriched_task}")
        if self.knowledge_context:
            parts.append(self.knowledge_context)
        if self.capability_context:
            parts.append(self.capability_context)
        if self.schema_context:
            parts.append(self.schema_context)
        return "\n\n".join(parts)


# ── ProgramAgent ─────────────────────────────────────────────────────────────

class ProgramAgent:
    """
    An agent that grows, learns, and persists across sessions.

    Usage:
        # Create a new agent
        agent = ProgramAgent.create(
            name="analyst",
            description="Financial data analyst",
            directory="~/.kerno/agents/analyst"
        )

        # Run a task
        result = agent.run("Build a churn model from customers.csv")

        # Inspect accumulated state
        print(agent.identity())
        print(agent.what_do_i_know())
        print(agent.capabilities())

        # Persist for next run
        # (auto-persisted after each run)
    """

    def __init__(self, storage: AgentStorage):
        self._storage = storage
        self._profile = storage.load_profile() or AgentProfile(name=storage.agent_name)

    # ── Factory methods ──────────────────────────────────────────────────────

    @staticmethod
    def create(
        name: str = "kerno-agent",
        description: str = "A data analysis agent",
        goals: list[str] | None = None,
        directory: str | Path = ".kerno/agents/default",
        llm: object | None = None,
    ) -> ProgramAgent:
        """
        Create a new agent with a fresh profile.
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        identity = AgentIdentity(
            name=name,
            description=description,
            goals=goals or [
                "Help the user analyse data accurately",
                "Learn from past sessions",
                "Propose reusable skills",
            ],
        )
        profile = AgentProfile(
            name=name,
            identity=identity,
        )

        storage = AgentStorage(
            agent_name=name,
            directory=directory,
        )
        storage.save_profile(profile)
        if llm:
            storage.set_llm(llm)

        return ProgramAgent(storage)

    @staticmethod
    def load(
        directory: str | Path = ".kerno/agents/default",
        llm: object | None = None,
    ) -> ProgramAgent:
        """
        Load an existing agent from its persisted state.
        """
        directory = Path(directory)
        if not directory.exists():
            raise FileNotFoundError(f"Agent directory not found: {directory}")

        # Discover the agent name from the directory
        name = directory.name
        storage = AgentStorage(
            agent_name=name,
            directory=directory,
        )
        if llm:
            storage.set_llm(llm)

        return ProgramAgent(storage)

    # ── Core API ─────────────────────────────────────────────────────────────

    def run(self, task: str, **kwargs) -> SessionResult:
        """
        Run a task, enriched with accumulated knowledge and capabilities.
        """
        from kerno.compose import Session

        # Enrich the task with accumulated context
        ctx = self._build_session_context(task)

        # Determine domain from task
        domain = self._infer_domain(task)

        # Build skills from accumulated capabilities
        skill_set = self._storage.capabilities.to_skill_set()

        # Run the session
        session_builder = (
            Session()
            .with_llm(self._storage.llm)
            .with_kernel()
            .with_skills(skill_set)
            .with_loop("reflect")
        )

        # Inject knowledge context
        if ctx.as_prompt_injection():
            enriched_task = f"{task}\n\n{ctx.as_prompt_injection()}"
        else:
            enriched_task = task

        result = session_builder.run(enriched_task)

        # ── Post-processing: learn from this session ─────────────────────────
        self._learn_from_result(result, domain)

        # Update profile
        self._profile.total_sessions += 1
        self._profile.total_cells += result.cells_executed
        if result.status == SessionStatus.COMPLETE:
            self._profile.success_rate = (
                (self._profile.success_rate * (self._profile.total_sessions - 1) + 1.0)
                / self._profile.total_sessions
            )
        else:
            self._profile.success_rate = (
                (self._profile.success_rate * (self._profile.total_sessions - 1) + 0.0)
                / self._profile.total_sessions
            )
        now = time.time()
        if self._profile.first_run is None:
            self._profile.first_run = now
        self._profile.last_run = now

        # Persist everything
        self._storage.vault.store(result)
        self._storage.save_profile(self._profile)

        return result

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        """
        Search the vault for past sessions matching a query.
        """
        return self._storage.vault.query(query, limit=limit)

    def what_do_i_know(self, domain: str = "") -> list[Observation]:
        """
        Return all observations the agent has accumulated.
        """
        return self._storage.knowledge.relevant_to(
            "", domain=domain, k=50, min_confidence=0.1,
        )

    def capabilities(self) -> list[RegisteredSkill]:
        """
        Return all active capabilities.
        """
        return self._storage.capabilities.active_skills()

    def identity(self) -> AgentIdentity:
        """Return the agent's identity."""
        return self._profile.identity

    # ── Internals ────────────────────────────────────────────────────────────

    def _enrich_task(self, task: str) -> str:
        """
        Enrich a raw task description with context from
        accumulated knowledge and capabilities.
        """
        ctx = self._build_session_context(task)
        if ctx.as_prompt_injection():
            return f"{task}\n\n{ctx.as_prompt_injection()}"
        return task

    def _build_session_context(self, task: str) -> SessionContext:
        """
        Build a SessionContext for a specific task,
        pulling from knowledge, capabilities, and schema.
        """
        domain = self._infer_domain(task)

        knowledge_ctx = self._storage.knowledge.context_for(task, domain=domain)
        capability_ctx = self._capability_context()
        schema_ctx = self._storage.knowledge.schema_context(
            self._accumulated_schema()
        )

        enriched = task
        if knowledge_ctx:
            enriched += f"\n\n{knowledge_ctx}"
        if capability_ctx:
            enriched += f"\n\n{capability_ctx}"

        return SessionContext(
            task=task,
            enriched_task=enriched,
            knowledge_context=knowledge_ctx,
            capability_context=capability_ctx,
            schema_context=schema_ctx,
            domain=domain,
        )

    def _capability_context(self) -> str:
        """
        Build a context string describing the agent's active capabilities.
        """
        skills = self._storage.capabilities.active_skills()
        if not skills:
            return ""
        lines = ["## Available capabilities:"]
        for s in skills:
            lines.append(f"- {s.name} (v{s.version}): {s.description}")
        return "\n".join(lines)

    def _infer_domain(self, task: str) -> str:
        """
        Infer the domain from the task description.
        """
        domain_keywords = {
            "finance":  ["stock", "price", "portfolio", "trading", "financial", "revenue"],
            "health":   ["patient", "clinical", "diagnosis", "medical", "health"],
            "marketing": ["campaign", "ad", "conversion", "marketing", "churn"],
            "retail":   ["sales", "product", "inventory", "customer", "store"],
            "general":  [],
        }
        task_lower = task.lower()
        for domain, keywords in domain_keywords.items():
            if any(kw in task_lower for kw in keywords):
                return domain
        return "general"

    def _accumulated_schema(self) -> dict[str, str]:
        """
        Return the accumulated schema knowledge.
        """
        # Collect all schema observations
        schema_obs = [
            o for o in self._storage.knowledge._observations.values()
            if o.kind == ObservationKind.SCHEMA
        ]
        schema = {}
        for o in schema_obs:
            # Parse "Column 'X' has type Y" format
            match = re.search(r"Column '(\w+)' has type (\w+)", o.content)
            if match:
                schema[match.group(1)] = match.group(2)
        return schema

    def _learn_from_result(self, result: SessionResult, domain: str) -> None:
        """
        Learn from a completed session:
        1. Extract knowledge (observations)
        2. Update schema knowledge
        3. Propose new skills
        4. Update skill usage stats
        """
        # 1. Extract knowledge
        self._storage.knowledge.learn_from_session(result)

        # 2. Update schema knowledge
        self._update_schema_knowledge(result)

        # 3. Propose new skills
        self._propose_skill(result)

        # 4. Update skill stats
        self._update_skill_stats(result)

    def _update_schema_knowledge(self, result: SessionResult) -> None:
        """
        Extract schema from successful code cells and record as observations.
        Looks for patterns like `_schema = {c: str(t) for c, t in df.dtypes.items()}`
        """
        for cell in result.cells:
            if not cell.output.has_error:
                # Check if the cell defines a schema variable
                schema_match = re.search(
                    r"(\w+)\s*=\s*\{.*for.*dtypes\.items\(\)",
                    cell.code,
                )
                if schema_match:
                    # The cell explored the data schema — record it
                    content = f"Session {result.session_id} explored data schema"
                    obs = Observation(
                        content=content,
                        kind=ObservationKind.SCHEMA,
                        confidence=0.5,
                        domain=self._infer_domain(result.task),
                        scope="domain",
                        tags=["schema", "discovery"],
                    )
                    existing = self._storage.knowledge._find_similar(content)
                    if existing:
                        existing.reinforce()
                    else:
                        self._storage.knowledge._observations[obs.id] = obs

    def _propose_skill(self, result: SessionResult) -> None:
        """
        Extract skill proposals from a successful session
        and register them in the capability registry.
        """
        if result.status != SessionStatus.COMPLETE:
            return

        extractor = CapabilityExtractor()
        proposals = extractor.extract(result)

        for proposal in proposals:
            # Only register proposals with sufficient confidence
            if proposal.confidence >= 0.6:
                existing = self._storage.capabilities.get_by_name(proposal.name)
                if existing:
                    # Update existing skill
                    self._storage.capabilities.update(
                        existing.skill_id,
                        code=proposal.code,
                        version=f"{existing.version}+1",
                    )
                else:
                    # Register new skill
                    self._storage.capabilities.register(
                        name=proposal.name,
                        code=proposal.code,
                        description=proposal.description,
                        source="extracted",
                        session_id=result.session_id,
                        tags=proposal.tags,
                    )

    def _update_skill_stats(self, result: SessionResult) -> None:
        """
        Update skill usage statistics based on what was loaded
        in this session.
        """
        # Mark active skills as used
        active = self._storage.capabilities.active_skills()
        success = result.status == SessionStatus.COMPLETE
        for skill in active:
            self._storage.capabilities.record_use(skill.name, success=success)


# ── AgentStorage ─────────────────────────────────────────────────────────────

class AgentStorage:
    """
    Persistence layer for all agent state.
    Manages: profile, vault, knowledge, capabilities.
    """

    def __init__(
        self,
        agent_name: str = "kerno-agent",
        directory: str | Path = ".kerno/agents/default",
    ):
        self.agent_name = agent_name
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.llm: Optional[object] = None

        # Initialize subsystems
        self.vault = SessionVault(directory=self.directory / "vault")
        self.knowledge = KnowledgeEngine(directory=self.directory / "knowledge")
        self.capabilities = CapabilityRegistry(directory=self.directory / "capabilities")

    def discover(self) -> list[str]:
        """
        Discover all existing agent directories.
        """
        agents_dir = self.directory.parent
        if not agents_dir.exists():
            return []
        return [
            d.name for d in agents_dir.iterdir()
            if d.is_dir() and (d / "profile.json").exists()
        ]

    def save_profile(self, profile: AgentProfile) -> None:
        """
        Persist the agent profile to disk.
        """
        path = self.directory / "profile.json"
        path.write_text(json.dumps(profile.to_dict(), indent=2))

    def load_profile(self) -> Optional[AgentProfile]:
        """
        Load the agent profile from disk.
        """
        path = self.directory / "profile.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return AgentProfile.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None

    def set_llm(self, llm: object) -> None:
        """Set the LLM callable for this agent."""
        self.llm = llm
