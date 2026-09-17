"""Find tests that cannot fail, or can only fail trivially.

Heuristics, not proof — every hit needs a human read. The point is the shape of
the distribution. A suite where this script prints a long list is decoration; a
suite where it prints a short one is a net.

What it cannot catch is the subtler form: a test that constructs the answer it
then checks. For the eval board, ``scripts/audit_eval_scenarios.py`` catches
that specific case. Everywhere else it takes reading.

    python scripts/audit_test_assertions.py
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "tests"

WEAK_CALLS = {"isinstance", "callable", "hasattr"}


def is_weak(node: ast.Assert) -> bool:
    """True for asserts that pass for almost any non-broken value."""
    test = node.test
    if isinstance(test, ast.Constant) and test.value is True:
        return True
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        comparator = test.comparators[0]
        if isinstance(test.ops[0], ast.IsNot) and isinstance(comparator, ast.Constant):
            if comparator.value is None:
                return True
    if isinstance(test, ast.Call) and isinstance(test.func, ast.Name):
        if test.func.id in WEAK_CALLS:
            return True
    # Bare truthiness: `assert thing` / `assert obj.attr`.
    return isinstance(test, (ast.Name, ast.Attribute))


def has_raises(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.With) and child.items:
            if "raises" in ast.dump(child.items[0].context_expr):
                return True
    return False


def checks_by_other_means(node: ast.AST) -> bool:
    """True when a test asserts without the `assert` keyword.

    Two shapes, both legitimate, both reported as no-assert by a plain scan —
    which is how an instrument teaches people to ignore it. Of the four
    no-assert hits on 2026-09-17, two were these:

      * `raise AssertionError("missing file must not open")` after a
        try/except that returns on the expected error.
      * delegation to a shared `_assert_routes_image_edit(ask)` helper, where
        the real assertions live one frame down.
    """
    for child in ast.walk(node):
        if isinstance(child, ast.Raise):
            exc = child.exc
            name = ""
            if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
                name = exc.func.id
            elif isinstance(exc, ast.Name):
                name = exc.id
            if name == "AssertionError":
                return True
        if isinstance(child, ast.Call):
            func = child.func
            called = ""
            if isinstance(func, ast.Name):
                called = func.id
            elif isinstance(func, ast.Attribute):
                called = func.attr
            if called.lstrip("_").startswith("assert"):
                return True
    return False


def main() -> int:
    no_assert: list[str] = []
    only_weak: list[str] = []
    counts: Counter[str] = Counter()
    total = 0

    for path in sorted(ROOT.rglob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            print(f"  !! could not parse {path.as_posix()}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            total += 1
            asserts = [n for n in ast.walk(node) if isinstance(n, ast.Assert)]
            where = f"{path.relative_to(ROOT.parent).as_posix()}:{node.lineno} {node.name}"
            if not asserts and not has_raises(node) and not checks_by_other_means(node):
                no_assert.append(where)
                counts["no_assert"] += 1
                continue
            if asserts and all(is_weak(a) for a in asserts):
                only_weak.append(where)
                counts["only_weak"] += 1
            segment = ast.get_source_segment(source, node) or ""
            if any(m in segment for m in ("monkeypatch.setattr", "MagicMock", "AsyncMock")):
                counts["uses_patch_or_mock"] += 1

    print(f"test functions scanned: {total}")
    print()
    for key, value in counts.most_common():
        print(f"  {key:24} {value:5}  ({100 * value / max(total, 1):.1f}%)")
    print()
    print(f"--- NO ASSERT, NO RAISES ({len(no_assert)}) ---")
    for where in no_assert:
        print("  " + where)
    print()
    print(f"--- ONLY WEAK ASSERTS ({len(only_weak)}) ---")
    for where in only_weak:
        print("  " + where)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
