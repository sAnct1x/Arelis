"""Held inbound SMS: one batched system line when the floor is free."""

from __future__ import annotations

from arelis.sms_inbound import (
    InboundSms,
    format_held_inbound_flush,
)
from arelis.ui.sms_host import on_sms_received


def _msg(
    mid: str,
    *,
    sender: str = "5551112222",
    body: str = "hey",
    name: str = "Robin",
    alias: str = "wife",
) -> InboundSms:
    return InboundSms(
        id=mid,
        sender=sender,
        body=body,
        time="2026-09-18T01:00:00Z",
        contact_alias=alias,
        contact_name=name,
    )


def _payload(msg: InboundSms) -> dict:
    return {
        "id": msg.id,
        "from": msg.sender,
        "body": msg.body,
        "time": msg.time,
        "contact_alias": msg.contact_alias,
        "contact_name": msg.contact_name,
    }


def test_empty_hold_formats_to_nothing() -> None:
    assert format_held_inbound_flush([]) == ""
    assert format_held_inbound_flush([None]) == ""  # type: ignore[list-item]


def test_two_senders_are_named() -> None:
    """Mutant: two senders not named — both names have to be in the batch."""
    held = [
        _msg("m1", body="pump", name="Robin", alias="wife"),
        _msg(
            "m2",
            sender="5553334444",
            body="hello",
            name="Alex",
            alias="coach",
        ),
    ]
    text = format_held_inbound_flush(held)
    assert "Robin" in text
    assert "Alex" in text
    assert text.startswith("2 texts from Robin and Alex:")
    assert "- Robin: pump" in text
    assert "- Alex: hello" in text


def test_held_pair_flushes_one_batched_line(arelis_window, monkeypatch) -> None:
    win = arelis_window()
    said: list[str] = []
    monkeypatch.setattr(win.chat, "add_system", said.append)
    win._set_busy(True)
    first = _msg("m1", body="one")
    second = _msg("m2", body="two")
    on_sms_received(win, _payload(first))
    on_sms_received(win, _payload(second))
    assert [m.id for m in win._held_inbound] == ["m1", "m2"]
    assert said == []
    win._set_busy(False)
    assert win._held_inbound == []
    assert said == [format_held_inbound_flush([first, second])]


