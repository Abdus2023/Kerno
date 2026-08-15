# kerno/server/__init__.py
"""
kerno HTTP server.

Exposes kerno as an HTTP service with:
  - POST /run          — synchronous task execution
  - POST /stream       — Server-Sent Events streaming
  - WebSocket /ws/{id} — WebSocket streaming
  - GET  /sessions     — list past sessions
  - GET  /sessions/{id}— get session details
  - GET  /health       — health check
  - GET  /metrics      — current metrics snapshot

Requires: pip install fastapi uvicorn
"""
