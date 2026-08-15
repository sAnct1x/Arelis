"""The chords a user can find, and the ones the window actually installs.

Fifteen chords existed and eleven were written down nowhere a user would look:
two lines of small mono text on the idle orbit, and QAction shortcuts visible
only if you opened the View menu. The sheet fixes that, and these checks stop it
becoming a list of chords the app no longer honours.
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence

from arelis.ui.shortcuts import SHORTCUTS, ShortcutsSheet, chords, groups, normalise


def test_every_installed_shortcut_is_written_down(arelis_window) -> None:
    """The drift check. A chord the window has and the sheet does not is a
    feature the user cannot discover."""
    window = arelis_window()
    installed: set[str] = set()
    for action in window.actions():
        for sequence in action.shortcuts():
            text = sequence.toString(QKeySequence.SequenceFormat.PortableText)
            if text:
                installed.add(normalise(text))

    missing = sorted(installed - chords())
    assert not missing, (
        f"the window installs chords the sheet does not list: {missing}. "
        "Add them to SHORTCUTS or the user will never find them."
    )


def test_the_sheet_does_not_promise_chords_that_do_nothing(arelis_window) -> None:
    """The other direction, allowing for the chords handled outside QAction.

    Ctrl+M and Ctrl+Shift+M go through the window's eventFilter rather than an
    action, because key repeat on Windows fires a QAction twice. Enter, Esc and
    Ctrl+Shift+A belong to the composer.
    """
    handled_elsewhere = {
        normalise(c) for c in ("Ctrl+M", "Ctrl+Shift+M", "Enter", "Esc", "Ctrl+Shift+A")
    }
    window = arelis_window()
    installed = {
        normalise(seq.toString(QKeySequence.SequenceFormat.PortableText))
        for action in window.actions()
        for seq in action.shortcuts()
    }

    invented = sorted(chords() - installed - handled_elsewhere)
    assert not invented, f"the sheet lists chords nothing honours: {invented}"


def test_plus_is_one_chord_and_not_two() -> None:
    """QKeySequence prints Ctrl+= for what a keyboard calls plus."""
    assert normalise("Ctrl++") == normalise("Ctrl+=")
    assert normalise("CTRL+1") == "ctrl+1"


def test_groups_keep_their_order_and_do_not_repeat_the_heading() -> None:
    names = [name for name, _rows in groups()]
    assert names == list(dict.fromkeys(names)), "a group appears twice"
    assert names[0] == "voice", "talking is what this app is for; put it first"
    assert sum(len(rows) for _n, rows in groups()) == len(SHORTCUTS)


def test_the_sheet_builds_and_shows_every_chord(qt_app) -> None:
    sheet = ShortcutsSheet()
    try:
        from PySide6.QtWidgets import QLabel

        shown = {label.text() for label in sheet.findChildren(QLabel)}
        for _group, chord, what in SHORTCUTS:
            assert chord in shown, chord
            assert what in shown, what
    finally:
        sheet.deleteLater()


def test_f1_opens_the_sheet_and_reuses_the_one_window(arelis_window) -> None:
    window = arelis_window()
    window._open_shortcuts()
    first = window._shortcuts_sheet
    assert first is not None
    window._open_shortcuts()
    assert window._shortcuts_sheet is first, "a second sheet stacked on the first"
