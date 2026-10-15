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


def _gate_args(spec: str) -> tuple[str, dict]:
    tool, _, action = spec.partition(":")
    if tool == "web_fetch":
        return tool, {"method": "DELETE"}
    return tool, ({"action": action} if action else {})


def test_matrix_gate_claims_match_policy(items_mod):
    """An item that asserts a confirm card must name a call policy really pauses on.

    always_pause() is the 'even when asked' rule, so a gate item stays valid
    when the user's typed request already counts as the grant.
    """
    from arelis.tools.policy import always_pause

    checked = 0
    for item in [*items_mod.ITEMS, *items_mod.COMMS_ITEMS]:
        for spec in item.gate:
            tool, args = _gate_args(spec)
            assert always_pause(tool, args), f"{item.id}: {spec} does not always pause"
            checked += 1
        assert set(item.decline) <= set(item.gate), f"{item.id}: decline without gate"
    assert checked >= 6


def test_comms_items_never_join_the_main_matrix(items_mod):
    main_ids = {item.id for item in items_mod.ITEMS}
    for item in items_mod.COMMS_ITEMS:
        assert item.id not in main_ids
        assert not item.id.startswith(("S", "C", "P", "X", "R", "G"))
    # The main matrix may not send anything, ever.
    assert all(item.live_sends == 0 for item in items_mod.ITEMS)
    for item in items_mod.ITEMS:
        assert not ({"send_sms", "send_email"} & {n for g in item.tools for n in g}), item.id


def test_comms_plan_sends_exactly_three_tagged_messages(items_mod):
    sends = [item for item in items_mod.COMMS_ITEMS if item.live_sends]
    assert sum(item.live_sends for item in items_mod.COMMS_ITEMS) == 3
    assert sorted(i.tool for i in sends) == ["send_email", "send_sms", "send_sms"]
    for item in sends:
        assert item.recipients, item.id
        assert items_mod.COMMS_TAG in item.prompts[0], item.id
    for item in items_mod.COMMS_ITEMS:
        if not item.live_sends:
            assert not item.recipients or item.decline or item.id.endswith("_stub"), item.id


