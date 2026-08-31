"""A turn that is working says so, without being asked.

Tool turns paint nothing until the tools finish — the draft is retracted when a
round turns out to be a preamble — and a full-surface turn was measured at 34 to
36 seconds cold on 2026-08-14. The proof of life used to be: a composer
placeholder that said "model loading…" after the model had loaded, a Thinking dock
that is closed by default, and an honest "still working" line that only fired if
you pressed Esc to cancel.

These cover the copy and the state machine. The widget half — that the shimmer is
hung off the busy flag, so it cannot outlive its turn — is checked in
test_ui_polish.py where a window already exists.
"""

from __future__ import annotations

from arelis.ui.status_copy import (
    THINKING_STATUS,
    WAITING_STATUS,
    WARMING_STATUS,
    tool_status_line,
)


def test_the_errand_is_named_not_the_tool() -> None:
    """The user did not pick the tool names and should not have to learn them.

    "checking the weather" contains the word weather because that is the English
    for it. What must not appear is the identifier — web_search, send_sms — or
    anything shaped like a call.
    """
    assert "checking the weather" in tool_status_line("weather")
    assert "searching the web" in tool_status_line("web_search")
    assert "writing the text" in tool_status_line("send_sms")

    from arelis.ui.status_copy import _ERRANDS

    for tool in _ERRANDS:
        line = tool_status_line(tool)
        if "_" in tool:
            assert tool not in line, tool
        assert "(" not in line and "{" not in line, tool
        assert "call" not in line.lower(), tool


def test_an_action_sharpens_the_line_where_it_matters() -> None:
    assert "saving the file" in tool_status_line("workspace", {"action": "write"})
    assert "keeping that note" in tool_status_line("workspace", {"action": "keep"})
    assert "reading the file" in tool_status_line("workspace", {"action": "read"})
    assert "adding that task" in tool_status_line("tasks", {"action": "add"})
    assert "checking your tasks" in tool_status_line("tasks", {"action": "list"})


def test_an_unknown_action_falls_back_to_the_tools_own_errand() -> None:
    assert "reading the file" in tool_status_line("workspace", {"action": "chmod"})
    assert "checking your email" in tool_status_line("inbox", {})


def test_a_new_tool_reads_as_dull_rather_than_wrong() -> None:
    """Better an unpolished sentence than an invented errand."""
    assert tool_status_line("some_new_tool") == "✦ using some_new_tool…"


def test_a_nameless_tool_falls_back_to_the_waiting_state() -> None:
    assert tool_status_line("") == THINKING_STATUS
    assert tool_status_line("   ", {"action": "read"}) == THINKING_STATUS


def test_every_line_is_short_enough_for_one_row() -> None:
    from arelis.ui.status_copy import _ERRANDS

    for tool in _ERRANDS:
        assert len(tool_status_line(tool)) <= 48, tool


def test_the_waiting_state_describes_the_right_side_of_the_wait() -> None:
    """An Allow card means the app is blocked on a person, not working."""
    assert "waiting for you" in WAITING_STATUS
    assert WAITING_STATUS != THINKING_STATUS


def test_warmup_is_not_called_thinking() -> None:
    """The first turn waits on the prefix seed. 'thinking' made that look hung."""
    assert "loading the model" in WARMING_STATUS
    assert WARMING_STATUS != THINKING_STATUS
    assert len(WARMING_STATUS) <= 48


def test_the_errands_only_name_tools_the_registry_offers() -> None:
    """A line for a deleted tool is copy that can never show.

    briefing and attention went on 2026-08-14; this is the check that notices the
    next time.
    """
    import arelis.tools as tools_pkg
    from arelis.config import load_config
    from arelis.tools import build_tool_registry
    from arelis.ui.status_copy import _BY_ACTION, _ERRANDS
    from arelis.workspace import WorkspaceRoots

    config = load_config()
    registry = build_tool_registry(
        config, WorkspaceRoots.from_config(config), allow_send=True, memory_store=None
    )
    # Optional local models mean a given machine may not build camera or vision,
    # so judge against what the package knows how to build too.
    buildable = {
        getattr(getattr(tools_pkg, attr), "name", "")
        for attr in dir(tools_pkg)
        if attr.endswith("Tool")
    }
    known = set(registry.names()) | {n for n in buildable if n}

    unknown = sorted((set(_ERRANDS) | set(_BY_ACTION)) - known)
    assert not unknown, f"status copy for tools that do not exist: {unknown}"


