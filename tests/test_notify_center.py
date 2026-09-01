"""Notification center: grouping, calendar leads, channels."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from arelis.contacts import Contact, match_mail_sender
from arelis.notify.center import (
    NotificationCenter,
    calendar_lead_notices,
    load_channels,
    new_notice,
)
from arelis.notify.sources import due_task_notices


def test_clear_drops_sms_and_keeps_allow_and_a_running_job() -> None:
    """Clear is delete. Allow and a live job must still be on the glass."""
    center = NotificationCenter()
    center.add(new_notice(kind="sms", title="Robin", body="hi", group_key="sms:robin"))
    center.set_allow(True, "send email")
    running = center.upsert_job("image", elapsed_s=12)
    done = center.upsert_job("scrape", done=True)
    assert running is not None and done is not None
    center.clear_non_sticky()
    kinds = {n.kind for n in center.items}
    assert kinds == {"allow", "job"}
    assert center.find_group("job:image") is not None
    assert center.find_group("job:scrape") is None
    assert center.head() is not None
    assert center.head().kind in {"allow", "job"}


def test_clear_leaves_the_overlay_quiet() -> None:
    center = NotificationCenter()
    center.add(new_notice(kind="sms", title="Robin", body="hi", group_key="sms:robin"))
    assert center.head() is not None
    center.clear_non_sticky()
    assert center.head() is None
    assert center.unread_count() == 0


def test_same_sms_body_does_not_stack_twice() -> None:
    """Ticker plus the same body used to bump the count as a second text."""
    center = NotificationCenter({"ui": {"notifications": {"channels": {"sms": "visual"}}}})
    first = center.add(
        new_notice(kind="sms", title="Robin", body="hi", group_key="sms:robin")
    )
    second = center.add(
        new_notice(kind="sms", title="Robin", body="hi", group_key="sms:robin")
    )
    assert first is not None and second is not None
    assert first.id == second.id
    assert second.count == 1


def test_sms_groups_by_sender() -> None:
    center = NotificationCenter({"ui": {"notifications": {"channels": {"sms": "visual"}}}})
    a = center.add(
        new_notice(
            kind="sms",
            title="Robin",
            body="one",
            group_key="sms:wife",
            data={"alias": "wife"},
        )
    )
    b = center.add(
        new_notice(
            kind="sms",
            title="Robin",
            body="two",
            group_key="sms:wife",
            data={"alias": "wife"},
        )
    )
    assert a is not None and b is not None
    assert a.id == b.id
    assert center.unread_count() == 1
    assert b.count == 2
    assert "Robin · 2" in b.pill_label()


def test_channel_off_drops_notice() -> None:
    center = NotificationCenter({"ui": {"notifications": {"channels": {"sms": "off"}}}})
    got = center.add(new_notice(kind="sms", title="x", body="hi", group_key="sms:x"))
    assert got is None
    assert center.items == []


def test_load_channels_defaults() -> None:
    channels = load_channels({})
    assert channels["sms"] == "voice"
    assert channels["calendar"] == "visual"


def test_calendar_leads_fire_inside_window() -> None:
    now = datetime(2026, 8, 13, 12, 0, tzinfo=datetime.now().astimezone().tzinfo)
    start = now + timedelta(minutes=15)
    ev = SimpleNamespace(id="standup", summary="standup", starts_at=start, all_day=False)
    first = calendar_lead_notices([ev], now, leads_min=(15, 5, 0), already=set())
    assert len(first) == 1
    assert first[0].lead == "t15"
    already = {f"{first[0].data['event_id']}:{first[0].lead}"}
    again = calendar_lead_notices([ev], now, leads_min=(15, 5, 0), already=already)
    assert again == []
    too_early = calendar_lead_notices(
        [ev], now - timedelta(minutes=2), leads_min=(15, 5, 0), already=set()
    )
    assert too_early == []


def test_calendar_dismiss_quiets_later_leads() -> None:
    now = datetime(2026, 8, 13, 12, 0, tzinfo=datetime.now().astimezone().tzinfo)
    center = NotificationCenter()
    start = now + timedelta(minutes=15)
    ev = SimpleNamespace(id="e1", summary="standup", starts_at=start, all_day=False)
    added = center.apply_calendar([ev], now)
    assert len(added) == 1
    center.dismiss(added[0].id)
    later = now + timedelta(minutes=10)
    ev2 = SimpleNamespace(id="e1", summary="standup", starts_at=start, all_day=False)
    assert center.apply_calendar([ev2], later) == []


def test_snooze_hides_then_returns() -> None:
    center = NotificationCenter()
    notice = center.add(new_notice(kind="task", title="milk", body="due"))
    assert notice is not None
    until = datetime.now().astimezone() + timedelta(minutes=15)
    center.snooze(notice.id, until)
    assert center.head() is None
    assert center.unread_count() == 0
    assert center.head(now=until + timedelta(seconds=1)) is not None


def test_allow_stays_on_head_after_read() -> None:
    center = NotificationCenter()
    center.set_allow(True, "send email")
    head = center.head()
    assert head is not None
    center.mark_read(head.id)
    still = center.head()
    assert still is not None
    assert still.kind == "allow"
    center.set_allow(False)
    assert center.head() is None


def test_open_with_missing_file_raises() -> None:
    from pathlib import Path

    from arelis.local_open import open_local_file_as

    missing = Path("C:/this/path/does/not/exist-arelis-test.md")
    try:
        open_local_file_as(missing)
    except FileNotFoundError:
        return
    raise AssertionError("missing file must not open")


def test_done_research_job_keeps_the_artifact_path() -> None:
    center = NotificationCenter()
    live = center.upsert_job("research_report", elapsed_s=8)
    assert live is not None
    assert not live.data.get("path")
    done = center.upsert_job(
        "research_report",
        done=True,
        output="Research report written to C:/tmp/r.md",
        path="C:/tmp/r.md",
    )
    assert done is not None
    assert done.id == live.id
    assert done.data["path"] == "C:/tmp/r.md"
    assert "ready" in done.data["pill"]


def test_job_elapsed_pill() -> None:
    center = NotificationCenter()
    live = center.upsert_job("image", elapsed_s=42)
    assert live is not None
    assert live.data["pill"] == "image · 0:42"
    done = center.upsert_job("image", done=True)
    assert done is not None
    assert "ready" in done.data["pill"]


def test_due_tasks_once() -> None:
    seen: set[str] = set()

    def remember(task_id: str) -> bool:
        if task_id in seen:
            return False
        seen.add(task_id)
        return True

    today = datetime(2026, 8, 13).date()
    rows = [
        {"id": 1, "title": "milk", "due": "2026-08-13"},
        {"id": 2, "title": "later", "due": "2026-08-20"},
        {"id": 3, "title": "overdue", "due": "2026-08-10"},
    ]
    first = due_task_notices(rows, today=today, remember=remember)
    assert {n.title for n in first} == {"milk", "overdue"}
    again = due_task_notices(rows, today=today, remember=remember)
    assert again == []


def test_match_mail_sender_address_only() -> None:
    book = {
        "wife": Contact(
            alias="wife",
            name="Robin Hale",
            phone="+1555",
            digits="1555",
            email="robbie@example.com",
        )
    }
    hit = match_mail_sender("Robin Hale <robbie@example.com>", book)
    assert hit is not None
    assert hit.alias == "wife"
    miss = match_mail_sender("Robin Hale <stranger@example.com>", book)
    assert miss is None
    name_only = match_mail_sender("Robin Hale", book)
    assert name_only is None
