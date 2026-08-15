"""
CapabilityRegistry: an evolving library of skills the agent has learned.

The CapabilityRegistry is the backbone of Level 5 persistence.  It tracks
not just what skills exist, but how they evolved — which sessions created
them, how often they succeed, and when they were superseded.

Design:
  - RegisteredSkill: a skill with provenance, versioning, and usage stats
  - CapabilityRegistry: CRUD for skills, with evolution tracking
  - Supersession: old skills can be marked as superseded by better ones
  - Skill manifests: export the full skill library for inspection
  - Changelogs: track every skill registration, update, and supersession

The registry is the agent's "muscle memory" — it remembers not just
what it can do, but how well it does it and how it learned to do it.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from kerno.skills.composer import CodeSkill, SkillSet


# ── SkillStatus ──────────────────────────────────────────────────────────────

class SkillStatus(Enum):
    ACTIVE     = auto()
    EXPERIMENTAL = auto()
    DEPRECATED = auto()
    SUPERSEDED = auto()


# ── RegisteredSkill ──────────────────────────────────────────────────────────

@dataclass
class RegisteredSkill:
    """
    A skill with provenance, versioning, and usage statistics.

    Fields:
        skill_id:        Unique identifier
        name:            Human-readable name
        code:            The actual Python code
        description:     What this skill does
        version:         Semantic version
        status:          Current lifecycle status
        source:          How this skill was created ("manual", "extracted", "composed")
        origin_sessions: Session IDs that contributed to this skill
        created_at:      When this skill was first registered
        last_used_at:    When this skill was last used
        use_count:       How many times this skill has been loaded
        success_rate:    Fraction of sessions where this skill worked (0.0–1.0)
        dependencies:    Other skill names this depends on
        tags:            Free-form categorisation tags
        superseded_by:   If deprecated, the skill_id that replaces this
    """
    skill_id:        str                       = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name:            str                       = ""
    code:            str                       = ""
    description:     str                       = ""
    version:         str                       = "1.0.0"
    status:          SkillStatus               = SkillStatus.ACTIVE
    source:          str                       = "manual"
    origin_sessions: list[str]                 = field(default_factory=list)
    created_at:      float                     = field(default_factory=time.time)
    last_used_at:    Optional[float]           = None
    use_count:       int                       = 0
    success_rate:    float                     = 1.0
    dependencies:    list[str]                 = field(default_factory=list)
    tags:            list[str]                 = field(default_factory=list)
    superseded_by:   Optional[str]            = None

    def to_dict(self) -> dict:
        return {
            "skill_id":        self.skill_id,
            "name":            self.name,
            "code":            self.code,
            "description":     self.description,
            "version":         self.version,
            "status":          self.status.name,
            "source":          self.source,
            "origin_sessions": self.origin_sessions,
            "created_at":      self.created_at,
            "last_used_at":    self.last_used_at,
            "use_count":       self.use_count,
            "success_rate":    self.success_rate,
            "dependencies":    self.dependencies,
            "tags":            self.tags,
            "superseded_by":   self.superseded_by,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RegisteredSkill:
        d = dict(d)
        d["status"] = SkillStatus[d.pop("status", "ACTIVE")]
        return cls(**d)


# ── CapabilityRegistry ───────────────────────────────────────────────────────

class CapabilityRegistry:
    """
    An evolving library of skills the agent has learned.

    Usage:
        cap = CapabilityRegistry(directory="~/.kerno/capabilities")
        cap.register(name="load_sales", code="...", description="...")
        cap.record_use("load_sales", success=True)
        skills = cap.active_skills()
        skill_set = cap.to_skill_set()
    """

    def __init__(self, directory: str | Path = ".kerno/capabilities"):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._skills: dict[str, RegisteredSkill] = {}
        self._changelog: list[dict] = []
        self._load()

    # ── Public API ────────────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        code: str,
        description: str = "",
        version: str = "1.0.0",
        source: str = "manual",
        dependencies: list[str] | None = None,
        tags: list[str] | None = None,
        session_id: str = "",
    ) -> RegisteredSkill:
        """
        Register a new skill.  If a skill with the same name exists,
        the old one is superseded.
        """
        existing = self.get_by_name(name)
        if existing:
            # Supersede the old skill
            existing.status = SkillStatus.SUPERSEDED
            existing.superseded_by = name  # Will be updated below

        skill = RegisteredSkill(
            name=name,
            code=code,
            description=description,
            version=version,
            status=SkillStatus.ACTIVE,
            source=source,
            origin_sessions=[session_id] if session_id else [],
            dependencies=dependencies or [],
            tags=tags or [],
        )
        if existing:
            existing.superseded_by = skill.skill_id

        self._skills[skill.skill_id] = skill
        self._log("register", skill.skill_id, name, session_id)
        self._save()
        return skill

    def update(
        self,
        skill_id: str,
        **kwargs,
    ) -> Optional[RegisteredSkill]:
        """
        Update fields on an existing skill.
        """
        skill = self._skills.get(skill_id)
        if not skill:
            return None
        for key, value in kwargs.items():
            if hasattr(skill, key):
                setattr(skill, key, value)
        self._log("update", skill_id, skill.name)
        self._save()
        return skill

    def record_use(
        self,
        name: str,
        success: bool = True,
    ) -> Optional[RegisteredSkill]:
        """
        Record that a skill was used in a session.
        Updates use_count and success_rate.
        """
        skill = self.get_by_name(name)
        if not skill:
            return None
        skill.use_count += 1
        skill.last_used_at = time.time()
        # Running average for success_rate
        n = skill.use_count
        skill.success_rate = ((n - 1) * skill.success_rate + (1.0 if success else 0.0)) / n
        self._log("use", skill.skill_id, name)
        self._save()
        return skill

    def get_by_name(self, name: str) -> Optional[RegisteredSkill]:
        """Find an active skill by name."""
        for skill in self._skills.values():
            if skill.name == name and skill.status == SkillStatus.ACTIVE:
                return skill
        return None

    def active_skills(self) -> list[RegisteredSkill]:
        """Return all active (non-deprecated, non-superseded) skills."""
        return [
            s for s in self._skills.values()
            if s.status == SkillStatus.ACTIVE
        ]

    def to_skill_set(self) -> SkillSet:
        """
        Convert the active skills into a SkillSet for loading into a kernel.
        """
        ss = SkillSet()
        for skill in sorted(self.active_skills(), key=lambda s: s.name):
            cs = CodeSkill(
                name=skill.name,
                code=skill.code,
                dependencies=skill.dependencies,
                version=skill.version,
                description=skill.description,
                tags=skill.tags,
            )
            ss.add(cs)
        return ss

    def manifest(self) -> dict:
        """
        Export a full manifest of all registered skills.
        """
        return {
            "total_skills": len(self._skills),
            "active": len(self.active_skills()),
            "deprecated": sum(1 for s in self._skills.values() if s.status == SkillStatus.DEPRECATED),
            "superseded": sum(1 for s in self._skills.values() if s.status == SkillStatus.SUPERSEDED),
            "skills": [s.to_dict() for s in self._skills.values()],
        }

    def changelog(self, limit: int = 50) -> list[dict]:
        """Return recent changelog entries."""
        return self._changelog[-limit:]

    # ── Internals ─────────────────────────────────────────────────────────────

    def _log(self, action: str, skill_id: str, name: str = "", session_id: str = "") -> None:
        """Append an entry to the changelog."""
        self._changelog.append({
            "action":     action,
            "skill_id":   skill_id,
            "name":       name,
            "session_id": session_id,
            "timestamp":  time.time(),
        })

    def _save(self) -> None:
        """Persist skills and changelog to disk."""
        skills_path = self.directory / "skills.json"
        data = [s.to_dict() for s in self._skills.values()]
        skills_path.write_text(json.dumps(data, indent=2))

        log_path = self.directory / "changelog.json"
        log_path.write_text(json.dumps(self._changelog[-1000:], indent=2))

    def _load(self) -> None:
        """Load skills and changelog from disk."""
        skills_path = self.directory / "skills.json"
        if skills_path.exists():
            try:
                data = json.loads(skills_path.read_text())
                for d in data:
                    skill = RegisteredSkill.from_dict(d)
                    self._skills[skill.skill_id] = skill
            except (json.JSONDecodeError, KeyError):
                self._skills = {}

        log_path = self.directory / "changelog.json"
        if log_path.exists():
            try:
                self._changelog = json.loads(log_path.read_text())
            except json.JSONDecodeError:
                self._changelog = []
