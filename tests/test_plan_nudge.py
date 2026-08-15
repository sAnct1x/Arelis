"""Deterministic plan nudges + fail-tag replan notices."""

from __future__ import annotations

from arelis.core.fail_tags import tool_fail_replan_notice
from arelis.core.plan_nudge import (
    plan_progress_notice,
    plan_system_message,
    select_plan,
)
from arelis.core.preflight import plan_system_message as preflight_export


def test_research_plan_from_text() -> None:
    msg = plan_system_message("Please deep-dive and write a report on fusion")
    assert msg is not None
    assert msg.startswith("Plan:")
    assert "research_report" in msg


def test_research_plan_from_preflight_or_skill() -> None:
    assert "research_report" in (
        plan_system_message("hello", preflight_kinds=["research"]) or ""
    )
    assert "research_report" in (
        plan_system_message("hello", skill_ids=["research"]) or ""
    )


def test_weather_plan() -> None:
    msg = plan_system_message("hi", preflight_kinds=["weather"])
    assert msg and "weather" in msg.lower()
    assert msg.startswith("Plan:")


def test_recall_plan() -> None:
    msg = plan_system_message("hi", preflight_kinds=["recall"])
    assert msg and "recall" in msg.lower()


def test_inbox_plan() -> None:
    msg = plan_system_message("Summarize my inbox")
    assert msg and "inbox" in msg.lower()
    assert "send_email" in msg
    msg2 = plan_system_message("hi", skill_ids=["email"])
    assert msg2 and "inbox" in msg2.lower()


def test_default_multi_search_then_scrape() -> None:
    msg = plan_system_message("Look up the latest on battery tech", skill_ids=["web"])
    assert msg is not None
    assert "web_search" in msg
    assert "scrape" in msg


def test_plain_chat_has_no_plan() -> None:
    assert plan_system_message("Good morning") is None
    assert plan_system_message("Thanks!") is None


def test_research_beats_web_skill() -> None:
    msg = plan_system_message(
        "deep dive into lithium",
        skill_ids=["web", "research"],
    )
    assert msg and "research_report" in msg


def test_deadline_pack_plan_from_text() -> None:
    for text in (
        "What are my upcoming deadlines?",
        "What's due this week?",
        "Pack my week",
    ):
        msg = plan_system_message(text)
        assert msg is not None, text
        assert msg.startswith("Plan:")
        assert "tasks" in msg
        assert "agenda" in msg
        assert "Allow" in msg


def test_deadline_pack_from_preflight_or_skill() -> None:
    assert "tasks" in (
        plan_system_message("hello", preflight_kinds=["deadline_pack"]) or ""
    )
    assert "agenda" in (
        plan_system_message("hello", skill_ids=["deadline"]) or ""
    )


def test_research_beats_deadline_pack() -> None:
    msg = plan_system_message(
        "deep dive into my deadlines for the report",
        skill_ids=["deadline", "research"],
    )
    assert msg and "research_report" in msg


def test_exported_from_preflight() -> None:
    assert preflight_export is plan_system_message


def test_analyze_git_agenda_clipboard_ocr_plans() -> None:
    assert "analyze" in (plan_system_message("summarize data.csv") or "").lower()
    assert "git_info" in (plan_system_message("what's my git status") or "")
    assert "agenda" in (
        plan_system_message("what's on my calendar today") or ""
    ).lower()
    assert "clipboard" in (
        plan_system_message("what's on my clipboard") or ""
    ).lower()
    assert "ocr" in (
        plan_system_message("OCR the text in this screenshot") or ""
    ).lower()
    assert "browser" in (
        plan_system_message("screenshot and describe the page") or ""
    ).lower()
    read_plan = plan_system_message("what's on this tab") or ""
    assert "action=read" in read_plan
    assert "scrape" in read_plan.lower()
    assert "1) browser(action=screenshot)" not in read_plan
    maps_plan = plan_system_message("directions to Midway") or ""
    assert "action=maps" in maps_plan
    assert "phone" in maps_plan.lower()
    search_plan = plan_system_message("search youtube for never gonna") or ""
    assert "action=search" in search_plan
    assert "cart" in search_plan.lower()
    reserve_plan = plan_system_message("book a table at The Inn") or ""
    assert "action=reserve" in reserve_plan
    assert "Book" in reserve_plan


