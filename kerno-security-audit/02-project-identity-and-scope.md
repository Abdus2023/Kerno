# 02 · Project Identity and Scope

## Identity

| Field | Value |
|---|---|
| Name | Kerno |
| Repository | `Abdus2023/Kerno` (public) |
| Version audited | 0.2.0 |
| Audit head | `75fa4ab` — "deps: split kerno into a lean core + optional packs" |
| Language / runtime | Python ≥ 3.11 |
| Package | `kerno` (wheel `kerno-0.2.0-py3-none-any.whl`, 176 modules) |
| Description | "A kernel-native agent runtime. Brain meets body." — an LLM writes Python cells executed in a persistent Jupyter kernel, with an agent loop, persistence, reproducibility, and security layers around it |

## What the system is

Kerno connects a **brain** (any LLM callable) to a **body** (a Jupyter/IPython
kernel) and wraps the pair in a runtime:

- **Execution layer** — `KernelRuntime` over `jupyter_client`; `ExecutionEngine`
  as the single choke point; `KernelPool`; distributed `WorkerPool`.
- **Agent layer** — six loop strategies (reactive, reflect, plan, hierarchical,
  multi-agent, debate), session resume/fork/replay, checkpoints, budgets,
  cancellation.
- **Security layer** — capability broker, allowlist policy, human approval,
  secrets, redaction, isolation primitives.
- **Surface layer** — CLI (`kerno`), HTTP `/run`, OpenAI-compatible API,
  authenticated server, notebook projection, reproducibility manifests.

## Scope of this audit

**In scope:**

- The `kerno` package source (39 top-level modules + subpackages).
- All execution paths: loops, pool, distributed executor, server endpoints.
- The security primitives: allowlist, capability broker, secrets, approval,
  isolation, redaction.
- The test suite (1047 tests) and its coverage of security invariants.
- The release artifact (wheel build, fresh-venv install, doctor).
- The dependency split (core vs optional packs).

**Out of scope:**

- The LLM providers themselves (Anthropic/OpenAI SDKs — treated as trusted
  transport).
- The Jupyter/IPython kernel internals (treated as the trusted compute
  substrate; Kerno's job is to police what reaches it).
- The host operating system and container runtime (assumed patched).
- The audit's own tooling (pytest, hypothesis, etc.).

## Source material

This audit is the consolidated result of a 16-part analysis trail:

1. Initial query and package status
2. Dependency architecture
3. Branch audit (time-series skills)
4. Skill registry and composition
5. Kernel runtime execution boundary
6. Kernel pool and concurrency
7. Isolation and communication
8. Kernel output and execution design
9. Agent loop and orchestration
10. Prompt, error, and persistence
11. Security and policy enforcement
12. Critical security findings
13. Execution-path audit
14. Repository evidence and trust
15. Guardrail and enforcement audit
16. Security invariants and specification

plus direct source verification (every claim in this audit was re-checked
against the code, the test suite, and fresh-venv installs).

Next: `03-architecture-and-threat-model.md`.
