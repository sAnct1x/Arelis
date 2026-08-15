"""What a machine with no history shows, and what it does when you click it.

The idle face is deliberately bare — an orbit and "what are we working on" —
which is right for the owner and tells a first-time user nothing about what this
can reach. With no sessions the ghost column stood empty as well, so the one
place with room for guidance was the one place showing nothing.
"""

from __future__ import annotations

from arelis.ui.void_idle import FIRST_RUN_ASKS, OrbitIdle


def _ghost_titles(idle: OrbitIdle) -> list[str]:
    from PySide6.QtWidgets import QLabel

    out: list[str] = []
    layout = idle._ghost_layout
    for i in range(layout.count()):
        widget = layout.itemAt(i).widget()
        if widget is None:
            continue
        labels = widget.findChildren(QLabel)
        out.extend(label.text() for label in labels)
    return out


def test_an_empty_history_offers_somewhere_to_start(qt_app) -> None:
    idle = OrbitIdle()
    try:
        idle.set_sessions([])
        shown = _ghost_titles(idle)
        assert "TRY" in shown
        for ask in FIRST_RUN_ASKS:
            assert ask in shown
    finally:
        idle.deleteLater()


def test_the_suggestions_step_aside_for_real_history(qt_app) -> None:
    idle = OrbitIdle()
    try:
        idle.set_sessions([("s1", "the sherpa work")])
        shown = _ghost_titles(idle)
        assert "RECENT" in shown
        assert "TRY" not in shown
        assert "the sherpa work" in shown
        for ask in FIRST_RUN_ASKS:
            assert ask not in shown
    finally:
        idle.deleteLater()


def test_going_back_to_an_empty_history_brings_them_back(qt_app) -> None:
    """Deleting every session is the one way to see first run twice."""
    idle = OrbitIdle()
    try:
        idle.set_sessions([("s1", "something")])
        idle.set_sessions([])
        assert "TRY" in _ghost_titles(idle)
    finally:
        idle.deleteLater()


def test_a_suggestion_asks_for_the_composer_rather_than_sending(qt_app) -> None:
    idle = OrbitIdle()
    seen: list[str] = []
    sent: list[str] = []
    try:
        idle.suggestion_clicked.connect(seen.append)
        idle.session_clicked.connect(sent.append)
        idle.set_sessions([])
        row = idle._ghost_layout.itemAt(0).widget()
        row.clicked.emit()
        assert seen == [FIRST_RUN_ASKS[0]]
        # Not a session load, which is what the same chip means when it says
        # RECENT. Mixing the two would open a conversation nobody asked for.
        assert sent == []
    finally:
        idle.deleteLater()


def test_the_suggestion_lands_in_the_composer_unsent(qt_app) -> None:
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    submitted: list[str] = []
    try:
        stage.submitted.connect(lambda *a: submitted.append("sent"))
        stage.chat.empty.set_sessions([])
        row = stage.chat.empty._ghost_layout.itemAt(0).widget()
        row.clicked.emit()
        assert stage.input.text() == FIRST_RUN_ASKS[0]
        assert not submitted, "a first-run hint must never send a turn on one click"
    finally:
        stage.deleteLater()


def test_the_opening_asks_reach_different_parts_of_the_surface(qt_app) -> None:
    """Three asks that all landed on the same tool would teach one thing."""
    assert len(FIRST_RUN_ASKS) == len(set(FIRST_RUN_ASKS))
    joined = " ".join(FIRST_RUN_ASKS).lower()
    assert "weather" in joined
    assert "calendar" in joined
    assert "remember" in joined
