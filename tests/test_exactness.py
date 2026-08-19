"""Exactness kernel: math gate, evidence ledger, scripted force rounds."""

from __future__ import annotations

import pytest

from arelis.core.claims import (
    answer_looks_like_ack_only,
    answer_looks_like_refusal,
    detect_agenda_ask,
    detect_analyze_ask,
    detect_cas_ask,
    detect_catalog_ask,
    detect_doc_ask,
    detect_exactness_need,
    detect_git_ask,
    detect_goals_ask,
    detect_inbound_sms_ask,
    detect_inbox_ask,
    detect_math_ask,
    detect_plot_ask,
    detect_send_success_claim,
    detect_tasks_ask,
    detect_units_ask,
    detect_vision_ask,
    send_claim_missing_kinds,
    unsupported_exactness_reply,
)
from arelis.core.evidence import EvidenceLedger, classify_fetch_failure
from arelis.core.sms_complete import SmsDraft, fill_send_sms_args
from arelis.eval.harness import run_scripted_scenario
from arelis.eval.scenarios import SCENARIOS, Scenario


def test_detect_math_percentage() -> None:
    assert detect_math_ask("What is 17.5% of 840?")
    need = detect_exactness_need("What is 17.5% of 840?")
    assert need.needs_calculator
    assert "math" in need.kinds


def test_image_filename_dimensions_are_not_math() -> None:
    """PNG dimension tags (1965x1106) must not trip the calculator gate."""
    ask = (
        "describe this image to me\n"
        "beam-final-green-purple-1965x1106.png"
    )
    assert not detect_math_ask(ask)
    need = detect_exactness_need(ask)
    assert not need.needs_calculator
    assert need.needs_vision
    assert "vision" in need.kinds
    # Spaced multiply still counts as math.
    assert detect_math_ask("What is 17 x 19?")
    assert detect_math_ask("calculate 3*4")


def test_a_spaced_resolution_is_not_math_either() -> None:
    """The unspaced guard above assumed sizes arrive as 1965x1106. They do not.

    "1280 x 720 pixels" is how a person writes a thumbnail size, and the spaces
    in it defeated that guard. What followed was calculator(expression="1280,
    720") — not an expression — and then a refusal, for a request that had
    nothing in it to calculate.
    """
    ask = (
        "make this image more vibrant and resize it to the correct size for a "
        "youtube thumbnail. The ideal YouTube thumbnail size is 1280 x 720 "
        "pixels with a 16:9 aspect ratio"
    )
    assert not detect_math_ask(ask)
    assert not detect_exactness_need(ask).needs_calculator

    for phrasing in (
        "resize it to 1280 x 720",
        "crop the screenshot to 1920 x 1080",
        "what resolution is 2560 x 1440",
        "make the wallpaper 3840 x 2160",
    ):
        assert not detect_math_ask(phrasing), phrasing

    # Arithmetic with no picture in it is still arithmetic.
    for phrasing in ("what is 1280 x 720", "calculate 40 x 12", "how much is 8 x 7"):
        assert detect_math_ask(phrasing), phrasing


def test_detect_news_needs_web() -> None:
    need = detect_exactness_need("What did the WSJ say about AI virus genomes?")
    assert need.needs_web_evidence
    assert not need.needs_calculator


def test_weather_ask_not_definitional() -> None:
    ask = detect_exactness_need("What's the weather today?")
    assert ask.needs_weather
    meta = detect_exactness_need("What is humidity?")
    assert not meta.needs_weather


def test_weather_force_notice_mentions_tool() -> None:
    from arelis.core.claims import weather_force_notice

    text = weather_force_notice()
    assert "weather" in text.lower()
    assert "web_search" in text.lower() or "scrape" in text.lower()


def test_refusal_rejects_hedge_then_claim() -> None:
    assert answer_looks_like_refusal("I don't know — search failed.")
    assert not answer_looks_like_refusal(
        "I don't know the headline id, but the story is that genomes were engineered."
    )


def test_ack_only_after_file_read() -> None:
    assert answer_looks_like_ack_only(
        "Got it! I'll keep that in mind as we continue. If you have any "
        "questions or need assistance, feel free to ask. What can I help "
        "you with today?"
    )
    assert not answer_looks_like_ack_only(
        "README describes Arelis as a local research assistant for AMD GPUs."
    )


