"""
Provenance tracking for every object the agent creates.

A ProvenanceRecord answers:
  "Where did this object come from?"

This is Level 3 persistence: not just saving the result,
but recording *how* it was produced, so any object can be
reproduced from its provenance chain.

Design:
  - Every kernel variable gets a ProvenanceRecord
  - Records form a DAG: object_ids reference input_ids
  - The checksum verifies the object hasn't been tampered with
  - The reconstruction field stores the recipe for re-running
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProvenanceRecord:
    """
    One provenance record: the birth certificate of a kernel object.

    Fields:
        object_id:       Name of the variable in kernel namespace
        created_at:      Timestamp when the cell was executed
        session_id:      Which session produced this
        cell_num:        Which cell in the session
        code:            The exact code that created this object
        input_ids:       List of object_ids this cell read from
        checksum:        Hash of the object's value (for integrity)
        reconstruction:  Optional recipe for reproducing this object
    """
    object_id:       str
    created_at:      float            = field(default_factory=time.time)
    session_id:      str              = ""
    cell_num:        int              = 0
    code:            str              = ""
    input_ids:       list[str]        = field(default_factory=list)
    checksum:        str              = ""
    reconstruction:  Optional[str]    = None

    @staticmethod
    def compute_checksum(value_repr: str) -> str:
        """Compute a SHA-256 checksum from an object's string representation."""
        return hashlib.sha256(value_repr.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        """Serialize to a plain dictionary."""
        return {
            "object_id":      self.object_id,
            "created_at":     self.created_at,
            "session_id":     self.session_id,
            "cell_num":       self.cell_num,
            "code":           self.code,
            "input_ids":      self.input_ids,
            "checksum":       self.checksum,
            "reconstruction": self.reconstruction,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ProvenanceRecord:
        """Deserialize from a plain dictionary."""
        return cls(**d)


# ── ProvenanceGraph ───────────────────────────────────────────────────────────

# Node kinds in the provenance graph
KIND_TASK      = "task"       # a task/session
KIND_ACTION    = "action"     # an agent action (decision)
KIND_CODE      = "code"       # the code produced by an action
KIND_EXECUTION = "execution"  # one execution of code in the kernel
KIND_ARTIFACT  = "artifact"   # a produced artifact (file, notebook, report)


class ProvenanceGraphError(Exception):
    """Raised on invalid graph operations (e.g. cycle creation)."""


@dataclass
class ProvenanceNode:
    """One node in the provenance graph."""

    node_id:   str
    kind:      str                       # task | action | code | execution | artifact
    attrs:     dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "kind":    self.kind,
            "attrs":   dict(self.attrs),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ProvenanceEdge:
    """A directed edge child → parent (child derived_from parent)."""

    child:  str
    parent: str
    relation: str = "derived_from"       # derived_from | created_by | part_of


class ProvenanceGraph:
    """
    A DAG answering: "Where did this artifact come from?" (audit #39, K-006).

    Nodes: task → action → code → execution → artifact.
    Edges point from child to parent (derivation direction).

    Usage:
        g = ProvenanceGraph()
        g.add_node("task-1", KIND_TASK, attrs={"task": "..."})
        g.add_node("act-1",  KIND_ACTION, attrs={"action_id": "act_0047"})
        g.add_edge("act-1", "task-1")
        g.add_node("exec-1", KIND_EXECUTION, attrs={"execution_id": "exec_00000042"})
        g.add_edge("exec-1", "act-1")
        g.add_node("report.pdf", KIND_ARTIFACT)
        g.add_edge("report.pdf", "exec-1")
        chain = g.trace("report.pdf")   # artifact → execution → action → task
    """

    def __init__(self):
        self._nodes: dict[str, ProvenanceNode] = {}
        self._edges: list[ProvenanceEdge] = []

    # ── Nodes ────────────────────────────────────────────────────────────

    def add_node(
        self,
        node_id: str,
        kind:    str,
        attrs:   Optional[dict] = None,
    ) -> ProvenanceNode:
        if node_id in self._nodes:
            raise ProvenanceGraphError(f"Node already exists: {node_id}")
        node = ProvenanceNode(node_id=node_id, kind=kind, attrs=attrs or {})
        self._nodes[node_id] = node
        return node

    def node(self, node_id: str) -> Optional[ProvenanceNode]:
        return self._nodes.get(node_id)

    @property
    def nodes(self) -> tuple[ProvenanceNode, ...]:
        return tuple(self._nodes.values())

    # ── Edges (DAG invariant: no cycles) ─────────────────────────────────

    def add_edge(
        self,
        child:    str,
        parent:   str,
        relation: str = "derived_from",
    ) -> ProvenanceEdge:
        if child not in self._nodes:
            raise ProvenanceGraphError(f"Unknown child node: {child}")
        if parent not in self._nodes:
            raise ProvenanceGraphError(f"Unknown parent node: {parent}")
        if self._would_create_cycle(child, parent):
            raise ProvenanceGraphError(
                f"Edge {child} → {parent} would create a cycle"
            )
        edge = ProvenanceEdge(child=child, parent=parent, relation=relation)
        self._edges.append(edge)
        return edge

    def _would_create_cycle(self, child: str, parent: str) -> bool:
        # Adding child → parent closes a cycle iff parent can already reach
        # child by following child→parent edges (ancestors include self,
        # which also rejects self-loops).
        return child in self._ancestors(parent)

    def _ancestors(self, node_id: str) -> set[str]:
        """All nodes reachable from node_id following child→parent edges,
        including node_id itself."""
        seen: set[str] = {node_id}
        stack = [node_id]
        while stack:
            current = stack.pop()
            for edge in self._edges:
                if edge.child == current and edge.parent not in seen:
                    seen.add(edge.parent)
                    stack.append(edge.parent)
        return seen

    # ── Queries ──────────────────────────────────────────────────────────

    def parents(self, node_id: str) -> list[str]:
        return [e.parent for e in self._edges if e.child == node_id]

    def children(self, node_id: str) -> list[str]:
        return [e.child for e in self._edges if e.parent == node_id]

    def trace(self, node_id: str) -> list[dict]:
        """
        Walk the derivation chain from node_id up to its roots.

        Returns an ordered list of {"node_id", "kind", "attrs"} starting
        with node_id itself, then its parents, grandparents, etc.
        For a report: artifact → execution → action → task.
        """
        chain: list[dict] = []
        seen: set[str] = set()
        stack = [node_id]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            node = self._nodes.get(current)
            if node is None:
                continue
            chain.append({
                "node_id": node.node_id,
                "kind":    node.kind,
                "attrs":   dict(node.attrs),
            })
            # Depth-first: parents pushed in order
            for parent in reversed(self.parents(current)):
                stack.append(parent)
        return chain

    def lineage(self, node_id: str) -> list[str]:
        """The kinds of the derivation chain, root-first: [task, action, ...]."""
        return [entry["kind"] for entry in reversed(self.trace(node_id))]

    # ── Serialization ────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [
                {"child": e.child, "parent": e.parent, "relation": e.relation}
                for e in self._edges
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProvenanceGraph":
        g = cls()
        for nd in d.get("nodes", []):
            g.add_node(nd["node_id"], nd["kind"], nd.get("attrs", {}))
        for ed in d.get("edges", []):
            g.add_edge(ed["child"], ed["parent"], ed.get("relation", "derived_from"))
        return g
