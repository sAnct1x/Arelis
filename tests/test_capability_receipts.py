"""Capability classes + action receipts (Wave 3 + trustworthy)."""

from __future__ import annotations

import json
from pathlib import Path

from arelis.core.receipts import (
    action_receipt,
    append_action_ledger,
    format_action_receipt,
)
from arelis.tools.base import capability_class


def test_capability_classes() -> None:
    assert capability_class("web_search") == "READ"
    assert capability_class("calculator") == "READ"
    assert capability_class("cas") == "READ"
    assert capability_class("units") == "READ"
    assert capability_class("plot") == "WRITE_LOCAL"
    assert capability_class("workspace", {"action": "read"}) == "READ"
    assert capability_class("workspace", {"action": "write"}) == "WRITE_LOCAL"
    assert capability_class("tasks", {"action": "add"}) == "WRITE_LOCAL"
    assert capability_class("send_email") == "WRITE_EXTERNAL"
    assert capability_class("send_sms") == "WRITE_EXTERNAL"
    assert capability_class("agenda", {"action": "create"}) == "WRITE_EXTERNAL"
    assert capability_class("agenda", {"action": "list"}) == "READ"
    assert capability_class("image") == "SIDE_EFFECT_LOCAL"
    assert capability_class("browser") == "SIDE_EFFECT_LOCAL"
    assert capability_class("memory", {"action": "prefer"}) == "WRITE_LOCAL"
    assert capability_class("research_report") == "WRITE_LOCAL_ARTIFACT"


def test_receipt_send_email() -> None:
    r = action_receipt(
        "send_email",
        ok=True,
        args={"to": "a@b.com", "subject": "Hi", "body": "x"},
        data={"message_id": "m1"},
    )
    assert r is not None
    assert r["action"] == "send_email"
    assert "message_id=m1" in r["ids"]
    assert "receipt" in format_action_receipt(r)


def test_receipt_skips_list_and_failures() -> None:
    assert action_receipt("agenda", ok=True, args={"action": "list"}) is None
    assert action_receipt("send_sms", ok=False, args={"to": "1", "body": "x"}) is None
    r = action_receipt(
        "tasks",
        ok=True,
        args={"action": "add", "title": "Buy milk"},
        data={"id": 3},
    )
    assert r is not None
    assert r["action"] == "tasks.add"


def test_receipt_browser_and_research_report() -> None:
    br = action_receipt(
        "browser",
        ok=True,
        args={"action": "open", "url": "youtube"},
        data={"url": "https://www.youtube.com", "mode": "attach"},
    )
    assert br is not None
    assert br["action"] == "browser.open"
    assert br["url"].startswith("https://")
    assert action_receipt("browser", ok=True, args={"action": "snapshot"}) is None
    shot = action_receipt(
        "browser",
        ok=True,
        args={"action": "screenshot"},
        data={"path": "outputs/images/browser_stub.png"},
    )
    assert shot is not None
    assert shot["action"] == "browser.screenshot"
    assert any("browser_stub" in str(x) for x in shot.get("ids") or [])

    rr = action_receipt(
        "research_report",
        ok=True,
        args={"query": "q"},
        data={"path": "outputs/research/x.md", "ok_count": 2},
    )
    assert rr is not None
    assert rr["action"] == "research_report"
    assert rr["path"].endswith(".md")


def test_receipt_schedule_create_includes_job_id() -> None:
    r = action_receipt(
        "schedule",
        ok=True,
        args={"action": "create_briefing", "name": "Daily Weather Summary", "time": "7am"},
        data={"id": "daily-weather-summary", "name": "Daily Weather Summary"},
    )
    assert r is not None
    assert r["action"] == "schedule.create_briefing"
    assert "id=daily-weather-summary" in r["ids"]
    line = format_action_receipt(r)
    assert "daily-weather-summary" in line
    assert action_receipt("schedule", ok=True, args={"action": "list"}) is None


def test_append_action_ledger(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    r = action_receipt(
        "workspace",
        ok=True,
        args={"action": "write", "path": "notes.txt"},
        data={"path": "notes.txt"},
    )
    assert r is not None
    append_action_ledger(r, path=path, session_id="s1")
    append_action_ledger(r, path=path, session_id="s1")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    row = json.loads(lines[0])
    assert row["session_id"] == "s1"
    assert row["action"] == "workspace.write"
    assert "ts" in row
