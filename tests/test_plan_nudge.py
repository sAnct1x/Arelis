"""Deterministic plan nudges + fail-tag replan notices."""

from __future__ import annotations

from arelis.core.fail_tags import tool_fail_replan_notice
from arelis.core.plan_nudge import (
    plan_progress_notice,
    plan_system_message,
    select_plan,
)
from arelis.core.skills import select_skill_ids, select_skill_ids_detailed
from arelis.rooms import KINDS

_LEAN_TOOLS = {
    "analyze",
    "workspace",
    "cas",
    "units",
    "calculator",
    "python",
    "plot",
    "catalog",
    "web_search",
    "scrape",
    "web_fetch",
    "document",
    "doc_extract",
}

_PHYSICS_ASK = "how do toroids relate to physics?"


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


def test_clock_ask_does_not_plan_web() -> None:
    """Live 20 Aug 2026: 'what time is it' logged plan_nudge skills=web."""
    assert plan_system_message("what time is it") is None
    assert plan_system_message("what time is it", skill_ids=["web"]) is None
    assert select_plan("what time is it", skill_ids=["web"]) is None


def test_who_is_this_without_a_real_web_skill_has_no_scrape_plan() -> None:
    """Live 15 Aug 2026: 'Who is this' got plan=multi_web and a 48s re-prefill.

    The loop passes plan_ids=() on fallback-only. Direct skill_ids=['web']
    still plans, because that is a matched card, not the floor.
    """
    from arelis.core.skills import select_skill_ids_detailed

    ids, fallback = select_skill_ids_detailed(
        "Who is this",
        available_tools={"web_search", "scrape", "web_fetch"},
    )
    assert fallback is True
    plan_ids = () if fallback else ids
    assert select_plan("Who is this", skill_ids=plan_ids) is None


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


def test_the_message_is_the_selected_plans_own_message() -> None:
    """plan_system_message is a convenience over select_plan, not a second path.

    This replaces a test that asserted core.preflight re-exported this function.
    The re-export had no other caller, so the test was the only reason the
    indirection existed.
    """
    text = "Please deep-dive and write a report on fusion"
    plan = select_plan(text)
    assert plan is not None
    assert plan_system_message(text) == plan.message


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
    signin_plan = plan_system_message("go to sign in") or ""
    assert "action=click" in signin_plan
    assert "goto_sign_in" in signin_plan
    assert "1) browser(action=screenshot)" not in signin_plan


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


def test_fail_replan_workspace_outside_roots() -> None:
    notice = tool_fail_replan_notice(
        "workspace",
        "Path outside allowed workspace roots: C:/Users/you/Documents",
        ok=False,
    )
    assert notice is not None
    assert "do not list" in notice.lower()
    assert "Settings" in notice
    assert tool_fail_replan_notice(
        "workspace", "Not a file: C:/proj/x", ok=False
    ) is None


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
    assert "comfyui" in notice.lower()
    assert "Ask them to start ComfyUI by hand" not in notice


def test_room_lean_is_not_this_turn_plan() -> None:
    """Live Aug 2026: physics room kind=analysis planned analyze on toroids.

    Room extras keep tools in reach. They are not this-turn intent. Feeding
    them to select_plan cages conceptual questions into a CSV / scrape /
    document plan.
    """
    matched = select_skill_ids(_PHYSICS_ASK, available_tools=_LEAN_TOOLS)
    assert "analyze" not in matched
    assert select_plan(_PHYSICS_ASK, skill_ids=matched) is None

    for kind, trapped in (
        ("analysis", "analyze"),
        ("writing", "document"),
        ("research", "multi_web"),
    ):
        extras = KINDS[kind].skills
        leaned = select_skill_ids(
            _PHYSICS_ASK, available_tools=_LEAN_TOOLS, extra_ids=extras
        )
        trap = select_plan(_PHYSICS_ASK, skill_ids=leaned)
        assert trap is not None, kind
        assert trap.id == trapped, (kind, trap.id)


def test_table_ask_still_plans_analyze_without_room_extras() -> None:
    text = "summarize reports/sales.csv"
    matched = select_skill_ids(text, available_tools=_LEAN_TOOLS)
    assert "analyze" in matched
    plan = select_plan(text, skill_ids=matched)
    assert plan is not None and plan.id == "analyze"


def test_web_fallback_is_not_a_scrape_plan() -> None:
    """Unmatched 'what is' tags skills=web so a 9B searches instead of inventing.

    That floor must not become a scrape plan. Clock asks already special-case
    this; definitional physics was the same cage once room extras stopped
    suppressing the fallback.
    """
    text = "what is a toroidal shape and how does it relate to physics?"
    ids, fallback = select_skill_ids_detailed(text, available_tools=_LEAN_TOOLS)
    assert fallback is True
    assert "web" in ids
    trap = select_plan(text, skill_ids=ids)
    assert trap is not None and trap.id == "multi_web"
    assert select_plan(text, skill_ids=()) is None


def test_inspect_plan_wins_over_research_wording() -> None:
    plan = select_plan("investigate the solar system simulation files")
    assert plan is not None and plan.id == "inspect"
    assert select_plan("please investigate the outage thoroughly").id == "research"


def test_inspect_plan_wins_over_web_fallback() -> None:
    for text, path in (
        ("what's in policy.py?", "arelis/tools/policy.py"),
        ("what does tool_subset do?", "arelis/core/tool_subset.py"),
        ("where is the Drive strip?", "arelis/ui/panels/drive.py"),
    ):
        plan = select_plan(text, skill_ids=["web"])
        assert plan is not None, text
        assert plan.id == "inspect", text
        assert plan.steps == ("workspace",), text
        assert path in plan.message, text
        assert "web_search" not in plan.steps, text


def test_physics_and_clock_do_not_plan_inspect() -> None:
    assert select_plan(_PHYSICS_ASK) is None or select_plan(_PHYSICS_ASK).id != "inspect"
    physics = select_plan(_PHYSICS_ASK)
    assert physics is None
    assert select_plan("what time is it") is None
    assert select_plan("what time is it", skill_ids=["web"]) is None
