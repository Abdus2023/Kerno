# kerno/skills/builtins/meta.py
"""
Built-in meta-skills for self-extension and skill discovery.
"""

_META_SKILLS_CODE = r'''
import inspect as _inspect
import types as _types

from IPython.display import display as _display, Markdown as _MD


def register_skill(name: str, code: str, description: str = "") -> bool:
    """
    Dynamically define a new callable and expose it in the kernel namespace.

    The code must define a function named ``name``. It is executed with globals()
    so the function remains available to later cells.
    """
    try:
        before = set(globals())
        exec(code, globals())
        after = set(globals())
        new_names = after - before
        if name not in globals() or not callable(globals()[name]):
            print(f"⚠️ Code executed, but '{name}' was not defined as a callable.")
            return False
        fn = globals()[name]
        if description and not getattr(fn, "__doc__", None):
            fn.__doc__ = description
        try:
            sig = _inspect.signature(fn)
        except (ValueError, TypeError):
            sig = "(...)"
        _display(_MD(f"### ✅ Skill registered: `{name}{sig}`"))
        if description:
            print(description[:160])
        print(f"New names introduced: {sorted(new_names)}")
        return True
    except Exception as exc:
        print(f"❌ Failed to register skill '{name}': {exc}")
        return False


def inspect_skill(skill_name: str) -> dict:
    """
    Inspect a registered skill's signature, docstring, and source (if available).
    """
    obj = globals().get(skill_name)
    if obj is None:
        print(f"Skill '{skill_name}' not found.")
        return {}
    try:
        signature = str(_inspect.signature(obj))
    except (ValueError, TypeError):
        signature = "(...)"
    info = {
        "name": skill_name,
        "signature": signature,
        "docstring": _inspect.getdoc(obj) or "",
    }
    try:
        info["source"] = _inspect.getsource(obj)
    except Exception:
        info["source"] = "Source unavailable."
    print(f"{skill_name}{signature}")
    print(info["docstring"][:300])
    return info


def list_session_skills() -> dict:
    """
    List user-defined functions currently present in the session namespace.
    """
    skills = {}
    for name, obj in globals().items():
        if name.startswith("_"):
            continue
        if isinstance(obj, _types.FunctionType) and obj.__module__ in (None, "__main__"):
            skills[name] = (obj.__doc__ or "No docstring")[:120]
    if not skills:
        print("No custom session skills defined yet.")
    else:
        for name, doc in skills.items():
            print(f"- {name}: {doc}")
    return skills


def search_skills(query: str) -> list:
    """
    Search available callables by name/docstring keyword and print signatures.
    """
    query_terms = set(query.lower().split())
    matches = []
    for name, obj in list(globals().items()):
        if name.startswith("_") or not callable(obj) or isinstance(obj, type):
            continue
        doc = (getattr(obj, "__doc__", "") or "").lower()
        haystack = f"{name.lower()} {doc}"
        score = sum(1 for term in query_terms if term in haystack)
        if score == 0 and any(term in haystack for term in query_terms):
            score = 1
        if score:
            try:
                sig = str(_inspect.signature(obj))
            except (ValueError, TypeError):
                sig = "()"
            matches.append({
                "name": name,
                "signature": f"{name}{sig}",
                "doc": doc.strip().split("\n")[0][:160],
                "score": score,
            })
    matches.sort(key=lambda m: m["score"], reverse=True)
    if not matches:
        print(f"No skills found for '{query}'.")
        return []
    print(f"Found {len(matches)} skill(s) for '{query}':")
    for match in matches[:10]:
        print(f"  • {match['signature']}")
        if match["doc"]:
            print(f"    {match['doc']}")
    return [m["name"] for m in matches]
'''


def get_code() -> str:
    return _META_SKILLS_CODE
