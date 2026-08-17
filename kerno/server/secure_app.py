"""
Production-ready server with authentication, rate limiting,
per-user isolation, and usage tracking.
"""

from __future__ import annotations

import time
import uuid
from typing import Optional

try:
    from fastapi            import Depends, FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses  import JSONResponse, StreamingResponse
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


try:
    from kerno.server.auth  import verify_api_key, RateLimiter
except ImportError:
    # fastapi not installed → auth helpers are unavailable.
    # create_secure_app() raises a clear error below when called.
    verify_api_key = None
    RateLimiter    = None
try:
    from kerno.server.openai_compat import (
        ChatCompletionRequest,
        _extract_task,
        _compile_output,
    )
except ImportError:
    ChatCompletionRequest = None
    _extract_task         = None
    _compile_output       = None


def create_secure_app(
    llm_factory,           # Callable(user_info) -> LLM
    pool_size:    int = 3,
    skills_path:  Optional[str] = None,
    enable_auth:  bool = True,
    default_security: str = "data_analysis",
) -> "FastAPI":
    """
    Create a production-ready server.

    Args:
        llm_factory:  Function that creates an LLM given user_info.
                      Allows per-user model assignment.
        pool_size:    Kernel pool size.
        skills_path:  Path to skills file.
        enable_auth:  Enable API key authentication.
        default_security: Allowlist profile for every session (the
                          authenticated server defaults to data_analysis).
    """
    if not HAS_FASTAPI:
        raise ImportError("pip install fastapi uvicorn")

    from kerno.kernel.pool import KernelPool

    app  = FastAPI(title="Kerno Secure API", version="1.0.0")
    pool = KernelPool(size=pool_size, skills_path=skills_path)
    pool.start()

    # Usage tracking
    usage_log: list[dict] = []

    app.add_middleware(
        CORSMiddleware,
        allow_origins  = ["*"],
        allow_methods  = ["*"],
        allow_headers  = ["*"],
    )

    # Auth dependency
    auth_dep = verify_api_key if enable_auth else lambda: {"user_id": "anon", "max_cells": 50, "rate_limit": 1000}

    @app.get("/v1/models")
    async def list_models():
        return {
            "object": "list",
            "data": [
                {"id": "kerno-agent", "object": "model",
                 "created": int(time.time()), "owned_by": "kerno"}
            ]
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(
        request:   ChatCompletionRequest,
        user_info: dict = Depends(auth_dep),
    ):
        session_id = str(uuid.uuid4())
        task_id    = f"secure-{session_id[:8]}"
        user_id    = user_info.get("user_id", "anonymous")

        # Apply per-user cell limit
        max_cells  = min(
            request.max_cells,
            user_info.get("max_cells", 50),
        )

        # Create LLM for this user
        llm = llm_factory(user_info)

        usage_log.append({
            "ts":        time.time(),
            "user_id":   user_id,
            "session_id":session_id,
            "task":      _extract_task(request.messages)[:80],
        })

        kernel = pool.acquire(task_id)

        try:
            from kerno.skills.bootstrap   import bootstrap
            from kerno.loop.factory       import make_reactive, make_reflect
            from kerno.interfaces         import AgentState
            from kerno.server.files       import FileMaterializer
            from kerno.server.security    import make_server_engine

            bootstrap(kernel)
            # K-001: the authenticated server never executes raw kernel
            # code — every session goes through the choke point.
            # K-012 (F-006): the server default is authoritative — the
            # client may not downgrade below it. Canonical gateway builder
            # (same as /run, /stream, /ws and the OpenAI-compatible app).
            from kerno.server.security import build_gateway_engine
            engine = build_gateway_engine(
                kernel,
                profile           = getattr(request, "security", default_security),
                capability_broker = None,
                budget            = None,
                server_default    = default_security,
                allow_downgrade   = False,
            )

            # File handling — through the engine choke point (F-001).
            # FileMaterializer receives a narrow MaterializationExecutor,
            # never the raw kernel.
            from kerno.server.files import MaterializationExecutor
            body = request.dict()
            mat  = FileMaterializer(MaterializationExecutor(engine))
            try:
                files = mat.process_from_context(body)
                task = _extract_task(request.messages)
                if files:
                    task += "\n\n" + mat.build_context_message(files)
            finally:
                mat.cleanup()

            factory  = make_reflect if request.loop == "reflect" else make_reactive
            pipeline = factory(kernel=engine, llm=llm, max_cells=max_cells)

            if request.stream:
                from kerno.streaming.executor import StreamingExecutor
                from kerno.streaming.protocol import EventKind
                import json as _json

                async def _stream():
                    executor = StreamingExecutor(pipeline, session_id=session_id)
                    async for event in executor.stream(task):
                        chunk_text = None
                        if event.kind == EventKind.OUTPUT_STDOUT:
                            chunk_text = event.payload.get("text", "")
                        elif event.kind == EventKind.CELL_START:
                            chunk_text = f"\n```python\n# Cell {event.cell_num}\n"
                        elif event.kind == EventKind.CELL_COMPLETE:
                            chunk_text = "```\n"
                        elif event.kind == EventKind.SESSION_COMPLETE:
                            chunk_text = f"\n✅ Complete — {event.payload.get('cells', 0)} cells"

                        if chunk_text:
                            yield f"data: {_json.dumps({'choices': [{'delta': {'content': chunk_text}}]})}\n\n"

                        if event.kind == EventKind.SESSION_COMPLETE:
                            yield "data: [DONE]\n\n"
                            break

                return StreamingResponse(_stream(), media_type="text/event-stream")

            else:
                import asyncio
                state = AgentState(task=task, session_id=session_id)
                final = await asyncio.get_event_loop().run_in_executor(
                    None, pipeline.run, state
                )
                return {
                    "id":      f"chatcmpl-{session_id[:8]}",
                    "object":  "chat.completion",
                    "created": int(time.time()),
                    "model":   request.model,
                    "choices": [{
                        "index":         0,
                        "message":       {"role": "assistant", "content": _compile_output(final)},
                        "finish_reason": "stop",
                    }],
                }
        finally:
            pool.release(task_id, reason="complete")

    @app.get("/health")
    async def health():
        return {"status": "ok", "pool": pool.stats, "sessions": len(usage_log)}

    @app.get("/usage")
    async def usage(user_info: dict = Depends(auth_dep)):
        user_id = user_info.get("user_id")
        user_sessions = [u for u in usage_log if u["user_id"] == user_id]
        return {"user_id": user_id, "sessions": len(user_sessions), "log": user_sessions[-10:]}

    @app.on_event("shutdown")
    async def shutdown():
        pool.shutdown()

    return app
