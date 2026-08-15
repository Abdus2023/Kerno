"""
End-to-end stack test.
Run after starting both servers (Kerno + Open WebUI).

These tests verify the OpenAI-compatible API endpoints
that Open WebUI uses to connect to Kerno.

To run:
    pytest tests/integration/test_openai_compat.py -v --timeout=60

Note: These tests require the Kerno server to be running on localhost:8001.
      They are skipped if the server is not reachable.
"""

from __future__ import annotations

import json
import pytest

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

BASE_URL = "http://localhost:8001"


def _server_available() -> bool:
    """Check if the Kerno server is reachable."""
    if not HAS_HTTPX:
        return False
    try:
        resp = httpx.get(f"{BASE_URL}/health", timeout=5.0)
        return resp.status_code == 200
    except Exception:
        return False


# Skip all tests if server is not available
skip_no_server = pytest.mark.skipif(
    not _server_available(),
    reason="Kerno server not running on localhost:8001"
)


@skip_no_server
def test_health():
    resp = httpx.get(f"{BASE_URL}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    print(f"✓ Health: {data['status']}")


@skip_no_server
def test_models():
    resp = httpx.get(f"{BASE_URL}/v1/models")
    assert resp.status_code == 200
    models = resp.json()["data"]
    assert len(models) >= 1
    print(f"✓ Models: {[m['id'] for m in models]}")


@skip_no_server
def test_sync_completion():
    resp = httpx.post(
        f"{BASE_URL}/v1/chat/completions",
        json={
            "model":    "kerno-agent",
            "messages": [
                {"role": "user", "content": "Print 'Hello from Kerno!' and compute 2+2"}
            ],
            "stream":   False,
        },
        timeout=120.0,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "choices" in data
    assert len(data["choices"]) >= 1
    content = data["choices"][0]["message"]["content"]
    print(f"✓ Sync completion:\n{content[:200]}")


@skip_no_server
def test_streaming():
    with httpx.stream(
        "POST",
        f"{BASE_URL}/v1/chat/completions",
        json={
            "model":    "kerno-agent",
            "messages": [
                {"role": "user", "content": "Create a 10-row DataFrame with columns a, b, c and print it"}
            ],
            "stream":   True,
        },
        timeout=120.0,
    ) as resp:
        assert resp.status_code == 200
        chunks_received = 0
        for line in resp.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                chunk = json.loads(line[6:])
                delta = chunk["choices"][0]["delta"].get("content", "")
                if delta:
                    chunks_received += 1
        print(f"✓ Streaming: {chunks_received} content chunks received")
        assert chunks_received > 0
