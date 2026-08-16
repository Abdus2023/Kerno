# kerno/isolation.py
"""
Agent isolation primitives (audit #33, K-009).

K-009: "Agents do not share mutable kernel state unless explicitly
configured."

Two mechanisms:

1. SharedMemory — the ONLY way state crosses an agent boundary. Every
   value records its producer (agent) and timestamp, so shared state is
   explicit and attributable.

2. NamespacePartition — each agent declares which namespace prefixes it
   may write. After a turn, the partition verifies the kernel namespace:
   keys outside the agent's declared prefixes (and not explicitly shared)
   are violations — they are never exported to other agents.
"""

from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional


# ── SharedMemory ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SharedValue:
    """One explicitly shared value with provenance."""

    key:       str
    value:     Any
    producer:  str          # agent name that produced it
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "key":       self.key,
            "value":     copy.deepcopy(self.value),
            "producer":  self.producer,
            "timestamp": self.timestamp,
        }


class SharedMemory:
    """
    Explicit cross-agent state store (audit #33, K-009).

    Only values put here may cross an agent boundary. Every value is
    deep-copied on write and read so caller mutations cannot contaminate
    the shared memory or other agent runtimes.
    """

    def __init__(self):
        self._values: dict[str, SharedValue] = {}

    def put(self, key: str, value: Any, producer: str) -> SharedValue:
        """Share a value produced by `producer` under `key` (deep-copied)."""
        sv = SharedValue(key=key, value=copy.deepcopy(value), producer=producer)
        self._values[key] = sv
        return sv

    def get(self, key: str) -> Optional[SharedValue]:
        sv = self._values.get(key)
        if sv is None:
            return None
        return SharedValue(
            key       = sv.key,
            value     = copy.deepcopy(sv.value),
            producer  = sv.producer,
            timestamp = sv.timestamp,
        )

    def keys(self) -> list[str]:
        return list(self._values.keys())

    def items(self) -> list[SharedValue]:
        return [
            SharedValue(
                key       = sv.key,
                value     = copy.deepcopy(sv.value),
                producer  = sv.producer,
                timestamp = sv.timestamp,
            )
            for sv in self._values.values()
        ]

    def producers(self) -> dict[str, list[str]]:
        """{agent: [keys it produced]} for attribution."""
        result: dict[str, list[str]] = {}
        for sv in self._values.values():
            result.setdefault(sv.producer, []).append(sv.key)
        return result

    def seed_code(self) -> str:
        """
        Generate kernel code that materializes the shared values.

        The seeded variables are ordinary JSON literals — immutable,
        attributable copies. The kernel receiving them cannot mutate the
        shared store.
        """
        if not self._values:
            return ""
        lines = ["import json as _json"]
        for sv in self._values.values():
            payload = json.dumps(sv.value)
            lines.append(
                f"{sv.key} = _json.loads(r'''{payload}''')  "
                f"# shared by {sv.producer}"
            )
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._values)


# ── NamespacePartition ────────────────────────────────────────────────────────

# Names IPython injects into the user namespace automatically. They are
# kernel machinery, not agent writes — never isolation violations.
IPYTHON_INTERNALS = frozenset({
    "In", "Out", "get_ipython", "exit", "quit", "open",
})


class NamespacePartition:
    """
    Declares which namespace prefixes each agent may write (K-009).

    After an agent's turn, verify(namespace_keys, shared_keys) reports
    keys the agent wrote outside its declared prefixes — those keys are
    isolated and never exported.
    """

    def __init__(self):
        self._writes: dict[str, list[str]] = {}

    def register(self, agent: str, prefixes: list[str]) -> None:
        self._writes[agent] = list(prefixes)

    def writes_for(self, agent: str) -> list[str]:
        return list(self._writes.get(agent, []))

    def allows(self, agent: str, key: str) -> bool:
        """True if `key` matches one of the agent's declared prefixes."""
        prefixes = self._writes.get(agent, [])
        if not prefixes:
            return False
        return any(
            key == p or key.startswith(p) for p in prefixes
        )

    def violations(
        self,
        agent:          str,
        namespace_keys: list[str],
        shared_keys:    list[str],
    ) -> list[str]:
        """
        Keys in the namespace that the agent may not write.

        A key is allowed if it matches the agent's declared prefixes OR
        is explicitly shared (seeded by a previous agent).
        """
        shared = set(shared_keys)
        return [
            key for key in namespace_keys
            if key not in IPYTHON_INTERNALS
            and key not in shared
            and not self.allows(agent, key)
        ]


# ── Export / import helpers (host-side) ───────────────────────────────────────

EXPORT_CODE = """
import json as _json
_out = dict()
for _k, _v in list(globals().items()):
    if _k.startswith('_'):
        continue
    if not any(_k.startswith(_p) or _k == _p for _p in {prefixes!r}):
        continue
    if isinstance(_v, (str, int, float, bool)) or _v is None:
        _out[_k] = _v
    elif isinstance(_v, (list, dict)):
        try:
            _json.dumps(_v)
            _out[_k] = _v
        except Exception:
            pass
print(_json.dumps(_out))
"""


def export_code(prefixes: list[str]) -> str:
    """Kernel code that prints a JSON map of the agent's declared writes."""
    return EXPORT_CODE.format(prefixes=prefixes)


def parse_export(stdout: str) -> dict:
    """Parse the JSON printed by export_code(). Returns {} on failure."""
    try:
        data = json.loads(stdout)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def isolate_seed_code(shared: SharedMemory, agent: str) -> str:
    """
    Seed code for one agent: shared values it may READ.

    An agent may read any shared value, but shared values are immutable
    JSON copies — the agent can never mutate another agent's state
    through them.
    """
    return shared.seed_code()
