"""Nothing written for a model, and no exception class, reaches the transcript.

Two paths used to break that. The orchestrator's last-resort handler published
``Turn failed: ConnectError: [Errno 11001] getaddrinfo failed`` as the chat
message, and failed tool output went to chat verbatim — which stopped being
harmless the moment tools started answering in instructions, as analyze now does
with "Call vision(path=…) for an image".

The passthrough half matters as much as the substitution half: "Not a file:
C:/typo.csv" is the whole answer, and the reason raw output was ever shown is that
hiding it made a wrong path look like a silent no-op.
"""

from __future__ import annotations

import httpx

from arelis.core.failure_copy import (
    TURN_FAILED_NOTICE,
    is_model_directed,
    plain_reason,
    should_nudge_write_after_page,
    tool_failure_notice,
    turn_failed_notice,
)


def test_a_crashed_turn_never_shows_its_exception_class() -> None:
    chat, detail = turn_failed_notice(KeyError("expected_tools"))
    assert chat == TURN_FAILED_NOTICE
    assert "KeyError" not in chat
    # The class belongs in Thinking, where there is room for it.
    assert "KeyError" in detail
    assert "expected_tools" in detail


def test_the_chat_line_says_what_to_do_next() -> None:
    chat, _ = turn_failed_notice(RuntimeError("boom"))
    assert "Thinking" in chat
    assert "again" in chat.lower()


def test_an_ollama_failure_keeps_the_copy_that_names_the_chip() -> None:
    """The user's next action differs, so the generic line would be worse."""
    chat, detail = turn_failed_notice(httpx.ConnectError("connection refused"))
    assert chat != TURN_FAILED_NOTICE
    assert "Ollama" in chat
    assert "chip" in chat
    assert "ConnectError" in detail


def test_analyzes_advice_to_the_model_does_not_reach_the_user() -> None:
    raw = ".png is not a table. Call vision(path=…) for an image, or ocr for its exact text."
    assert is_model_directed(raw)
    notice = tool_failure_notice("analyze", raw)
    assert "Call vision" not in notice
    assert "spreadsheet" in notice


def test_a_rejected_call_does_not_reach_the_user() -> None:
    raw = "Rejected: `calculator` takes none of latitude, longitude."
    notice = tool_failure_notice("calculator", raw)
    assert "Rejected:" not in notice
    assert "calculator" in notice


def test_a_wrong_path_still_reaches_the_user_verbatim() -> None:
    """The regression this whole path exists to prevent."""
    assert tool_failure_notice("workspace", "Not a file: C:/typo.csv") == (
        "Not a file: C:/typo.csv"
    )


def test_a_page_of_output_is_summarised_rather_than_pasted() -> None:
    notice = tool_failure_notice("scrape", "x" * 4000)
    assert len(notice) < 200
    assert "x" * 100 not in notice


def test_silence_gets_copy_rather_than_an_empty_line() -> None:
    assert tool_failure_notice("image", "").strip()
    assert tool_failure_notice("", "").strip()


def test_the_first_line_is_what_shows() -> None:
    notice = tool_failure_notice("workspace", "Not a file: x.csv\n  stack frame\n  more")
    assert notice == "Not a file: x.csv"


def test_a_model_directed_sentence_later_in_the_output_still_counts() -> None:
    """The first line can look innocent and the advice follow underneath."""
    raw = "Unsupported file.\nDo not call analyze on a PDF."
    notice = tool_failure_notice("analyze", raw)
    assert "Do not call" not in notice


def test_errno_framing_comes_off_but_the_reason_stays() -> None:
    reason = plain_reason(OSError("[Errno 13] Permission denied: 'C:/x.txt'"))
    assert reason.startswith("Permission denied")
    assert "Errno" not in reason
    assert "C:/x.txt" in reason


def test_a_policy_refusal_is_the_useful_part_and_survives() -> None:
    reason = plain_reason(ValueError("path is outside the workspace roots"))
    assert "outside the workspace roots" in reason


def test_an_exception_with_no_message_still_says_something() -> None:
    assert plain_reason(RuntimeError()) == "RuntimeError"


