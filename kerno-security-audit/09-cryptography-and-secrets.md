# 09 · Cryptography and Secrets

## Secrets model — `SecretBroker`

- Secrets are **registered** by id and **granted per subject** with optional
  expiry; anonymous grants (subject `""`) serve any subject.
- `request(secret_id, subject)` returns the value only with a valid grant;
  `SecretNotFound` / `SecretDenied` otherwise.
- Revocation: per-subject `revoke`, and `revoke_all` (cascades).
- **The kernel never receives an environment dump** — `os.environ` is
  blocked in restrictive profiles, and reproducibility manifests record
  environment variable **names only, never values**.

## Redaction — the audit #67/#68 chain

```
Execution → Observation → Redaction → Event Store
```

A single `redactor` callable (typically `SecretBroker.redact`, longest-first
substitution) is applied at every egress point:

| Egress | Redacted? |
|---|---|
| Execution records (`code_preview`) | ✅ |
| Event payloads | ✅ |
| Policy error values (matched code fragments) | ✅ |
| Agent-origin cell outputs (stdout/stderr/result/displays) | ✅ |
| Notebook projection (code source, reasoning, error text) | ✅ |
| Session persistence (JSON) | ✅ |
| Reproducibility manifests (env var NAMES only) | ✅ |

Verified e2e on real kernels: a cell that prints `token=sk-live-…` produces
`[REDACTED]` in the session result, and the saved `.ipynb` contains neither
the printed value nor the code literal.

## Hashing and integrity

| Use | Mechanism |
|---|---|
| Artifact identity | content-addressed `sha256:<hex>`; **verified on read** (tampering → `ArtifactIntegrityError`), self-healed on re-store |
| Task / input / artifact hashes | full SHA-256 in `ReproducibilityManifest` |
| Notebook cell correlation | `code_hash` / `output_hash` (16-hex) in cell metadata |
| Checkpoint identity (K-007) | checkpoint binds `state_version + event_sequence + kernel_generation + artifact_hashes` |
| API keys at rest | server `APIKeyStore` hashes keys with SHA-256 (noted: for an API-key store, a KDF (bcrypt/argon2) would be stronger — see `16-next-steps`) |

## What is NOT provided (honest list)

- No TLS for the kernel transport (Jupyter default TCP; the kernel itself
  warns on startup). Mitigation: IPC transport or CurveZMQ in deployment.
- No key-management integration (HSM/KMS) — secrets live in the
  `SecretBroker` in memory.
- No at-rest encryption of session notebooks / memory JSON — protection is
  redaction, not encryption.
- API keys are SHA-256-hashed, not KDF-stretched.

## Cryptographic test coverage

- `test_secrets.py` — grants, expiry, revocation, redaction, engine
  integration (secrets never enter records/events/errors).
- `test_artifacts_effects_approval.py` — content addressing, dedupe,
  tamper detection, creator-execution provenance.
- `test_reproducibility.py` — manifest hashes, env-var names only,
  notebook metadata embedding.
- `test_output_redaction*.py` — output + notebook redaction e2e.

Next: `10-network-and-api-security.md`.
