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


def test_matrix_path_checks_stay_inside_work_folder(items_mod):
    for item in [*items_mod.ITEMS, *items_mod.COMMS_ITEMS]:
        for rel in (*item.keep, *item.gone):
            assert rel.startswith("work/") and ".." not in rel, f"{item.id}: {rel}"


def test_matrix_gone_and_keep_targets_are_fixtures_or_created(items_mod):
    """scratch_* files are recreated by make_fixtures; the others are made by the item."""
    import re

    text = (_ROOT / "scripts" / "live_matrix.py").read_text(encoding="utf-8")
    for item in items_mod.ITEMS:
        for rel in item.gone:
            name = rel.rsplit("/", 1)[-1]
            assert name in text or any(name in p for p in item.prompts), f"{item.id}: {rel}"
        assert not re.search(r"[^\x00-\x7f]", " ".join(item.prompts)), item.id


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


def test_comms_items_are_inert_and_carry_no_personal_data(items_mod):
    """The runner only imports ITEMS and keeps the send tools BANNED, so the
    comms plan cannot send anything; and no address or number is in the repo."""
    import re

    runner = (_ROOT / "scripts" / "live_matrix.py").read_text(encoding="utf-8")
    assert "COMMS_ITEMS" not in runner
    assert {"send_sms", "send_email"} <= items_mod.BANNED
    blob = " ".join(p for i in items_mod.COMMS_ITEMS for p in i.prompts)
    assert not re.search(r"\+?\d[\d\s().-]{8,}\d", blob)
    assert "@gmail.com" not in blob and "@example.invalid" in blob