def test_classify_fetch_failure_taxonomy() -> None:
    from arelis.core.evidence import classify_search_failure

    assert classify_fetch_failure("HTTP 403 Forbidden") == "fail:http_403"
    assert classify_fetch_failure("404 not found") == "fail:http_404"
    assert classify_fetch_failure("paywall subscribe now") == "fail:paywall"
    assert classify_fetch_failure("enable javascript to continue") == "fail:js_shell"
    assert classify_fetch_failure("request timeout after 30s") == "fail:timeout"
    assert classify_search_failure("", ["duckduckgo: connection refused"]) == "fail:connect"
    assert classify_search_failure("", ["duckduckgo: HTTP 429"]) == "fail:rate_limit"
    assert classify_search_failure("", ["duckduckgo: no results"]) == "fail:empty"


def test_ledger_web_search_is_not_web_warrant() -> None:
    ledger = EvidenceLedger()
    ledger.record_tool(
        "web_search",
        ok=True,
        output="1. Example — URL: https://example.com",
        data={},
        args={"query": "news"},
    )
    assert ledger.has_ok("web_search")
    assert not ledger.has_ok("web")
    assert ledger.missing_kinds(("web",)) == ["web"]
    ledger.record_tool(
        "scrape",
        ok=True,
        output="Article body here.",
        data={"url": "https://example.com"},
        args={"url": "https://example.com"},
    )
    assert ledger.satisfies(("web",))


def test_ledger_records_calculator_and_scrape_fail() -> None:
    ledger = EvidenceLedger()
    ledger.record_tool(
        "calculator",
        ok=True,
        output="147",
        data={"value": 147},
        args={"expression": "0.175*840"},
    )
    assert ledger.has_ok("calc")
    cas = EvidenceLedger()
    cas.record_tool(
        "cas",
        ok=True,
        output="integrate(x**2) = x**3/3",
        data={"result": "x**3/3"},
        args={"action": "integrate", "expr": "x**2"},
    )
    assert cas.has_ok("cas")
    assert cas.satisfies(("symbolic",))
    units = EvidenceLedger()
    units.record_tool(
        "units",
        ok=True,
        output="5 ft 8 in = 1.7272 meter",
        data={"value": 1.7272},
        args={"action": "convert", "quantity": "5 ft 8 in", "to": "meter"},
    )
    assert units.has_ok("units")
    assert units.satisfies(("units",))
    ledger.record_tool(
        "scrape",
        ok=False,
        output="HTTP 403 Forbidden",
        data={"url": "https://example.com"},
        args={"url": "https://example.com"},
    )
    fails = [w for w in ledger.items if w.kind == "web_fail"]
    assert fails and "403" in fails[0].span


def test_unsupported_exactness_reply_mentions_unknown() -> None:
    text = unsupported_exactness_reply(["math"])
    assert "don't know" in text.lower()


def test_integral_is_not_forced_calculator_math() -> None:
    assert not detect_math_ask("what is the integral of x^2?")
    assert not detect_math_ask("what is the integral of x^2. use the calculator tool")
    assert detect_math_ask("what is 0 divided by 0?")
    need = detect_exactness_need("what is the integral of x^2?")
    assert not need.needs_calculator
    assert need.needs_cas
    assert "symbolic" in need.kinds
    assert not detect_cas_ask("integrate this with my calendar")
    assert detect_cas_ask("integrate x**2")


def test_units_and_constants_are_forced() -> None:
    conv = detect_exactness_need("convert 5 ft 8 in to meters")
    assert conv.needs_units
    assert not conv.needs_calculator
    g = detect_exactness_need("what is the gravitational constant?")
    assert g.needs_units
    assert "units" in g.kinds
    assert detect_units_ask("speed of light")
    assert not detect_units_ask("convert this file to pdf")
    assert not detect_units_ask("2.7 K to the CMB frame")


def test_plot_asks_are_forced() -> None:
    need = detect_exactness_need("fit a line and plot residuals")
    assert need.needs_plot
    assert "plot" in need.kinds
    assert detect_plot_ask("plot this csv")
    assert not detect_plot_ask("I loved the plot twist")
    assert not detect_plot_ask("What's the weather today?")


