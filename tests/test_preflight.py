"""Deterministic intent preflight (no tool execution)."""

from __future__ import annotations

from arelis.core.preflight import detect_intents, preflight_system_message


def test_weather_intent() -> None:
    hints = detect_intents("What's the weather like?")
    assert any(h.kind == "weather" for h in hints)
    msg = preflight_system_message("What's the weather like?")
    assert msg and "weather tool" in msg.lower()


def test_sms_intent_with_body() -> None:
    hints = detect_intents("Text Brian: Running 10 minutes late")
    assert any(h.kind == "sms_send" for h in hints)
    sms = next(h for h in hints if h.kind == "sms_send")
    assert "brian" in sms.nudge.lower()
    assert "Running 10 minutes late" in sms.nudge


def test_no_false_sms_on_text_me_later() -> None:
    hints = detect_intents("text me later about the optics run")
    assert not any(h.kind == "sms_send" for h in hints)


def test_run_script_not_diagnostics() -> None:
    hints = detect_intents("run measure_drift.py and tell me the results")
    assert any(h.kind == "run_script" for h in hints)
    assert not any(h.kind == "diagnostics" for h in hints)
    assert "run_script" in {t for h in hints for t in h.expected_tools}


def test_workspace_write_not_sms() -> None:
    for phrase in (
        "write a temp file with hello",
        "create a text file named note.txt",
        "save a file called scratch.md",
    ):
        hints = detect_intents(phrase)
        assert any(h.kind == "workspace_write" for h in hints), phrase
        assert not any(h.kind == "sms_send" for h in hints), phrase


def test_list_goals_beats_pending_sms_history() -> None:
    history = [
        {"role": "user", "content": "Text my wife"},
        {"role": "assistant", "content": "What should I say?"},
    ]
    hints = detect_intents("list my goals", history=history)
    assert any(h.kind == "goals" for h in hints)
    assert not any(h.kind == "sms_send" for h in hints)


def test_inbox_read_not_compose_email() -> None:
    """R11: triage must not expect send_email from a stale draft."""
    history = [
        {
            "role": "user",
            "content": "Email Brian subject: Hi body: Hello there friend.",
        },
        {"role": "assistant", "content": "Ready to send when you say so."},
    ]
    for phrase in (
        "any new emails today?",
        "check my inbox",
        "what's in my inbox",
    ):
        hints = detect_intents(phrase, history=history)
        assert any(h.kind == "inbox" for h in hints), phrase
        assert not any(h.kind == "compose_email" for h in hints), phrase
        assert "send_email" not in {
            t for h in hints for t in h.expected_tools
        }, phrase


def test_delete_mail_is_inbox_not_compose() -> None:
    history = [
        {
            "role": "user",
            "content": "Email Brian subject: Hi body: Hello there friend.",
        },
        {"role": "assistant", "content": "Ready to send when you say so."},
    ]
    ask = "delete the email from Claude"
    hints = detect_intents(ask, history=history)
    tools = {t for h in hints for t in h.expected_tools}
    kinds = [h.kind for h in hints]
    assert "inbox" in tools
    assert "send_email" not in tools
    assert "compose_email" not in kinds


def test_graph_ask_after_email_does_not_expect_send() -> None:
    history = [
        {
            "role": "user",
            "content": "Email Brian subject: Hi body: Hello there friend.",
        },
        {"role": "assistant", "content": "Ready to send when you say so."},
    ]
    ask = "show me a graph of y=x^2"
    hints = detect_intents(ask, history=history)
    tools = {t for h in hints for t in h.expected_tools}
    kinds = [h.kind for h in hints]
    assert "send_email" not in tools
    assert "compose_email" not in kinds


def test_plain_chat_has_no_preflight() -> None:
    assert preflight_system_message("Good morning") is None


def test_attachment_continue_affirmation() -> None:
    history = [
        {
            "role": "user",
            "content": (
                "Attachments for this turn (call the listed tool; "
                "do not invent contents):\n"
                "- data/drops/20260810/ui_launch.log (text) → workspace read\n\n"
                "summarize this log"
            ),
        },
        {
            "role": "assistant",
            "content": "Want a line-by-line summary?",
        },
    ]
    hints = detect_intents("yea", history=history)
    assert any(h.kind == "attachment_continue" for h in hints)
    expanded = (
        "Attachments for this turn …\n"
        "Continue the prior request about these attachments.\n"
        "User affirmed: yea"
    )
    hints2 = detect_intents(expanded)
    assert any(h.kind == "attachment_continue" for h in hints2)


