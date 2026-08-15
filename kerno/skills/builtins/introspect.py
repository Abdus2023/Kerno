# kerno/skills/builtins/introspect.py
"""
Built-in introspection skills.

These are the agent's self-awareness tools.
The LLM uses them to answer: "What do I have? What can I do with it?"

Critical for:
  - Recovering from NameErrors (what's actually in scope?)
  - Debugging data issues (what does this DataFrame actually contain?)
  - Avoiding re-computation (does this object already exist?)
  - Planning (what skills are available?)
"""

_INTROSPECT_SKILLS_CODE = '''
import pandas as pd
import numpy as np
import inspect as _inspect
import json as _json
from IPython.display import display as _display, HTML as _HTML, Markdown as _MD


def what_exists(pattern: str = None) -> dict:
    """
    List everything currently in the kernel namespace.

    Args:
        pattern: Optional substring filter (case-insensitive)

    Returns:
        dict: {name: type_description}

    Example:
        what_exists()           # All objects
        what_exists("df")       # Only objects with "df" in their name
        what_exists("model")    # Only model objects
    """
    result = {}
    for name, obj in list(globals().items()):
        if name.startswith('_'):
            continue
        if pattern and pattern.lower() not in name.lower():
            continue
        try:
            t = type(obj).__name__
            if hasattr(obj, 'shape'):
                result[name] = f"{t}{list(obj.shape)}"
            elif hasattr(obj, '__len__') and not isinstance(obj, (str, bytes, type)):
                result[name] = f"{t}(len={len(obj)})"
            elif callable(obj) and not isinstance(obj, type):
                doc = (getattr(obj, '__doc__', '') or '')[:50].split('\\n')[0]
                result[name] = f"fn — {doc}" if doc else f"fn:{obj.__name__}"
            elif isinstance(obj, (int, float, bool)):
                result[name] = f"{t} = {obj}"
            elif isinstance(obj, str):
                preview = repr(obj[:40])
                result[name] = f"str = {preview}"
            else:
                result[name] = t
        except Exception:
            result[name] = "?"

    if not result:
        msg = (f"No objects matching '{pattern}'" if pattern
               else "Namespace is empty")
        print(msg)
        return {}

    # Rich display
    rows = "".join(
        f"<tr><td><code>{n}</code></td><td>{v}</td></tr>"
        for n, v in sorted(result.items())
    )
    _display(_HTML(
        f"<table style='font-family:monospace;font-size:12px'>"
        f"<tr><th>Name</th><th>Type / Value</th></tr>{rows}</table>"
    ))
    return result


def schema_of(obj_name: str) -> dict:
    """
    Show the detailed schema of an object in the namespace.
    Most useful for DataFrames, dicts, and fitted models.

    Args:
        obj_name: Name of the variable (as a string)

    Returns:
        dict with type-specific schema information

    Example:
        schema_of("df")
        schema_of("model")
        schema_of("results")
    """
    obj = globals().get(obj_name)
    if obj is None:
        available = [k for k in globals() if not k.startswith('_')]
        print(f"'{obj_name}' not found. Available: {available[:10]}")
        return {}

    info = {"name": obj_name, "type": type(obj).__name__}

    if isinstance(obj, pd.DataFrame):
        nulls     = obj.isnull().sum()
        null_cols = nulls[nulls > 0].to_dict()

        info.update({
            "shape":       list(obj.shape),
            "columns":     {c: str(t) for c, t in obj.dtypes.items()},
            "nulls":       null_cols,
            "memory_mb":   round(obj.memory_usage(deep=True).sum() / 1e6, 2),
            "index_type":  str(obj.index.dtype),
            "sample":      obj.head(3).to_dict(orient='records'),
        })

        # Rich display
        rows = [
            f"<tr><td><b>Shape</b></td><td>{obj.shape[0]:,} × {obj.shape[1]}</td></tr>",
            f"<tr><td><b>Memory</b></td><td>{info['memory_mb']} MB</td></tr>",
        ]
        for col, dtype in obj.dtypes.items():
            n_null = nulls[col]
            null_str = f" <span style='color:orange'>({n_null} nulls)</span>" if n_null else ""
            rows.append(f"<tr><td><code>{col}</code></td><td>{dtype}{null_str}</td></tr>")

        _display(_HTML(
            "<table style='font-family:monospace;font-size:12px'>"
            + "".join(rows)
            + "</table>"
        ))
        _display(obj.head(3))

    elif callable(obj) and not isinstance(obj, type):
        try:
            sig = _inspect.signature(obj)
            params = {
                p: str(v.annotation) if v.annotation != _inspect.Parameter.empty else "Any"
                for p, v in sig.parameters.items()
            }
            ret = (str(sig.return_annotation)
                   if sig.return_annotation != _inspect.Parameter.empty
                   else "Any")
        except (ValueError, TypeError):
            params, ret = {}, "unknown"

        info.update({
            "parameters": params,
            "returns":    ret,
            "doc":        (obj.__doc__ or "")[:500],
        })
        print(f"fn {obj_name}({', '.join(params.keys())}) → {ret}")
        if obj.__doc__:
            print(obj.__doc__[:300])

    elif hasattr(obj, 'get_params'):
        # sklearn-like model
        fitted = (hasattr(obj, 'feature_importances_') or
                  hasattr(obj, 'coef_')               or
                  hasattr(obj, 'n_iter_'))
        info.update({
            "params": obj.get_params(),
            "fitted": fitted,
            "classes": list(getattr(obj, 'classes_', [])),
            "n_features": getattr(obj, 'n_features_in_', None),
        })
        print(f"{'✓ Fitted' if fitted else '✗ Not fitted'} {type(obj).__name__}")
        print(f"Parameters: {obj.get_params()}")

    elif isinstance(obj, dict):
        info.update({
            "keys":       list(obj.keys())[:20],
            "n_keys":     len(obj),
            "value_types": list({type(v).__name__ for v in obj.values()}),
        })
        print(f"dict with {len(obj)} keys: {list(obj.keys())[:10]}")

    elif isinstance(obj, (list, tuple)):
        info.update({
            "length":      len(obj),
            "value_types": list({type(v).__name__ for v in obj[:20]}),
            "sample":      [str(v)[:50] for v in obj[:5]],
        })
        print(f"{type(obj).__name__} of length {len(obj)}")
        print(f"First 5: {obj[:5]}")

    return info


def dependencies_of(obj_name: str) -> list:
    """
    Trace which cells created and modified a variable.
    Requires execution history (In variable) to be available.

    Args:
        obj_name: Variable name to trace

    Returns:
        list of cell numbers where the variable was assigned
    """
    try:
        history = list(In)           # IPython execution history
    except NameError:
        print("Execution history not available outside IPython.")
        return []

    involved = []
    for i, cell_code in enumerate(history):
        if cell_code and obj_name in cell_code:
            lines = [l for l in cell_code.split('\\n') if obj_name in l]
            involved.append({
                "cell":  i,
                "lines": lines[:3],
            })

    if not involved:
        print(f"'{obj_name}' not found in execution history.")
        return []

    print(f"'{obj_name}' appears in {len(involved)} cell(s):")
    for item in involved:
        print(f"  Cell {item['cell']}:")
        for line in item['lines']:
            print(f"    {line.strip()}")

    return involved


def memory_report() -> dict:
    """
    Report memory usage of all objects in the namespace, largest first.

    Returns:
        dict: {name: size_mb}
    """
    import sys

    report = {}
    for name, obj in list(globals().items()):
        if name.startswith('_'):
            continue
        try:
            if isinstance(obj, pd.DataFrame):
                size_mb = obj.memory_usage(deep=True).sum() / 1e6
            elif isinstance(obj, np.ndarray):
                size_mb = obj.nbytes / 1e6
            else:
                size_mb = sys.getsizeof(obj) / 1e6
            report[name] = round(size_mb, 3)
        except Exception:
            pass

    report = dict(sorted(report.items(), key=lambda x: x[1], reverse=True))

    total = sum(report.values())
    print(f"Namespace memory usage (total ≈ {total:.1f} MB):")
    for name, mb in list(report.items())[:15]:
        bar = "█" * max(1, int(mb / max(report.values()) * 20))
        print(f"  {name:<25} {mb:>7.2f} MB  {bar}")

    return report


def diagnose(obj_name: str) -> str:
    """
    Run a diagnostic check on a variable.
    Useful after an unexpected error — tells you what's actually there.

    Args:
        obj_name: Variable name to diagnose

    Returns:
        Plain text diagnostic report
    """
    obj = globals().get(obj_name)

    lines = [f"=== Diagnostic: {obj_name} ==="]

    if obj is None:
        similar = [k for k in globals()
                   if k[:3].lower() == obj_name[:3].lower()
                   and not k.startswith('_')]
        lines.append(f"NOT FOUND in namespace.")
        if similar:
            lines.append(f"Similar names: {similar}")
        report = '\\n'.join(lines)
        print(report)
        return report

    lines.append(f"Type:    {type(obj).__name__}")
    lines.append(f"Module:  {type(obj).__module__}")

    if isinstance(obj, pd.DataFrame):
        lines.append(f"Shape:   {obj.shape}")
        lines.append(f"Columns: {list(obj.columns)}")
        lines.append(f"Dtypes:  {dict(obj.dtypes.astype(str))}")
        nulls = obj.isnull().sum()
        if nulls.any():
            lines.append(f"Nulls:   {nulls[nulls > 0].to_dict()}")
        lines.append(f"Sample row 0: {obj.iloc[0].to_dict() if len(obj) > 0 else '(empty)'}")

    elif isinstance(obj, np.ndarray):
        lines.append(f"Shape:   {obj.shape}")
        lines.append(f"Dtype:   {obj.dtype}")
        lines.append(f"Range:   [{obj.min():.4f}, {obj.max():.4f}]")
        lines.append(f"Has NaN: {bool(np.isnan(obj).any())}")

    elif callable(obj):
        try:
            sig = _inspect.signature(obj)
            lines.append(f"Signature: {sig}")
        except Exception:
            pass

    report = '\\n'.join(lines)
    print(report)
    return report


def search_skills(query: str) -> list:
    """
    Search callable skills by keyword in their name or first docstring line.

    Useful for discovering available capabilities mid-session.
    Returns matching names and prints up to 10 signatures.
    """
    query_terms = [term.lower() for term in str(query).split() if term]
    matches = []
    for name, obj in list(globals().items()):
        if name.startswith("_") or not callable(obj) or isinstance(obj, type):
            continue
        doc = (getattr(obj, "__doc__", "") or "").lower()
        text = f"{name.lower()} {doc}"
        score = sum(1 for term in query_terms if term in text)
        if not query_terms or not score:
            continue
        try:
            signature = str(_inspect.signature(obj))
        except (ValueError, TypeError):
            signature = "()"
        summary = doc.strip().splitlines()[0][:160] if doc else ""
        matches.append({"name": name, "signature": f"{name}{signature}",
                        "summary": summary, "score": score})

    matches.sort(key=lambda item: item["score"], reverse=True)
    if not matches:
        print(f"No skills found for '{query}'.")
        return []
    print(f"Found {len(matches)} skill(s) for '{query}':")
    for match in matches[:10]:
        print(f"  • {match['signature']}")
        if match["summary"]:
            print(f"    {match['summary']}")
    return [match["name"] for match in matches]
'''


def get_code() -> str:
    return _INTROSPECT_SKILLS_CODE
