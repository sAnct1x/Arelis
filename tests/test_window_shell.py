"""The other person at the sodium desk.

Construct one ArelisWindow, type in the composer, press Enter, click View
and the theme actions, count HWNDs. Cesium / voice / Chrome stay unopened
— pytest is offscreen on purpose, not because those paths are skipped as
ideas.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from arelis.tools.policy import confirm_mode
from arelis.ui.surface_report import report_lines
from arelis.ui.theme import active_theme
from arelis.ui.world_host import should_offer_world, world_available


def _watched_count(lines: list[str], name: str) -> int:
    prefix = f"  {name}: "
    for line in lines:
        if line.startswith(prefix):
            return int(line[len(prefix) :])
    return 0


def test_construct_is_one_window_and_dispose_clears_it(arelis_window) -> None:
    window = arelis_window()
    lines = report_lines(window)
    assert _watched_count(lines, "ArelisWindow") == 1
    assert _watched_count(lines, "ConversationStage") == 1
    assert _watched_count(lines, "HistoryPanel") == 1
    window.dispose()
    assert window._disposed


def test_view_toggles_do_not_mint_a_second_window(arelis_window, qt_app) -> None:
    window = arelis_window()
    before = len([w for w in QApplication.topLevelWidgets() if type(w).__name__ == "ArelisWindow"])
    window._toggle_thinking(True)
    window._toggle_workspace(True)
    window._toggle_history(True)
    qt_app.processEvents()
    after = len([w for w in QApplication.topLevelWidgets() if type(w).__name__ == "ArelisWindow"])
    assert after == before == 1
    assert _watched_count(report_lines(window), "ArelisWindow") == 1
    window._toggle_thinking(False)
    window._toggle_workspace(False)
    window._toggle_history(False)


def test_theme_switch_is_one_hwnd_and_flips_confirm_mode(arelis_window) -> None:
    from arelis.ui.settings_host import apply_window_theme

    window = arelis_window()
    assert active_theme() == "sodium"
    assert confirm_mode() == "card"
    apply_window_theme(window, "filament", persist=False)
    assert active_theme() == "filament"
    assert confirm_mode() == "voice"
    assert not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    apply_window_theme(window, "sodium", persist=False)
    assert active_theme() == "sodium"
    assert confirm_mode() == "card"
    assert _watched_count(report_lines(window), "ArelisWindow") == 1


def test_reality_offer_is_the_grant_not_cesium() -> None:
    """Pytest never opens the plate. The grant is the pin."""
    assert world_available() is True
    assert should_offer_world("physics") is True
    assert should_offer_world("lab") is False


def test_user_types_a_line_and_presses_enter(arelis_window, qt_app) -> None:
    """Sit at the composer: type, Return, the line leaves and the turn is busy."""
    import threading

    from PySide6.QtTest import QTest

    window = arelis_window()
    loop = window.loop
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        composer = window.conversation.input
        composer.setFocus()
        QTest.keyClicks(composer, "hello from the desk")
        qt_app.processEvents()
        assert composer.toPlainText() == "hello from the desk"
        QTest.keyClick(composer, Qt.Key.Key_Return)
        qt_app.processEvents()
        assert composer.toPlainText() == ""
        assert window._turn_busy
        assert window.chat._last_user_text == "hello from the desk"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)


def test_user_clicks_view_thinking_and_it_is_still_one_window(
    arelis_window, qt_app
) -> None:
    """The View → thinking action, not a private helper."""
    window = arelis_window()
    window._reset_layout()
    assert window.think_dock.isHidden()
    before = len(
        [w for w in QApplication.topLevelWidgets() if type(w).__name__ == "ArelisWindow"]
    )
    window.act_thinking.trigger()
    qt_app.processEvents()
    assert not window.think_dock.isHidden()
    after = len(
        [w for w in QApplication.topLevelWidgets() if type(w).__name__ == "ArelisWindow"]
    )
    assert after == before == 1
    window.act_thinking.trigger()
    qt_app.processEvents()
    assert window.think_dock.isHidden()


def test_user_picks_filament_from_the_theme_action(arelis_window, qt_app) -> None:
    """Theme menu click after the first-run ack. Same HWND, voice confirms."""
    window = arelis_window()
    window.config.setdefault("ui", {})["filament_ack"] = True
    window._theme_actions["filament"].trigger()
    qt_app.processEvents()
    assert active_theme() == "filament"
    assert confirm_mode() == "voice"
    assert not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    window._theme_actions["sodium"].trigger()
    qt_app.processEvents()
    assert active_theme() == "sodium"
    assert confirm_mode() == "card"
    assert _watched_count(report_lines(window), "ArelisWindow") == 1
