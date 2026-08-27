"""Chat empty state is the Orbit idle face."""

from __future__ import annotations

from arelis.ui.panels.chat import ChatPanel
from arelis.ui.void_idle import _LISTEN_IDLE, OrbitIdle


def test_empty_state_is_orbit_idle(qt_app) -> None:
    panel = ChatPanel()
    panel.show()
    assert panel.empty.isVisible()
    assert isinstance(panel.empty, OrbitIdle)
    # Against the constant, not a phrase: the idle line used to invite typing and
    # now names the talk chord, and a substring check went stale silently.
    assert panel.empty.listen_word.text() == _LISTEN_IDLE
    assert "hey arelis" in panel.empty.listen_word.text().lower()
    panel.add_user("hi")
    assert not panel.empty.isVisible()
    assert panel.view.isVisible()
    assert panel.has_messages


def test_unchanged_parked_gutter_does_not_move_scroll(qt_app) -> None:
    """30s notify/readiness polls re-place the orbit at the same pixel width.

    Restyling QTextBrowser on that path used to shove the transcript up a line.
    """
    panel = ChatPanel()
    panel.resize(480, 360)
    panel.show()
    panel.add_user("hello " * 24)
    panel.finish_assistant("reply " * 40)
    panel.set_parked_gutter(64)
    bar = panel.view.verticalScrollBar()
    if bar.maximum() > 0:
        bar.setValue(max(0, bar.maximum() - 30))
    pos = bar.value()
    style = panel.view.styleSheet()
    panel.set_parked_gutter(64)
    assert bar.value() == pos
    assert panel.view.styleSheet() == style
    panel.set_parked_gutter(80)
    _l, _t, right, _b = panel.layout().getContentsMargins()
    assert right == 80
