# kerno/server/app.py
"""
FastAPI application for kerno-as-a-service.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Optional

try:
    from fastapi              import Depends, FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses    import StreamingResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic             import BaseModel, Field
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from kerno.streaming.protocol import EventKind, StreamEvent
from kerno.types              import SessionResult


# ── Request / Response models ──────────────────────────────────────────────────

if HAS_FASTAPI:
    class RunRequest(BaseModel):
        task:          str
        loop:          str  = "reactive"
        max_cells:     int  = 50
        memory:        bool = False
        security:      str  = "permissive"   # "none" opts out entirely
        save_notebook: bool = False
        budget_cells:  Optional[int] = None   # ExecutionBudget cap (audit #85)

    class RunResponse(BaseModel):
        session_id:     str
        status:         str
        cells_executed: int
        duration_s:     float
        summary:        str  = ""
        error:          Optional[str] = None


def create_app(
    llm,
    *,
    skills_path:       Optional[str] = None,
    memory_path:       str           = ".kerno/memory.json",
    pool_size:         int           = 3,
    cors_origins:      Optional[list[str]] = None,
    capability_broker: Optional[object] = None,
    budget:            Optional[object] = None,
    default_security:  str           = "data_analysis",
    require_auth:      Optional[bool] = None,
) -> "FastAPI":
    """
    Create and configure the FastAPI application with universal gateway governance (K-011).

    CORS (F-010): cors_origins defaults to the secure same-origin policy;
    pass an explicit allowlist (or set KERNO_CORS_ORIGINS) for
    cross-origin deployments — the wildcard "*" is never implicit.

    Management-plane authorization (F-011): when ``require_auth`` is True
    (or ``KERNO_ENABLE_AUTH`` is set, or ``KERNO_RUNTIME_MODE=production``),
    the operational endpoints (``/health``, ``/metrics``, ``/sessions``,
    ``/sessions/{id}``, cancellation) require a valid API key, and
    session-scoped operations enforce ownership. ``/health/live`` remains
    public (minimal disclosure) so load balancers can liveness-probe
    without credentials.
    """
    if not HAS_FASTAPI:
        raise ImportError(
            "FastAPI is required for the kerno server. "
            "Install with: pip install fastapi uvicorn"
        )

    from kerno.kernel.pool    import KernelPool
    from kerno.memory.simple  import SimpleMemoryStore
    from kerno.server.security import resolve_cors_origins, DEFAULT_CORS_METHODS, DEFAULT_CORS_HEADERS
    from kerno.server.management import (
        ANONYMOUS_PRINCIPAL,
        assert_session_owner,
        management_auth_required,
        make_principal_dependency,
    )
    from kerno.cancel         import CancellationToken

    # Allow the caller to force management-plane auth on or off; the
    # environment/process policy is the default. When explicitly
    # disabled, ownership still uses the anonymous principal.
    auth_required = (
        require_auth if require_auth is not None else management_auth_required()
    )

    # Per-app dependency closure so two apps in the same process (e.g.
    # in tests) can have different auth policies.
    _mgmt_principal = make_principal_dependency(auth_required)

    app = FastAPI(
        title       = "kerno",
        description = "A kernel-native agent runtime",
        version     = "0.2.1-dev",
    )

    # F-010: explicit-origin CORS policy. Wildcard origins never carry
    # credentials.
    origins = resolve_cors_origins(cors_origins)
    allow_creds = bool(origins) and "*" not in origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins     = origins,
        allow_credentials = allow_creds,
        allow_methods     = DEFAULT_CORS_METHODS,
        allow_headers     = DEFAULT_CORS_HEADERS,
    )

    # Shared resources
    pool   = KernelPool(size=pool_size, skills_path=skills_path)
    memory = SimpleMemoryStore(persist_path=memory_path)
    sessions: dict[str, SessionResult] = {}
    # F-011: per-session owner map so /sessions/{id} and cancellation
    # cannot cross principals. The data-plane endpoints also record
    # ownership here so management-plane lookups stay consistent.
    session_owners: dict[str, str] = {}
    active_tokens: dict[str, CancellationToken] = {}

    pool.start()

    def _principal_id(principal: Optional[dict]) -> str:
        if not principal:
            return ANONYMOUS_PRINCIPAL
        return principal.get("user_id", ANONYMOUS_PRINCIPAL) or ANONYMOUS_PRINCIPAL

    def _build_gateway_engine(kernel, profile: str = None, budget_cells: int = None,
                              transport: str = "generic"):
        # K-011/K-012: canonical gateway — a single authoritative builder
        # for every public transport (F-007 consolidation).
        from kerno.server.security import build_gateway_engine as _build_gateway

        return _build_gateway(
            kernel,
            profile           = profile,
            capability_broker = capability_broker,
            budget            = budget,
            server_default    = default_security,
            allow_downgrade   = False,
            budget_cells      = budget_cells,
            transport         = transport,
        )

    # ── Routes ────────────────────────────────────────────────────────────────

    @app.get("/health/live")
    async def health_live():
        """Public liveness probe (minimal disclosure, F-011)."""
        return {"status": "ok"}

    @app.get("/health")
    async def health(principal: dict = Depends(_mgmt_principal)):
        """Operational readiness probe — management-plane (F-011)."""
        return {
            "status":      "ok",
            "pool_stats":  pool.stats,
            "sessions":    len(sessions),
            "timestamp":   time.time(),
        }

    @app.get("/metrics")
    async def metrics(principal: dict = Depends(_mgmt_principal)):
        from kerno.telemetry import get_metrics
        return get_metrics().snapshot()

    @app.post("/sessions/{session_id}/cancel")
    async def cancel_session(
        session_id: str,
        principal: dict = Depends(_mgmt_principal),
    ):
        """Cancel an actively executing session (audit #83). Ownership-gated (F-011)."""
        owner = session_owners.get(session_id)
        if owner is None and session_id not in active_tokens:
            return JSONResponse(
                status_code = 404,
                content     = {"error": f"Active session {session_id} not found or already completed"}
            )
        assert_session_owner(owner, principal, session_id=session_id)
        token = active_tokens.get(session_id)
        if not token:
            return JSONResponse(
                status_code = 404,
                content     = {"error": f"Active session {session_id} not found or already completed"}
            )
        token.cancel()
        return {"status": "cancelling", "session_id": session_id}

    @app.post("/run", response_model=RunResponse)
    async def run_task(
        request: RunRequest,
        principal: dict = Depends(_mgmt_principal),
    ):
        """
        Execute a task synchronously through the ExecutionGateway (K-011).
        """
        session_id   = str(uuid.uuid4())
        task_id      = "http-{}".format(session_id[:8])
        cancel_token = CancellationToken()
        active_tokens[session_id] = cancel_token
        session_owners[session_id] = _principal_id(principal)

        kernel = pool.acquire(task_id)
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _execute_task(
                    kernel            = kernel,
                    llm               = llm,
                    request           = request,
                    session_id        = session_id,
                    memory            = memory if request.memory else None,
                    capability_broker = capability_broker,
                    budget            = budget,
                    cancel_token      = cancel_token,
                    default_security  = default_security,
                )
            )
            sessions[result.session_id] = result
            return RunResponse(
                session_id     = result.session_id,
                status         = result.status.name,
                cells_executed = result.cells_executed,
                duration_s     = round(result.duration, 2),
                summary        = result.summary[:500] if result.summary else "",
            )

        except Exception as e:
            return RunResponse(
                session_id     = session_id,
                status         = "ERROR",
                cells_executed = 0,
                duration_s     = 0,
                error          = str(e)[:500],
            )
        finally:
            active_tokens.pop(session_id, None)
            pool.release(task_id, reason="complete")

    @app.post("/stream")
    async def stream_task(
        request: RunRequest,
        principal: dict = Depends(_mgmt_principal),
    ):
        """
        Execute a task and stream events through the ExecutionGateway (K-011).
        """
        session_id   = str(uuid.uuid4())
        task_id      = "sse-{}".format(session_id[:8])
        cancel_token = CancellationToken()
        active_tokens[session_id] = cancel_token
        session_owners[session_id] = _principal_id(principal)

        async def event_generator():
            kernel = pool.acquire(task_id)
            try:
                from kerno.streaming.executor import StreamingExecutor
                from kerno.loop.factory       import make_reactive
                from kerno.skills.bootstrap   import bootstrap

                bootstrap(kernel)
                # K-011 / K-013: stream transport wraps kernel in server gateway engine
                engine   = _build_gateway_engine(kernel, request.security, request.budget_cells, transport="sse")
                pipeline = make_reactive(
                    kernel    = engine,
                    llm       = llm,
                    memory    = memory if request.memory else None,
                    max_cells = request.max_cells,
                )

                executor = StreamingExecutor(pipeline, session_id=session_id)

                async for event in executor.stream(request.task):
                    if cancel_token.is_set():
                        break
                    yield "data: {}\n\n".format(json.dumps(event.to_dict()))
                    if event.kind == EventKind.SESSION_COMPLETE:
                        break

            except Exception as e:
                error_event = StreamEvent(
                    kind       = EventKind.SESSION_ERROR,
                    session_id = session_id,
                    error      = str(e),
                )
                yield "data: {}\n\n".format(json.dumps(error_event.to_dict()))
            finally:
                active_tokens.pop(session_id, None)
                pool.release(task_id, reason="complete")

        return StreamingResponse(
            event_generator(),
            media_type = "text/event-stream",
            headers    = {
                "Cache-Control":     "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.websocket("/ws/{session_id}")
    async def websocket_stream(ws: WebSocket, session_id: str):
        """
        WebSocket endpoint with ExecutionGateway governance (K-011).

        Transport parity (F-007 / Gate D): the WebSocket now accepts an
        optional ``security`` field in its connect payload — exactly like
        ``/run`` and ``/stream`` — and routes it through the canonical
        gateway. A client cannot downgrade below the server default
        (``allow_downgrade=False``); a request for a stronger profile is
        honored. The previous behaviour hard-coded the server default,
        which was safer than allowing downgrade but inconsistent with
        the other transports.

        Authentication (F-011): browsers cannot set Authorization
        headers on WebSocket handshakes, so when management auth is
        required the client may pass ``?token=<api-key>`` as a query
        parameter. The token is validated against the same key store
        used by HTTP. If no valid token is supplied and auth is
        required, the connection is closed with code 1008 (policy
        violation) before any task is accepted.
        """
        # Gate C: authenticate before accepting the task so anonymous
        # callers cannot reach the session machinery.
        from kerno.server import auth as _auth_mod
        if auth_required:
            token = ws.query_params.get("token")
            if not token:
                await ws.close(code=1008, reason="authentication required")
                return
            info = _auth_mod._key_store.validate(token)
            if not info:
                await ws.close(code=1008, reason="invalid API key")
                return
            allowed, _remaining = _auth_mod._rate_limiter.check(
                info["user_id"], info.get("rate_limit", 100),
            )
            if not allowed:
                await ws.close(code=1008, reason="rate limit exceeded")
                return
            principal = info
        else:
            principal = {"user_id": ANONYMOUS_PRINCIPAL}

        await ws.accept()
        task_id      = "ws-{}".format(session_id[:8])
        cancel_token = CancellationToken()
        active_tokens[session_id] = cancel_token
        # F-011: record the authenticated principal (or anonymous) so
        # management-plane lookups/cancels remain ownership-consistent.
        session_owners[session_id] = _principal_id(principal)

        try:
            data      = await ws.receive_json()
            task      = data.get("task", "")
            raw_cells = data.get("max_cells", 50)
            max_cells = min(max(1, int(raw_cells)), 100) # Server-enforced cell cap
            # Gate D: client-requested profile (resolved through the
            # same canonical builder used by /run, /stream, OpenAI sync,
            # OpenAI streaming, and the secure app).
            requested_profile = data.get("security")
            raw_budget = data.get("budget_cells")
            budget_cells = int(raw_budget) if raw_budget is not None else None

            if not task:
                await ws.send_json({"error": "task is required"})
                return

            kernel = pool.acquire(task_id)

            try:
                from kerno.streaming.executor import StreamingExecutor
                from kerno.loop.factory       import make_reactive
                from kerno.skills.bootstrap   import bootstrap

                bootstrap(kernel)
                # K-011: WebSocket transport wraps kernel in server gateway engine
                engine   = _build_gateway_engine(
                    kernel, requested_profile, budget_cells, transport="ws",
                )
                pipeline = make_reactive(
                    kernel    = engine,
                    llm       = llm,
                    max_cells = max_cells,
                )

                executor = StreamingExecutor(pipeline, session_id=session_id)

                async for event in executor.stream(task):
                    if cancel_token.is_set():
                        break
                    try:
                        await ws.send_json(event.to_dict())
                    except WebSocketDisconnect:
                        break

                    if event.kind == EventKind.SESSION_COMPLETE:
                        break

            finally:
                active_tokens.pop(session_id, None)
                pool.release(task_id, reason="complete")

        except WebSocketDisconnect:
            pass
        except ValueError as e:
            # Unknown security profile — return a clear error instead of
            # a generic 500 surfaced via the except below.
            try:
                await ws.send_json({"error": str(e)})
            except Exception:
                pass
        except Exception as e:
            try:
                await ws.send_json({"error": str(e)})
            except Exception:
                pass

    @app.get("/sessions")
    async def list_sessions(
        limit: int = 20,
        principal: dict = Depends(_mgmt_principal),
    ):
        """List recent sessions owned by the caller (F-011)."""
        caller = _principal_id(principal)
        owned = [
            s for sid, s in sessions.items()
            if session_owners.get(sid, ANONYMOUS_PRINCIPAL) == caller
        ]
        recent = sorted(
            owned,
            key     = lambda s: s.started_at,
            reverse = True,
        )[:max(1, min(limit, 100))]

        return [{
            "session_id":     s.session_id,
            "task":           s.task[:80],
            "status":         s.status.name,
            "cells_executed": s.cells_executed,
            "duration_s":     round(s.duration, 2),
            "error_count":    s.error_count,
        } for s in recent]

    @app.get("/sessions/{session_id}")
    async def get_session(
        session_id: str,
        principal: dict = Depends(_mgmt_principal),
    ):
        """Get details of a specific session — ownership-gated (F-011)."""
        result = sessions.get(session_id)
        if not result:
            return JSONResponse(
                status_code = 404,
                content     = {"error": "Session {} not found".format(session_id)}
            )
        assert_session_owner(
            session_owners.get(session_id), principal, session_id=session_id,
        )
        return {
            "session_id":     result.session_id,
            "task":           result.task,
            "status":         result.status.name,
            "cells_executed": result.cells_executed,
            "duration_s":     round(result.duration, 2),
            "summary":        result.summary,
            "final_namespace": result.final_namespace,
            "cells": [{
                "cell_num":  c.cell_num,
                "code":      c.code[:200],
                "had_error": c.output.has_error,
                "stdout":    c.output.stdout[:200],
            } for c in result.cells],
        }

    @app.on_event("shutdown")
    async def shutdown():
        pool.shutdown()

    return app


def _execute_task(
    kernel,
    llm,
    request,
    session_id: str,
    memory,
    capability_broker: Optional[object] = None,
    budget:            Optional[object] = None,
    cancel_token:      Optional[object] = None,
    default_security:  str              = "data_analysis",
) -> SessionResult:
    """Execute a task synchronously in a kernel — through the choke point."""
    from kerno.loop.factory       import make_reactive, make_reflect
    from kerno.skills.bootstrap   import bootstrap
    from kerno.interfaces         import AgentState
    from kerno.server.security    import make_server_engine
    import time

    bootstrap(kernel)

    # K-001 / K-012: client cannot downgrade server policy.
    # Canonical gateway: one authoritative builder for every transport.
    from kerno.server.security import build_gateway_engine
    engine = build_gateway_engine(
        kernel,
        profile           = getattr(request, "security", None),
        capability_broker = capability_broker,
        budget            = budget,
        server_default    = default_security,
        allow_downgrade   = False,
        budget_cells      = getattr(request, "budget_cells", None),
        transport         = "http",
    )

    factory = {
        "reactive": make_reactive,
        "reflect":  make_reflect,
    }.get(request.loop, make_reactive)

    pipeline = factory(
        kernel    = engine,
        llm       = llm,
        memory    = memory,
        max_cells = request.max_cells,
    )

    meta = {}
    if cancel_token is not None:
        meta["cancel_token"] = cancel_token

    started = time.time()
    state   = AgentState(task=request.task, session_id=session_id, metadata=meta)
    final   = pipeline.run(state)

    from kerno.types import SessionResult, SessionStatus, Cell
    interrupted = (
        final.metadata.get("interrupted", False)
        or (cancel_token is not None and getattr(cancel_token, "is_set", lambda: False)())
    )
    status = (
        SessionStatus.INTERRUPTED    if interrupted
        else SessionStatus.COMPLETE  if final.complete
        else SessionStatus.ERROR_UNHANDLED if final.error
        else SessionStatus.MAX_CELLS
    )

    return SessionResult(
        session_id      = session_id,
        task            = request.task,
        status          = status,
        cells           = final.history,
        final_namespace = kernel.namespace,
        summary         = final.summary,
        started_at      = started,
        ended_at        = time.time(),
    )
