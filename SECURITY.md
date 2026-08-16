# Kerno Security

Kerno is a kernel-native agent runtime: an LLM writes Python that runs in
a persistent Jupyter kernel. This document states the security model, the
trust boundaries, and what is — and is not — guaranteed.

## Threat model

1. **Prompt injection via data** — hostile data tells the LLM to execute
   harmful code.
2. **Capability creep** — the agent imports or calls things it shouldn't.
3. **Data exfiltration** — the agent sends data to external endpoints.
4. **Secret disclosure** — secrets leak into prompts, outputs, notebooks,
   or logs.

## Defense in depth

```
                    Kerno
                      │
                 Policy Engine
                      │
        ┌─────────────┴─────────────┐
        ▼                           ▼
 Application policy           OS policy
 (choke point, K-001)      (Docker / VM isolation)
        │                           │
        ▼                           ▼
 Capability broker         Container / VM limits
        │                           │
        └─────────────┬─────────────┘
                      ▼
                   Kernel
```

### Layer 1 — The execution choke point (K-001)

Every agent-generated cell — in every loop strategy, the pool, the
distributed executor, and every HTTP server surface — passes through
`ExecutionEngine`, which applies, in order:

1. **Authorization** — capability broker grants (K-008), scoped per
   subject with expiry, revocation, and attenuation.
2. **Policy** — allowlist static analysis (imports, dangerous builtins,
   write methods, URL-backed loads, IPython `%magic`/`!shell` escapes).
3. **Human approval** — `human.approval` executions consult an
   `ApprovalGate`; **fail closed** when no gate is installed.
4. **Execution** — delegation to the kernel (or any Executor backend).
5. **Audit + events** — immutable records and a causal event stream.
6. **Redaction** — recorded previews, errors, cell outputs, and notebook
   cells are scrubbed of registered secrets (audit #67/#68).

Policy violations never reach the kernel: they become error cells the
loop can recover from.

### Layer 2 — Runtime import hook

The kernel's `builtins.__import__` is restricted to allowlisted modules,
stdlib, and already-loaded modules. This is **defense-in-depth**, not a
sandbox: a determined in-process attack can reach objects already in
`sys.modules`.

### Layer 3 — OS-level isolation

For untrusted workloads, run the kernel inside a container or VM:

- `DockerExecutor` — cpus/memory/pids-limit/network-none/read-only
  filesystem, hard exec timeout.
- `SubprocessExecutor` — fresh process per execution with prlimit
  resource limits (state isolation, not a security boundary).
- `isolation="isolated"` multi-agent mode — each agent runs in its own
  kernel; state crosses boundaries only through explicit, attributable
  `SharedMemory` and `AgentBus` messages.

**Kerno's allowlist is a policy layer, not a sandbox.** Until execution
is OS-isolated, treat LLM-generated code as running in your trust
domain.

## Trust boundaries

| Path | Trusted? | Notes |
|---|---|---|
| LLM-generated cells | **No** | Choke point enforced (K-001) |
| Notebook re-execution via `load_notebook(..., engine=...)` | **No** | Goes through the engine — policy applies |
| `load_notebook(..., re_execute=True)` without an engine | **No** | Raw re-execution; explicit opt-in for trusted callers only |
| Skills bootstrap (`bootstrap_skills`) | Host-authored | Loaded at session start from the installed package |
| Custom skills file (`skills_path`) | Host-authored | Loaded verbatim — vet before use |
| Allowlist hook install, comms setup, file materializer, RAG bridge | Host-authored | Trusted infrastructure, never LLM text |
| Kernel-side checkpoint code (`_auto_checkpoint`, CheckpointMiddleware) | Host-authored | Runs inside the agent namespace (audit #15 residual) — prefer host-side `CapturePoint` |
| `kerno dev` reload/REPL tools | Host-authored | Development tools; operate on your own code |

## Secrets

- `SecretBroker` grants secrets per subject with expiry and revocation;
  the kernel never receives an environment dump.
- Registered secret values are redacted from: execution records, event
  payloads, policy error values, agent cell outputs, notebook code/
  reasoning/error text, and session persistence.
- Reproducibility manifests record environment variable **names only**,
  never values.

## Invariants (audit #101)

K-001 single execution boundary · K-002 no direct privileged capability ·
K-003 kernel isolation for untrusted workloads · K-004 session survives
kernel death · K-005 event completeness · K-006 artifact provenance ·
K-007 checkpoint consistency · K-008 explicit capability authorization ·
K-009 multi-agent isolation · K-010 CI evidence.

Verify them locally: `kerno doctor` (P1–P10 checks) and `make ci`.

## Reporting

Open an issue in the repository. Include the kerno version, the security
profile in use, and (for suspected bypasses) a minimal reproduction.