def test_recall_intent() -> None:
    for phrase in (
        "What did I say about the deadline?",
        "Do you remember my wife's name?",
        "You told me the gate code earlier",
    ):
        hints = detect_intents(phrase)
        assert any(h.kind == "recall" for h in hints), phrase
        recall = next(h for h in hints if h.kind == "recall")
        assert "recall" in recall.expected_tools
        assert "recall tool" in recall.nudge.lower()


def test_inbound_sms_intent() -> None:
    for phrase in (
        "Did Brian text?",
        "What did they reply?",
        "Has Sarah texted back?",
        "Any texts from Mom?",
    ):
        hints = detect_intents(phrase)
        assert any(h.kind == "inbound_sms" for h in hints), phrase
        inbound = next(h for h in hints if h.kind == "inbound_sms")
        assert inbound.expected_tools == ("inbound_sms",)
        assert "inbound_sms" in inbound.nudge


def test_analyze_intent_path_or_extension() -> None:
    for phrase in (
        "Summarize reports/sales.csv",
        "What's in the xlsx export?",
        "Analyze the tsv on disk",
        "head of data\\metrics.xlsx please",
    ):
        hints = detect_intents(phrase)
        assert any(h.kind == "analyze" for h in hints), phrase
        analyze = next(h for h in hints if h.kind == "analyze")
        assert analyze.expected_tools == ("analyze",)
        assert "analyze tool" in analyze.nudge.lower()


def test_analyze_intent_summarize_data_shape() -> None:
    hints = detect_intents("Can you summarize the data in that table?")
    assert any(h.kind == "analyze" for h in hints)


def test_compose_email_intent() -> None:
    hints = detect_intents("Email bob@example.com about Dinner: See you at 7")
    assert any(h.kind == "compose_email" for h in hints)
    email = next(h for h in hints if h.kind == "compose_email")
    assert email.expected_tools == ("send_email",)
    assert "send_email" in email.nudge


def test_browser_intent_pull_up() -> None:
    hints = detect_intents("pull up YouTube")
    assert any(h.kind == "browser" for h in hints)
    browser = next(h for h in hints if h.kind == "browser")
    assert browser.expected_tools == ("browser",)


def test_open_my_calendar_is_agenda_not_browser() -> None:
    hints = detect_intents("open my calendar")
    assert any(h.kind == "agenda_open" for h in hints)
    assert not any(h.kind == "browser" for h in hints)
    pulled = detect_intents("pull up my calendar")
    assert any(h.kind == "agenda_open" for h in pulled)
    assert not any(h.kind == "browser" for h in pulled)


def test_close_my_calendar_is_agenda_close() -> None:
    hints = detect_intents("close my calendar")
    assert any(h.kind == "agenda_close" for h in hints)
    assert not any(h.kind == "agenda_delete" for h in hints)
    assert not any(h.kind == "browser" for h in hints)


def test_openx_com_does_not_revive_pending_sms() -> None:
    history = [
        {"role": "user", "content": "text Sam Brightley and tell him"},
        {"role": "assistant", "content": "What should I say?"},
    ]
    for phrase in ("OpenX.com", "open x.com", "open X.com"):
        hints = detect_intents(phrase, history=history)
        assert not any(h.kind == "sms_send" for h in hints), phrase


def test_calendar_reminder_to_text_is_agenda_not_sms() -> None:
    """Nested 'text my wife' inside a calendar create must not expect send_sms."""
    phrase = (
        "create a calendar event for tomorrow at 4pm. I want this calendar "
        "event to be a reminder to text my wife and tell her I love her."
    )
    hints = detect_intents(phrase)
    assert any(h.kind == "agenda_create" for h in hints)
    assert not any(h.kind == "sms_send" for h in hints)
    expected = {t for h in hints for t in h.expected_tools}
    assert "agenda" in expected
    assert "send_sms" not in expected
    msg = preflight_system_message(phrase)
    assert msg is not None
    assert "agenda" in msg.lower()
    assert "send_sms" not in msg.lower() or "do not send_sms" in msg.lower()


def test_preflight_never_implies_allow_skip() -> None:
    """Nudges only — wording must not tell the model to skip confirm."""
    for phrase in (
        "Text Brian: I'm late",
        "What did I say yesterday?",
        "Did Alex text?",
        "Summarize data/foo.csv",
        "Email bob@example.com about Dinner: See you at 7",
        "pull up YouTube",
    ):
        msg = preflight_system_message(phrase)
        assert msg is not None
        lowered = msg.lower()
        assert "skip" not in lowered
        assert "without confirm" not in lowered
        assert "bypass" not in lowered


