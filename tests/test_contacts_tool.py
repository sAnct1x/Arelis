from __future__ import annotations

import pytest

from arelis.contacts import add_contact, load_contacts, resolve_contact
from arelis.mail import MailAccount
from arelis.tools.base import CONTACTS_WRITE_ACTIONS, ToolRegistry
from arelis.tools.contacts_tool import ContactsTool


def _tool(tmp_path) -> ContactsTool:
    return ContactsTool(path=tmp_path / "contacts.yaml")


@pytest.mark.asyncio
async def test_list_empty(tmp_path) -> None:
    result = await _tool(tmp_path).run(action="list")
    assert result.ok
    assert "No contacts" in result.output


@pytest.mark.asyncio
async def test_add_requires_phone_not_carrier(tmp_path) -> None:
    tool = _tool(tmp_path)
    missing_phone = await tool.run(action="add", id="dave")
    assert not missing_phone.ok
    assert "phone" in missing_phone.output.lower()

    # Phone alone is enough; carrier is no longer part of the product.
    added = await tool.run(action="add", id="dave", phone="5551112222")
    assert added.ok
    book = load_contacts(tmp_path / "contacts.yaml")
    assert book["dave"].digits == "5551112222"


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


def test_describe_call_shows_contact_fields() -> None:
    registry = ToolRegistry()
    registry.register(ContactsTool())
    detail = registry.describe_call(
        "contacts",
        {
            "action": "add",
            "id": "dave",
            "name": "Dave",
            "phone": "5551112222",
            "aliases": "coach",
        },
    )
    assert "dave" in detail
    assert "5551112222" in detail
    assert "coach" in detail
    assert "Carrier" not in detail
    assert "SMS email" not in detail


def test_spoken_contact_reply_is_one_line() -> None:
    from arelis.contacts import format_contact_spoken

    data = {
        "id": "wife",
        "name": "Robin Hale",
        "phone": "5555550123",
        "email": "",
    }
    who = format_contact_spoken(data, field="who")
    assert "Robin Hale" in who
    assert "5555550123" in who
    assert "Do not report" not in who
    assert "also:" not in who
    phone = format_contact_spoken(data, field="phone")
    assert phone == "Robin Hale's SMS phone is 5555550123."
    assert "also:" not in phone


def test_job_runner_has_no_contacts_tool(tmp_path, monkeypatch) -> None:
    from arelis import tools as tools_pkg
    from arelis.workspace import WorkspaceRoots

    monkeypatch.setattr(
        tools_pkg, "load_account", lambda: MailAccount("me@example.com", "pw")
    )
    monkeypatch.setattr(tools_pkg, "load_sms_account", lambda: None)
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    attended = tools_pkg.build_tool_registry({"tools": {}, "agent": {}}, workspace)
    assert "contacts" in attended.names()
    unattended = tools_pkg.build_tool_registry(
        {"tools": {}, "agent": {}}, workspace, allow_send=False
    )
    assert "contacts" not in unattended.names()


def test_upsert_draft_stays_off_the_sms_book(tmp_path) -> None:
    from arelis.contacts import load_all_contacts, upsert_contact_record

    path = tmp_path / "contacts.yaml"
    result = upsert_contact_record(
        name="Alex Carter",
        title="Coach",
        path=path,
    )
    assert not isinstance(result, str)
    assert result.alias == "coach"
    assert load_contacts(path) == {}
    book = load_all_contacts(path)
    assert book["coach"].name == "Alex Carter"
    assert resolve_contact("coach", book) is book["coach"]


def test_upsert_mobile_makes_contact_addressable(tmp_path) -> None:
    from arelis.contacts import upsert_contact_record

    path = tmp_path / "contacts.yaml"
    result = upsert_contact_record(
        name="Alex Carter",
        title="Coach",
        phone="5551112222",
        email="you@example.com",
        path=path,
    )
    assert not isinstance(result, str)
    book = load_contacts(path)
    assert book["coach"].digits == "5551112222"
    assert book["coach"].title == "Coach"
    assert resolve_contact("coach", book) is book["coach"]


def test_tool_add_keeps_title_and_work_phone(tmp_path) -> None:
    path = tmp_path / "contacts.yaml"
    result = add_contact(
        key="coach",
        name="Alex Carter",
        title="Coach",
        phone="5551112222",
        work_phone="5559990000",
        path=path,
    )
    assert not isinstance(result, str)
    contact = load_contacts(path)["coach"]
    assert contact.title == "Coach"
    assert contact.work_phone == "5559990000"
