"""Notification center: grouping, calendar leads, channels."""

from __future__ import annotations

from arelis.notify.center import (
    NoticeOpen,
    NotificationCenter,
    new_notice,
    notice_open,
)


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


def test_notice_open_routes_by_kind() -> None:
    sms = new_notice(kind="sms", title="Robin", body="hi")
    assert notice_open(sms) == NoticeOpen("chat", True)
    job = new_notice(
        kind="job",
        title="research_report",
        body="ready",
        data={"path": "C:/tmp/r.md", "done": True},
    )
    assert notice_open(job) == NoticeOpen("artifact", True)
    running = new_notice(
        kind="job",
        title="image",
        body="running",
        sticky=True,
        data={"done": False, "failed": False},
    )
    assert notice_open(running) == NoticeOpen("none", False)
    cal = new_notice(kind="calendar", title="standup", body="in 5")
    assert notice_open(cal) == NoticeOpen("calendar", True)
    task = new_notice(kind="task", title="milk", body="due")
    assert notice_open(task) == NoticeOpen("tasks", True)
    mail = new_notice(kind="email", title="Robin", body="hello")
    assert notice_open(mail) == NoticeOpen("email", True)
    allow = new_notice(kind="allow", title="Allow", body="send", sticky=True)
    assert notice_open(allow) == NoticeOpen("allow", False)


