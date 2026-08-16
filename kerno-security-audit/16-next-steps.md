# 16 · Next Steps

Ordered by leverage, not by effort.

## Security (the boundary)

1. **Push the CI workflow** — grant the GitHub App `workflows` permission;
   the file is ready. Until then `make ci` is the honest gate.
2. **Container isolation as a documented requirement for hostile use** —
   ship a `docker-compose.security.yml` that runs each kernel in
   `DockerExecutor` with `--network none`, read-only rootfs, and memory
   caps; document it as the K-003 deployment.
3. **KDF-stretch server API keys** (bcrypt/argon2) instead of raw SHA-256.
4. **TLS/CurveZMQ for the kernel transport** in the server deployments.
5. **pip-audit + SBOM** in CI once the workflow is pushable.

## Runtime hardening

6. **Capability broker for skills** — skills currently declare
   dependencies, not capabilities; bridge `SkillApprover` grants into the
   broker so a loaded skill's capabilities are explicit (audit #65/#66).
7. **`RetryExecutor` + `Action` wired into `run()`** — the idempotency
   policy exists; the facade still retries only at the LLM-wrapper level.
8. **Cancellation tokens through the HTTP surfaces** — server requests
   currently lack a cancel path.
9. **Distributed controller with remote workers** — the in-process
   `WorkerPool` is a stepping stone; a ZMQ/HTTP transport would make
   `DistributedExecutor` actually distributed.

## Verification

10. **Allowlist regex fuzzing** (hypothesis-based) to find bypasses
    systematically.
11. **Mutation testing** on the security layer (engine, broker, allowlist).
12. **Soak test** — kernel pool under memory pressure with `memory_mb`
    gauges asserted.
13. **Reproducibility verification** — replay a recorded session in a
    locked environment and assert identical deterministic outputs
    (the audit's "execution reproducibility" bar, #14/#57).

## Product

14. **"Agent kernel" positioning** — once the boundary is airtight, the
    distinctive claim is persistent, replayable, forkable agent execution
    with provenance — not "another agent framework".
15. **Publish the audit** — this directory + `docs/kerno-deep-audit.md` as
    the project's security documentation.

Next: `17-final-assessment.md`.
