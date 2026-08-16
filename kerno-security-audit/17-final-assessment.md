# 17 · Final Assessment

## Maturity model position

| Stage | Definition | Kerno |
|---|---|---|
| K0 | Agent wrapper: `LLM → Python → Jupyter` | surpassed |
| K1 | Agent runtime: loop + persistent kernel + memory/artifacts | surpassed |
| **K2** | **Secure agent runtime: policy + capability broker + isolated kernel** | **≈ here** — policy + broker are real and tested; isolation is available but operator-deployed |
| K3 | Agent kernel: persistent state + event log + replay + fork + capabilities + isolation + provenance | partially — everything except deployment-grade isolation and distributed execution is implemented |

## Strengths (verified)

1. **Universal execution choke point** — the one invariant that matters is
   true across every surface, proven by per-loop real-kernel tests.
2. **Defense in depth that is honest** — allowlist, broker, approval,
   redaction, effect ledger, isolation are distinct layers with documented
   boundaries; `SECURITY.md` states what is not guaranteed.
3. **Verification culture** — 1047 tests; invariant checks detect
   violations; fault injection; fresh-venv release verification; flake
   archaeology. The audit's own tooling gaps (skipped suites, health bug)
   were found and fixed rather than ignored.
4. **Reproducibility as a security property** — manifests, content
   addressing, provenance, replay-without-LLM make the runtime auditable.
5. **The dependency split** — a lean core with graceful degradation is the
   correct supply-chain posture for an agent runtime.

## Weaknesses (honest)

1. **Not a sandbox.** The allowlist is regex-based static analysis; the
   import hook is bypassable via `sys.modules`; same-process execution
   shares the host trust domain. For hostile workloads, isolation is
   mandatory and currently operator-deployed.
2. **CI not on GitHub.** The workflow cannot be pushed by the automation
   token; `make ci` is the local substitute.
3. **Server auth fail-open by default** (no keys → allow) and wide-open
   CORS — fine for local tooling, must be locked in production.
4. **No at-rest encryption, no KDF for API keys, no TLS for the kernel
   transport by default.**
5. **Skill trust is newer** — trust levels and approval exist, but the
   bridge into runtime capability grants (next-step #6) is not yet wired.

## Overall

Kerno is a genuine, increasingly mature kernel-native agent runtime whose
security architecture is **substantially implemented and verified** — and
whose remaining gaps are explicit, documented, and remediable rather than
hidden. It is appropriate for trusted/internal agent workloads today; it
becomes appropriate for untrusted workloads when the OS-isolation layer is
deployed and CI is running on GitHub.

Next: `18-key-conclusion.md`.
