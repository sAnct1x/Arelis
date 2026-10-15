from __future__ import annotations

import pytest

from arelis.contacts import add_contact, load_contacts, resolve_contact
from arelis.tools.base import CONTACTS_WRITE_ACTIONS, ToolRegistry
from arelis.tools.contacts_tool import ContactsTool


def _tool(tmp_path) -> ContactsTool:
    return ContactsTool(path=tmp_path / "contacts.yaml")


@pytest.mark.asyncio
async def test_add_update_get_remove_round_trip(tmp_path) -> None:
    tool = _tool(tmp_path)
    added = await tool.run(
        action="add",
        id="dave",
        name="Dave Coach",
        phone="5551112222",
        aliases="coach, david",
    )
    assert added.ok
    book = load_contacts(tmp_path / "contacts.yaml")
    assert "dave" in book
    assert resolve_contact("coach", book) is book["dave"]

    updated = await tool.run(
        action="update",
        who="coach",
        phone="5559998888",
        aliases="davey",
    )
    assert updated.ok
    book = load_contacts(tmp_path / "contacts.yaml")
    assert book["dave"].digits == "5559998888"
    assert "davey" in book["dave"].aliases
    assert "coach" in book["dave"].aliases

    got = await tool.run(action="get", who="davey")
    assert got.ok
    assert "5559998888" in got.output
    by_name = await tool.run(action="get", name="dave")
    assert by_name.ok
    assert "5559998888" in by_name.output
    assert "carrier" not in got.output.lower()

    removed = await tool.run(action="remove", who="dave")
    assert removed.ok
    assert load_contacts(tmp_path / "contacts.yaml") == {}


@pytest.mark.asyncio
async def test_add_refuses_duplicate_nickname(tmp_path) -> None:
    path = tmp_path / "contacts.yaml"
    add_contact(
        key="wife",
        name="Robbie",
        phone="5551112222",
        aliases="robbie",
        path=path,
    )
    tool = ContactsTool(path=path)
    result = await tool.run(
        action="add",
        id="friend",
        phone="5553334444",
        aliases="robbie",
    )
    assert not result.ok
    assert "robbie" in result.output.lower()


def test_write_actions_need_confirm_list_does_not() -> None:
    registry = ToolRegistry()
    registry.register(ContactsTool())
    assert not registry.needs_confirm("contacts", {"action": "list"})
    assert not registry.needs_confirm("contacts", {"action": "get", "who": "me"})
    for action in CONTACTS_WRITE_ACTIONS:
        assert registry.needs_confirm("contacts", {"action": action, "id": "x"})
    assert not registry.needs_confirm(
        "contacts", {"action": "add"}, confirm_writes=False
    )