def test_catalog_asks_are_forced() -> None:
    need = detect_exactness_need("search arxiv for gravitational waves")
    assert need.needs_catalog
    assert "catalog" in need.kinds
    assert detect_catalog_ask("where is mars tonight")
    assert detect_catalog_ask("jpl horizons for Jupiter")
    assert not detect_catalog_ask("I loved the plot twist")
    assert not detect_catalog_ask("What's the weather today?")
    assert not detect_catalog_ask("where's the mars bar")


def test_failed_calculator_has_honest_copy() -> None:
    zero = unsupported_exactness_reply(
        ["math"], calc_failed=True, calc_detail="Division by zero."
    )
    assert "undefined" in zero.lower()
    symbolic = unsupported_exactness_reply(
        ["math"], calc_failed=True, calc_detail="Could not evaluate: unknown name"
    )
    assert "integral" in symbolic.lower() or "arithmetic" in symbolic.lower()
    cas = unsupported_exactness_reply(
        ["symbolic"], cas_failed=True, cas_detail="no closed form"
    )
    assert "closed form" in cas.lower()
    units = unsupported_exactness_reply(
        ["units"], units_failed=True, units_detail="not a unit"
    )
    assert "not a unit" in units.lower() or "boost" in units.lower()


def test_local_store_inject_args_parses_titles() -> None:
    from arelis.core.claims import local_store_inject_args

    add_task = local_store_inject_args(
        "tasks", "Add a task titled operator-smoke-task."
    )
    assert add_task == {"action": "add", "title": "operator-smoke-task"}
    assert local_store_inject_args("tasks", "List my tasks.") == {"action": "list"}
    add_goal = local_store_inject_args(
        "goals", "Add a goal titled Keep operator tests honest."
    )
    assert add_goal == {"action": "add", "title": "Keep operator tests honest"}
    assert local_store_inject_args("goals", "List my goals.") == {"action": "list"}
    forget = local_store_inject_args(
        "memory", "Forget that my favorite test fruit is durian."
    )
    assert forget["action"] == "forget"
    assert "durian" in forget["fact"]
    remember = local_store_inject_args(
        "memory", "Remember that my favorite test fruit is durian."
    )
    assert remember["action"] == "remember"
    assert "durian" in remember["fact"]
    from arelis.core.claims import contact_who_from_text
    from arelis.memory.store import _facts_loosely_match

    assert contact_who_from_text("who is my wife in my contacts?") == "wife"
    assert _facts_loosely_match(
        "my favorite test fruit is durian",
        "Sam's favorite test fruit is durian.",
    )
    assert not _facts_loosely_match("durian", "Name is Sam Whitlock")
    assert local_store_inject_args(
        "contacts", "what is her phone number?"
    )["action"] == "get"
    from arelis.core.claims import lock_memory_forget_args

    locked = lock_memory_forget_args(
        {
            "action": "forget",
            "fact": "Name is Sam Whitlock",
            "key": "favorite test fruit",
            "value": "durian",
        },
        "Forget that my favorite test fruit is durian.",
    )
    assert locked["action"] == "forget"
    assert "durian" in locked["fact"]
    assert "Sam Whitlock" not in locked["fact"]
    assert "key" not in locked
    assert "value" not in locked
    assert contact_who_from_text("what is my wifes phone number?") == "wife"
    from arelis.core.sms_complete import looks_like_goals_utterance, looks_like_tasks_utterance

    assert looks_like_tasks_utterance("List my tasks. Do not text anyone.")
    assert looks_like_goals_utterance("delete that goal")
    dropped = local_store_inject_args(
        "goals",
        "delete that goal",
        history=[{"role": "assistant", "content": "#1 [active/goal] Text wife at 10pm"}],
    )
    assert dropped == {"action": "remove", "id": "1"}


def test_inbox_and_inbound_ask_detectors() -> None:
    assert detect_inbox_ask("What's in my inbox from Alice?")
    assert detect_exactness_need("What's in my inbox?").needs_inbox
    assert not detect_inbox_ask("What is an inbox?")
    assert detect_inbound_sms_ask("Did Brian text me back?")
    assert detect_exactness_need("What did she reply?").needs_inbound_sms
    assert not detect_inbound_sms_ask("What is a text message?")


