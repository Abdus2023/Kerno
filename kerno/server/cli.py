# kerno/server/cli.py
"""
CLI command: kerno serve
"""

import sys


def serve(
    host:        str = "0.0.0.0",
    port:        int = 8000,
    model:       str = "claude-opus-4-5",
    provider:    str = "anthropic",
    pool_size:   int = 3,
    memory_path: str = ".kerno/memory.json",
    reload:      bool = False,
):
    """Start the kerno HTTP server."""
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required. Install with: pip install uvicorn", file=sys.stderr)
        sys.exit(1)

    from kerno.llm.adapters import make_llm
    from kerno.server.app   import create_app

    llm = make_llm(provider, model)
    app = create_app(
        llm         = llm,
        pool_size   = pool_size,
        memory_path = memory_path,
    )

    print("kerno server starting on http://{}:{}".format(host, port))
    print("Model: {}/{}  Pool: {} kernels".format(provider, model, pool_size))
    print("Endpoints: /run  /stream  /ws/{{id}}  /sessions  /health")

    uvicorn.run(app, host=host, port=port, reload=reload)
