# 03 · Architecture and Threat Model

## The architecture in one diagram

```
                ┌──────────────────────┐
                │      LLM / Brain     │   (any callable: anthropic, openai,
                └──────────┬───────────┘    openrouter, ScriptedBrain, …)
                           │  messages
                           ▼
                ┌──────────────────────┐
                │   Agent loops (×6)   │   reactive · reflect · plan ·
                └──────────┬───────────┘   hierarchical · multi_agent · debate
                           │  code cells
                           ▼
        ┌─────────────────────────────────────────┐
        │          ExecutionEngine (K-001)        │   THE choke point
        │  1. capability authorization (K-008)    │
        │  2. allowlist policy                    │
        │  3. human approval (fail closed)        │
        │  4. execution → audit → events → redact │
        └──────────────────┬──────────────────────┘
                           │
              ┌────────────┼─────────────┬──────────────┐
              ▼            ▼             ▼              ▼
        KernelRuntime  KernelPool   Distributed     HTTP servers
        (Jupyter)      (parallel)   (workers)       (/run, OpenAI, secure)
              │            │             │              │
              └────────────┴─────────────┴──────────────┘
                           │
              ┌────────────┴─────────────┐
              ▼                          ▼
        DockerExecutor            SubprocessExecutor
        (OS isolation,            (process isolation,
         optional)                 optional)
```

Every agent-generated cell — regardless of which loop, pool, worker, or HTTP
endpoint produced it — passes through `ExecutionEngine.execute()`.

## Components and trust

| Component | Trusted? | Why |
|---|---|---|
| LLM providers (SDKs) | Trusted transport | Model output is *untrusted content* |
| Jupyter/IPython kernel | Trusted substrate | Runs the code; does not police it |
| Skills bootstrap / custom skills file | Host-authored | Loaded verbatim at session start — vet before use |
| Allowlist hook, comms setup, file materializer, RAG bridge | Host-authored | Never LLM text |
| Kernel-side checkpoint code (`_auto_checkpoint`) | Host-authored (residual) | Runs inside the agent namespace — prefer host-side `CapturePoint` |
| Dev reload/REPL tools | Host-authored | Development tools on your own code |

## Threat model

Four adversary classes, in the repository's own terms:

1. **Prompt injection via data** — hostile data (CSV cells, web content,
   uploaded files) tells the LLM to emit harmful code.
   *Defense:* allowlist static analysis + capability grants + (optional)
   `InputSanitizer` on data columns.

2. **Capability creep** — the agent imports or calls things it shouldn't.
   *Defense:* allowlist module/pattern rules + runtime import hook +
   capability broker grants per subject.

3. **Data exfiltration** — the agent sends data to external endpoints.
   *Defense:* blocked network primitives in restrictive profiles,
   `--network none` in `DockerExecutor`, effect ledger for undeclared
   filesystem writes.

4. **Secret disclosure** — secrets leak into prompts, outputs, notebooks,
   logs.
   *Defense:* `SecretBroker` (per-subject grants) + redaction through
   records, events, outputs, and notebook cells.

Plus the meta-threat: **the tooling itself** (the audit's own test suite
being skipped, CI not running, packaging bugs) — which this audit found and
fixed (see `05`).

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

The allowlist is **layer 2, not the boundary**. The import hook is
**defense-in-depth**, not a sandbox. This is stated in `SECURITY.md` and
repeated here because it is the single most important honest caveat.

Next: `04-security-findings.md` (the master register).
