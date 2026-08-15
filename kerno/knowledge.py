"""
KnowledgeEngine: learning from sessions, not just storing them.

The KnowledgeEngine is the core of Level 4 persistence.  It goes
beyond the vault (which stores *what* happened) and extracts
*what was learned* — observations about data, schemas, errors,
and patterns that accumulate across sessions.

Design:
  - Observation: a unit of knowledge with confidence, evidence, and scope
  - KnowledgeEngine: extracts, stores, contradicts, and retrieves observations
  - Confidence decay: older observations lose weight unless reinforced
  - Contradiction tracking: new observations can invalidate old ones
  - Domain scoping: knowledge is tagged with the domain it applies to

The engine is deliberately conservative:
  - It only promotes observations above a confidence threshold
  - It flags contradictions rather than silently replacing
  - It tracks evidence (which sessions produced each observation)
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from kerno.types import SessionResult


# ── Observation ───────────────────────────────────────────────────────────────

class ObservationKind(Enum):
    SCHEMA    = auto()   # "column X is always a float"
    BEHAVIOR  = auto()   # "groupby on this column is slow"
    CONSTRAINT = auto()  # "values are always positive"
    ERROR     = auto()   # "this API always raises on empty input"
    PATTERN   = auto()   # "this join pattern works well"
    SKILL     = auto()   # "this code snippet solved a class of problems"


@dataclass
class Observation:
    """
    One unit of accumulated knowledge.

    Fields:
        id:          Unique identifier
        content:     The actual knowledge text
        kind:        What kind of observation this is
        confidence:  0.0–1.0, how confident we are
        evidence:    Session IDs that support this observation
        contradicts: Observation IDs this contradicts
        domain:      What domain this applies to (e.g., "finance", "health")
        scope:       How broadly this applies ("global", "domain", "session")
        first_seen:  When this was first observed
        last_seen:   When this was last reinforced
        tags:        Free-form tags for categorisation
    """
    id:          str                        = field(default_factory=lambda: uuid.uuid4().hex[:12])
    content:     str                        = ""
    kind:        ObservationKind            = ObservationKind.PATTERN
    confidence:  float                      = 0.5
    evidence:    list[str]                  = field(default_factory=list)
    contradicts: list[str]                  = field(default_factory=list)
    domain:      str                        = "general"
    scope:       str                        = "domain"
    first_seen:  float                      = field(default_factory=time.time)
    last_seen:   float                      = field(default_factory=time.time)
    tags:        list[str]                  = field(default_factory=list)

    def reinforce(self) -> None:
        """Increase confidence slightly and update last_seen."""
        self.confidence = min(1.0, self.confidence + 0.05)
        self.last_seen = time.time()

    def decay(self, factor: float = 0.99) -> None:
        """Decrease confidence slightly (time-based decay)."""
        self.confidence = max(0.0, self.confidence * factor)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "content":     self.content,
            "kind":        self.kind.name,
            "confidence":  self.confidence,
            "evidence":    self.evidence,
            "contradicts": self.contradicts,
            "domain":      self.domain,
            "scope":       self.scope,
            "first_seen":  self.first_seen,
            "last_seen":   self.last_seen,
            "tags":        self.tags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Observation:
        d = dict(d)
        d["kind"] = ObservationKind[d.pop("kind", "PATTERN")]
        return cls(**d)


# ── KnowledgeEngine ──────────────────────────────────────────────────────────

class KnowledgeEngine:
    """
    Extract, store, contradict, and retrieve observations.

    Usage:
        engine = KnowledgeEngine(directory="~/.kerno/knowledge")
        engine.learn_from_session(result)
        obs = engine.relevant_to("churn prediction")
        ctx = engine.context_for("Build a churn model")
    """

    def __init__(self, directory: str | Path = ".kerno/knowledge"):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._observations: dict[str, Observation] = {}
        self._load()

    # ── Public API ────────────────────────────────────────────────────────────

    def learn_from_session(self, result: SessionResult) -> list[Observation]:
        """
        Extract knowledge from a completed session.
        Returns the new observations created.
        """
        new_obs = self._extract_knowledge(result)
        for obs in new_obs:
            existing = self._find_similar(obs.content)
            if existing:
                # Reinforce existing observation
                existing.reinforce()
                existing.evidence.append(result.session_id)
                if obs.domain and obs.domain != "general":
                    existing.domain = obs.domain
            else:
                obs.evidence.append(result.session_id)
                self._observations[obs.id] = obs
        self._save()
        return new_obs

    def contradict(
        self,
        obs_id: str,
        new_content: str,
        session_id: str = "",
    ) -> Observation:
        """
        Record a contradiction: a new observation that invalidates an old one.
        """
        old = self._observations.get(obs_id)
        if not old:
            raise KeyError(f"Observation {obs_id} not found")

        new_obs = Observation(
            content=new_content,
            kind=old.kind,
            confidence=0.7,
            evidence=[session_id] if session_id else [],
            contradicts=[obs_id],
            domain=old.domain,
            scope=old.scope,
            tags=old.tags + ["contradiction"],
        )
        # Lower the old observation's confidence
        old.confidence = max(0.0, old.confidence - 0.3)
        self._observations[new_obs.id] = new_obs
        self._save()
        return new_obs

    def relevant_to(
        self,
        query: str,
        domain: str = "",
        k: int = 5,
        min_confidence: float = 0.1,
    ) -> list[Observation]:
        """
        Retrieve observations relevant to a query.
        Filters by domain and confidence threshold.
        """
        results = []
        for obs in self._observations.values():
            if obs.confidence < min_confidence:
                continue
            if domain and obs.domain != domain and obs.scope != "global":
                continue
            # Simple keyword overlap scoring
            query_words = set(query.lower().split())
            obs_words = set(obs.content.lower().split())
            overlap = len(query_words & obs_words)
            if overlap > 0:
                results.append((overlap, obs))

        results.sort(key=lambda x: x[0], reverse=True)
        return [obs for _, obs in results[:k]]

    def context_for(
        self,
        task: str,
        domain: str = "",
        max_observations: int = 5,
    ) -> str:
        """
        Build a context string for the LLM from relevant observations.
        """
        obs = self.relevant_to(task, domain=domain, k=max_observations)
        if not obs:
            return ""
        lines = ["## Relevant knowledge from past sessions:"]
        for o in obs:
            lines.append(
                f"- [{o.kind.name}] {o.content} "
                f"(confidence: {o.confidence:.2f}, domain: {o.domain})"
            )
        return "\n".join(lines)

    def observe_schema(self, schema: dict[str, str]) -> list[Observation]:
        """
        Record schema observations from a DataFrame's column types.
        schema: mapping of column_name → type_string
        """
        observations = []
        for col, dtype in schema.items():
            content = f"Column '{col}' has type {dtype}"
            obs = Observation(
                content=content,
                kind=ObservationKind.SCHEMA,
                confidence=0.6,
                domain="data",
                scope="domain",
                tags=["schema", dtype],
            )
            existing = self._find_similar(content)
            if existing:
                existing.reinforce()
                observations.append(existing)
            else:
                self._observations[obs.id] = obs
                observations.append(obs)
        self._save()
        return observations

    def schema_context(self, schema: dict[str, str]) -> str:
        """
        Build a context string describing the known schema.
        """
        if not schema:
            return ""
        lines = ["## Known schema:"]
        for col, dtype in schema.items():
            lines.append(f"- {col}: {dtype}")
        return "\n".join(lines)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _extract_knowledge(self, result: SessionResult) -> list[Observation]:
        """
        Extract observations from a session result.
        Looks at error patterns, successful code, and summary.
        """
        observations = []

        # Error patterns
        error_cells = [c for c in result.cells if c.output.has_error]
        if error_cells:
            for ec in error_cells[:3]:
                obs = Observation(
                    content=f"Error: {ec.output.error.ename}: {ec.output.error.evalue[:200]}",
                    kind=ObservationKind.ERROR,
                    confidence=0.4,
                    domain="error",
                    scope="session",
                    tags=["error", ec.output.error.ename],
                )
                observations.append(obs)

        # Recovery patterns (cell after error succeeded)
        for i in range(1, len(result.cells)):
            prev = result.cells[i - 1]
            curr = result.cells[i]
            if prev.output.has_error and not curr.output.has_error:
                obs = Observation(
                    content=f"Recovery: after {prev.output.error.ename}, "
                            f"code '{curr.code[:100]}' succeeded",
                    kind=ObservationKind.PATTERN,
                    confidence=0.5,
                    domain="error",
                    scope="domain",
                    tags=["recovery", prev.output.error.ename],
                )
                observations.append(obs)

        # Summary observation
        if result.summary:
            obs = Observation(
                content=result.summary[:500],
                kind=ObservationKind.BEHAVIOR,
                confidence=0.6,
                domain="general",
                scope="domain",
                tags=["summary"],
            )
            observations.append(obs)

        return observations

    def _update_confidence(self) -> None:
        """
        Apply time-based confidence decay to all observations.
        Called periodically or on save.
        """
        now = time.time()
        for obs in self._observations.values():
            age_days = (now - obs.last_seen) / 86400.0
            if age_days > 1.0:
                n_evidence = len(obs.evidence)
                # More evidence → slower decay
                if n_evidence >= 3:
                    obs.decay(factor=0.99)
                elif n_evidence >= 1:
                    obs.decay(factor=0.95)
                else:
                    obs.decay(factor=0.90)

    def _find_similar(self, content: str) -> Optional[Observation]:
        """
        Find an existing observation with similar content.
        Uses simple hash-based matching.
        """
        content_norm = content.strip().lower()[:100]
        for obs in self._observations.values():
            obs_norm = obs.content.strip().lower()[:100]
            if content_norm == obs_norm:
                return obs
        return None

    def _save(self) -> None:
        """Persist observations to disk."""
        self._update_confidence()
        path = self.directory / "observations.json"
        data = [obs.to_dict() for obs in self._observations.values()]
        path.write_text(json.dumps(data, indent=2))

    def _load(self) -> None:
        """Load observations from disk."""
        path = self.directory / "observations.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            for d in data:
                obs = Observation.from_dict(d)
                self._observations[obs.id] = obs
        except (json.JSONDecodeError, KeyError):
            # Corrupted file — start fresh
            self._observations = {}
