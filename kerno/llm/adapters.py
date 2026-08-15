# kerno/llm/adapters.py
"""
LLM adapters: standard callables for common providers.
"""

from __future__ import annotations

from typing import Optional
from kerno.types import Message


def anthropic_llm(
    model:       str   = "claude-opus-4-5",
    max_tokens:  int   = 4096,
    temperature: float = 0.0,
    api_key:     Optional[str] = None,
) -> callable:
    """Return a kerno-compatible LLM callable for Anthropic."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def llm(messages: list[Message]) -> str:
        response = client.messages.create(
            model      = model,
            max_tokens = max_tokens,
            system     = messages[0].content if messages else "",
            messages   = [
                {"role": m.role, "content": m.content}
                for m in messages[1:]
            ],
        )
        return response.content[0].text

    llm.__name__ = "anthropic/{}".format(model)
    llm.__repr__ = lambda: "anthropic_llm(model='{}')".format(model)
    return llm


def openai_llm(
    model:       str   = "gpt-4o",
    max_tokens:  int   = 4096,
    temperature: float = 0.0,
    api_key:     Optional[str] = None,
) -> callable:
    """Return a kerno-compatible LLM callable for OpenAI."""
    import openai
    client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()

    def llm(messages: list[Message]) -> str:
        response = client.chat.completions.create(
            model       = model,
            max_tokens  = max_tokens,
            temperature = temperature,
            messages    = [
                {"role": m.role, "content": m.content}
                for m in messages
            ],
        )
        return response.choices[0].message.content

    llm.__name__ = "openai/{}".format(model)
    return llm


def make_llm(
    provider: str,
    model:    str,
    **kwargs,
) -> callable:
    """
    Factory function: make_llm("anthropic", "claude-opus-4-5")

    Supports: "anthropic", "openai"
    """
    factories = {
        "anthropic": anthropic_llm,
        "openai":    openai_llm,
    }
    factory = factories.get(provider)
    if not factory:
        raise ValueError(
            "Unknown provider: {}. Available: {}".format(provider, list(factories))
        )
    return factory(model=model, **kwargs)
