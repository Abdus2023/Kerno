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
