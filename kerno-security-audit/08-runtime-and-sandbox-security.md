# 08 · Runtime and Sandbox Security

## The execution boundary, layer by layer

### L1 — `ExecutionEngine` (the choke point, K-001)

```
execute(code, origin="agent", capabilities=…, subject=…, action=…, …)
  │
  ├─ 1. Authorization   CapabilityBroker.require(each capability, subject)
  ├─ 1b. Human approval CAP_HUMAN_APPROVAL → ApprovalGate (FAIL CLOSED)
  ├─ 1c. Cancellation   CancellationToken checked before any work
  ├─ 2. Policy          AllowList.check(code) — static analysis
  ├─ 3. Effects         EffectLedger.declare(effects) before execution
  ├─ 4. Execution       delegate to the kernel executor (cancel-aware)
  ├─ 5. Redaction       agent-origin outputs scrubbed
  ├─ 6. Audit           immutable ExecutionRecord + causal events
  └─ 7. Effects         EffectLedger.observe() → undeclared writes flagged
```

Violations return a synthetic error cell (`AllowListViolation`,
`CapabilityViolation`, `ApprovalDenied`, `BudgetExceeded`) — the loop sees a
normal failed cell and can recover. **The kernel is never touched on a
denial.**

### L2 — Allowlist (policy, not a sandbox)

Profiles: `permissive` · `data_analysis` · `read_only` (and `none` = opt-out).

Blocks, among others:
- imports outside the allowed module list;
- dangerous builtins: `eval`, `exec`, `compile`, `__import__`, `open`
  (read_only);
- filesystem/network primitives: `subprocess`, `socket`, `requests`,
  `urllib`, `shutil`, `os.remove`, `os.environ`, `importlib`;
- write methods on allowlisted objects: `Path.write_text/write_bytes`,
  `df.to_csv/to_parquet/to_excel`, `plt.savefig`;
- URL-backed loads: `read_csv/read_json/read_excel("https://…")`;
- **IPython magics and shell escapes**: `%system`, `%sx`, `!curl`, `!ls` —
  these bypass Python-syntax regexes entirely and are now blocked explicitly.

### L3 — Runtime import hook (defense-in-depth)

`builtins.__import__` is replaced in the kernel with a restricted version:
allowlisted modules, stdlib (`sys.stdlib_module_names`), and already-loaded
modules pass; everything else raises `ImportError`. It is **non-reentrant**
(the old version recursed infinitely — C-2) and verified in-kernel.

### L4 — Kernel isolation (operator-deployable)

| Executor | Boundary | Use |
|---|---|---|
| `KernelRuntime` | none (trusted) | default |
| `DockerExecutor` | cpus / memory / pids-limit / `--network none` / `--read-only` rootfs / hard exec timeout | untrusted workloads |
| `SubprocessExecutor` | fresh `python -c` per execution; prlimit (memory/CPU/processes) | state isolation, resource control — NOT a security boundary |
| K-009 isolated multi-agent | each agent in its own kernel; explicit `SharedMemory` + `AgentBus` | multi-agent isolation |

## Kernel health and lifecycle

- `KernelRuntimeState` — STARTING/READY/BUSY/INTERRUPTING/RESTARTING/
  DEAD/CLOSED, with **sticky DEAD** (never bounces to READY after a crash)
  until explicit restart.
- K-004 — kernel death ≠ session death: `auto_restart` restarts and
  restores state by re-executing only cells that **succeeded** (blocked
  cells are never re-run during recovery).
- Timeout escalation — soft interrupt → grace → SIGKILL → restart.
- Kernel pool: health checks, in-place restart (generation increments),
  interrupt per task.

## What this layer explicitly does NOT do

- The allowlist is regex-based static analysis: `Blocking syntax ≠ blocking
  capability`. High-level libraries can still reach the network or
  filesystem through non-obvious paths; the effect ledger and container
  network policy are the compensating controls.
- The import hook can be bypassed by anything already in `sys.modules`.
- Same-process execution shares the host trust domain.

Next: `09-cryptography-and-secrets.md`.
