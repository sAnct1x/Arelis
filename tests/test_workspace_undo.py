"""Ctrl+Z in the workspace editor must undo typing, not wipe the file.

Roadmap 6.7. The editor is a QPlainTextEdit — Qt already has a stack.
The hole is delivery: WorkspacePanel takes StrongFocus for image
left/right, and a chord that lands on the panel (or a ShortcutOverride
the window sees first) used to vanish.

Mutants this file is supposed to catch:

1. Ctrl+Z does nothing (panel swallows the chord, never calls undo).
2. Ctrl+Z clears the file (undo implemented as setPlainText("")).
3. redo missing after we added it (Ctrl+Y / StandardKey.Redo).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence, QTextCursor
from PySide6.QtTest import QTest

from arelis.ui.panels.workspace import WorkspacePanel


def _panel(qt_app) -> WorkspacePanel:
    panel = WorkspacePanel()
    panel.set_file("notes.txt", "from disk", abs_path="/tmp/notes.txt")
    return panel


def _type_at_end(panel: WorkspacePanel, text: str) -> None:
    editor = panel.editor
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    editor.insertPlainText(text)


def _chord(widget, key: Qt.Key, modifiers: Qt.KeyboardModifier) -> None:
    """Send the chord at the panel, the swallow path, not editor.undo()."""
    override = QKeyEvent(QEvent.Type.ShortcutOverride, key, modifiers)
    widget.event(override)
    QTest.keyClick(widget, key, modifiers)


def test_typing_then_ctrl_z_restores_the_previous_text(qt_app) -> None:
    """Mutant: Ctrl+Z is ignored and the typed text stays."""
    panel = _panel(qt_app)
    _type_at_end(panel, " typed")
    assert panel.editor.toPlainText() == "from disk typed"
    assert panel.editor.document().isUndoAvailable()

    _chord(panel, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)

    assert panel.editor.toPlainText() == "from disk"
    assert panel.has_unsaved_changes() is False


def test_ctrl_z_on_a_clean_file_does_not_wipe_it(qt_app) -> None:
    """Mutant: undo is setPlainText('') and the buffer goes empty."""
    panel = _panel(qt_app)
    assert panel.editor.toPlainText() == "from disk"
    assert not panel.editor.document().isUndoAvailable()

    _chord(panel, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)

    assert panel.editor.toPlainText() == "from disk"
    assert panel.editor.toPlainText() != ""


def test_redo_puts_the_typing_back(qt_app) -> None:
    """Mutant: undo works, redo does not."""
    panel = _panel(qt_app)
    _type_at_end(panel, " typed")
    _chord(panel, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert panel.editor.toPlainText() == "from disk"

    redo = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Y,
        Qt.KeyboardModifier.ControlModifier,
    )
    assert redo.matches(QKeySequence.StandardKey.Redo)
    _chord(panel, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)

    assert panel.editor.toPlainText() == "from disk typed"
    assert panel.has_unsaved_changes()


def test_panel_claims_ctrl_z_as_a_shortcut(qt_app) -> None:
    """Mutant: ShortcutOverride is ignored, so the window can steal it."""
    panel = _panel(qt_app)
    event = QKeyEvent(
        QEvent.Type.ShortcutOverride,
        Qt.Key.Key_Z,
        Qt.KeyboardModifier.ControlModifier,
    )
    assert event.matches(QKeySequence.StandardKey.Undo)
    handled = panel.event(event)
    assert handled is True
    assert event.isAccepted()
