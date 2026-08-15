# kerno/skills/builtins/llm_tools.py
"""
Built-in LLM-as-a-function meta-skills.

These skills allow the agent to call an LLM from inside the kernel over
pandas Series or Python lists for classification, extraction, and
summarization. API dependencies and credentials are lazy-loaded so kernels
without an LLM configuration still start successfully.
"""

_LLM_TOOLS_CODE = r'''
import os as _os
import json as _json

import pandas as pd
import numpy as np
from IPython.display import display as _display, HTML as _HTML, Markdown as _MD


def _get_llm_client():
    """Lazy-load an OpenAI-compatible client for OpenRouter or OpenAI."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ImportError(
            "openai>=1.0 is required for LLM tools. Install with: pip install openai"
        ) from exc

    api_key = _os.environ.get("OPENROUTER_API_KEY") or _os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "Set OPENROUTER_API_KEY or OPENAI_API_KEY before using LLM tools."
        )

    kwargs = {"api_key": api_key}
    if _os.environ.get("OPENROUTER_API_KEY"):
        kwargs["base_url"] = "https://openrouter.ai/api/v1"
    return OpenAI(**kwargs)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("\n", 1)
        if len(parts) == 2:
            text = parts[1]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def llm_map(
    texts,
    prompt_template: str,
    model: str = "openai/gpt-4o-mini",
    max_tokens: int = 500,
    parse_json: bool = False,
    batch_size: int = 10,
    temperature: float = 0.0,
) -> list:
    """
    Apply an LLM prompt to each text item.

    The prompt template must contain ``{text}``. If ``parse_json`` is True,
    each response is parsed as JSON and failures are returned as
    ``{"error": ...}``.
    """
    if isinstance(texts, pd.Series):
        items = texts.astype(object).where(texts.notna(), None).tolist()
    elif isinstance(texts, np.ndarray):
        items = texts.tolist()
    else:
        items = list(texts)

    client = _get_llm_client()
    results = []
    total = len(items)
    print(f"Applying LLM to {total} item(s) with model {model}...")

    for i, text in enumerate(items, start=1):
        if text is None or not isinstance(text, str) or not text.strip():
            results.append({} if parse_json else None)
            continue

        prompt = prompt_template.replace("{text}", str(text))
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            content = (resp.choices[0].message.content or "").strip()
            if parse_json:
                try:
                    results.append(_json.loads(_strip_code_fence(content)))
                except _json.JSONDecodeError as exc:
                    results.append({"error": f"JSON decode failed: {exc}", "raw": content[:200]})
            else:
                results.append(content)
        except Exception as exc:  # pragma: no cover - network/API path
            results.append({"error": str(exc)} if parse_json else f"ERROR: {exc}")

        if batch_size and i % batch_size == 0:
            print(f"  Processed {i}/{total}")

    print(f"✓ llm_map complete: {total} item(s) processed.")
    return results


def classify_texts(
    texts,
    labels: list,
    instructions: str = "",
    model: str = "openai/gpt-4o-mini",
) -> pd.Series:
    """
    Zero-shot classify each text into exactly one of the supplied labels.

    The response is normalized back to one of the labels when possible.
    """
    labels_str = ", ".join(labels)
    instruction_line = f"Instructions: {instructions}\n" if instructions else ""
    prompt = (
        f"Classify the text into exactly one of these categories: [{labels_str}].\n"
        f"{instruction_line}"
        "Respond with only the category name.\n"
        "Text: {text}"
    )
    raw = llm_map(texts, prompt, model=model, parse_json=False, max_tokens=20)

    cleaned = []
    lowered = {str(label).lower(): label for label in labels}
    for item in raw:
        if not isinstance(item, str):
            cleaned.append("Unknown")
            continue
        match = next((value for key, value in lowered.items() if key in item.lower()), None)
        cleaned.append(match or item.strip() or "Unknown")

    if isinstance(texts, pd.Series):
        index = texts.index
    else:
        index = pd.RangeIndex(len(raw))
    result = pd.Series(cleaned, index=index, name="label")
    print(result.value_counts().to_string())
    return result


def extract_structured(
    texts,
    schema: dict,
    instructions: str = "",
    model: str = "openai/gpt-4o-mini",
) -> pd.DataFrame:
    """
    Extract structured fields from unstructured text.

    ``schema`` maps field names to type/description strings.
    Returns a DataFrame with one column per schema field.
    """
    schema_desc = "\n".join(f"- {key}: {value}" for key, value in schema.items())
    instruction_line = f"Instructions: {instructions}\n" if instructions else ""
    prompt = (
        "Extract the requested fields as one JSON object.\n"
        f"Fields:\n{schema_desc}\n"
        f"{instruction_line}"
        "Return only valid JSON.\n"
        "Text: {text}"
    )
    rows = llm_map(texts, prompt, model=model, parse_json=True, max_tokens=500)
    df = pd.DataFrame(rows)
    for field in schema:
        if field not in df.columns:
            df[field] = None
    return df[list(schema.keys())]


def semantic_search(
    query: str,
    documents,
    top_k: int = 5,
    model: str = "text-embedding-3-small",
) -> pd.DataFrame:
    """
    Semantic search using an embedding model.

    Returns a DataFrame ranked by cosine similarity.
    """
    docs = [str(doc) for doc in documents if doc is not None and not pd.isna(doc)]
    if not docs:
        print("⚠️  No documents provided")
        return pd.DataFrame(columns=["document", "similarity"])

    client = _get_llm_client()
    resp = client.embeddings.create(input=[query] + docs, model=model)
    vectors = np.array([item.embedding for item in resp.data], dtype=float)
    query_vec = vectors[0]
    doc_vecs = vectors[1:]

    similarities = doc_vecs @ query_vec / (
        np.linalg.norm(doc_vecs, axis=1) * np.linalg.norm(query_vec) + 1e-12
    )
    result = pd.DataFrame({"document": docs, "similarity": similarities})
    result = result.sort_values("similarity", ascending=False).head(top_k).reset_index(drop=True)
    _display(result.style.format({"similarity": "{:.4f}"}))
    return result
'''


def get_code() -> str:
    return _LLM_TOOLS_CODE
