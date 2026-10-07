"""The live test matrix must not drift from the production tool registry.

scripts/live_matrix_items.py defines the items the live matrix runner scores
(single tool, regression, slash command and chained prompts). The runner needs
a local model, so it is not part of CI, but its definitions are plain data and
can be checked cheaply: ids must be unique, and every tool an item expects (or
bans) must still be a real tool. A renamed or removed tool then fails here,
instead of surfacing as a mystery failure in the next live run.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from arelis.tools import build_tool_registry
from arelis.workspace import WorkspaceRoots

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = str(_ROOT / "scripts")


@pytest.fixture(scope="module")
def items_mod():
    sys.path.insert(0, _SCRIPTS)
    try:
        import live_matrix_items

        yield live_matrix_items
    finally:
        sys.path.remove(_SCRIPTS)
        sys.modules.pop("live_matrix_items", None)


def _declared_tool_names() -> set[str]:
    """Every `name = "..."` a tool class declares under arelis/tools.

    Some tools only register when a phone, a mail account or a vision model is
    configured, so a bare registry cannot be asked about them. The class
    declarations are what the registry registers once they are configured.
    """
    names: set[str] = set()
    for path in (_ROOT / "arelis" / "tools").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and stmt.targets[0].id == "name"
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    names.add(stmt.value.value)
    return names


@pytest.fixture(scope="module")
def known_tools(tmp_path_factory) -> set[str]:
    root = tmp_path_factory.mktemp("matrix-ws")
    config = {
        "tools": {},
        "agent": {},
        "workspace": {"roots": [{"name": "w", "path": str(root), "read_only": False}]},
    }
    workspace = WorkspaceRoots.from_config(config)
    live = set(build_tool_registry(config, workspace, allow_send=True, attended=True).names())
    assert {"calculator", "units", "workspace", "document"} <= live
    return live | _declared_tool_names()


def test_matrix_item_ids_are_unique(items_mod):
    ids = [item.id for item in items_mod.ITEMS]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate live matrix item ids: {dupes}"


def test_matrix_items_are_well_formed(items_mod):
    for item in items_mod.ITEMS:
        assert item.kind in {"single", "regress", "slash", "chain"}, item.id
        assert item.prompts and all(isinstance(p, str) and p for p in item.prompts), item.id
        assert all(isinstance(group, tuple) and group for group in item.tools), item.id


def test_matrix_expected_tools_exist_in_production_registry(items_mod, known_tools):
    missing: dict[str, list[str]] = {}
    for item in items_mod.ITEMS:
        names = {name for group in item.tools for name in group}
        gone = sorted(names - known_tools)
        if gone:
            missing[item.id] = gone
    assert not missing, (
        "live matrix items expect tools the production registry no longer has "
        f"(update scripts/live_matrix_items.py): {missing}"
    )


def test_matrix_banned_tools_are_real_tool_names(items_mod, known_tools):
    unknown = sorted(items_mod.BANNED - known_tools)
    assert not unknown, f"BANNED names no tool in the registry any more: {unknown}"
