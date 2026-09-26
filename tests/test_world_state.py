"""World-state prompt line: clock, place, role, readiness snippets."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from arelis.core.world_state import world_state_prompt_line
from arelis.location import UserLocation
from arelis.memory import MemoryStore
from arelis.workspace import WorkspaceRoots


def test_world_state_includes_clock_role_and_model() -> None:
    line = world_state_prompt_line({}, role="research", model="qwen2.5:14b")
    assert line.startswith("World state:")
    assert "role research (qwen2.5:14b)" in line
    assert "2026" in line or "August" in line or ":" in line


def test_world_state_includes_place_from_location() -> None:
    loc = UserLocation(city="Raleigh", region="NC", country="US")
    line = world_state_prompt_line(
        {"_location": loc},
        role="fast",
        model="qwen2.5:7b",
    )
    assert "place Raleigh, NC, US" in line


def test_world_state_counts_open_tasks(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.add_task("Buy solder")
    store.add_task("Calibrate mount")
    done_id = store.add_task("Already done")
    assert done_id is not None
    store.set_task_status(done_id, "done")
    line = world_state_prompt_line(
        {},
        role="default",
        model="m",
        store=store,
    )
    assert "open tasks 2" in line
    store.close()


def test_world_state_calendar_and_mail_fail_soft(monkeypatch) -> None:
    monkeypatch.setattr(
        "arelis.calendar.secrets.load_calendar_secrets",
        lambda: SimpleNamespace(
            google=SimpleNamespace(authorized=True),
            outlook=None,
        ),
    )
    monkeypatch.setattr("arelis.mail.load_account", lambda: None)
    monkeypatch.setattr("arelis.sms_android.load_sms_account", lambda: None)
    monkeypatch.setattr(
        "arelis.presence.pending_confirms.PendingConfirmStore.list",
        lambda self: [],
    )
    line = world_state_prompt_line({}, role="fast", model="m")
    assert "calendar Google authorized" in line
    assert "mail not configured" not in line
    assert "SMS companion not configured" not in line
    assert "pending confirms" not in line


def test_world_state_mail_configured(monkeypatch) -> None:
    monkeypatch.setattr(
        "arelis.calendar.secrets.load_calendar_secrets",
        lambda: SimpleNamespace(google=None, outlook=None),
    )
    monkeypatch.setattr(
        "arelis.mail.load_account",
        lambda: SimpleNamespace(address="me@example.com"),
    )
    monkeypatch.setattr("arelis.sms_android.load_sms_account", lambda: None)
    line = world_state_prompt_line({}, role="fast", model="m")
    assert "mail configured" in line
    assert "calendar Google" not in line


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


def test_world_state_does_not_inject_active_project(tmp_path: Path) -> None:
    """Project name is turn-gated in the agent loop, not on every chat turn."""
    from arelis.workspace import RootEntry

    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    workspace = WorkspaceRoots(
        [
            RootEntry(name="alpha", path=a.resolve()),
            RootEntry(name="beta", path=b.resolve()),
        ],
        active="alpha",
    )
    line = world_state_prompt_line(
        {},
        role="fast",
        model="qwen2.5:7b",
        workspace=workspace,
    )
    assert "Active project" not in line


def test_world_state_store_without_list_tasks_is_fine() -> None:
    line = world_state_prompt_line(
        {},
        role="fast",
        model="m",
        store=SimpleNamespace(),
    )
    assert "open tasks" not in line
    assert line.startswith("World state:")


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


def test_attention_survives_an_unreadable_calendar(tmp_path: Path, monkeypatch) -> None:
    import arelis.notify.sources as sources

    def _boom(config=None):
        raise RuntimeError("cache locked")

    monkeypatch.setattr(sources, "load_today_events", _boom)
    monkeypatch.setattr(sources, "cached_unread_mail", lambda **_kw: [])
    store = MemoryStore(tmp_path / "memory.db")
    try:
        line = world_state_prompt_line(
            _attention_config(), role="fast", model="m", store=store
        )
        assert line.startswith("World state:")
    finally:
        store.close()


def test_world_state_flags_image_generation_only_when_it_cannot_run() -> None:
    """So she offers "once ComfyUI is running" instead of trying and failing."""
    assert "ComfyUI" in world_state_prompt_line(
        {"_image_ready": False}, role="fast", model="m"
    )
    assert "ComfyUI" not in world_state_prompt_line(
        {"_image_ready": True}, role="fast", model="m"
    )
    # Nobody has probed (CLI, jobs): silence, not a claim either way.
    assert "ComfyUI" not in world_state_prompt_line({}, role="fast", model="m")


def test_world_state_no_competitor_names() -> None:
    line = world_state_prompt_line({}, role="fast", model="qwen2.5:7b")
    lowered = line.lower()
    for name in ("claude", "chatgpt", "openai", "odysseus", "gemini"):
        assert name not in lowered
