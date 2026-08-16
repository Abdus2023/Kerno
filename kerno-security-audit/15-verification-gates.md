# 15 · Verification Gates

The gates that must pass before any release — and their current status.

## Gate matrix

| Gate | Command | Covers | Status |
|---|---|---|---|
| Compile + import | `python -m compileall -q kerno tests` + `import kerno` | syntax, eager imports | ✅ passing |
| Unit | `pytest tests/unit -q` | 928 tests, no kernel | ✅ passing |
| Security invariants | `pytest …/test_security.py …/test_execution_engine.py …/test_capability_broker.py …/test_secrets.py …/test_isolation.py …/test_invariants.py` | the security layer | ✅ passing |
| Kernel behavioral | `pytest tests/behavioral tests/integration tests/property -q` | real kernels, live server, hypothesis | ✅ passing (integration needs a standing server) |
| Full gate | `make ci` | everything above, in order | ✅ verified end-to-end |
| Doctor | `kerno doctor` | environment + P1–P10 invariant checks | ✅ passing (fresh venv, core-only) |
| Release artifact | `make build && make smoke` | wheel build + fresh-venv install + doctor + dry-run + live/replay session | ✅ passing |
| **GitHub Actions CI** | `.github/workflows/ci.yml` | same jobs on push/PR | ⛔ **cannot be pushed** — the GitHub App token is denied `workflows` permission (403 via both `git push` and `gh api`) |

## The CI gap, precisely

- The workflow file exists and is valid (`.github/workflows/ci.yml`, four
  jobs: static+import gate, unit, security invariants, kernel tests).
- It is **not** tracked in git (kept local) because the automation token
  cannot create/update workflow files.
- `make ci` reproduces the exact same jobs locally and is verified.
- **Action needed:** grant the GitHub App `workflows` permission (or push
  the file manually), then `git add .github/workflows/ci.yml && git push`.

## K-010 discipline in this audit

The audit itself applied the invariant: property tests and integration
tests were found **skipped**, and the audit treated them as *not evidence*
until they actually ran — then fixed the causes (hypothesis in dev extras,
live-server verification, the `/health` bug those tests would have caught).

## Release checklist

1. `make ci` — all four stages green (✅ current).
2. `make build && make smoke` — wheel in a fresh venv (✅ current).
3. `kerno doctor` in the target environment (✅ current).
4. CI workflow pushed and green (⛔ blocked on permissions).
5. CHANGELOG updated (✅ current).

Next: `16-next-steps.md`.
