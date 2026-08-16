# 11 · Data and Storage Security

## What Kerno persists

| Artifact | Where | Integrity / protection |
|---|---|---|
| Session notebooks (`.ipynb`) | `sessions/` | Redacted (code/reasoning/errors/outputs); per-cell execution metadata; reproducibility summary in metadata |
| Notebook content-addressed copy | `ArtifactStore` | `sha256:` digest, verified on read, tamper → error |
| Session JSON | `save_session` | Full payload incl. outputs; redacted via engine before capture |
| Memory store | `.kerno/memory.json` | Semantic entries only; env names never; no secrets by construction |
| Checkpoints | `_checkpoints/ckpt_*.json` | Bound to state version + event sequence + kernel generation (K-007) |
| Reproducibility manifests | `<session>.manifest.json` | Env **names only**, package versions, input/artifact hashes, model, seeds |
| Metrics / traces / logs | `.kerno/*.jsonl` | Execution counters, no code payloads |

## The notebook projection (audit #56/#96)

The `.ipynb` is a **projection** of the execution ledger, not the database:

- every code cell carries `kerno_execution` metadata (`execution_id`,
  `code_hash`, `output_hash`);
- the full manifest is written beside it;
- the notebook can be re-stored content-addressed (`save_as_artifact`).

## Prompt / error / persistence hygiene (upload source #10)

- Errors are classified (`ErrorClassifier`) and fed back to the LLM as
  recovery hints — but **redacted** before they reach the prompt when they
  contain secrets.
- The prompt builder feeds the LLM the kernel namespace snapshot — which is
  why namespace access is guarded and why the output redaction happens
  *before* the loop sees a cell result.
- Persisted memory entries are semantic summaries, not raw outputs.

## Filesystem effects ledger (audit #92/#93)

`EffectLedger` + `WorkspaceObserver`: actions declare side effects before
execution; after execution the workspace is diffed; **undeclared filesystem
writes emit `EFFECT_VIOLATION` events** — defense-in-depth that catches
writes even when the allowlist misses a method.

## Capability-executed filesystem access (audit #31/#48)

`CapabilityExecutor` performs `filesystem.read` **host-side, without Python**:
scope check against grants, workspace-root traversal guard (rejects `..`
escapes), 1 MB read cap, utf-8 only. Artifacts are written via the
content-addressed store with `creator_execution` provenance (K-006).

## Storage threat notes

- **At-rest encryption:** none — protection is redaction, not encryption
  (see `09`).
- **Checkpoint directory:** kernel-side `_auto_checkpoint` writes into
  `_checkpoints/` from inside the agent namespace (documented residual,
  audit #15); the host-side `CapturePoint` is the recommended mechanism.
- **File uploads (server):** `FileMaterializer` injects uploaded files into
  the kernel via host-constructed code — trusted host path by design, but
  uploaded content is untrusted data → the LLM must see it as data, and the
  allowlist/sanitizer applies to what the LLM then generates.

Next: `12-code-quality-and-testing.md`.
