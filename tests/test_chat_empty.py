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
    assert "ctrl+shift+m" in panel.empty.listen_word.text().lower()
    panel.add_user("hi")
    assert not panel.empty.isVisible()
    assert panel.view.isVisible()
    assert panel.has_messages
