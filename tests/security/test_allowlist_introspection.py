"""Regression tests for Python object-introspection escape paths."""

import pytest

from kerno.security.allowlist import AllowList, AllowListViolation


@pytest.mark.parametrize(
    "code",
    [
        "().__class__.__base__.__subclasses__()",
        "(lambda: 0).__globals__",
        "(lambda: 0).__closure__",
        "(lambda: 0).__code__",
        "getattr(object, '__subclasses__')()",
        "hasattr(object, '__class__')",
        "x = globals()['__builtins__']",
        "x = {'__import__': 1}['__import__']",
        "x = 'importer'; getattr(object, x)",
    ],
)
def test_object_introspection_escape_is_blocked(code):
    with pytest.raises(AllowListViolation):
        AllowList.data_analysis().check(code)


def test_normal_attribute_access_remains_allowed():
    al = AllowList.data_analysis()
    al.check("value = df.shape")
    al.check("value = obj.name")