def test_send_success_claim_needs_warrant() -> None:
    assert detect_send_success_claim("I sent the text to Brian.")
    assert detect_send_success_claim(
        "I don't know the details, but I sent the text to Brian."
    )
    assert detect_send_success_claim("I've sent it.")
    assert detect_send_success_claim("It's on its way.")
    assert detect_send_success_claim("Done — I emailed him.")
    assert not detect_send_success_claim("Ready to send — check the confirm card.")
    missing = send_claim_missing_kinds(
        "I sent the text.",
        has_send_sms=False,
        has_send_email=False,
    )
    assert "send_sms" in missing
    assert send_claim_missing_kinds(
        "I emailed Brian.",
        has_send_sms=False,
        has_send_email=False,
    ) == ["send_email"]
    assert not send_claim_missing_kinds(
        "I sent the text.",
        has_send_sms=True,
        has_send_email=False,
    )


def test_ledger_records_inbox_send_and_failures_not_ok() -> None:
    ledger = EvidenceLedger()
    ledger.record_tool(
        "inbox",
        ok=True,
        output="1. Alice — Meeting",
        data={"uid": "12", "sender": "Alice", "subject": "Meeting"},
        args={"action": "list"},
    )
    assert ledger.has_ok("inbox")
    assert ledger.satisfies(("inbox",))
    ledger.record_tool(
        "send_sms",
        ok=False,
        output="declined",
        data={},
        args={"to": "brian", "body": "hi"},
    )
    assert not ledger.has_ok("send_sms")
    ledger.record_tool(
        "send_sms",
        ok=True,
        output="queued",
        data={"to": "brian"},
        args={"to": "brian", "body": "hi"},
    )
    assert ledger.has_ok("send_sms")
    ledger.record_tool(
        "inbound_sms",
        ok=True,
        output="Recent inbound texts:\n1. Brian: late",
        data={"count": 1},
        args={},
    )
    assert ledger.has_ok("inbound_sms")


def test_doc_and_agenda_ask_detectors() -> None:
    assert detect_doc_ask("What does this PDF say about termination?")
    assert detect_doc_ask("What does docs/contract.pdf say about termination?")
    assert detect_doc_ask("Quote from the PDF on page 2")
    need = detect_exactness_need("What does this PDF say about fees?")
    assert need.needs_doc
    assert "doc" in need.kinds
    assert not detect_doc_ask("What is a PDF?")
    assert detect_agenda_ask("What's on my calendar today?")
    assert detect_agenda_ask("What's on my agenda today?")
    assert detect_agenda_ask("Any meetings tomorrow?")
    agenda_need = detect_exactness_need("What's on my agenda today?")
    assert agenda_need.needs_agenda
    assert "agenda" in agenda_need.kinds
    assert not detect_agenda_ask("What is a calendar?")


def test_ledger_records_doc_and_agenda_warrants() -> None:
    ledger = EvidenceLedger()
    ledger.record_tool(
        "doc_extract",
        ok=True,
        output="Either party may terminate with 30 days notice.",
        data={"path": "docs/contract.pdf", "pages": [1, 2]},
        args={"path": "docs/contract.pdf"},
    )
    assert ledger.has_ok("doc")
    assert ledger.satisfies(("doc",))
    fail_only = EvidenceLedger()
    fail_only.record_tool(
        "doc_extract",
        ok=False,
        output="[fail:encrypted]",
        data={"path": "secret.pdf", "fail_class": "fail:encrypted"},
        args={"path": "secret.pdf"},
    )
    assert not fail_only.has_ok("doc")
    assert fail_only.missing_kinds(("doc",)) == ["doc"]
    agenda = EvidenceLedger()
    agenda.record_tool(
        "agenda",
        ok=True,
        output="Agenda today:\n- 10:00 Standup\n\nSource: data/calendar.ics",
        data={"action": "today", "count": 1, "source": "data/calendar.ics"},
        args={"action": "today"},
    )
    assert agenda.has_ok("agenda")
    assert agenda.satisfies(("agenda",))
    assert "don't know" in unsupported_exactness_reply(["doc"]).lower()
    assert "don't know" in unsupported_exactness_reply(["agenda"]).lower()


