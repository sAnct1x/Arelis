"""Private methods on Orchestrator have to be used by the package.

A method that nothing calls is leftover surface. This walks the class with
ast and fails when a private method's name never shows up again under
arelis/, as a name, an attribute, or an exact string.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = _ROOT / "arelis"
_ORCHESTRATOR = _PACKAGE / "core" / "orchestrator.py"


def _private_methods(source: str) -> list[str]:
    tree = ast.parse(source)
    names: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "Orchestrator":
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = item.name
            if name.startswith("_") and not (name.startswith("__") and name.endswith("__")):
                names.append(name)
        break
    return names


def _referenced_names() -> set[str]:
    """Names, attributes, and exact strings anywhere in the package.

    A function's own ``def`` is not one of these nodes, so a method that
    nothing else mentions is absent from the set.
    """
    found: set[str] = set()
    for path in sorted(_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                found.add(node.id)
            elif isinstance(node, ast.Attribute):
                found.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.add(node.value)
    return found


def test_orchestrator_private_methods_are_referenced() -> None:
    source = _ORCHESTRATOR.read_text(encoding="utf-8")
    methods = _private_methods(source)
    assert methods, "Orchestrator has no private methods to check"
    referenced = _referenced_names()
    unused = [name for name in methods if name not in referenced]
    assert not unused, (
        "private Orchestrator methods with no reference in the arelis package: " + ", ".join(unused)
    )
