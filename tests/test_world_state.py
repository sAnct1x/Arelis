"""World-state prompt line: clock, place, role, readiness snippets."""

from __future__ import annotations

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
    assert "mail not configured" in line
    assert "SMS companion not configured" in line
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
    assert "calendar Google not authorized" in line


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


def test_world_state_no_competitor_names() -> None:
    line = world_state_prompt_line({}, role="fast", model="qwen2.5:7b")
    lowered = line.lower()
    for name in ("claude", "chatgpt", "openai", "odysseus", "gemini"):
        assert name not in lowered