def test_git_tasks_analyze_ask_detectors() -> None:
    assert detect_git_ask("What's the git status of this project?")
    assert detect_git_ask("Show me the git diff")
    need = detect_exactness_need("What's the git status of this project?")
    assert need.needs_git
    assert "git" in need.kinds
    assert not detect_git_ask("What is git?")
    assert detect_tasks_ask("What tasks do I have open?")
    assert detect_tasks_ask("Add a task: buy coffee filters")
    assert detect_tasks_ask("What's on my todo list?")
    tasks_need = detect_exactness_need("What tasks do I have open?")
    assert tasks_need.needs_tasks
    assert "tasks" in tasks_need.kinds
    assert not detect_tasks_ask("What is a task?")
    assert detect_analyze_ask("Summarize the CSV at data/sales.csv")
    assert detect_analyze_ask("Describe the spreadsheet columns")
    analyze_need = detect_exactness_need("Summarize the CSV at data/sales.csv")
    assert analyze_need.needs_analyze
    assert "analyze" in analyze_need.kinds
    assert not detect_analyze_ask("What is a CSV?")
    assert detect_vision_ask("What's in this image?")
    assert detect_vision_ask("What's in outputs/images/demo.png?")
    vision_need = detect_exactness_need("Describe this screenshot")
    assert vision_need.needs_vision
    assert "vision" in vision_need.kinds
    assert not detect_vision_ask("What is a screenshot?")
    assert detect_goals_ask("What are my goals?")
    assert detect_goals_ask("Commit to shipping this week")
    goals_need = detect_exactness_need("What am I committed to?")
    assert goals_need.needs_goals
    assert "goals" in goals_need.kinds
    assert not detect_goals_ask("What is a goal?")
    assert not detect_goals_ask("git commit -m fix")


def test_ledger_records_git_tasks_analyze_warrants() -> None:
    ledger = EvidenceLedger()
    ledger.record_tool(
        "git_info",
        ok=True,
        output="On main\nnothing to commit, working tree clean",
        data={"action": "status"},
        args={"action": "status"},
    )
    assert ledger.has_ok("git")
    assert ledger.satisfies(("git",))
    fail_git = EvidenceLedger()
    fail_git.record_tool(
        "git_info",
        ok=False,
        output="not a git repository",
        data={},
        args={"action": "status"},
    )
    assert not fail_git.has_ok("git")
    assert fail_git.missing_kinds(("git",)) == ["git"]
    tasks = EvidenceLedger()
    tasks.record_tool(
        "tasks",
        ok=True,
        output="1. #1 [open] buy coffee filters",
        data={"action": "list", "count": 1},
        args={"action": "list"},
    )
    assert tasks.has_ok("tasks")
    assert tasks.satisfies(("tasks",))
    analyze = EvidenceLedger()
    analyze.record_tool(
        "analyze",
        ok=True,
        output="3 columns, 12 rows",
        data={"path": "data/sales.csv", "action": "summary"},
        args={"path": "data/sales.csv", "action": "summary"},
    )
    assert analyze.has_ok("analyze")
    assert analyze.satisfies(("analyze",))
    assert "don't know" in unsupported_exactness_reply(["git"]).lower()
    assert "don't know" in unsupported_exactness_reply(["tasks"]).lower()
    assert "don't know" in unsupported_exactness_reply(["analyze"]).lower()


def test_fill_send_sms_locks_complete_draft_body() -> None:
    draft = SmsDraft(to="Brian", body="Running 10 minutes late", alias="brian")
    filled = fill_send_sms_args(
        {"to": "brian", "body": "See you tomorrow"},
        draft,
    )
    assert filled["body"] == "Running 10 minutes late"
    assert filled["to"] == "brian"


@pytest.mark.asyncio
async def test_math_forces_calculator_scenario() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "math_forces_calculator")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "calculator" in result.tools_called


@pytest.mark.asyncio
async def test_integral_forces_cas_scenario() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "integral_forces_cas")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "cas" in result.tools_called
    assert "calculator" not in result.tools_called


@pytest.mark.asyncio
async def test_integral_hard_refuses_second_invent() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "integral_refuses_without_cas")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "don't know" in result.final_text.lower()
    assert "x^3" not in result.final_text.lower()
    assert "x**3" not in result.final_text.lower()


@pytest.mark.asyncio
async def test_convert_forces_units_scenario() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "convert_forces_units")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "units" in result.tools_called


@pytest.mark.asyncio
async def test_constant_hard_refuses_without_units() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "constant_refuses_without_units")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "don't know" in result.final_text.lower()
    assert "6.674" not in result.final_text


