# Changelog

All notable changes to Kerno are documented here, grouped by the deep-audit
implementation phases (see `docs/kerno-deep-audit.md`).

## [0.2.1-dev] — 2026-08-16 (Traceability & Phase D/E Hardening)

### Security & Hardening (Phase D)
- **Profile Attenuation Hierarchy & Downgrade Prevention** — implemented `PROFILE_RANK` and `resolve_effective_profile()` in `kerno/server/security.py`, preventing client requests from downgrading server security policies (`K-012`).
- **Complete Removal of `os.path` from Allowlists** — removed `os.path` from `data_analysis()` and enforced exact module name verification for dangerous imports in `kerno/security/allowlist.py` (`K-002`).
- **Universal Gateway Choke Point on all Transports** — routed `/run`, `/stream`, and WebSocket `/ws` through `_build_gateway_engine()` with cancellation token registration and server-side cell clamping (`K-011`, `K-013`).
- **Production Compose Port Isolation & Non-Root User** — removed external port 8001 publishing in `docker-compose.prod.yml` and configured non-root user `kerno` (UID 1000) in `Dockerfile.kerno`.
- **Thread-Safe Atomic Sequence Allocation** — guarded `_sequence` and `_event_seq` with `threading.Lock` in `ExecutionEngine`, ensuring race-free sequence monotonicity under multi-threaded parallel execution.
- **APIKeyStore Hash Minimization** — removed unused `legacy_hash` from stored API key records in `kerno/server/auth.py`.
- **Canonical Execution Transaction Pipeline** — implemented `_prepare_transaction()` and `_finalize_transaction()` in `ExecutionEngine`, ensuring 100% semantic and lifecycle parity between synchronous and streaming execution modes (`K-001`).
- **Indirect AST Builtin Defense** — enhanced `AllowList.check()` to intercept indirect builtin access via `getattr()`, `hasattr()`, `__builtins__`, `_original_import`, and dictionary subscript lookups in `kerno/security/allowlist.py`.
- **Dangerous Stdlib Filter in Runtime Hook** — filtered dangerous system modules (`os`, `subprocess`, `sys`, `socket`, `ctypes`, `shutil`, `importlib`, etc.) from automatic standard library allowance in `to_kernel_code()`.
- **Production Authentication Fail-Closed** — enforced fail-closed behavior on `verify_api_key()` when `KERNO_ENABLE_AUTH=true` or running in production mode with missing API keys in `kerno/server/auth.py`.
- **ExecutionRecord Monotonic Sequence Capture** — captured sequence number at transaction preparation time to prevent concurrency sequence collisions in `kerno/execution/engine.py`.
- **ExecutionEngine Streaming Choke Point** — added `stream_execute()` to `ExecutionEngine`, enforcing capability authorization, allowlist inspection, and secret redaction on all streamed execution chunks (`K-001`).
- **Import Hook Closure Encapsulation** — encapsulated `_restricted_import` in a closure and deleted helper references from kernel `globals()`, eliminating `_original_import` escape routes in `kerno/security/allowlist.py`.
- **SharedMemory Deep-Copy Mutation Isolation** — enforced deep-copying on `put()`, `get()`, and `items()` in `kerno/isolation.py`, preventing mutable reference contamination on the host (`K-009`).
- **P1/P8 Formal Invariant Alignment** — aligned `check_terminal_events()` with observational `EVT_EFFECT_VIOLATION` events and clarified `P8` non-decreasing generation semantics in `kerno/invariants.py`.
- **Docker Sandbox Hardening** — added default `--security-opt=no-new-privileges:true` and `--cap-drop=ALL` to `DockerExecutor.start()`.
- **PBKDF2-HMAC-SHA256 APIKeyStore** — upgraded from raw SHA-256 to salted PBKDF2 (100,000 iterations standard, 16-byte cryptographically random salt per key) with constant-time comparison (`hmac.compare_digest`) in `kerno/server/auth.py`.
- **Skill Capability Attenuation Bridge** — implemented `grant_skill_capabilities()` bridging `SkillProvenance` declared capabilities into `CapabilityBroker` grants with strict subject scoping (`K-008`, `P6`) in `kerno/skilltrust.py`.
- **Container Sandbox Profile** — added `docker-compose.security.yml` specifying the K-003 containment boundary (`cap_drop: [ALL]`, `read_only: true`, `network_mode: none`, `tmpfs`, and cgroups limits).
- **HTTP Server Cancellation** — added `POST /sessions/{session_id}/cancel` and thread-safe `CancellationToken` request mapping in `kerno/server/app.py`; wired mid-cell cancellation checks into `ExecuteStep` in `kerno/steps/execute.py`.
- **Action Retry Facade Integration** — wired `max_retries` and `RetryExecutor` directly into public `run()` and `run_with_pool()` in `kerno/_run.py` (audit #50).

### Verification & Scale (Phase E)
- **AllowList AST Defense-in-Depth** — augmented regex pattern matching with `ast.parse` and `ast.walk` to inspect all imports, from-imports, and calls against obfuscated syntax (e.g. multi-line imports, whitespace evasion) in `kerno/security/allowlist.py`.
- **Property-Based AllowList Fuzzing** — added `TestAllowListFuzzing` in `tests/property/test_pipeline_properties.py`.
- **Distributed Remote Worker** — implemented `RemoteWorker` supporting HTTP/JSON-RPC communication with remote Kerno daemons in `kerno/distributed.py` (audit #104).
- **Reproducibility Environment Verification** — added `verify_environment()` for automated validation of Python versions, platform info, and package dependencies against recorded `ReproducibilityManifest` snapshots in `kerno/reproducibility.py`.
- **Traceability Report** — added `docs/TRACEABILITY_REPORT.md` providing bidirectional mapping across requirements, findings 01–16, invariants K-001–K-010, and verification test gates.

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
