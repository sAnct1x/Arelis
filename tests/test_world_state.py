"""World-state prompt line: clock, place, role, readiness snippets."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from arelis.core.world_state import world_state_prompt_line
from arelis.memory import MemoryStore


def test_world_state_sms_and_pending_confirms(monkeypatch) -> None:
    monkeypatch.setattr(
        "arelis.calendar.secrets.load_calendar_secrets",
        lambda: SimpleNamespace(google=None, outlook=None),
    )
    monkeypatch.setattr("arelis.mail.load_account", lambda: None)
    monkeypatch.setattr(
        "arelis.sms_android.load_sms_account",
        lambda: SimpleNamespace(username="phone"),
    )
    monkeypatch.setattr(
        "arelis.presence.pending_confirms.PendingConfirmStore.list",
        lambda self: [SimpleNamespace(id="a"), SimpleNamespace(id="b")],
    )
    line = world_state_prompt_line({}, role="fast", model="m")
    assert "SMS companion configured" in line
    assert "pending confirms 2" in line


def _attention_config(**attention) -> dict:
    base = {"enabled": True}
    base.update(attention)
    return {"tools": {"briefing": {"attention": base}}}


def test_attention_applies_configured_inbox_rules(tmp_path: Path, monkeypatch) -> None:
    """Editing inbox_rules used to change the 7am email and nothing she says."""
    import arelis.notify.sources as sources

    monkeypatch.setattr(sources, "load_today_events", lambda config=None: [])
    monkeypatch.setattr(
        sources,
        "cached_unread_mail",
        lambda **_kw: [
            {"id": "1", "from": "billing@utility.example", "subject": "Your bill"}
        ],
    )
    store = MemoryStore(tmp_path / "memory.db")
    try:
        rule = _attention_config(
            inbox_rules=[{"id": "bills", "sender_contains": "billing@"}]
        )
        assert "attention 1" in world_state_prompt_line(
            rule, role="fast", model="m", store=store
        )
        # Same mail, no rule about it: nothing needs attention.
        assert "attention" not in world_state_prompt_line(
            _attention_config(), role="fast", model="m", store=store
        )
    finally:
        store.close()


def test_attention_reads_the_calendar_cache(tmp_path: Path, monkeypatch) -> None:
    from datetime import timedelta

    import arelis.notify.sources as sources

    soon = datetime.now().astimezone() + timedelta(minutes=30)
    monkeypatch.setattr(
        sources,
        "load_today_events",
        lambda config=None: [
            SimpleNamespace(starts_at=soon, summary="Dentist", all_day=False)
        ],
    )
    monkeypatch.setattr(sources, "cached_unread_mail", lambda **_kw: [])
    store = MemoryStore(tmp_path / "memory.db")
    try:
        line = world_state_prompt_line(
            _attention_config(), role="fast", model="m", store=store
        )
        assert "attention 1" in line
    finally:
        store.close()


