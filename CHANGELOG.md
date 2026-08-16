# Changelog

All notable changes to Kerno are documented here, grouped by the deep-audit
implementation phases (see `docs/kerno-deep-audit.md`).

## [0.2.0] — 2026-08-16

### Security (Phase A)
- **ExecutionEngine** — the single execution choke point (K-001): every
  agent cell passes authorization → policy → execution → audit → event
  stream. All loop strategies, the pool, the distributed executor, and
  every HTTP server surface go through it.
- **CapabilityBroker** — scoped, subject-attributed grants with expiry,
  revocation, and attenuation (child ⊆ parent); agents are security
  principals.
- **Allowlist hardening** — runtime import hook fixed (was re-entrant and
  wedged kernels); pathlib/pandas/matplotlib write methods, URL-backed
  loads, `os.environ`, `importlib`, IPython `%magic` lines, and `!shell`
  escapes blocked.
- **SecretBroker + redaction** — secrets granted per-subject; outputs,
  code previews, errors, and notebook cells scrubbed before they reach
  the LLM, the notebook, or persistence (audit #67/#68).
- **Human approval** — `CAP_HUMAN_APPROVAL` gates fail closed.
- **Isolation** — DockerExecutor (cpus/memory/network/read-only limits),
  SubprocessExecutor (prlimit + clean namespaces), K-009 isolated
  multi-agent kernels with SharedMemory + AgentBus.

### State & execution model (Phase B)
- AgentState versioning/fork/snapshot; StateLedger; ProvenanceGraph
  (K-006); CheckpointStore (K-007); host-side CapturePoint checkpoints
  in live loops.
- Action model + state machine (exactly one terminal outcome, P10);
  idempotency-aware RetryExecutor; ExecutionEvent causal chains;
  execution_id correlation end-to-end.

### Lifecycle (Phase C)
- K-004 kernel-death recovery (`auto_restart`), resume_session,
  resume_from_notebook, fork_session; kernel health state with sticky
  DEAD; timeout escalation; ExecutionBudget + hierarchical
  BudgetAllocator; KernelPool health_check/restart/interrupt;
  TaskScheduler (priorities + concurrency); CancellationToken across
  every loop strategy and the HTTP surface.

### Reproducibility (Phase E)
- ReproducibilityManifest (env snapshot, input/artifact hashes, model,
  seeds), environment locks, notebook projection with execution
  metadata, notebook as content-addressed artifact, replay without the
  LLM (audit #58), execution modes (dry_run), session JSON persistence.

### Operations
- `kerno doctor` runtime invariant checks (P1–P10); `kerno resume`,
  `kerno fork`, `kerno session export`; `--dry-run`, `--budget`,
  `--isolation`, `--auto-restart`; config validation; execution → metrics
  projection; server choke point on all HTTP surfaces.
- Full suite: **1031 tests passing** (unit, behavioral on real kernels,
  integration, property).

### Package split (audit #16)

- **Lean core + optional packs**: `pip install kerno` now installs only
  the runtime (jupyter-client, nbformat, ipykernel, pyyaml). The
  analytical stack moved to `kerno[data]`; HTTP surfaces to
  `kerno[server]`; providers and skill-packs remain per-extra.
- **Graceful skill degradation**: `bootstrap(skip_missing_deps=True)`
  probes each skill module's kernel-side dependencies in one batched
  cell and skips modules whose deps are missing — with a warning —
  instead of crashing the session. Verified: a core-only install runs
  full live sessions; a `[data]` install loads 114 skills.
- `kerno doctor` reports optional packs with ○ (never fails the check).
- Fixed the probe's f-string bug (the dependency probe cell was a
  SyntaxError and silently skipped everything).

### Fixed (deep-verification pass)
- **OpenAI-compat `/health` endpoint 500'd** — `pool.stats()` was called
  as a method but `KernelPool.stats` is a property (`TypeError: 'dict'
  object is not callable`); only discovered by standing up a live server
  and running the integration suite (previously skipped).
- **Property-based tests never ran** — `hypothesis` was missing from the
  dev extras, so `tests/property/` (7 tests) was silently skipped all
  session; now runs and passes.
- **Integration tests verified live** — stood up the OpenAI-compat server
  with a deterministic `ScriptedBrain` and ran all 4 tests (health,
  models, sync completion, streaming) against it: all pass.

### Fixed (earlier)
- `run()` crashed for every caller (`load_default_skills` shadowing).
- Allowlist runtime hook infinite recursion (wedged kernels).
- Comm listener thread stole iopub messages (hung cells + zmq segfault).
- Falsy-store bugs (`__len__` on memory/shared stores breaking `or`/`and`
  checks — three occurrences).
- Hierarchical/Debate loops hardcoded `COMPLETE` status, ignoring
  cancellation.
- Skill-load 30s timeout under load; never-yielding mock LLM in a test
  (120 real kernel executions).

## [0.1.0] — baseline

Original Kerno: kernel runtime over Jupyter/IPython, loop strategies,
skills, memory, notebooks, plugins, telemetry, server.
