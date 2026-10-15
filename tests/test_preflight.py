"""Deterministic intent preflight (no tool execution)."""

from __future__ import annotations

from arelis.core.preflight import detect_intents, preflight_system_message


def test_sms_intent_with_body() -> None:
    hints = detect_intents("Text Brian: Running 10 minutes late")
    assert any(h.kind == "sms_send" for h in hints)
    sms = next(h for h in hints if h.kind == "sms_send")
    assert "brian" in sms.nudge.lower()
    assert "send_sms" in sms.nudge
    assert "number" in sms.nudge.lower()


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
    twitter = draft_browser_args("open twitter in your browser")
    assert twitter["action"] == "open"
    assert "x.com" in twitter["url"].lower()
    spoken = draft_browser_args("take me to x dot com")
    assert spoken["action"] == "open"
    assert "x.com" in spoken["url"].lower()
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
    howto = detect_intents("how do I sign in to github from the terminal")
    assert not any(h.kind == "browser_click" for h in howto)

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

    from arelis.core.preflight import looks_like_browser_open_ask

    assert looks_like_browser_open_ask(
        "go to x.com and take me to the login page if it does not "
        "automatically sign me in."
    )
    assert not looks_like_browser_open_ask(
        "go to amazon.com and add batteries to cart"
    )
    assert not looks_like_browser_open_ask(
        "Hay take me to you tube doc calm and do us search "
        "for the organic chemistry tutor"
    )
    assert not looks_like_browser_open_ask(
        "on his page i want you to pull up the precalculus playlist"
    )


def _expected(text: str) -> set[str]:
    out: set[str] = set()
    for hint in detect_intents(text):
        out |= set(hint.expected_tools or ())
    return out


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


BROWSER_COMPLAINTS = (
    "i never asked you to do anything, why did you open your browser, check the time",
    "why did you open your browser",
    "you shouldn't have opened your browser",
    "no need to open your browser",
    "I didn't ask you to open the browser",
)


