# Branch Protection & Release Governance (Gate G)

This document is the executable specification for the GitHub-side
release gate. The settings below cannot be enforced from code alone —
they live in the GitHub UI / GitHub API — so this file is the
authoritative checklist the maintainer signs off before a release is
certified.

**Repository:** [Abdus2023/Kerno](https://github.com/Abdus2023/Kerno)
**Protected branch:** `main`
**Date:** 2026-08-17

---

## 1. Required status checks

The following checks MUST be green and required before a PR can merge
into `main`:

| Check | Workflow | Step |
|---|---|---|
| `test` | `.github/workflows/ci.yml` | full job (static gates + unit + security + behavioral/integration/property) |
| `Verify lockfile is up to date` | `.github/workflows/ci.yml` | Gate B drift check |

Configuration:

- [ ] Require status checks to pass before merging.
- [ ] Require branches to be up to date before merging.
- [ ] Add the exact check names above (see the Actions tab for the
      canonical names after the first run on `arena/01a00e9b-kerno`).

## 2. Review and approvals

- [ ] Require pull request reviews before merging: **1 approval**
      minimum.
- [ ] Dismiss stale review approvals when new commits are pushed.
- [ ] Require review from code owners for changes under:
  - `kerno/security/**`
  - `kerno/server/**`
  - `kerno/execution/**`
  - `scripts/check_raw_kernel.py`
  - `.github/workflows/**`
  - `requirements.lock.txt`

A `CODEOWNERS` file should be added (see §6 below).

## 3. Direct push restrictions

- [ ] Do not allow anyone to push directly to `main` — including
      administrators (the "Do not allow bypassing the above settings"
      checkbox).
- [ ] Do not allow force pushes.
- [ ] Do not allow deletions.

## 4. Signed commits

- [ ] Require signed commits on `main` (recommended; not yet enforced
      because the existing merge commit `fc205225` is a GitHub-generated
      merge commit).

## 5. Release-tag protection

- [ ] Protect tag pattern `v*` so release tags can only be created by
      the maintainer and only from a green commit on `main`.

## 6. CODEOWNERS

Add `.github/CODEOWNERS`:

```text
# Security-sensitive paths require explicit review.
/kerno/security/      @Abdus2023
/kerno/server/        @Abdus2023
/kerno/execution/     @Abdus2023
/scripts/check_raw_kernel.py  @Abdus2023
/.github/workflows/   @Abdus2023
/requirements.lock.txt  @Abdus2023
```

## 7. Verification

Once the settings are applied, verify with `gh`:

```bash
gh api repos/Abdus2023/Kerno/branches/main/protection \
  --jq '{required_status_checks: .required_status_checks.contexts,
         required_pull_request_reviews: .required_pull_request_reviews,
         enforce_admins: .enforce_admins.enabled,
         allow_force_pushes: .allow_force_pushes.enabled}'
```

Expected output:

- `required_status_checks.contexts` contains `test` and
  `Verify lockfile is up to date`.
- `required_pull_request_reviews.required_approving_review_count >= 1`.
- `enforce_admins.enabled == true`.
- `allow_force_pushes.enabled == false`.

Record the verified output (with date and SHA) in
`docs/security/REMEDIATION_TRACKER.md` under the Pass 5 entry to close
Gate F.

## 8. Release certification

Only after every Gate A–G is verified:

1. Gate A — green Actions run on the exact branch-tip SHA.
2. Gate B — `requirements.lock.txt` present, `--require-hashes` install
   verified, drift check green.
3. Gate C — `tests/unit/test_management_plane.py` green in CI.
4. Gate D — `tests/unit/test_transport_parity.py` green in CI.
5. Gate E — `scripts/check_raw_kernel.py` and
   `tests/unit/test_static_gate.py` green in CI.
6. Gate F — branch protection settings applied and verified with `gh`.
7. The state in `REMEDIATION_TRACKER.md` is `CERTIFIED`.

Tag the release:

```bash
git tag -s v0.2.1 -m "Kerno v0.2.1 — Phase-6 certified"
git push origin v0.2.1
```
