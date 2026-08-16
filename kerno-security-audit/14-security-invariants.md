# 14 · Security Invariants

The audit's ten architectural invariants (K-001…K-010), each with its
enforcing mechanism and the test that verifies it.

## K-001 — Single execution boundary

> Every executable agent action passes through `ExecutionEngine`.

- **Enforced by:** all loops, pool workers, distributed workers, and server
  endpoints construct with the engine; raw `kernel.execute` call sites
  audited and categorized.
- **Verified by:** `tests/behavioral/test_security_chokepoint.py` (per-loop
  real-kernel policy enforcement); source audit of every `execute` call.

## K-002 — No direct privileged capability

> Kernel code cannot directly obtain privileged host capabilities.

- **Enforced by:** allowlist blocks `os.environ`, `subprocess`, `socket`,
  `requests`, magics/shell escapes; capability broker gates operations;
  `CapabilityExecutor` performs filesystem/artifact/secret ops host-side.
- **Verified by:** `test_execution_engine.py::TestMagicAndShellBlocking`,
  `test_capability_exec.py`, `test_security.py`.

## K-003 — Kernel isolation

> Untrusted workloads execute in an OS-level isolation boundary.

- **Enforced by (available):** `DockerExecutor` (cpus/memory/pids/network
  none/read-only), `SubprocessExecutor`, K-009 isolated kernels.
- **Verified by:** `test_isolation.py` (mocked docker), `test_subprocess_exec.py`.
- **Honest status:** operator must deploy; not the default.

## K-004 — Session/kernel independence

> Kernel failure does not imply session failure.

- **Enforced by:** `auto_restart` + state restoration (only successful cells
  re-run), `resume_session`, `resume_from_notebook`, sticky DEAD state.
- **Verified by:** `test_session_resume.py` (SIGKILL), `test_kernel_state.py`,
  `test_fault_injection.py`.

## K-005 — Event completeness

> Every externally meaningful execution transition emits an event.

- **Enforced by:** `ExecutionEngine._emit` for REQUESTED / STARTED /
  COMPLETED / CAPABILITY_DENIED / POLICY_BLOCKED / APPROVAL_DENIED /
  EFFECT_VIOLATION / CANCELLED.
- **Verified by:** `test_execution_engine.py::TestEventStream`.

## K-006 — Provenance

> Every artifact is traceable to the execution that created it.

- **Enforced by:** `ProvenanceGraph` (execution nodes with code hashes),
  `ArtifactStore.creator_execution`, notebook cell metadata.
- **Verified by:** `test_provenance_graph.py`, `test_artifacts_effects_approval.py`.

## K-007 — Checkpoint consistency

> A checkpoint identifies exactly which state and event sequence it
> represents.

- **Enforced by:** `Checkpoint.capture(state_version, event_sequence,
  kernel_generation, artifact_hashes)`; host-side `CapturePoint` in live
  loops.
- **Verified by:** `test_checkpoint.py`, `test_checkpoint_live.py`,
  `test_capture_point.py`.

## K-008 — Capability authorization

> Capabilities are granted explicitly, never inferred from Python syntax.

- **Enforced by:** `CapabilityBroker` (scoped, subject-attributed, expiring,
  attenuating grants); agents as principals (`subject=agent name`).
- **Verified by:** `test_capability_broker.py`,
  `test_multi_agent_isolation.py::TestAgentsAsSecurityPrincipals` (real
  kernel: grant to analyst only → critic's code never executes).

## K-009 — Multi-agent isolation

> Agents do not share mutable kernel state unless explicitly configured.

- **Enforced by:** `isolation="isolated"` (fresh kernel per turn),
  `SharedMemory` (attributable, immutable JSON copies), `NamespacePartition`
  (undeclared writes flagged, never exported), `AgentBus`.
- **Verified by:** `test_multi_agent_isolation.py`, `test_multi_agent_bus.py`.

## K-010 — CI evidence

> Test presence is never treated as evidence that CI passed.

- **Enforced by:** the audit's own discipline — property/integration suites
  were found skipped and fixed; `make ci` reproduces gates; the workflow
  file is ready but un-pushed (documented, not claimed).
- **Verified by:** this audit's verification section; the flake archaeology
  in `12`.

## P1–P10 runtime properties (audit #101)

| P | Property | Check |
|---|---|---|
| P1 | completed execution cannot return to running | `check_terminal_events` |
| P2 | denied action cannot execute | `check_denied_never_started` |
| P3/P10 | exactly one terminal outcome, terminal is final | `check_single_terminal_state` |
| P4 | artifact provenance references valid executions | `check_artifact_provenance` |
| P5 | event sequence is monotonic | `check_monotonic_sequence` |
| P6 | child capability set ⊆ parent | `check_attenuation` |
| P7 | replay does not invoke the Brain | `check_replay_llm_free` |
| P8 | kernel restart increments generation | `check_generation_monotonic` |
| P9 | session survives kernel restart | `check_session_recovered` |

All checks detect violations (tested both ways); `kerno doctor` runs them
operationally.

Next: `15-verification-gates.md`.
