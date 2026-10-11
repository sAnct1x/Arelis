"""The shortcut sheet and the window have to name the same chords.

On main the sheet was missing Ctrl+N, Ctrl+K, Ctrl+Shift+F, and Ctrl+F.
Ctrl+F is find in this chat, and it is bound with the others.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QShortcut

from arelis.ui.shortcuts import chords, normalise

# Spoken or handled on the composer, not installed as window QActions.
_COMPOSER_ONLY = frozenset(
    {
        "ctrl+m",
        "ctrl+shift+m",
        "enter",
        "esc",
        "ctrl+shift+a",
    }
)


def _action_chords(window) -> set[str]:
    found: set[str] = set()
    for action in window.actions():
        for seq in action.shortcuts():
            text = seq.toString()
            if text:
                found.add(normalise(text))
    return found


def test_shortcut_sheet_lists_comfort_chords() -> None:
    want = {"ctrl+f", "ctrl+k", "ctrl+n", "ctrl+shift+f"}
    assert want <= chords()


def test_every_window_chord_is_on_the_sheet(arelis_window) -> None:
    window = arelis_window()
    bound = _action_chords(window)
    sheet = chords()
    assert bound == sheet - _COMPOSER_ONLY
    assert sheet - bound == _COMPOSER_ONLY
    assert {"ctrl+n", "ctrl+k", "ctrl+shift+f", "ctrl+f"} <= bound

    installed: set[str] = set()
    for shortcut in window.findChildren(QShortcut):
        text = shortcut.key().toString()
        if text:
            installed.add(normalise(text))
    assert installed <= sheet
    assert "ctrl+shift+a" in installed
    assert "esc" in installed or "escape" in installed

    ctrl = Qt.KeyboardModifier.ControlModifier
    shift = Qt.KeyboardModifier.ShiftModifier
    dictate = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_M, ctrl)
    talk = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_M, ctrl | shift)
    assert window._is_voice_hotkey(dictate)
    assert window._is_voice_hotkey(talk)
