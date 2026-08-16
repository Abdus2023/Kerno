# kerno/security/capabilities.py
"""
CapabilityBroker — capability-oriented authorization (audit #21, #31, #87, #88).

The allowlist answers "which Python syntax is allowed?". The broker answers
the more precise question: "is this *capability* granted to this subject,
within this scope, right now?"

    CapabilityGrant
    ├── capability (name + scope + constraints)
    ├── subject            — who holds the grant
    ├── issuer             — who granted it
    ├── expires_at         — optional expiry
    └── parent_grant_id    — attenuation lineage (child ⊆ parent, never more)

Properties enforced here:

    K-008  Capabilities are granted explicitly, never inferred from syntax.
    P6     Child capability set ⊆ parent capability set (attenuation).
    K-009  (basis) Subjects are first-class: a grant names its subject.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Optional


class CapabilityViolation(Exception):
    """Raised by CapabilityBroker.require() when a capability is not granted."""

    def __init__(self, name: str, scope: str, subject: str, reason: str):
        self.name    = name
        self.scope   = scope
        self.subject = subject
        self.reason  = reason
        scope_txt = f"@{scope}" if scope and scope != "*" else ""
        subject_txt = f" for subject '{subject}'" if subject else ""
        super().__init__(
            f"Capability denied [{name}{scope_txt}{subject_txt}]: {reason}"
        )


@dataclass(frozen=True)
class Capability:
    """
    A named, optionally scoped permission.

    name:   e.g. "filesystem.read", "network.connect", "kernel.execute"
    scope:  fnmatch pattern the requested scope must match ("*" = any)
    constraints: optional key/value constraints (e.g. {"path_prefix": "/workspace"})
    """

    name:        str
    scope:       str   = "*"
    constraints: dict  = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilityGrant:
    """A scoped, attributable grant of one capability to one subject."""

    grant_id:         str
    capability:       Capability
    subject:          str                = ""      # "" = any subject
    issuer:           str                = ""
    expires_at:       Optional[float]    = None    # epoch seconds, None = never
    parent_grant_id:  Optional[str]      = None    # attenuation lineage
    created_at:       float              = field(default_factory=time.time)


# ── Standard capability names ─────────────────────────────────────────────────

CAP_KERNEL_EXECUTE  = "kernel.execute"
CAP_FILESYSTEM_READ = "filesystem.read"
CAP_FILESYSTEM_WRITE = "filesystem.write"
CAP_NETWORK_CONNECT = "network.connect"
CAP_PROCESS_SPAWN   = "process.spawn"
CAP_PACKAGE_IMPORT  = "package.import"
CAP_NOTEBOOK_WRITE  = "notebook.write"
CAP_ARTIFACT_CREATE = "artifact.create"
CAP_SECRET_READ     = "secret.read"
CAP_DATAFRAME       = "dataframe.compute"
CAP_HUMAN_APPROVAL  = "human.approval"

WILDCARD = "*"

# ── Preset profiles (mirrors of the allowlist profiles) ───────────────────────

PROFILE_READ_ONLY = frozenset({
    CAP_KERNEL_EXECUTE, CAP_FILESYSTEM_READ, CAP_ARTIFACT_CREATE,
})

PROFILE_DATA_ANALYSIS = PROFILE_READ_ONLY | {CAP_DATAFRAME}

PROFILE_RESEARCH = PROFILE_READ_ONLY | {CAP_NETWORK_CONNECT}

PROFILE_TRUSTED = frozenset({WILDCARD})


def grant_profile(
    broker: "CapabilityBroker",
    profile: frozenset[str],
    *,
    subject: str = "",
    issuer:  str = "",
) -> list[CapabilityGrant]:
    """Grant every capability in a profile to a subject."""
    return broker.grant_many(profile, subject=subject, issuer=issuer)


class CapabilityBroker:
    """
    Issues, checks, attenuates, and revokes capability grants.

    Usage:
        broker = CapabilityBroker()
        grant  = broker.grant(
            Capability(CAP_FILESYSTEM_READ, scope="/workspace/datasets/**"),
            subject="agent-1",
        )
        broker.require(CAP_FILESYSTEM_READ,
                       scope="/workspace/datasets/x.csv", subject="agent-1")  # ok
        broker.require(CAP_FILESYSTEM_READ,
                       scope="/etc/passwd", subject="agent-1")                 # denied
    """

    def __init__(self):
        self._grants:  dict[str, CapabilityGrant] = {}
        self._revoked: set[str] = set()

    # ── Granting ───────────────────────────────────────────────────────────────

    def grant(
        self,
        capability: Capability,
        *,
        subject:   str                = "",
        issuer:    str                = "",
        expires_at: Optional[float]   = None,
        parent:    Optional[CapabilityGrant] = None,
    ) -> CapabilityGrant:
        """
        Issue a grant. If `parent` is given, the new grant is an attenuation:
        it must be a subset of the parent (name, scope, constraints, subject).
        """
        if parent is not None:
            self._require_active(parent)
            self._check_subset(capability, parent, subject)

        grant = CapabilityGrant(
            grant_id        = "cap_" + uuid.uuid4().hex[:12],
            capability      = capability,
            subject         = subject,
            issuer          = issuer or (parent.issuer if parent else ""),
            expires_at      = expires_at,
            parent_grant_id = parent.grant_id if parent else None,
        )
        self._grants[grant.grant_id] = grant
        return grant

    def grant_many(
        self,
        names:      frozenset[str] | set[str] | list[str],
        *,
        subject:   str              = "",
        issuer:    str              = "",
        expires_at: Optional[float] = None,
    ) -> list[CapabilityGrant]:
        """Grant one capability per name (unscoped, no constraints)."""
        return [
            self.grant(
                Capability(name),
                subject=subject, issuer=issuer, expires_at=expires_at,
            )
            for name in names
        ]

    def attenuate(
        self,
        parent:     CapabilityGrant,
        *,
        name:       Optional[str] = None,
        scope:      Optional[str] = None,
        constraints: Optional[dict] = None,
        subject:    Optional[str] = None,
        expires_at: Optional[float] = None,
    ) -> CapabilityGrant:
        """
        Derive a strictly narrower grant from a parent.

        The child may never grant more than the parent: same or narrower
        name, scope, constraints, and subject (invariant P6).
        """
        capability = Capability(
            name        = name        if name        is not None else parent.capability.name,
            scope       = scope       if scope       is not None else parent.capability.scope,
            constraints = constraints if constraints is not None else parent.capability.constraints,
        )
        return self.grant(
            capability,
            subject    = subject if subject is not None else parent.subject,
            issuer     = parent.issuer,
            expires_at = expires_at,
            parent     = parent,
        )

    def revoke(self, grant_id: str) -> None:
        """Revoke a grant (and by extension all of its descendants)."""
        if grant_id in self._grants:
            self._revoked.add(grant_id)
            for gid, grant in self._grants.items():
                if grant.parent_grant_id == grant_id:
                    self._revoked.add(gid)

    # ── Checking ───────────────────────────────────────────────────────────────

    def check(
        self,
        name:        str,
        scope:       str  = "*",
        subject:     str  = "",
        constraints: Optional[dict] = None,
    ) -> bool:
        """True if some active grant covers (name, scope, subject, constraints)."""
        return any(
            self._covers(grant, name, scope, subject, constraints)
            for grant in self._grants.values()
        )

    def require(
        self,
        name:        str,
        scope:       str  = "*",
        subject:     str  = "",
        constraints: Optional[dict] = None,
    ) -> None:
        """Raise CapabilityViolation unless the capability is granted."""
        if not self.check(name, scope=scope, subject=subject, constraints=constraints):
            raise CapabilityViolation(name, scope, subject, "no active grant")

    def all_grants(self) -> list[CapabilityGrant]:
        """Every grant, active or not (for invariant checks, P6)."""
        return list(self._grants.values())

    def active_grants(self, subject: str = "") -> list[CapabilityGrant]:
        """All grants visible to a subject ("" = any)."""
        return [
            g for g in self._grants.values()
            if self._is_active(g) and (not subject or not g.subject or g.subject == subject)
        ]

    # ── Internals ──────────────────────────────────────────────────────────────

    def _is_active(self, grant: CapabilityGrant) -> bool:
        if grant.grant_id in self._revoked:
            return False
        if grant.expires_at is not None and time.time() >= grant.expires_at:
            return False
        return True

    def _covers(
        self,
        grant:       CapabilityGrant,
        name:        str,
        scope:       str,
        subject:     str,
        constraints: Optional[dict],
    ) -> bool:
        if not self._is_active(grant):
            return False
        if subject and grant.subject and grant.subject != subject:
            return False
        cap = grant.capability
        if cap.name != WILDCARD and cap.name != name:
            return False
        if not fnmatch(scope, cap.scope):
            return False
        # Every grant constraint must be satisfied by the request
        for key, value in cap.constraints.items():
            if not constraints or constraints.get(key) != value:
                return False
        return True

    def _require_active(self, grant: CapabilityGrant) -> None:
        if not self._is_active(grant):
            raise CapabilityViolation(
                grant.capability.name, grant.capability.scope, grant.subject,
                "parent grant is not active",
            )

    def _check_subset(
        self,
        child:   Capability,
        parent:  CapabilityGrant,
        subject: str,
    ) -> None:
        pcap = parent.capability
        # Name: child must equal parent (or parent is wildcard)
        if pcap.name != WILDCARD and child.name != pcap.name:
            raise CapabilityViolation(
                child.name, child.scope, subject,
                f"not a subset of parent capability '{pcap.name}'",
            )
        # Scope: child scope must be within the parent's pattern
        if not fnmatch(child.scope, pcap.scope):
            raise CapabilityViolation(
                child.name, child.scope, subject,
                f"scope '{child.scope}' exceeds parent scope '{pcap.scope}'",
            )
        # Constraints: child may only tighten, never add
        for key, value in child.constraints.items():
            if key not in pcap.constraints or pcap.constraints[key] != value:
                raise CapabilityViolation(
                    child.name, child.scope, subject,
                    f"constraint '{key}' exceeds parent constraints",
                )
        # Subject: child may narrow, never widen
        if parent.subject and subject and subject != parent.subject:
            raise CapabilityViolation(
                child.name, child.scope, subject,
                f"subject '{subject}' exceeds parent subject '{parent.subject}'",
            )

    def __len__(self) -> int:
        return len(self._grants)

    def __repr__(self) -> str:
        return (
            f"CapabilityBroker({len(self._grants)} grants, "
            f"{len(self._revoked)} revoked)"
        )