def test_contacts_lookup_intent() -> None:
    hints = detect_intents("Who is my wife in my contacts?")
    assert any(h.kind == "contacts" for h in hints)
    assert not any(h.kind == "sms_send" for h in hints)
    follow = detect_intents(
        "proceed",
        history=[
            {"role": "user", "content": "Who is my wife in my contacts?"},
            {"role": "assistant", "content": "I would need to call the contacts tool."},
        ],
    )
    assert any(h.kind == "contacts" for h in follow)


def test_tasks_and_goal_delete_intents() -> None:
    assert any(h.kind == "tasks" for h in detect_intents("List my tasks. Do not text anyone."))
    assert any(h.kind == "goals" for h in detect_intents("delete that goal"))
    assert any(h.kind == "goals" for h in detect_intents("Now delete both of those goals"))
    from arelis.core.preflight import draft_browser_args

    assert draft_browser_args("whats on this page?") == {"action": "read"}
    opened = draft_browser_args("I accidentally closed the window, please reopen x.com")
    assert opened["action"] == "open"
    assert "x.com" in opened["url"]
    assert any(h.kind == "browser" for h in detect_intents("reopen x.com"))
    assert any(h.kind == "browser_read" for h in detect_intents("whats on this page?"))

    youtube = draft_browser_args("Open YouTube in your browser.")
    assert youtube["action"] == "open"
    assert "youtube" in youtube["url"].lower()
    assert "x.com" not in youtube["url"].lower()
    yt_hints = detect_intents("Open YouTube in your browser.")
    assert "browser" in {t for h in yt_hints for t in h.expected_tools}
    assert "web_search" not in {t for h in yt_hints for t in h.expected_tools}

    video_search = detect_intents(
        "Search for interferometry videos and tell me the top three results."
    )
    video_tools = {t for h in video_search for t in h.expected_tools}
    assert "browser" in video_tools
    assert "web_search" not in video_tools
    drafted = draft_browser_args(
        "Search for interferometry videos and tell me the top three results."
    )
    assert drafted["action"] == "search"
    assert drafted["site"] == "youtube"
    assert "interferometry" in drafted["query"].lower()
    assert "tell me" not in drafted["query"].lower()
    assert "top three" not in drafted["query"].lower()

    web = detect_intents("Search the web for recent news about interferometry")
    web_tools = {t for h in web for t in h.expected_tools}
    # 6.3: must not become a browser drive.
    assert "browser" not in web_tools

    from arelis.core.preflight import rewrite_browser_calls

    for phrase in (
        "go to sign in",
        "click on the sign in the top right corner",
        "i would like to proceed with signing in.",
        "sign me in",
        "take me to the login",
        "log me in",
        "go to the login page",
        "go to signin",
    ):
        hints = detect_intents(phrase)
        assert any(h.kind == "browser_click" for h in hints), phrase
        assert draft_browser_args(phrase) == {"action": "click", "text": "Sign in"}
        nudge = next(h.nudge for h in hints if h.kind == "browser_click")
        assert "click" in nudge.lower()
        assert "goto_sign_in" in nudge
    howto = detect_intents("how do I sign in to github from the terminal")
    assert not any(h.kind == "browser_click" for h in howto)
    rewritten = rewrite_browser_calls(
        [("browser", {"action": "goto_sign_in"})]
    )
    assert rewritten == [("browser", {"action": "snapshot"})]
    kept = rewrite_browser_calls([("browser", {"action": "click", "ref": "e3"})])
    assert kept == [("browser", {"action": "click", "ref": "e3"})]
    navigated = rewrite_browser_calls(
        [
            (
                "browser",
                {
                    "action": "navigate",
                    "url": "https://www.youtube.com/account_signin",
                },
            )
        ],
        text="go to signin",
    )
    assert navigated == [("browser", {"action": "snapshot"})]

    from arelis.core.preflight import draft_signin_click_args, signin_ref_from_snapshot

    snap = (
        "title: optics videos - YouTube\n"
        "url: https://www.youtube.com/results?search_query=optics+videos\n"
        "elements:\n"
        "[e5] input type=search\n"
        "[e11] button 'Sign in'\n"
        "[e24] button 'Sign in to like videos, comment, and subscribe'\n"
    )
    assert signin_ref_from_snapshot(snap) == "e11"
    assert draft_signin_click_args(snap) == {"action": "click", "ref": "e11"}
    assert signin_ref_from_snapshot("elements:\n[e1] a 'Home'\n") is None


