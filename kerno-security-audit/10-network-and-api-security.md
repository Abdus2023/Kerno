# 10 · Network and API Security

## The surfaces

| Surface | File | Choke point |
|---|---|---|
| `POST /run`, streaming, WebSocket | `kerno/server/app.py` | ✅ `make_server_engine` |
| OpenAI-compatible `/v1/chat/completions` (sync + SSE streaming) | `kerno/server/openai_compat.py` | ✅ |
| Authenticated server (API keys, rate limits, per-user kernels) | `kerno/server/secure_app.py` | ✅ (defaults to `data_analysis`) |

## How a request executes (after the fix, C-3)

```
HTTP request
   → RunRequest.security (default "permissive"; "none" opts out)
   → make_server_engine(kernel, profile, broker, budget)
        = ExecutionEngine + optional BudgetedExecutor
   → pipeline factory receives the ENGINE, never the raw kernel
```

Per-request `budget_cells` applies an `ExecutionBudget` even when no
server-wide budget is configured. `create_openai_app` and `create_secure_app`
accept `capability_broker` / `budget` / `default_security`.

## Authentication and rate limiting (`secure_app`)

- `APIKeyStore` — keys hashed (SHA-256), per-key user/rate-limit/max-cells;
  loaded from `KERNO_API_KEYS`.
- `verify_api_key` FastAPI dependency — 401 on missing/invalid key, 429 on
  rate-limit exceed with `Retry-After`.
- Per-user `max_cells` cap applied to sessions.
- **Fail-open note:** if no keys are configured, requests are allowed
  (development mode) — documented behavior, must be disabled in production.

## Network posture

- **Kernel:** Jupyter TCP transport (unencrypted by default — kernel
  startup warning; see `09`).
- **DockerExecutor:** `--network none` by default.
- **Allowlist profiles** block `requests`/`socket`/`urllib`/URL-backed loads
  in `data_analysis`/`read_only`.
- **OpenAI-compat server:** CORS wide-open by default (`*`) — suitable for
  local Open WebUI; restrict in production.

## Bugs found and fixed on these surfaces

| Bug | Fix |
|---|---|
| `/health` 500'd (`pool.stats()` called as method) | property access; regression test; live verification |
| Raw kernel execution on all endpoints | `make_server_engine` everywhere |

## Test coverage

- Unit: `test_server_security.py` (10 tests) — engine wrapping, per-request
  budgets, deny paths.
- Behavioral (real kernels): `test_server_security_live.py`, plus the
  live-server run of `tests/integration/test_openai_compat.py` (4 tests:
  health, models, sync completion, streaming — all passing against a
  standing server).

Next: `11-data-and-storage-security.md`.