def test_status_shows_without_being_asked_and_never_outlives_the_turn(
    arelis_window,
) -> None:
    """The blank-thread problem, at the level where it actually happens.

    Hung off the busy flag so that a turn ending at the watchdog clears it as
    surely as one ending at an answer.
    """
    from arelis.core.events import Event, EventType

    window = arelis_window()
    window._set_busy(True)
    # isVisible() is false for any child of a hidden window; isHidden() is the
    # widget's own show/hide latch.
    assert not window.chat.progress.isHidden()
    assert "thinking" in window.chat.progress.text()

    window._on_event(Event(EventType.TOOL_START, {"tool": "weather", "args": {"days": 2}}))
    assert "checking the weather" in window.chat.progress.text()
    # The developer view keeps the arguments; the transcript does not.
    assert "days" not in window.chat.progress.text()

    window._on_event(Event(EventType.TOOL_RESULT, {"tool": "weather", "ok": True}))
    assert "thinking" in window.chat.progress.text()

    window._on_event(Event(EventType.ASSISTANT_DELTA, {"text": "It will be"}))
    # First tokens used to hide the line, so a preamble-then-tool flash was
    # "thinking…" gone then back. Stay up until the answer is finished.
    assert not window.chat.progress.isHidden()
    assert "thinking" in window.chat.progress.text()

    # A draft that turns out to be a preamble empties the thread again. This is
    # the moment that made three spoken SMS turns look dead.
    window._on_event(Event(EventType.ASSISTANT_RETRACT, {}))
    assert not window.chat.progress.isHidden()

    window._on_event(Event(EventType.ASSISTANT_DONE, {"text": "It will be sunny."}))
    assert window.chat.progress.isHidden()


def test_a_first_turn_during_warmup_says_loading_not_thinking(arelis_window) -> None:
    from arelis.core.events import Event, EventType
    from arelis.llm.startup import WARMUP_READY

    window = arelis_window()

    class _Warming:
        def warmup_pending(self) -> bool:
            return True

    window.router = _Warming()  # type: ignore[assignment]
    window._set_busy(True)
    assert "loading the model" in window.chat.progress.text()

    window._on_event(Event(EventType.STATUS, {"message": WARMUP_READY}))
    assert "thinking" in window.chat.progress.text()
    assert "loading the model" not in window.chat.progress.text()


def test_an_allow_card_says_it_is_waiting_on_you_not_working(arelis_window) -> None:
    from arelis.core.events import Event, EventType

    window = arelis_window()
    window._set_busy(True)
    window._on_event(Event(EventType.TOOL_START, {"tool": "send_sms", "args": {}}))
    assert "writing the text" in window.chat.progress.text()
    window._on_event(
        Event(
            EventType.TOOL_CONFIRM,
            {"id": "c1", "tool": "send_sms", "summary": "text your wife"},
        )
    )
    assert "waiting for you" in window.chat.progress.text()


def test_clicking_thinking_status_opens_the_dock_or_pulses_it(arelis_window) -> None:
    """The line is a control, not a hyperlink. Closed dock opens; open dock pulses."""
    from PySide6.QtCore import Qt

    window = arelis_window()
    window.think_dock.hide()
    window._set_busy(True)
    assert window.chat.progress.cursor().shape() == Qt.CursorShape.PointingHandCursor
    window.chat.progress_clicked.emit()
    # isVisible() is false for any child of a hidden window; isHidden() is the
    # widget's own show/hide latch.
    assert not window.think_dock.isHidden()
    assert not window.think_host.has_attention

    window.chat.progress_clicked.emit()
    assert window.think_host.has_attention
    window._on_think_pulse_done()
    assert not window.think_host.has_attention
