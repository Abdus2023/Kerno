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
    from fastapi              import FastAPI, WebSocket, WebSocketDisconnect
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
    cors_origins:      list[str]     = ["*"],
    capability_broker: Optional[object] = None,
    budget:            Optional[object] = None,
    default_security:  str           = "data_analysis",
) -> "FastAPI":
    """
    Create and configure the FastAPI application with universal gateway governance (K-011).
    """
    if not HAS_FASTAPI:
        raise ImportError(
            "FastAPI is required for the kerno server. "
            "Install with: pip install fastapi uvicorn"
        )

    from kerno.kernel.pool    import KernelPool
    from kerno.memory.simple  import SimpleMemoryStore
    from kerno.server.security import make_server_engine
    from kerno.cancel         import CancellationToken
    from kerno.execution.budget import ExecutionBudget

    app = FastAPI(
        title       = "kerno",
        description = "A kernel-native agent runtime",
        version     = "0.2.1-dev",
    )

    # Wildcard origins must not allow credentials in production
    allow_creds = cors_origins != ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins     = cors_origins,
        allow_credentials = allow_creds,
        allow_methods     = ["*"],
        allow_headers     = ["*"],
    )

    # Shared resources
    pool   = KernelPool(size=pool_size, skills_path=skills_path)
    memory = SimpleMemoryStore(persist_path=memory_path)
    sessions: dict[str, SessionResult] = {}
    active_tokens: dict[str, CancellationToken] = {}

    pool.start()

    def _build_gateway_engine(kernel, profile: str = None, budget_cells: int = None):
        # K-012: client cannot downgrade below server policy
        prof = profile or default_security
        if prof == "none":
            prof = default_security

        req_budget = None
        if budget_cells:
            req_budget = ExecutionBudget(max_executions=int(budget_cells))

        return make_server_engine(
            kernel,
            profile           = prof,
            capability_broker = capability_broker,
            budget            = budget or req_budget,
        )

    # ── Routes ────────────────────────────────────────────────────────────────

    @app.get("/health/live")
    async def health_live():
        """Public liveness probe (minimal disclosure)."""
        return {"status": "ok"}

    @app.get("/health")
    async def health():
        """Operational readiness probe."""
        return {
            "status":      "ok",
            "pool_stats":  pool.stats,
            "sessions":    len(sessions),
            "timestamp":   time.time(),
        }

    @app.get("/metrics")
    async def metrics():
        from kerno.telemetry import get_metrics
        return get_metrics().snapshot()

    @app.post("/sessions/{session_id}/cancel")
    async def cancel_session(session_id: str):
        """Cancel an actively executing session (audit #83)."""
        token = active_tokens.get(session_id)
        if not token:
            return JSONResponse(
                status_code = 404,
                content     = {"error": f"Active session {session_id} not found or already completed"}
            )
        token.cancel()
        return {"status": "cancelling", "session_id": session_id}

    @app.post("/run", response_model=RunResponse)
    async def run_task(request: RunRequest):
        """
        Execute a task synchronously through the ExecutionGateway (K-011).
        """
        session_id   = str(uuid.uuid4())
        task_id      = "http-{}".format(session_id[:8])
        cancel_token = CancellationToken()
        active_tokens[session_id] = cancel_token

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
    async def stream_task(request: RunRequest):
        """
        Execute a task and stream events through the ExecutionGateway (K-011).
        """
        session_id   = str(uuid.uuid4())
        task_id      = "sse-{}".format(session_id[:8])
        cancel_token = CancellationToken()
        active_tokens[session_id] = cancel_token

        async def event_generator():
            kernel = pool.acquire(task_id)
            try:
                from kerno.streaming.executor import StreamingExecutor
                from kerno.loop.factory       import make_reactive
                from kerno.skills.bootstrap   import bootstrap

                bootstrap(kernel)
                # K-011 / K-013: stream transport wraps kernel in server gateway engine
                engine   = _build_gateway_engine(kernel, request.security, request.budget_cells)
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
        """
        await ws.accept()
        task_id      = "ws-{}".format(session_id[:8])
        cancel_token = CancellationToken()
        active_tokens[session_id] = cancel_token

        try:
            data      = await ws.receive_json()
            task      = data.get("task", "")
            raw_cells = data.get("max_cells", 50)
            max_cells = min(max(1, int(raw_cells)), 100) # Server-enforced cell cap

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
                engine   = _build_gateway_engine(kernel, default_security, max_cells)
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
        except Exception as e:
            try:
                await ws.send_json({"error": str(e)})
            except Exception:
                pass

    @app.get("/sessions")
    async def list_sessions(limit: int = 20):
        """List recent sessions."""
        recent = sorted(
            sessions.values(),
            key     = lambda s: s.started_at,
            reverse = True,
        )[:limit]

        return [{
            "session_id":     s.session_id,
            "task":           s.task[:80],
            "status":         s.status.name,
            "cells_executed": s.cells_executed,
            "duration_s":     round(s.duration, 2),
            "error_count":    s.error_count,
        } for s in recent]

    @app.get("/sessions/{session_id}")
    async def get_session(session_id: str):
        """Get details of a specific session."""
        result = sessions.get(session_id)
        if not result:
            return JSONResponse(
                status_code = 404,
                content     = {"error": "Session {} not found".format(session_id)}
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

    # K-001 / K-012: client cannot downgrade server policy
    prof = getattr(request, "security", default_security) or default_security
    if prof == "none":
        prof = default_security

    req_budget = None
    req_cells = getattr(request, "budget_cells", None)
    if req_cells:
        from kerno.execution.budget import ExecutionBudget
        req_budget = ExecutionBudget(max_executions=int(req_cells))
    engine = make_server_engine(
        kernel,
        profile            = prof,
        capability_broker  = capability_broker,
        budget             = budget or req_budget,
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
