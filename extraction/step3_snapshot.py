# kerno/kernel/snapshot.py
"""
NamespaceSnapshot: queries the live kernel namespace and returns
a compact, token-efficient representation for LLM consumption.

This is the bridge between infinite kernel state and finite context window.
"""

import json

from kerno.kernel.output import collect


_SNAPSHOT_CODE = """
import json as _json

_snap = {}
for _k, _v in list(globals().items()):
    if _k.startswith('_'):
        continue
    try:
        _t = type(_v).__name__
        if hasattr(_v, 'shape'):
            _snap[_k] = f"{_t}{list(_v.shape)}"
        elif hasattr(_v, 'dtypes'):  # DataFrame-like without shape
            _snap[_k] = f"{_t}(cols={list(_v.columns)[:6]})"
        elif hasattr(_v, '__len__') and not isinstance(_v, (str, bytes, type)):
            _snap[_k] = f"{_t}(len={len(_v)})"
        elif callable(_v) and not isinstance(_v, type):
            _doc = (getattr(_v, '__doc__', '') or '')[:60].replace('\\n', ' ')
            _snap[_k] = f"fn({_doc})" if _doc else f"fn:{_v.__name__}"
        elif isinstance(_v, (int, float, bool)):
            _snap[_k] = f"{_t}={_v}"
        elif isinstance(_v, str):
            _snap[_k] = f"str={repr(_v[:40])}"
        else:
            _snap[_k] = _t
    except Exception:
        pass

print(_json.dumps(_snap))
"""

_TYPE_DETAIL_CODE = """
import json as _json, inspect as _inspect, pandas as _pd

_target = globals().get('{name}')
_info = {{'name': '{name}', 'type': type(_target).__name__}}

if isinstance(_target, _pd.DataFrame):
    _info['shape']   = list(_target.shape)
    _info['columns'] = {{c: str(t) for c, t in _target.dtypes.items()}}
    _info['nulls']   = _target.isnull().sum().to_dict()
    _info['sample']  = _target.head(3).to_dict(orient='records')

elif callable(_target) and not isinstance(_target, type):
    try:
        _sig = _inspect.signature(_target)
        _info['signature'] = {{
            _p: str(_v.annotation) if _v.annotation != _inspect.Parameter.empty else 'Any'
            for _p, _v in _sig.parameters.items()
        }}
    except (ValueError, TypeError):
        pass
    _info['doc'] = (_target.__doc__ or '')[:300]

print(_json.dumps(_info, default=str))
"""


def get_snapshot(kc) -> str:
    """
    Return a JSON string summarising the kernel namespace.
    Executes silently in the kernel (no side effects in output).

    Returns:
        JSON string: {name: type_description, ...}
    """
    output = collect(kc, kc.execute(_SNAPSHOT_CODE, silent=True), timeout=15)
    text   = output.stdout.strip()

    # Validate: should be JSON
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        return "{}"


def get_object_detail(kc, name: str) -> dict:
    """
    Return detailed type information about a specific object in the namespace.
    Used when the LLM needs to know the schema of a DataFrame, etc.
    """
    code   = _TYPE_DETAIL_CODE.format(name=name)
    output = collect(kc, kc.execute(code, silent=True), timeout=15)
    text   = output.stdout.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"name": name, "type": "unknown"}