@pytest.mark.asyncio
async def test_plot_forces_plot_scenario() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "plot_forces_plot")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "plot" in result.tools_called


@pytest.mark.asyncio
async def test_plot_hard_refuses_ascii() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "plot_refuses_without_plot")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "don't know" in result.final_text.lower()
    assert "rising" not in result.final_text.lower()


@pytest.mark.asyncio
async def test_arxiv_forces_catalog_scenario() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "arxiv_forces_catalog")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "catalog" in result.tools_called


@pytest.mark.asyncio
async def test_arxiv_hard_refuses_invented_id() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "arxiv_refuses_without_catalog")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "don't know" in result.final_text.lower()
    assert "1234.5678" not in result.final_text


@pytest.mark.asyncio
async def test_news_forces_web_evidence_scenario() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "news_forces_web_evidence")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "web_search" in result.tools_called
    assert "scrape" in result.tools_called


@pytest.mark.asyncio
async def test_math_hard_refuses_second_invent() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "math_refuses_without_calculator")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "don't know" in result.final_text.lower()
    assert "147" not in result.final_text


@pytest.mark.asyncio
async def test_news_hard_refuses_without_warrant() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "news_refuses_without_web_warrant")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "don't know" in result.final_text.lower()
    assert "engineered" not in result.final_text.lower()


@pytest.mark.asyncio
async def test_inbox_claim_needs_warrant_scenario() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "inbox_claim_needs_warrant")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "don't know" in result.final_text.lower()
    assert "meeting tomorrow" not in result.final_text.lower()


@pytest.mark.asyncio
async def test_pdf_quote_refuses_without_doc_warrant() -> None:
    """Inline refuse path — not added to SCENARIOS (keeps foundation 19/19)."""
    scenario = Scenario(
        id="pdf_quote_refuses_without_doc_warrant",
        user="What does docs/contract.pdf say about termination?",
        expect_tools=(),
        allow_no_tools=True,
        offline_only=True,
        expect_answer_contains=("don't know",),
        forbid_claim_if_no_tool=("30 days notice",),
        failure_class="unsupported_contingent_claim",
        notes="Exactness: inventing PDF quotes without doc_extract must refuse.",
        script=[
            [
                (
                    "token",
                    'The PDF says "Either party may terminate with 30 days notice."',
                )
            ],
            [
                (
                    "token",
                    'I\'m sure it says "Either party may terminate with 30 days notice."',
                )
            ],
        ],
    )
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "don't know" in result.final_text.lower()
    assert "30 days notice" not in result.final_text.lower()


@pytest.mark.asyncio
async def test_inbound_sms_claim_needs_warrant_scenario() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "inbound_sms_claim_needs_warrant")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "don't know" in result.final_text.lower()
    assert "running late" not in result.final_text.lower()


@pytest.mark.asyncio
async def test_git_claim_needs_warrant_scenario() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "git_claim_needs_warrant")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "don't know" in result.final_text.lower()
    assert "working tree clean" not in result.final_text.lower()


@pytest.mark.asyncio
async def test_tasks_claim_needs_warrant_scenario() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "tasks_claim_needs_warrant")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "tasks" in result.tools_called
    assert result.first_args.get("action") == "list"
    assert "buy coffee filters" not in result.final_text.lower()


@pytest.mark.asyncio
async def test_analyze_claim_needs_warrant_scenario() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "analyze_claim_needs_warrant")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "don't know" in result.final_text.lower()
    assert "12 rows" not in result.final_text.lower()


@pytest.mark.asyncio
async def test_send_claim_without_tool_refuses_scenario() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "send_claim_without_tool_refuses")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "not sent" in result.final_text.lower()


@pytest.mark.asyncio
async def test_sms_body_matches_draft_scenario() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "sms_body_matches_draft")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "send_sms" in result.tools_called
    body = str(result.first_args.get("body") or "")
    assert "Running 10 minutes late" in body
    assert "See you tomorrow" not in body


@pytest.mark.asyncio
async def test_all_scripted_foundation_still_passes() -> None:
    from arelis.eval.harness import run_all_scripted

    results = await run_all_scripted()
    failed = [r for r in results if not r.ok]
    assert not failed, [(r.scenario_id, r.reasons) for r in failed]