def test_empty_after_tool_strips_agenda_instruction_footers() -> None:
    from arelis.core.failure_copy import chat_followup_from_tool

    raw = (
        "No events in this window.\n\n"
        "Source: cache (ics)\n"
        "Summarize these events for the user (time, title, place, "
        "one-line notes). Do not invent events. Do not quote event ids."
    )
    chat = chat_followup_from_tool("agenda", raw)
    assert "Do not invent" not in chat
    assert "Summarize these events" not in chat
    assert "No events" in chat


def test_long_scrape_nudges_a_write_short_fact_does_not() -> None:
    price = "NASDAQ:SPCX last $143.34"
    assert not should_nudge_write_after_page("scrape", price)
    assert not should_nudge_write_after_page("agenda", "Created on google: lab")
    article = (
        "# What is Single Crystal Piezo or PMN-PT?\n"
        "Site: piezo.com\n"
        + ("PMN-PT single crystals have a high d33. " * 20)
    )
    assert should_nudge_write_after_page("scrape", article)


def test_scrape_fallback_is_a_lede_not_the_article() -> None:
    from arelis.core.failure_copy import chat_followup_from_tool

    raw = (
        "# Song Yadong KO's Umar Nurmagomedov in massive UFC upset\n"
        "\n"
        "Site: ESPN.com\n"
        "Length: ~794 words (4 min read)\n"
        "\n"
        "Song Yadong saved the greatest performance of his career for his "
        "home country, knocking out former title challenger Umar Nurmagomedov "
        "in the men's bantamweight main event of UFC Fight Night on Saturday "
        "in Shanghai. Song, a nearly 5-1 underdog, dropped Nurmagomedov with "
        "a short right hand. The rest of the article goes on for many "
        "paragraphs about walkouts, nine years, and finishing shots on the mat. "
        + ("filler " * 80)
        + "\n[extracted via json-ld]\n"
    )
    chat = chat_followup_from_tool("scrape", raw)
    assert "Song Yadong" in chat
    assert "Nurmagomedov" in chat
    assert "filler" not in chat
    assert "[extracted via" not in chat
    assert "Site:" not in chat
    assert len(chat) < 600


def test_search_fallback_is_the_first_hit() -> None:
    from arelis.core.failure_copy import chat_followup_from_tool

    raw = (
        "1. Title: Song Yadong KO's Umar Nurmagomedov\n"
        "   URL: https://espn.com/mma/story\n"
        "2. Title: Some other fight recap\n"
        "   URL: https://example.com/other\n"
    )
    chat = chat_followup_from_tool("web_search", raw)
    assert "Song Yadong" in chat
    assert "other fight" not in chat


def test_workspace_list_fallback_is_not_a_dir_dump() -> None:
    from arelis.core.failure_copy import chat_followup_from_tool

    listing = "[dir] src\n[file] README.md\n[file] LICENSE"
    chat = chat_followup_from_tool("workspace", listing)
    assert "[dir]" not in chat
    assert "[file]" not in chat
    assert "Workspace" in chat


def test_a_crashed_turn_puts_no_exception_in_the_transcript(arelis_window) -> None:
    """End to end, at the window: the split the publisher makes is honoured."""
    from arelis.core.events import Event, EventType

    window = arelis_window()
    window._set_busy(True)
    window._on_event(
        Event(
            EventType.ERROR,
            {
                "message": TURN_FAILED_NOTICE,
                "detail": "ConnectError: [Errno 11001] getaddrinfo failed",
            },
        )
    )
    shown = window.chat.view.toPlainText()
    assert "ConnectError" not in shown
    assert "Errno" not in shown
    assert "went wrong mid-turn" in shown
    # The detail is not lost, it is where there is room for it.
    assert "ConnectError" in window.thinking.footer.text()


def test_a_tool_that_answers_in_instructions_is_translated_at_the_window(
    arelis_window,
) -> None:
    from arelis.core.events import Event, EventType

    window = arelis_window()
    window._set_busy(True)
    window._on_event(
        Event(
            EventType.TOOL_RESULT,
            {
                "tool": "analyze",
                "ok": False,
                "output": ".png is not a table. Call vision(path=…) for an image.",
            },
        )
    )
    shown = window.chat.view.toPlainText()
    assert "Call vision" not in shown
    assert "spreadsheet" in shown