def test_remember_that_does_not_plan_recall() -> None:
    plan = select_plan(
        "Remember that my favorite test fruit is durian.",
        skill_ids=["memory"],
    )
    assert plan is None or plan.id != "recall"


def test_calendar_create_reminder_plans_agenda_create() -> None:
    plan = select_plan(
        "create a calendar event for tomorrow at 4pm as a reminder to text my wife"
    )
    assert plan is not None
    assert plan.id == "agenda_create"
    assert "agenda" in plan.steps
    assert "send_sms" in (plan.message or "").lower()


def test_attached_image_describe_plans_vision_not_doc_extract() -> None:
    turn = (
        "Attachments for this turn (call the listed tool; do not invent contents):\n"
        "- data/drops/20260810/shot.png (image) → vision\n"
        "Rules: Images: call vision(path=…). Do not call doc_extract on images.\n\n"
        "describe this photo i have attached"
    )
    plan = select_plan(turn)
    assert plan is not None and plan.id == "attach_vision"
    msg = plan_system_message(turn) or ""
    assert "vision" in msg.lower()
    assert "doc_extract" in msg.lower()  # told not to use it


def test_attached_image_text_ask_plans_ocr() -> None:
    turn = (
        "Attachments for this turn (call the listed tool; do not invent contents):\n"
        "- data/drops/20260810/shot.png (image) → ocr\n\n"
        "extract text from this image"
    )
    plan = select_plan(turn)
    assert plan is not None and plan.id == "ocr"


def test_deadline_plan_progress_asks_for_agenda_after_tasks() -> None:
    plan = select_plan("pack my week")
    assert plan is not None and plan.id == "deadline"
    assert plan_progress_notice(plan, set()) is None  # nothing started yet
    notice = plan_progress_notice(
        plan, {"tasks"}, available_tools={"tasks", "agenda"}
    )
    assert notice is not None
    assert "agenda" in notice
    assert plan_progress_notice(
        plan, {"tasks", "agenda"}, available_tools={"tasks", "agenda"}
    ) is None


def test_multi_web_skips_progress_gate() -> None:
    plan = select_plan("look up battery tech", skill_ids=["web"])
    assert plan is not None and plan.skip_progress
    assert (
        plan_progress_notice(plan, {"web_search"}, available_tools={"web_search", "scrape"})
        is None
    )


def test_fail_replan_scrape_tag() -> None:
    notice = tool_fail_replan_notice(
        "scrape",
        "[fail:empty] No article text extracted.",
    )
    assert notice is not None
    assert "replan" in notice.lower()
    assert "scrape" in notice
    assert "fail:empty" in notice


def test_fail_replan_web_search_ok_false() -> None:
    notice = tool_fail_replan_notice(
        "web_search",
        "[fail:empty] web_search found nothing for 'xyz'.",
        ok=False,
    )
    assert notice is not None
    assert "web_search" in notice
    assert "fail:empty" in notice


def test_fail_replan_ignores_success() -> None:
    assert tool_fail_replan_notice("scrape", "Title\n\nArticle body…") is None
    assert tool_fail_replan_notice("calculator", "[fail:empty] n/a", ok=False) is None


def test_fail_replan_send_email() -> None:
    notice = tool_fail_replan_notice(
        "send_email",
        "[fail:send_email] SMTP auth failed",
        ok=False,
    )
    assert notice is not None
    assert "NOT sent" in notice
    assert "send_email" in notice


def test_fail_replan_send_sms() -> None:
    notice = tool_fail_replan_notice(
        "send_sms",
        "[fail:send_sms] gateway down",
        ok=False,
    )
    assert notice is not None
    assert "NOT sent" in notice
    assert "text" in notice.lower()


def test_fail_replan_image() -> None:
    notice = tool_fail_replan_notice(
        "image",
        "[fail:image] ComfyUI exited immediately",
        ok=False,
    )
    assert notice is not None
    assert "send_sms" in notice
    assert "Do NOT" in notice
