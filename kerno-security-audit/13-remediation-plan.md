# 13 · Remediation Plan

Priority-ordered. **Done** items are verified (test that fails on pre-fix
code); **Open** items are the honest remainder.

## Phase A — Execution boundary (COMPLETE)

| Item | Status |
|---|---|
| Universal choke point (K-001) across all loops, pool, distributed, HTTP | ✅ Done |
| Policy bypass closed (hierarchical/multi_agent/debate/pool) | ✅ Done |
| Allowlist import hook non-reentrant | ✅ Done |
| Server surfaces wrapped (`make_server_engine`) | ✅ Done |
| Capability broker with attenuation, subjects, expiry | ✅ Done |
| Human approval, fail-closed | ✅ Done |
| Secrets + redaction at every egress | ✅ Done |
| Effect ledger (undeclared writes flagged) | ✅ Done |
| IPython magic / shell-escape blocking | ✅ Done |

## Phase B — State and lifecycle (COMPLETE)

| Item | Status |
|---|---|
| Event stream with causal parents; execution_id correlation | ✅ Done |
| AgentState versioning/fork/snapshot; StateLedger | ✅ Done |
| Provenance graph (K-006); content-addressed artifacts (verified on read) | ✅ Done |
| Checkpoints bound to state+events (K-007); host-side CapturePoint | ✅ Done |
| K-004 recovery (auto_restart, resume, fork); sticky DEAD state | ✅ Done |
| Cancellation across all six loop strategies | ✅ Done |
| Budgets: per-session, per-agent, hierarchical allocator; per-request server budgets | ✅ Done |
| Timeout escalation; kernel pool health/restart/interrupt | ✅ Done |

## Phase C — Reproducibility and operations (COMPLETE)

| Item | Status |
|---|---|
| Manifests (env names only, hashes, model, seeds); env locks | ✅ Done |
| Notebook projection with execution metadata; notebook-as-artifact | ✅ Done |
| Replay without LLM; execution modes; session persistence | ✅ Done |
| `make ci` gate; doctor invariant checks; config validation; wheel smoke | ✅ Done |
| Dependency split: lean core + optional packs; graceful skill degradation | ✅ Done |

## Phase D — Remaining (OPEN)

| Item | Priority | Why open | Path |
|---|---|---|---|
| Push `.github/workflows/ci.yml` | P1 | GitHub App token denied `workflows` permission (403 via git and gh api) | Grant `workflows` permission; file is ready |
| OS-level isolation for hostile workloads | P1 | Operator deployment decision | Deploy `DockerExecutor`/container per kernel; document as mandatory for untrusted use |
| KDF for API keys (`APIKeyStore`) | P2 | SHA-256 acceptable for random keys, KDF is stronger | swap to bcrypt/argon2 |
| TLS/CurveZMQ for kernel transport | P2 | deployment concern | configure IPC or CurveZMQ |
| Vulnerability scanning + SBOM in CI | P2 | needs CI workflow first | add `pip-audit` step to workflow |
| Fuzz the allowlist regexes | P3 | nice-to-have | hypothesis-based regex fuzzing |
| Mutation testing | P3 | nice-to-have | cosmonic/cosmic-ray |
| Soak/load tests for pool under memory pressure | P3 | nice-to-have | benchmark suite exists |

## Sequencing rule (from the original audit)

Do NOT add features before the boundary is real. The boundary is now real
and tested. The next *security* step is Phase D row 2 (isolation) — after
that, feature work is safe to resume.

Next: `14-security-invariants.md`.
