"""who= fills contacts.yaml into non-secret fields."""

from __future__ import annotations

import asyncio

from arelis.browser.fill import contact_field_for, fill_from_who, is_address_into
from arelis.browser.session import BrowserSession
from arelis.contacts import Contact
from arelis.tools.browser_tool import BrowserTool

_MOM = Contact(
    alias="mom",
    name="Robin Hale",
    phone="5551112222",
    digits="5551112222",
    email="robin@example.com",
    work_phone="5559990000",
    aliases=("mom",),
)


def test_contact_field_aliases() -> None:
    assert contact_field_for("Email address") == "email"
    assert contact_field_for("work phone") == "work_phone"
    assert contact_field_for("mobile") == "phone"
    assert contact_field_for("your name") == "name"
    assert contact_field_for("search") == ""
    assert is_address_into("street address")
    assert not is_address_into("email")


def test_fill_from_who_slots() -> None:
    book = {"mom": _MOM}
    value, data = fill_from_who("Mom", into="email", contacts=book)
    assert value == "robin@example.com"
    assert data["field"] == "email"
    value, data = fill_from_who("mom", into="phone", contacts=book)
    assert value == "5551112222"
    value, data = fill_from_who("mom", into="name", contacts=book)
    assert value == "Robin Hale"
    value, data = fill_from_who("mom", into="work_phone", contacts=book)
    assert value == "5559990000"
    _, data = fill_from_who("mom", into="street", contacts=book)
    assert data.get("code") == "NO_ADDRESS"
    _, data = fill_from_who("nobody", into="email", contacts=book)
    assert data.get("code") == "NO_CONTACT"


def test_tool_type_who_email(monkeypatch) -> None:
    monkeypatch.setattr(
        "arelis.browser.fill.load_contacts", lambda: {"mom": _MOM}
    )
    monkeypatch.setattr(
        "arelis.browser.fill.resolve_contact",
        lambda who, contacts=None: _MOM if str(who).strip().lower() == "mom" else None,
    )
    session = BrowserSession.fake()
    tool = BrowserTool(session)

    async def _run() -> None:
        await tool.run(action="open", url="https://example.com")
        result = await tool.run(action="type", who="Mom", into="email")
        assert result.ok
        assert result.data.get("field") == "email"
        typed = session._driver.typed  # type: ignore[attr-defined]
        assert typed
        assert typed[-1][1] == "robin@example.com"

    asyncio.run(_run())


def test_tool_type_who_refuses_address(monkeypatch) -> None:
    monkeypatch.setattr(
        "arelis.browser.fill.load_contacts", lambda: {"mom": _MOM}
    )
    session = BrowserSession.fake()
    tool = BrowserTool(session)

    async def _run() -> None:
        await tool.run(action="open", url="https://example.com")
        result = await tool.run(action="type", who="Mom", into="street address")
        assert not result.ok
        assert result.data.get("code") == "NO_ADDRESS"
        assert not session._driver.typed  # type: ignore[attr-defined]

    asyncio.run(_run())
