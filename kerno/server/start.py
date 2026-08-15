"""
Server startup script for Docker deployment.
Reads configuration from environment variables.
"""

import os
import sys


def main():
    import uvicorn
    from kerno.llm.openrouter import openrouter_llm
    from kerno.server.openai_compat import create_openai_app

    api_key  = os.environ.get("OPENROUTER_API_KEY")
    model    = os.environ.get("KERNO_MODEL", "anthropic/claude-opus-4-5")
    pool_size= int(os.environ.get("KERNO_POOL_SIZE", "3"))
    max_cells= int(os.environ.get("KERNO_MAX_CELLS", "50"))
    port     = int(os.environ.get("PORT", "8001"))
    host     = os.environ.get("HOST", "0.0.0.0")

    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    llm = openrouter_llm(model=model, api_key=api_key)

    app = create_openai_app(
        llm       = llm,
        pool_size = pool_size,
        model_id  = "kerno-agent",
        model_name= f"Kerno Agent ({model})",
    )

    print(f"Starting Kerno server on {host}:{port}")
    print(f"Model: {model}")
    print(f"Pool:  {pool_size} kernels")

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
