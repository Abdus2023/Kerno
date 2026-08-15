"""
OpenRouter adapter for kerno.

OpenRouter provides unified access to 200+ LLMs through
an OpenAI-compatible API.

Base URL: https://openrouter.ai/api/v1
Auth:     Bearer token (OPENROUTER_API_KEY)
Protocol: OpenAI Chat Completions

Usage:
    from kerno.llm.openrouter import openrouter_llm

    llm = openrouter_llm("anthropic/claude-opus-4-5")
    llm = openrouter_llm("openai/gpt-4o")
    llm = openrouter_llm("meta-llama/llama-3.1-70b-instruct")
    llm = openrouter_llm("google/gemini-pro-1.5")
    llm = openrouter_llm("mistralai/mixtral-8x7b-instruct")
"""

from __future__ import annotations

import os
from typing import Optional

from kerno.types import Message


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Popular models available on OpenRouter
# Format: "provider/model-name"
MODELS = {
    # Anthropic
    "claude-opus":      "anthropic/claude-opus-4-5",
    "claude-sonnet":    "anthropic/claude-sonnet-4-5",
    "claude-haiku":     "anthropic/claude-haiku-4-5",

    # OpenAI
    "gpt-4o":           "openai/gpt-4o",
    "gpt-4o-mini":      "openai/gpt-4o-mini",
    "o1":               "openai/o1",
    "o1-mini":          "openai/o1-mini",

    # Meta
    "llama-3.1-405b":   "meta-llama/llama-3.1-405b-instruct",
    "llama-3.1-70b":    "meta-llama/llama-3.1-70b-instruct",
    "llama-3.1-8b":     "meta-llama/llama-3.1-8b-instruct",

    # Google
    "gemini-pro":       "google/gemini-pro-1.5",
    "gemini-flash":     "google/gemini-flash-1.5",

    # Mistral
    "mixtral-8x7b":     "mistralai/mixtral-8x7b-instruct",
    "mistral-7b":       "mistralai/mistral-7b-instruct",

    # Free tier (good for testing)
    "llama-3-8b-free":  "meta-llama/llama-3-8b-instruct:free",
    "mistral-7b-free":  "mistralai/mistral-7b-instruct:free",
}


def openrouter_llm(
    model:       str   = "anthropic/claude-opus-4-5",
    api_key:     Optional[str] = None,
    max_tokens:  int   = 4096,
    temperature: float = 0.0,
    site_url:    str   = "https://github.com/kerno",   # OpenRouter attribution
    site_name:   str   = "kerno",
    timeout:     float = 120.0,
    **extra_params,
) -> callable:
    """
    Create a kerno-compatible LLM callable backed by OpenRouter.

    Args:
        model:       OpenRouter model ID (e.g., "anthropic/claude-opus-4-5")
                     Use a shorthand from MODELS dict or full provider/model string.
        api_key:     OpenRouter API key. Falls back to OPENROUTER_API_KEY env var.
        max_tokens:  Maximum tokens to generate.
        temperature: Sampling temperature (0.0 = deterministic).
        site_url:    Your site URL for OpenRouter attribution headers.
        site_name:   Your site name for OpenRouter attribution headers.
        timeout:     Request timeout in seconds.
        extra_params: Additional parameters passed to the API
                       (e.g., top_p, frequency_penalty, transforms).

    Returns:
        Callable(messages: list[Message]) -> str

    Examples:
        # Use a shorthand
        llm = openrouter_llm("claude-opus")

        # Use full model ID
        llm = openrouter_llm("anthropic/claude-opus-4-5")

        # Free tier for testing
        llm = openrouter_llm("llama-3-8b-free")

        # With fallback models (OpenRouter feature)
        llm = openrouter_llm(
            "anthropic/claude-opus-4-5",
            extra_params={"models": [
                "anthropic/claude-opus-4-5",
                "openai/gpt-4o",            # fallback 1
                "meta-llama/llama-3.1-70b-instruct",  # fallback 2
            ]}
        )
    """
    # Resolve shorthand to full model ID
    resolved_model = MODELS.get(model, model)

    # Resolve API key
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise ValueError(
            "OpenRouter API key required. "
            "Set OPENROUTER_API_KEY environment variable or pass api_key=..."
        )

    try:
        import openai
    except ImportError:
        raise ImportError(
            "openai package required for OpenRouter. "
            "Install: pip install openai"
        )

    client = openai.OpenAI(
        api_key  = key,
        base_url = OPENROUTER_BASE_URL,
        timeout  = timeout,
    )

    def llm(messages: list[Message]) -> str:
        # Convert kerno Message objects to OpenAI format
        formatted = [
            {"role": m.role, "content": m.content}
            for m in messages
        ]

        response = client.chat.completions.create(
            model       = resolved_model,
            messages    = formatted,
            max_tokens  = max_tokens,
            temperature = temperature,
            extra_headers = {
                "HTTP-Referer": site_url,
                "X-Title":      site_name,
            },
            **extra_params,
        )
        return response.choices[0].message.content

    # Attach metadata for introspection
    llm.__name__   = f"openrouter/{resolved_model}"
    llm._model     = resolved_model
    llm._provider  = "openrouter"

    return llm


def openrouter_streaming_llm(
    model:      str   = "anthropic/claude-opus-4-5",
    api_key:    Optional[str] = None,
    max_tokens: int   = 4096,
    **kwargs,
) -> callable:
    """
    Streaming variant. Returns a generator instead of a string.
    Used by the streaming server to forward tokens to clients.

    Usage:
        for chunk in llm_stream(messages):
            print(chunk, end="", flush=True)
    """
    resolved_model = MODELS.get(model, model)
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise ValueError(
            "OpenRouter API key required. "
            "Set OPENROUTER_API_KEY environment variable or pass api_key=..."
        )

    import openai
    client = openai.OpenAI(
        api_key  = key,
        base_url = OPENROUTER_BASE_URL,
    )

    def llm_stream(messages: list[Message]):
        formatted = [{"role": m.role, "content": m.content} for m in messages]
        with client.chat.completions.create(
            model      = resolved_model,
            messages   = formatted,
            max_tokens = max_tokens,
            stream     = True,
            **kwargs,
        ) as stream:
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta

    return llm_stream


def list_models(api_key: Optional[str] = None) -> list[dict]:
    """
    Fetch the current list of models available on OpenRouter.
    Returns list of {id, name, context_length, pricing}.
    """
    import urllib.request, json

    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    req = urllib.request.Request(
        f"{OPENROUTER_BASE_URL}/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return data.get("data", [])


def cheapest_model(
    api_key:        Optional[str] = None,
    min_context:    int           = 8000,
) -> str:
    """
    Return the cheapest available model with at least min_context tokens.
    Useful for cost-sensitive executor LLM in hierarchical loops.
    """
    models = list_models(api_key)
    eligible = [
        m for m in models
        if m.get("context_length", 0) >= min_context
        and m.get("pricing", {}).get("prompt", "999") != "0"
    ]
    if not eligible:
        return "meta-llama/llama-3.1-8b-instruct:free"

    return min(
        eligible,
        key=lambda m: float(m.get("pricing", {}).get("prompt", "999"))
    )["id"]
