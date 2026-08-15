"""Tests for SkillRegistry code-string registration behavior."""

from kerno.skills.registry import SkillRegistry


class DummyKernel:
    """Minimal kernel stand-in that executes code in a real dict namespace."""

    def __init__(self):
        self.ns = {}
        self.protection_installed = False

    def execute(self, code, silent=False, timeout=None):
        class _Out:
            has_error = False
            error = None
        exec(code, self.ns)
        return _Out()

    def execute_silent(self, code, timeout=None):
        before = len(self.ns.get("__out__", []))
        self.ns.setdefault("__out__", []).append("")
        buf = []
        def fake_print(*args):
            buf.append(" ".join(map(str, args)))
        old_print = self.ns.get("print")
        self.ns["print"] = fake_print
        try:
            exec(code, self.ns)
        finally:
            self.ns["print"] = old_print
        return buf[-1] if buf else ""

    def inspect(self, name):
        import inspect
        obj = self.ns.get(name)
        if obj is None:
            return {}
        try:
            sig = str(inspect.signature(obj))
        except (TypeError, ValueError):
            sig = ""
        return {
            "signature": sig,
            "doc": inspect.getdoc(obj) or "",
        }


def test_load_code_records_module_and_public_callables():
    kernel = DummyKernel()
    registry = SkillRegistry()
    code = '''
def alpha(x: int) -> int:
    """Double x."""
    return x * 2

def beta():
    """No-op."""
    return None
'''
    names = registry.load_code(kernel, code, "example_skills", protect=True)
    assert set(names) == {"alpha", "beta"}
    assert "example_skills" in registry.names()
    assert "alpha" in registry.names()
    assert "beta" in registry.names()

    records = {r.name: r for r in registry._records.values()}
    assert "x: int" in records["alpha"].signature
    assert "Double x." in records["alpha"].docstring
    assert "example_skills" in records["alpha"].source_file


def test_manifest_contains_individual_skills():
    kernel = DummyKernel()
    registry = SkillRegistry()
    registry.load_code(kernel, "def gamma():\n    'Gamma skill.'\n", "gamma_module")
    manifest = registry.manifest(style="full")
    assert "gamma" in manifest
    assert "Gamma skill." in manifest
