"""
OpenAI-compatible API server for Kerno.

Open WebUI (and anything else speaking OpenAI protocol)
connects to this as if it were an OpenAI endpoint.

Endpoint: POST /v1/chat/completions
Models:   GET  /v1/models

The trick: translate OpenAI chat format into Kerno tasks,
execute them in a kernel session, and stream results back
in OpenAI SSE format.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Optional

try:
    from fastapi            import Depends, FastAPI
    from fastapi.responses  import StreamingResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic           import BaseModel, Field
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


# ── OpenAI-format request/response models ────────────────────────────────────

if HAS_FASTAPI:
    class ChatMessage(BaseModel):
        role:    str
        content: str

    class ChatCompletionRequest(BaseModel):
        model:       str                        = "kerno-default"
        messages:    list[ChatMessage]
        stream:      bool                       = False
        max_tokens:  Optional[int]              = None
        temperature: Optional[float]            = None

        # Kerno-specific extensions (ignored by standard clients)
        loop:        str                        = "reactive"
        max_cells:   int                        = 50
        security:    str                        = "permissive"  # "none" opts out


def create_openai_app(
    llm,
    *,
    pool_size:         int  = 3,
    skills_path:       Optional[str] = None,
    model_id:          str  = "kerno-1",
    model_name:        str  = "Kerno Kernel Agent",
    capability_broker: Optional[object] = None,
    budget:            Optional[object] = None,
    default_security:  str  = "data_analysis",
    cors_origins:      Optional[list[str]] = None,
) -> "FastAPI":
    """
    Create an OpenAI-compatible FastAPI application.

    Open WebUI configuration:
        Settings → Connections → Add Connection
        URL:    http://localhost:8001
        Key:    (any string — we don't validate it)
        Model:  kerno-1

    Args:
        llm:         LLM callable (e.g., openrouter_llm(...))
        pool_size:   Number of warm kernels
        skills_path: Path to extra skills
        model_id:    Model ID shown in Open WebUI dropdown
        model_name:  Display name in Open WebUI
        capability_broker: CapabilityBroker (K-008) for every session
        budget:       ExecutionBudget (audit #85) for every session
        default_security: allowlist profile when the request omits it
    """
    if not HAS_FASTAPI:
        raise ImportError("pip install fastapi uvicorn")

    from kerno.kernel.pool        import KernelPool
    from kerno.skills.bootstrap   import bootstrap
    from kerno.streaming.protocol import EventKind

    app  = FastAPI(title="Kerno OpenAI-Compatible API")
    pool = KernelPool(size=pool_size, skills_path=skills_path)
    pool.start()

    # F-010: explicit-origin CORS policy — the wildcard "*" is never
    # implicit. Pass cors_origins (or set KERNO_CORS_ORIGINS) for
    # cross-origin deployments; credentials require explicit origins.
    from kerno.server.security import resolve_cors_origins, DEFAULT_CORS_METHODS, DEFAULT_CORS_HEADERS
    origins = resolve_cors_origins(cors_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins  = origins,
        allow_credentials = bool(origins) and "*" not in origins,
        allow_methods  = DEFAULT_CORS_METHODS,
        allow_headers  = DEFAULT_CORS_HEADERS,
    )

    # ── Health check ─────────────────────────────────────────────────────────
    # F-011: /health/live stays public (minimal disclosure, used by load
    # balancers). /health exposes pool statistics and is therefore
    # management-plane — gated by management_principal, which fails
    # closed in production / when KERNO_ENABLE_AUTH is set.
    from kerno.server.management import management_principal as _mgmt
    # The OpenAI-compatible app does not take an explicit enable_auth
    # flag; it follows the process/environment policy. Use the default
    # (env-driven) dependency directly.

    @app.get("/health/live")
    async def health_live():
        return {"status": "ok"}

    @app.get("/health")
    async def health(principal: dict = Depends(_mgmt)):
        return {
            "status":      "ok",
            "pool_stats":  pool.stats,     # KernelPool.stats is a property
            "timestamp":   time.time(),
        }

    # ── Model listing (required by Open WebUI) ────────────────────────────────
    # The catalog itself is not sensitive (model id/name), but in an
    # authenticated deployment it should not be reachable anonymously as
    # an existence oracle. It is therefore gated by the same management
    # principal.

    @app.get("/v1/models")
    async def list_models(principal: dict = Depends(_mgmt)):
        """
        Open WebUI calls this to populate the model dropdown.
        Return at least one model.
        """
        return {
            "object": "list",
            "data": [
                {
                    "id":       model_id,
                    "object":   "model",
                    "created":  int(time.time()),
                    "owned_by": "kerno",
                    "name":     model_name,
                }
            ]
        }

    # ── Chat completions ───────────────────────────────────────────────────────

    @app.post("/v1/chat/completions")
    async def chat_completions(request: ChatCompletionRequest):
        """
        Main endpoint. Open WebUI sends messages here.

        Translates the conversation into a Kerno task,
        executes it, and returns the result in OpenAI format.
        """
        task       = _extract_task(request.messages)
        task_id    = f"oai-{str(uuid.uuid4())[:8]}"
        session_id = str(uuid.uuid4())

        if request.stream:
            return StreamingResponse(
                _stream_response(
                    task, task_id, session_id, request, pool, llm
                ),
                media_type = "text/event-stream",
                headers    = {"Cache-Control": "no-cache"},
            )
        else:
            return await _sync_response(
                task, task_id, session_id, request, pool, llm
            )

    async def _sync_response(task, task_id, session_id, request, pool, llm):
        """Synchronous completion — waits for full session."""
        import asyncio

        kernel = pool.acquire(task_id)
        try:
            def _run():
                from kerno.loop.factory import make_reactive, make_reflect
                from kerno.interfaces   import AgentState
                from kerno.skills.bootstrap import bootstrap
                from kerno.server.security  import make_server_engine

                bootstrap(kernel)
                # K-001 / K-012 (F-005): client cannot downgrade below the
                # authoritative server policy. Canonical gateway builder —
                # the same one used by /run, /stream, /ws and secure_app.
                from kerno.server.security import build_gateway_engine
                engine = build_gateway_engine(
                    kernel,
                    profile           = getattr(request, "security", default_security),
                    capability_broker = capability_broker,
                    budget            = budget,
                    server_default    = default_security,
                    allow_downgrade   = False,
                    transport         = "openai",
                )
                factory  = make_reflect if request.loop == "reflect" else make_reactive
                pipeline = factory(
                    kernel    = engine,
                    llm       = llm,
                    max_cells = request.max_cells,
                )
                state = AgentState(task=task, session_id=session_id)
                return pipeline.run(state)

            final = await asyncio.get_event_loop().run_in_executor(None, _run)

            # Compile all cell outputs into one response
            full_output = _compile_output(final)

            return {
                "id":      f"chatcmpl-{session_id[:8]}",
                "object":  "chat.completion",
                "created": int(time.time()),
                "model":   request.model,
                "choices": [{
                    "index":         0,
                    "message": {
                        "role":    "assistant",
                        "content": full_output,
                    },
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens":     0,
                    "completion_tokens": 0,
                    "total_tokens":      0,
                },
            }
        finally:
            pool.release(task_id, reason="complete")

    async def _stream_response(task, task_id, session_id, request, pool, llm):
        """
        Streaming completion — yields SSE events as cells execute.
        Open WebUI renders output progressively.
        """
        import asyncio
        from kerno.streaming.executor import StreamingExecutor
        from kerno.streaming.protocol import EventKind
        from kerno.loop.factory       import make_reactive, make_reflect
        from kerno.skills.bootstrap   import bootstrap
        from kerno.server.security    import make_server_engine

        kernel = pool.acquire(task_id)

        try:
            bootstrap(kernel)
            # K-001 / K-012 (F-005): client cannot downgrade below the
            # authoritative server policy. Canonical gateway builder (same
            # as the sync path and every other transport).
            from kerno.server.security import build_gateway_engine
            engine = build_gateway_engine(
                kernel,
                profile           = getattr(request, "security", default_security),
                capability_broker = capability_broker,
                budget            = budget,
                server_default    = default_security,
                allow_downgrade   = False,
                transport         = "openai-stream",
            )
            factory  = make_reflect if request.loop == "reflect" else make_reactive
            pipeline = factory(
                kernel    = engine,
                llm       = llm,
                max_cells = request.max_cells,
            )

            executor = StreamingExecutor(pipeline, session_id=session_id)

            # Buffer to accumulate output for streaming
            output_buffer = []

            async for event in executor.stream(task):

                chunk_text = None

                if event.kind == EventKind.CELL_START:
                    cell_num = event.cell_num
                    preview  = event.payload.get("code_preview", "")
                    chunk_text = f"\n```python\n# Cell {cell_num}: {preview}\n"

                elif event.kind == EventKind.OUTPUT_STDOUT:
                    chunk_text = event.payload.get("text", "")

                elif event.kind == EventKind.OUTPUT_IMAGE:
                    chunk_text = f"\n[📊 Plot generated]\n"

                elif event.kind == EventKind.CELL_COMPLETE:
                    had_error = event.payload.get("had_error", False)
                    dur_ms    = event.payload.get("duration_ms", 0)
                    if not had_error:
                        chunk_text = f"# ✓ ({dur_ms:.0f}ms)\n```\n"
                    else:
                        chunk_text = f"# ✗ error\n```\n"

                elif event.kind == EventKind.ERROR_CLASSIFIED:
                    error_class = event.payload.get("error_class", "")
                    hint        = event.payload.get("recovery_hint", "")
                    chunk_text  = f"\n> ⚠️ `{error_class}`: {hint}\n"

                elif event.kind == EventKind.SESSION_COMPLETE:
                    status = event.payload.get("status", "COMPLETE")
                    cells  = event.payload.get("cells", 0)
                    chunk_text = f"\n---\n✅ **{status}** — {cells} cells executed\n"

                if chunk_text:
                    # Format as OpenAI SSE chunk
                    sse_chunk = {
                        "id":      f"chatcmpl-{session_id[:8]}",
                        "object":  "chat.completion.chunk",
                        "created": int(time.time()),
                        "model":   request.model,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": chunk_text},
                            "finish_reason": None,
                        }],
                    }
                    yield f"data: {json.dumps(sse_chunk)}\n\n"

                if event.kind == EventKind.SESSION_COMPLETE:
                    # Final chunk with finish_reason
                    final_chunk = {
                        "id":      f"chatcmpl-{session_id[:8]}",
                        "object":  "chat.completion.chunk",
                        "created": int(time.time()),
                        "model":   request.model,
                        "choices": [{
                            "index":         0,
                            "delta":         {},
                            "finish_reason": "stop",
                        }],
                    }
                    yield f"data: {json.dumps(final_chunk)}\n\n"
                    yield "data: [DONE]\n\n"
                    break

        finally:
            pool.release(task_id, reason="complete")

    @app.on_event("shutdown")
    async def shutdown():
        pool.shutdown()

    return app


def _extract_task(messages: list["ChatMessage"]) -> str:
    """
    Convert OpenAI message history into a Kerno task string.

    Strategy:
      - System messages → prepend as context
      - Last user message → the task
      - Prior conversation → append as context
    """
    system_parts = []
    conversation = []

    for msg in messages:
        if msg.role == "system":
            system_parts.append(msg.content)
        else:
            conversation.append(f"{msg.role.upper()}: {msg.content}")

    # Last user message is the primary task
    last_user = next(
        (m.content for m in reversed(messages) if m.role == "user"),
        "No task provided"
    )

    parts = [last_user]

    if system_parts:
        parts.append(
            f"\n\nSystem context:\n{chr(10).join(system_parts)}"
        )

    if len(conversation) > 2:
        # Prior conversation as context (exclude last user message)
        prior = conversation[:-1]
        parts.append(
            f"\n\nPrior conversation:\n{chr(10).join(prior[-6:])}"
        )

    return "\n".join(parts)


def _compile_output(final_state) -> str:
    """Compile all cell outputs into a markdown response."""
    if not final_state.history:
        return "Session completed with no output."

    parts = []
    for cell in final_state.history:
        parts.append(f"```python\n{cell.code}\n```")

        out = cell.output.as_text(max_chars=1000)
        if out and out != "[no output]":
            parts.append(out)

        if cell.output.images:
            parts.append(f"*{len(cell.output.images)} plot(s) generated*")

    return "\n\n".join(parts)
