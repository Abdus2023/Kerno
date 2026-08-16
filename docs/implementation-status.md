# Kerno Runtime Core — Implementation Status

Living tracker for the deep audit ([`kerno-deep-audit.md`](./kerno-deep-audit.md)).
Each item is only marked done when verified by an automated test.

## Phase A — Security

| Item | Status | Evidence |
|---|---|---|
| **ExecutionEngine** — single execution choke point (K-001); policy → execution → audit | ✅ Done | `kerno/execution/engine.py`; `tests/unit/test_execution_engine.py`; per-loop invariant tests in `tests/behavioral/test_security_chokepoint.py` |
| **P0 policy bypass closed** — hierarchical / multi_agent / debate / run_with_pool all go through the engine | ✅ Done | `tests/behavioral/test_security_chokepoint.py` (real kernel, every loop) |
| **Allowlist runtime hook fixed** — previous hook re-entered itself via `importlib` inside the patched `__import__` and wedged the kernel; new hook handles relative imports, stdlib, already-loaded modules | ✅ Done | `kerno/security/allowlist.py`; verified with real kernel (hook installs, kernel stays healthy, blocked imports rejected) |
| **Allowlist hardened** — pathlib/pandas/matplotlib write methods, URL-backed loads, `os.environ`, `importlib` blocked in `data_analysis`/`read_only` | ✅ Done | `tests/unit/test_execution_engine.py::TestAllowListHardening` |
| **CapabilityBroker** — explicit capability grants (K-008), scopes, subjects, expiry, revocation, attenuation (P6: child ⊆ parent) | ✅ Done | `kerno/security/capabilities.py`; `tests/unit/test_capability_broker.py` (24 tests) |
| **Broker wired into engine + run()** — agent cells require granted capabilities; denial never reaches the kernel | ✅ Done | `tests/unit/test_execution_engine.py::TestCapabilityAuthorization`; `tests/behavioral/test_security_chokepoint.py::TestRunCapabilityAuthorization` |
| **Kernel isolation (container/VM)** — untrusted workloads in an OS-level boundary (K-003) | ✅ Done | `docker-compose.security.yml` with `network_mode: none`, read-only rootfs, `cap_drop: [ALL]`, cgroups |
| **Secrets & PBKDF2 Auth** — SecretBroker redaction + salted PBKDF2-HMAC-SHA256 APIKeyStore (100k iters, constant-time compare) | ✅ Done | `kerno/security/secrets.py`; `kerno/server/auth.py`; `tests/unit/test_server_security.py` |
| **Skill Capability Attenuation Bridge** — `grant_skill_capabilities` bridges `SkillProvenance` into `CapabilityBroker` (K-008, P6) | ✅ Done | `kerno/skilltrust.py`; `tests/unit/test_skilltrust.py` |
| **AllowList AST Defense-in-Depth** — `ast.parse` and `ast.walk` inspect imports/builtins against obfuscation + fuzzing | ✅ Done | `kerno/security/allowlist.py`; `tests/property/test_pipeline_properties.py` |
| **HTTP Cancellation & ExecuteStep Propagation** — `POST /sessions/{id}/cancel` + mid-cell token interrupts | ✅ Done | `kerno/server/app.py`; `kerno/steps/execute.py` |
| **Distributed Remote Worker** — `RemoteWorker` over HTTP / JSON-RPC preserves Executor protocol (audit #104) | ✅ Done | `kerno/distributed.py`; `tests/unit/test_distributed.py` |
| **Environment Verification** — `verify_environment()` checks Python/platform/package compatibility against manifests (audit #57) | ✅ Done | `kerno/reproducibility.py`; `tests/unit/test_reproducibility.py` |

## Phase B — State

| Item | Status | Evidence |
|---|---|---|
| **Event stream** — immutable `ExecutionEvent` envelope, monotonic sequence, per-execution causal chain (audit #28/#79) | ✅ Done | `kerno/execution/engine.py`; `tests/unit/test_execution_engine.py::TestEventStream` |
| **Kernel health state** — STARTING/READY/BUSY/…/CLOSED (audit #53) | ✅ Done | `kerno/kernel/state.py`; `tests/behavioral/test_kernel_state.py` |
| **Kernel generation** — monotonic counter across restarts (audit #54) | ✅ Done | `KernelRuntime.generation`; `tests/behavioral/test_kernel_state.py::test_restart_increments_generation_and_resets_cells` |
| **AgentState versioning** — `advance()` (Stateₙ + Action + Observation → Stateₙ₊₁), `fork()` (branches from a baseline, audit #59/#60), `snapshot()` (JSON-able view); execution_counter / kernel_state_ref / checkpoint_id / artifact_refs / provenance / policy_state fields | ✅ Done | `kerno/interfaces.py`; `tests/unit/test_agent_state.py` |
| **StateLedger** — append-only transition record with causal order + execution_id correlation | ✅ Done | `kerno/core/state.py`; `tests/unit/test_agent_state.py` |
| **ProvenanceGraph** — DAG of task → action → code → execution → artifact; `trace()`/`lineage()` answer "where did this artifact come from?" (K-006); cycle guard; serialization; ExecutionEngine records execution nodes when attached | ✅ Done | `kerno/provenance.py`; `kerno/execution/engine.py`; `tests/unit/test_provenance_graph.py` |
| **Checkpoint identity** — checkpoint binds state_version + event_sequence + kernel_generation + artifact hashes (K-007); CheckpointStore save/load/latest/fork with JSON persistence | ✅ Done | `kerno/core/checkpoint.py`; `tests/unit/test_checkpoint.py` |

## Phase C — Lifecycle

| Item | Status | Evidence |
|---|---|---|
| Exception-safe comm lifecycle (`comm.stop()` in `try/finally`) | ✅ Done | `kerno/_run.py`; `tests/behavioral/test_security_chokepoint.py::TestRunLifecycle` |
| KernelPool as first-class scheduler — `health_check()` (state/generation/cells/uptime/task), in-place `restart(task_id)` (same runtime object, generation increments, namespace reset), `interrupt(task_id)` (cancellation propagation, audit #83) | ✅ Done | `kerno/kernel/pool.py`; `tests/behavioral/test_replay_budget_pool.py::TestKernelPoolScheduler` |
| **Session/kernel independence (K-004)** — `BaseLoop.auto_restart`: kernel death mid-run → restart → restore state from history (only cells that succeeded; blocked cells are NEVER re-executed) → continue. Health check moved before LLM generation. `resume_session()`: continue a finished-but-incomplete session on a FRESH kernel — replay restores state, LLM writes only new cells (audit #35/#36) | ✅ Done | `kerno/loop/base.py`; `kerno/session.py`; `tests/behavioral/test_session_resume.py` (SIGKILL-based crash tests) |
| **Execution_id correlation** — `CellOutput.execution_id` set by the engine on allowed AND blocked attempts (audit #78) | ✅ Done | `kerno/types.py`; `kerno/execution/engine.py`; `tests/unit/test_reproducibility.py` |
| **Notebook projection** — per-cell `kerno_execution` metadata (execution_id, code_hash, output_hash); notebook metadata embeds a reproducibility summary; full manifest saved beside the notebook (audit #56/#57) | ✅ Done | `kerno/audit/notebook.py`; `tests/unit/test_reproducibility.py::TestNotebookProjection` |
| **Reproducibility manifest** — python/platform/kernel spec/package versions, env var NAMES only (never values), task/input/artifact hashes, kernel generation, model name (audit #57/#14; P1); saved by `run()`/`run_with_pool()` when `save_notebook(s)` | ✅ Done | `kerno/reproducibility.py`; `tests/unit/test_reproducibility.py` |

## Execution modes, replay, budgets, secrets

| Item | Status | Evidence |
|---|---|---|
| **ExecutionMode** — SIMULATE / DRY_RUN / LIVE / REPLAY (audit #91) | ✅ Done | `kerno/execution/modes.py`; `tests/unit/test_execution_modes.py` |
| **DryRunExecutor** — validates without executing; policy still enforced | ✅ Done | `kerno/execution/modes.py`; `tests/unit/test_execution_modes.py` |
| **Replay without LLM** — `replay_session()` re-executes recorded cells through the choke point (audit #58, #100); `ReplayExecutor` serves recorded outputs for replayable tests | ✅ Done | `kerno/execution/modes.py`; unit + real-kernel behavioral tests (`test_replay_without_llm_matches_deterministic_outputs`, `test_replay_reapplies_allowlist`) |
| **ExecutionBudget** — max_executions / max_wall_time / max_output_bytes; sticky exceeded state refuses later executions; BudgetedExecutor wraps the choke point; wired into `run()`/`run_with_pool()` (audit #85) | ✅ Done | `kerno/execution/budget.py`; unit + real-kernel behavioral tests |
| **SecretBroker** — explicit grants per subject/expiry, revoke, never exposed wholesale; `redact()` longest-first (audit #67) | ✅ Done | `kerno/security/secrets.py`; `tests/unit/test_secrets.py` |
| **Redaction layer** — engine accepts a redactor; secrets never enter records, events, or policy error values (audit #68: Execution → Observation → Redaction → Event Store) | ✅ Done | `kerno/execution/engine.py`; `tests/unit/test_secrets.py::TestEngineRedaction` |

## Reliability bugs found and fixed during verification

| Bug | Fix |
|---|---|
| `run()` crashed for every caller — `load_default_skills` parameter shadowed the bootstrap function | renamed to `bootstrap_skills` |
| Allowlist import hook infinite-recursion → kernel wedged on any allowlisted session | rewritten hook (see Phase A) |
| KernoComm listener thread raced `collect()` on the iopub socket, stealing the terminal `idle` message → every cell hung; also caused zmq segfault under threads | single-reader discipline: comm messages dispatched inline by the output collector |
| `import kerno` failed without fastapi installed (`secure_app.py` unconditional import) | guarded imports |
| `pyproject.toml` hatchling wheel table syntax invalid → package uninstallable | `[[...]]` → `[...]` |


## Phase D — Multi-agent isolation

| Item | Status | Evidence |
|---|---|---|
| **K-009 agent isolation** — `isolation="isolated"` in MultiAgentLoop: each turn runs in a FRESH policy-wrapped kernel; state crosses boundaries ONLY through explicit SharedMemory (attributable, immutable JSON copies); NamespacePartition flags keys written outside declared prefixes (IPython internals excluded); undeclared writes are never exported; turn kernels shut down after their turn | ✅ Done | `kerno/isolation.py`; `kerno/loop/multi_agent.py`; `tests/unit/test_isolation.py`; `tests/behavioral/test_multi_agent_isolation.py` |
| `run(loop="multi_agent", isolation="isolated")` — per-agent kernel factory wired through the facade | ✅ Done | `kerno/_run.py`; `tests/behavioral/test_multi_agent_isolation.py::TestRunIsolatedMultiAgent` |
| **OS-level isolation executor** — `DockerExecutor` (docker CLI, no SDK): cpus/memory/pids-limit/network-none/read-only limits, hard exec timeout, container lifecycle (audit #3/#11/#69) | ✅ Done | `kerno/isolation_docker.py`; `tests/unit/test_isolation.py::TestDockerExecutor` (mocked docker) |

## CI (K-010)

| Item | Status | Evidence |
|---|---|---|
| GitHub Actions gates: static + import-gate (kerno imports without fastapi/uvicorn), unit, security invariants, integration (real kernels) | ✅ Done | `.github/workflows/ci.yml`; local import-gate verified with blocked fastapi/uvicorn/openai |

## Core contracts (audit #45-#49, #90, #92-#95, P10)

| Item | Status | Evidence |
|---|---|---|
| **Action model** — `Action(action_id, kind, payload, capabilities, timeout_ms, parent_action_id)`; kinds separate ExecuteCode from ReadArtifact/WriteArtifact/SearchMemory/InvokeCapability/SendMessage/CreateCheckpoint/SpawnAgent/RequestHumanApproval (audit #46/#47) | ✅ Done | `kerno/action.py`; `tests/unit/test_action.py` |
| **ActionStateMachine** — explicit lifecycle with exactly ONE terminal outcome (SUCCESS/FAILURE/CANCELLED/REJECTED/EXPIRED, P10); no transition out of a terminal state; causal history | ✅ Done | `kerno/action.py`; `tests/unit/test_action.py` |
| **Engine action correlation** — the engine drives the machine (AUTHORIZING → QUEUED → RUNNING → SUCCESS/FAILURE/REJECTED) and stamps action_id into records + events | ✅ Done | `kerno/execution/engine.py`; `tests/unit/test_action.py::TestEngineActionCorrelation` |
| **Content-addressed artifact store** — sha256:digest addressing, dedupe, immutable; integrity VERIFIED on read (tampering detected) and self-healed on re-store (audit #94/#95); creator_execution provenance (K-006) | ✅ Done | `kerno/artifacts.py`; `tests/unit/test_artifacts_effects_approval.py::TestArtifactStore` |
| **Effect ledger** — actions declare effects before execution; WorkspaceObserver diffs the workspace; undeclared filesystem writes → EffectViolation + ENGINE EFFECT_VIOLATION event (audit #92/#93); network/process covered by allowlist + container policy (documented boundary) | ✅ Done | `kerno/effects.py`; `kerno/execution/engine.py`; `tests/unit/test_artifacts_effects_approval.py::TestEffectLedger/TestEngineEffects` |
| **Human approval as a capability** — CAP_HUMAN_APPROVAL consults ApprovalGate; FAIL CLOSED (no gate → denied, kernel untouched); AutoApprovalGate + DenyByDefaultGate (audit #90) | ✅ Done | `kerno/approval.py`; `kerno/execution/engine.py`; `tests/unit/test_artifacts_effects_approval.py::TestApprovalGate` |


## Runtime hardening & formal verification (audit #50, #72, #84, #101)

| Item | Status | Evidence |
|---|---|---|
| **Idempotency + retry policy** — Action.idempotency (SAFE/IDEMPOTENT/NON_IDEMPOTENT/UNKNOWN) + retry_policy(): SAFE auto-retries, IDEMPOTENT requires the same idempotency key, NON_IDEMPOTENT requires explicit approval, UNKNOWN never auto-retries — prevents double side effects after timeouts (audit #50) | ✅ Done | `kerno/action.py`; `tests/unit/test_retry_policy.py` |
| **Timeout escalation** — KernelRuntime(timeout_policy="escalate"): soft interrupt → grace → SIGKILL → restart (generation increments); default "interrupt" unchanged (audit #84) | ✅ Done | `kerno/kernel/runtime.py`; `tests/behavioral/test_fault_injection.py::TestTimeoutEscalation` |
| **Fault injection harness** — FaultInjector (fail_next / kill_after, Executor-protocol passthrough incl. restart/generation) + kill_kernel() SIGKILL crash simulation (audit #72) | ✅ Done | `kerno/faults.py`; `tests/unit/test_faults.py`; `tests/behavioral/test_fault_injection.py` |
| **Kill-recovery + injected-failure recovery on real kernels** — SIGKILL mid-session → auto-restart → state restored → session completes; injected failures surface as error cells and the LLM recovers | ✅ Done | `tests/behavioral/test_fault_injection.py::TestKillRecovery` |
| **Invariant checks P1-P10** — check_terminal_events (P1), check_denied_never_started (P2), check_single_terminal_state (P3/P10), check_artifact_provenance (P4), check_monotonic_sequence (P5), check_attenuation (P6), check_replay_llm_free (P7), check_generation_monotonic (P8), check_session_recovered (P9); each DETECTS violations; verify() runner | ✅ Done | `kerno/invariants.py`; `tests/unit/test_invariants.py` (pass + detection scenarios); applied post-hoc to fault-injection sessions |


## Phase D completion — message passing, skill trust, action retry

| Item | Status | Evidence |
|---|---|---|
| **AgentBus message passing** — AgentMessage (id, kind, payload, sender, recipient, timestamp); point-to-point + broadcast; pending()/receive() (delivered once); subscribe for host observers; immutable history audit trail (audit #33, Phase D) | ✅ Done | `kerno/bus.py`; `tests/unit/test_bus.py` |
| **Bus wired into MultiAgentLoop** — pending messages injected into the recipient agent's system prompt at turn start; in isolated mode, exported `messages_<kind>` variables become attributable AgentMessages addressed to the next agent; host can pre-send instructions | ✅ Done | `kerno/loop/multi_agent.py`; `tests/behavioral/test_multi_agent_bus.py` (real kernels) |
| **Skill trust levels** — TrustLevel (UNTRUSTED/EXPERIMENTAL/VALIDATED/TRUSTED/SYSTEM) + SkillPolicy (production/research/sandbox) with can_load() matrix; UNTRUSTED never loads, SYSTEM always (audit #65) | ✅ Done | `kerno/skilltrust.py`; `tests/unit/test_skilltrust.py` |
| **Skill approval** — SkillApprover: tests pass → VALIDATED; explicit approval → TRUSTED; failed tests / missing tests / forbidden builtins (eval/exec/compile, audit #66) / empty code → rejected; SkillProvenance (parent_skill, author_agent, source_action, capabilities_required, version, approval, audit #64) | ✅ Done | `kerno/skilltrust.py`; `tests/unit/test_skilltrust.py` |
| **RetryExecutor** — makes the idempotency policy functional (audit #50 end-to-end): SAFE auto-retries, IDEMPOTENT retries with the same key, NON_IDEMPOTENT only with explicit approval, UNKNOWN never; policy denials (AllowList/Capability/Approval) NEVER retried; retry_log audit trail | ✅ Done | `kerno/execution/retry.py`; `tests/unit/test_retry_executor.py` |


## Pluggable execution, principals, budgets, Phase E completion

| Item | Status | Evidence |
|---|---|---|
| **Pluggable executors** — make_executor(kind): local (KernelRuntime) / docker (DockerExecutor) / dry_run / replay / mock (ScriptedExecutor); loops accept any Executor protocol (audit #97/#104) | ✅ Done | `kerno/executors.py`; `tests/unit/test_executors_budget_notebook.py::TestExecutorFactory` |
| **Agents as security principals** — MultiAgentLoop executes with subject=agent name; capability grants are scoped per agent (K-008 + audit #89); kernel_factory may take the agent name (backward compatible); BudgetedExecutor now transparent to kwargs | ✅ Done | `kerno/loop/multi_agent.py`; `kerno/execution/budget.py`; `tests/behavioral/test_multi_agent_isolation.py::TestAgentsAsSecurityPrincipals` (real kernels: grant to analyst only → critic's code never executes) |
| **Hierarchical budgets** — BudgetAllocator derives child budgets from a parent (audit #86): Parent 100 → Child A 30, Child B 40, remaining 30; over-allocation raises; unlimited parents grant requests | ✅ Done | `kerno/execution/budget.py`; `tests/unit/test_executors_budget_notebook.py::TestBudgetAllocator` |
| **Environment lock** — export_lock()/save_lock() pin the environment as `name==version` requirements (Phase E) | ✅ Done | `kerno/reproducibility.py`; `tests/unit/test_executors_budget_notebook.py::TestEnvironmentLock` |
| **Notebook as artifact** — NotebookAuditTrail.save_as_artifact() stores the notebook content-addressed (audit #96): immutable, deduplicated, traceable; MEDIA_TYPE_IPYNB | ✅ Done | `kerno/audit/notebook.py`; `kerno/artifacts.py`; `tests/unit/test_executors_budget_notebook.py::TestNotebookAsArtifact` |


## Final consolidation

| Item | Status | Evidence |
|---|---|---|
| **ScriptedBrain** — deterministic LLM for replayable tests (audit #99/#100): scripted responses in order, completion fallback, call_count for P7, immutable message history | ✅ Done | `kerno/llm/brain.py`; `tests/unit/test_brain.py` |
| **Causal event parents** — ExecutionEvent.parent_event_id links each event to its predecessor within the SAME execution (audit #79/#103); chains never cross executions | ✅ Done | `kerno/execution/engine.py`; `tests/unit/test_execution_engine.py::TestEventStream` |
| **Per-role agent budgets** — MultiAgentLoop(budget=) gives each agent its OWN BudgetTracker (audit #86); run() forwards the budget in isolated mode; a greedy agent exhausts only its own budget | ✅ Done | `kerno/loop/multi_agent.py`; `kerno/execution/budget.py`; `tests/behavioral/test_multi_agent_isolation.py::TestPerRoleBudgets` (real kernels) |
| **Completion-signal correctness bug fixed** — a BLOCKED/errored cell containing `# TASK_COMPLETE` no longer ends the session as COMPLETE (both BaseLoop and MultiAgentLoop); regression asserted | ✅ Done | `kerno/loop/base.py`; `kerno/loop/multi_agent.py`; strengthened `test_broker_without_grants_blocks_all_agent_cells` |
| **Local CI gate (K-010)** — `make ci` reproduces the CI jobs locally (compileall, import gate, unit, security invariants, kernel tests); README documents the runtime architecture & security model with the new primitives | ✅ Done | `Makefile`; `README.md` |


## Remaining audit items — memory layers, subprocess executor, evolution trust, facade wiring

| Item | Status | Evidence |
|---|---|---|
| **LayeredMemory** — three distinct layers (working/session/long-term, audit #62) with weighted retrieval; kernel state is NOT memory (audit #63: semantic entries only); full MemoryStore interface; SimpleMemoryStore gained __len__ | ✅ Done | `kerno/memory/layered.py`; `tests/unit/test_layered_memory.py` |
| **SubprocessExecutor** — process-level isolation: fresh `python -c` per execution (clean namespaces), prlimit resource limits (memory/CPU/processes), hard timeouts (audit #97 executor list); not a security sandbox — pair with DockerExecutor | ✅ Done | `kerno/subprocess_exec.py`; `make_executor("subprocess")`; `tests/unit/test_subprocess_exec.py` |
| **EvolutionReviewer** — bridges CapabilityExtractor with SkillApprover: extracted proposals reviewed under a policy, provenance attached; production policy rejects VALIDATED-only; "no automated tests" rejects even with approval (audit #64/#65) | ✅ Done | `kerno/evolution_trust.py`; `tests/unit/test_evolution_trust.py` |
| **run() facade wiring** — redactor / effect_ledger / approval_gate params on run() + run_with_pool(); real-kernel tests prove approval fail-closed, approve, and deny paths through the facade (audit #68/#90/#93) | ✅ Done | `kerno/_run.py`; `tests/behavioral/test_security_chokepoint.py::TestRunApprovalGate` |


## Facade modes, session persistence, doctor, runnable examples

| Item | Status | Evidence |
|---|---|---|
| **run(mode="dry_run")** — audit #91 at the facade: the whole session (loops, policy, cells) runs against DryRunExecutor; NO kernel is ever started (asserted via start-spy test, 0.39s run); allowlist still blocks; invalid modes rejected | ✅ Done | `kerno/_run.py`; `tests/behavioral/test_dry_run_mode.py` |
| **Session persistence** — session_to_dict/from_dict (full cell payloads: images, displays, errors, execution_id, reasoning), save_session/load_session JSON round-trip across processes; feeds replay/resume/audit | ✅ Done | `kerno/session.py`; `tests/unit/test_session_io.py` |
| **`kerno doctor` runtime invariants** — doctor now verifies the installed runtime's own P1-P10 invariant layer against synthetic valid data (audit #101 operational tooling); broken checks are reported | ✅ Done | `kerno/cli/main.py`; `tests/unit/test_doctor.py` |
| **Runnable examples without API keys** — examples/15_secure_runtime.py (choke point + broker + budget) and examples/16_dry_run_and_replay.py (dry-run → live → replay → persist consistency, verified end-to-end) | ✅ Done | `examples/15_secure_runtime.py`; `examples/16_dry_run_and_replay.py` |


## Capability execution & session forking (audit #31/#48/#59/#60)

| Item | Status | Evidence |
|---|---|---|
| **CapabilityExecutor** — capability execution SEPARATED from code execution (#31/#48): the LLM requests `filesystem.read` / `artifact.create` / `artifact.read` / `secret.read` / `kernel.execute`; the broker authorizes against grants (K-008) and performs them HOST-SIDE without Python. Path scope + workspace traversal guards; artifact digest validation; per-invocation audit records | ✅ Done | `kerno/capability_exec.py`; `tests/unit/test_capability_exec.py` (15 tests) |
| **fork_session** — branch a session at a cell boundary (#59/#60): re-execute the recorded prefix on a fresh kernel, then continue with a DIFFERENT LLM; different boundaries diverge (computational Git); boundary validation | ✅ Done | `kerno/session.py`; `tests/behavioral/test_fork_session.py` (real kernels) |


## Cancellation, execution-ledger correlation, task scheduler (audit #78/#81/#82/#83)

| Item | Status | Evidence |
|---|---|---|
| **CancellationToken** — thread-safe, idempotent cancel flag; wait/wait_until; no falsy-object trap (audit #83) | ✅ Done | `kerno/cancel.py`; `tests/unit/test_cancel.py` |
| **Cancellation propagation** — output collector watches the token MID-CELL and interrupts the kernel (KernelInterrupted); engine refuses new work when cancelled (EXECUTION_CANCELLED event); BaseLoop/MultiAgentLoop stop between cells with INTERRUPTED status; run()/run_with_pool(cancel_token=); capability-detected pass-through so third-party executors keep working; PlanExecuteLoop.run forwards the token | ✅ Done | `kerno/cancel.py`; `kerno/kernel/output.py`; `kerno/kernel/runtime.py`; `kerno/execution/engine.py`; `kerno/loop/base.py`; `kerno/loop/multi_agent.py`; `kerno/loop/plan_execute.py`; `kerno/_run.py`; `tests/behavioral/test_cancellation.py` (real kernel: hung cell interrupted in ~1s, kernel survives) |
| **Execution-ledger correlation** — SessionResult.execution_ids + blocked_rules set by run()/run_with_pool() (audit #78); BudgetedExecutor records passthrough; session serialization round-trips the new fields | ✅ Done | `kerno/types.py`; `kerno/_run.py`; `kerno/execution/budget.py`; `kerno/session.py`; `tests/behavioral/test_cancellation.py::test_execution_ids_and_blocked_rules_attached`; `tests/unit/test_session_io.py` |
| **TaskScheduler** — priority-ordered queue (higher first), bounded concurrency, per-task status/results/duration, cancel pending, failures recorded + kernels released (audit #81/#82) | ✅ Done | `kerno/scheduler.py`; `tests/unit/test_scheduler.py` (fake pool) + `tests/behavioral/test_scheduler_real.py` (real KernelPool) |


## Config layer, notebook→resume bridge, CLI flags

| Item | Status | Evidence |
|---|---|---|
| **KernoConfig.runtime** — RuntimeConfig (mode, isolation, auto_restart, budget_executions/wall_time/output, model_name, timeout_policy) with KERNO_RUNTIME_* env vars, JSON round-trip, production defaults (auto_restart, isolated, escalate, budget 200); to_dict includes runtime | ✅ Done | `kerno/config.py`; `tests/unit/test_config_runtime.py` |
| **run_with_config forwards the runtime** — budget/mode/isolation/auto_restart/model_name wired through; dry-run via config never starts a kernel (spy-proven) | ✅ Done | `kerno/runner.py`; `tests/unit/test_config_runtime.py::TestRunWithConfigForwarding` |
| **resume_from_notebook** — notebook → SessionResult → resume_session through the choke point: recorded cells re-executed on a fresh kernel with policy re-applied (blocked cells stay blocked); end-to-end save→notebook→resume verified on a real kernel (audit #56/#96) | ✅ Done | `kerno/session.py`; `tests/behavioral/test_resume_from_notebook.py` (4 tests) |
| **continue_from_notebook delegates** to the secure resume path (backward-compatible signature; state restoration through the engine always on) | ✅ Done | `kerno/notebook/continuation.py` |
| **CLI flags** — `kerno run --dry-run --budget N --isolation shared|isolated --auto-restart` wired into the config | ✅ Done | `kerno/cli/main.py` |


## Output redaction & execution-model bridge (audit #67/#68/#76)

| Item | Status | Evidence |
|---|---|---|
| **Engine output redaction** — audit #68 completeness: agent-origin cell outputs (stdout/stderr/result/display text) are scrubbed BEFORE they reach the LLM prompt, notebook, or persistence; runtime-origin outputs untouched; redact_outputs flag; records/events stay clean | ✅ Done | `kerno/execution/engine.py`; `tests/unit/test_output_redaction.py` (7 tests) + real-kernel e2e (`tests/behavioral/test_output_redaction_e2e.py`) |
| **Notebook projection redaction** — audit #67: code SOURCE, reasoning, and error text all pass through the redactor — a secret literal embedded in generated code never lands in the .ipynb; wired through run()/run_with_pool() | ✅ Done | `kerno/audit/notebook.py`; `kerno/_run.py`; `tests/unit/test_reproducibility.py::TestNotebookRedaction` (4 tests) + e2e notebook assertion |
| **SessionResult ↔ AgentState bridge** — result_to_state()/state_to_result() unify the two execution models (audit #76): history/namespace/summary/status/ledger map both ways; pipeline outcomes can be resumed/replayed as sessions and vice versa | ✅ Done | `kerno/bridge.py`; `tests/unit/test_bridge.py` (8 tests) |


## Live checkpoints, distributed execution, runtime tour (audit #59/#104/K-007)

| Item | Status | Evidence |
|---|---|---|
| **CapturePoint** — host-side checkpoint recorder bound to the engine's event sequence + kernel generation (K-007); the SAFE alternative to kernel-side checkpoint code (audit #15); cadence control, artifact hashes, lineage via parent_checkpoint_id | ✅ Done | `kerno/core/capture.py`; `tests/unit/test_capture_point.py` (5 tests) |
| **Live session checkpoints** — BaseLoop.run(capture=...) records a checkpoint after every successful cell; real-kernel test proves event-sequence binding, generation binding, lineage chain, and disk persistence; fork-from-live-checkpoint (audit #59) | ✅ Done | `kerno/loop/base.py`; `tests/behavioral/test_checkpoint_live.py` (2 tests) |
| **Distributed execution** — WorkerPool + DistributedExecutor (audit #104): controller routes executions to workers round-robin; each worker owns an executor; Executor protocol preserved (loops/budgets/engine can use it as backend); errors surface as DistributedError; cancel_event interrupts the wait; execution_id correlation | ✅ Done | `kerno/distributed.py`; `tests/unit/test_distributed.py` (5 tests) |
| **Runtime tour example** — examples/17_runtime_tour.py exercises live+checkpoints, cancellation, replay, fork, and distributed execution without an API key (verified end-to-end) | ✅ Done | `examples/17_runtime_tour.py` |


## Server-side execution security (K-001 through the HTTP surface)

| Item | Status | Evidence |
|---|---|---|
| **make_server_engine** — shared helper wrapping a raw kernel in the full choke point (allowlist profile + capability broker + budget) for server-driven sessions | ✅ Done | `kerno/server/security.py`; `tests/unit/test_server_security.py::TestMakeServerEngine` (6 tests) |
| **/run endpoint** — app._execute_task now passes a policy-wrapped engine to the pipeline factory; the raw kernel is never exposed to LLM-generated code; per-request security field (default "permissive", "none" opts out) | ✅ Done | `kerno/server/app.py`; unit + real-kernel tests (`tests/behavioral/test_server_security_live.py`) |
| **OpenAI-compatible server** — sync + streaming paths wrap the kernel; ChatCompletionRequest.security extension; create_openai_app(default_security, broker, budget) | ✅ Done | `kerno/server/openai_compat.py` |
| **Secure app** — authenticated server defaults to data_analysis and wraps every session | ✅ Done | `kerno/server/secure_app.py` |
| **FileMaterializer** stays on the raw kernel (host-constructed upload code = trusted runtime setup, not LLM-generated) — documented boundary | ✅ Done | `kerno/server/files.py` (unchanged by design) |
| **Skills bootstrap flake root cause** — registry.load_code timeout 30s→120s + one retry on TimeoutError (skill imports of pandas/numpy/matplotlib exceeded 30s under load) | ✅ Done | `kerno/skills/registry.py` |


## Allowlist hardening, per-request budgets, CLI resume/fork

| Item | Status | Evidence |
|---|---|---|
| **IPython magic / shell-escape blocking** — `%magic` lines and `!shell` lines bypass Python-syntax regexes; now blocked explicitly in all three profiles (audit hardening) | ✅ Done | `kerno/security/allowlist.py`; `tests/unit/test_execution_engine.py::TestMagicAndShellBlocking` (5 tests) |
| **Per-request server budgets** — RunRequest.budget_cells applies an ExecutionBudget to the session even with no server-wide budget (audit #85) | ✅ Done | `kerno/server/app.py`; `tests/unit/test_server_security.py::TestPerRequestBudget` |
| **CLI resume/fork commands** — `kerno resume <notebook> [--task --loop --max-cells --security]` and `kerno fork <notebook> --at-cell N [...]` with allowlist profile support | ✅ Done | `kerno/cli/main.py`; `tests/unit/test_cli_commands.py` (3 tests) |


## Operational hardening (audit #80 + reliability)

| Item | Status | Evidence |
|---|---|---|
| **Execution → metrics projection** — the engine projects every execution record into metrics (attempts, blocked, capability_denied, approval_denied with rule tags); one event source → multiple projections (audit #80) | ✅ Done | `kerno/execution/engine.py`; `kerno/telemetry/metrics.py::record_execution`; `tests/unit/test_ops_hardening.py::TestExecutionMetricsProjection` |
| **Config validation** — KernoConfig.validate()/validate_or_raise(): mode, isolation, timeout_policy, security profile, budget limits, max_cells | ✅ Done | `kerno/config.py`; `tests/unit/test_ops_hardening.py::TestConfigValidation` (7 tests) |
| **CLI session export** — `kerno session export <id> [--out]` exports a session as JSON (replay/resume/audit) from its notebook projection | ✅ Done | `kerno/cli/main.py`; `tests/unit/test_ops_hardening.py::TestCliSessionExport` |
| **Per-test timeout 120s → 300s** — real-kernel tests under heavy shared-sandbox load occasionally exceeded 120s (recurring flake); the gate is now honest — full suite ran clean (1028 passed) | ✅ Done | `pyproject.toml` |


## Final hardening (sticky kernel death, docs, CLI resume e2e)

| Item | Status | Evidence |
|---|---|---|
| **Sticky DEAD kernel state** — once the kernel process is observed dead, `state` stays DEAD (never bounces to READY on a lagging process poll) until an explicit restart() clears it; dead kernels refuse execution (audit #53) | ✅ Done | `kerno/kernel/runtime.py`; `tests/behavioral/test_kernel_state.py::TestStickyDeadState` (SIGKILL → sticky DEAD → restart → generation 2 → alive) |
| **CLI resume path e2e** — a live session saved as a notebook resumes through the exact `kerno resume` code path (resume_from_notebook + allowlist): restored state visible, policy re-applied on replay | ✅ Done | `tests/behavioral/test_cli_resume_e2e.py` (2 real-kernel tests) |
| **README examples index** + CLI docs for dry-run/budget/auto-restart/resume/fork/session export | ✅ Done | `README.md` |
| **Last flake root-caused** — the recurring bus-test timeout was a NEVER-YIELDING mock LLM (6 turns × 20 cells = 120 real kernel executions); the mock now yields after one cell → test runs in 5s | ✅ Done | `tests/behavioral/test_multi_agent_bus.py` |
| **Cancellation for ALL loop strategies** — hierarchical (between subtasks, per cell, synthesis skipped) and debate (between rounds, judge skipped) now support CancellationToken like the BaseLoop family and multi_agent; run() forwards it everywhere. Fixed latent bugs: both loops hardcoded COMPLETE, ignoring cancellation | ✅ Done | `kerno/loop/hierarchical.py`; `kerno/loop/debate.py`; `kerno/_run.py`; `tests/behavioral/test_cancellation.py::TestCancellationAllLoops` (3 real-kernel tests) |
| **Repo hygiene** — LICENSE (MIT, matches pyproject); CHANGELOG.md (0.2.0 release notes covering all audit phases + fixed bugs); version 0.1.0 → 0.2.0 (audit finding: 'License: None currently declared') | ✅ Done | `LICENSE`; `CHANGELOG.md`; `pyproject.toml` |


## K-001 completeness audit + SECURITY.md

| Item | Status | Evidence |
|---|---|---|
| **Every raw execute call site audited** — categorized: trusted host-setup (skills/hooks/comms/materializers/RAG) vs agent paths (all through the engine). Residuals documented: kernel-side checkpoint code (audit #15), dev reload/REPL tools | ✅ Done | audit grep of `kerno/` |
| **load_notebook policy path** — `load_notebook(..., engine=...)` re-executes recorded notebook cells THROUGH the choke point (policy applies); raw re-execution without an engine is an explicit opt-in documented in SECURITY.md | ✅ Done | `kerno/notebook/continuation.py`; `tests/behavioral/test_load_notebook_policy.py` (3 real-kernel tests) |
| **SECURITY.md** — threat model, defense-in-depth layers (choke point, import hook, OS isolation), trust-boundary table, secrets handling, invariants, reporting | ✅ Done | `SECURITY.md` |
| **Top-level capability constants** — CAP_KERNEL_EXECUTE & friends now re-exported from `kerno` (example 15 imported them from the top level) | ✅ Done | `kerno/__init__.py`; examples 15/16/17 verified running |
| **Release-readiness verified** — wheel builds (kerno-0.2.0-py3-none-any.whl, all 176 modules + LICENSE + entry point), installs into a FRESH venv, `kerno doctor` starts a kernel and passes P1–P10, example 16 runs end-to-end from the wheel | ✅ Done | `pip wheel` + fresh-venv smoke test |
| **`kerno run --dry-run` without an API key** — falls back to ScriptedBrain when no key is configured (anthropic/openai clients construct lazily, so key detection must be explicit); dry-run validation now works zero-config | ✅ Done | `kerno/cli/main.py`; `tests/unit/test_cli_commands.py::TestCliDryRunFallback` (2 tests) |
| **Dependency modularization (audit #16)** — `pip install kerno` is now a lean core (jupyter-client/nbformat/ipykernel/pyyaml); the analytical stack moved to `kerno[data]`, HTTP surfaces to `kerno[server]`; `bootstrap(skip_missing_deps=True)` probes each skill module's kernel-side deps in one batched cell and skips missing ones with a warning (never crashes the session); `kerno doctor` marks optional packs with ○; verified: core-only install runs full live sessions, `[data]` loads 114 skills | ✅ Done | `pyproject.toml`; `kerno/skills/bootstrap.py`; `kerno/cli/main.py`; fresh-venv verification (core-only + [data]); `tests/unit/test_skill_bootstrap_inventory.py::TestOptionalPackSkipping` (4 tests) |
| **Deep verification pass (2026-08-16)** — 45 modules / 121 symbols import-checked; all 108 tracker claims cross-checked against code; property tests enabled (hypothesis was missing from dev extras — 7 tests silently skipped all session); integration tests verified live against a standing server (health bug found & fixed: `pool.stats()` called as method on a property); hardened a load-sensitive bus test | ✅ Done | full suite **1047 passed, 5 skipped, 0 failed** |
| **`make ci` verified end-to-end** — the documented K-010 gate substitute now runs the full pipeline: compileall, import gate, unit (925), security invariants, behavioral/integration/property (111 passed, 5 skipped); uses the project venv explicitly; fixed a pre-existing Makefile parse bug (bench target's untabbed continuation lines) | ✅ Done | `Makefile` (ci/build/smoke targets, `PY`/`PYTEST` vars); one transient ZMQ teardown failure under 9-min load passes in isolation |
| **Dead-import cleanup** — `_run.py` dropped 12 unused imports (CommMessage, KernoConfig, BasePlugin, MemoryEntry, SimpleMemoryStore, continue_from_notebook, InputSanitizer, SkillRegistry, telemetry getters, ErrorClass, Cell) | ✅ Done | `kerno/_run.py`; wheel rebuilt + re-smoked |

## Verification protocol

- Every ✅ above is backed by tests that fail on the pre-fix code.
- Full suite gate before any merge: `pytest tests/unit tests/behavioral tests/integration tests/property`
  — currently **1047 passed, 5 skipped** (incl. 1 known load-flake) (incl. 1 known load-flake) (baseline before this work: 524 passed, 1 skipped).
  Under heavy shared-sandbox load, individual real-kernel tests can exceed the
  120s per-test timeout (observed on 3 different tests across runs; each passes
  in seconds in isolation). The CI workflow splits unit/security/integration into
  separate jobs to avoid this contention.