def _expected(text: str) -> set[str]:
    out: set[str] = set()
    for hint in detect_intents(text):
        out |= set(hint.expected_tools or ())
    return out


def test_analyze_a_picture_reaches_vision_not_the_table_reader() -> None:
    """"Analyze" is the word the user says, and it named a pandas tool.

    Every one of these used to produce no expected tool at all, which left the
    ask to a model looking at a menu where `analyze` reads spreadsheets — and
    answers "Unsupported file type: .png".
    """
    for phrase in (
        "analyze this picture",
        "analyze the photo i pasted",
        "analyze the screenshot",
        "analyze the image",
        "analyse the picture",
        "analyze my photograph",
    ):
        assert "vision" in _expected(phrase), phrase
        assert "analyze" not in _expected(phrase), phrase


def test_analyze_a_document_reaches_doc_extract() -> None:
    for phrase in (
        "analyze the document i just gave you",
        "analyze this pdf",
        "what does this document say",
        "summarize the document",
        "go through these documents",
        "read the pdf",
    ):
        assert "doc_extract" in _expected(phrase), phrase


def test_the_document_nudge_says_not_to_ask_permission() -> None:
    """Measured, not stylistic.

    Without the closing clause this nudge routed correctly and qwen2.5:7b still
    answered in prose three times out of three, hedging about needing access
    instead of calling doc_extract. With it, 3/3 called the tool. Every sibling
    nudge in preflight.py ends the same way for the same reason.
    """
    hints = [h for h in detect_intents("analyze the document I gave you") if h.kind == "docs"]
    assert hints
    nudge = hints[0].nudge.lower()
    assert "do not ask permission" in nudge
    assert "doc_extract" in nudge


def test_a_table_ask_still_belongs_to_analyze() -> None:
    for phrase in ("analyze sales.csv", "analyze the spreadsheet"):
        assert "analyze" in _expected(phrase), phrase
        assert "vision" not in _expected(phrase), phrase
        assert "doc_extract" not in _expected(phrase), phrase


def test_the_document_words_that_are_not_asks_stay_put() -> None:
    """A bare noun is not a request to read one.

    "document this decision" is a write, "documentation" is not a document, and
    "email me the pdf" is a send. Forcing doc_extract on any of them would spend
    a round opening a file nobody named.
    """
    for phrase in (
        "document this decision in the readme",
        "check the documentation for that flag",
        "email me the pdf",
        "save it as a pdf",
    ):
        assert "doc_extract" not in _expected(phrase), phrase


def test_create_a_pdf_reaches_document_not_extract() -> None:
    for phrase in (
        "create a pdf about the dirac equation",
        "make a pdf",
        "save it as a pdf",
        "export this as a csv",
        "write a word document",
    ):
        assert "document" in _expected(phrase), phrase
        assert "doc_extract" not in _expected(phrase), phrase


def test_inspect_preflight_names_the_path_and_skips_stale_sends() -> None:
    history_sms = [
        {"role": "user", "content": "Text Brian"},
        {"role": "assistant", "content": "What should I say?"},
    ]
    history_email = [
        {
            "role": "user",
            "content": "Email Brian subject: Hi body: Hello there friend.",
        },
        {"role": "assistant", "content": "Ready to send when you say so."},
    ]
    ask = "what's in policy.py?"
    hints = detect_intents(ask, history=history_sms)
    inspect = next(h for h in hints if h.kind == "inspect")
    assert inspect.expected_tools == ("workspace",)
    assert "arelis/tools/policy.py" in inspect.nudge
    assert "workspace(action=read)" in inspect.nudge
    assert "do not ask permission" in inspect.nudge.lower()
    assert not any(h.kind == "sms_send" for h in hints)
    email_hints = detect_intents(ask, history=history_email)
    assert any(h.kind == "inspect" for h in email_hints)
    assert not any(h.kind == "compose_email" for h in email_hints)


def test_inspect_write_preflight_is_allow_not_a_read() -> None:
    hints = detect_intents("fix your confirm gate")
    kinds = {h.kind for h in hints}
    assert "inspect_write" in kinds or "workspace_write" in kinds
    assert "inspect" not in kinds
    write = next(
        h for h in hints if h.kind in {"inspect_write", "workspace_write"}
    )
    assert write.expected_tools == ("workspace",)
    assert "Allow" in write.nudge
    assert "write" in write.nudge.lower() or "edit" in write.nudge.lower()
