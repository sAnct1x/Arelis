"""Every chord in one place, and a sheet that shows them.

The chords were only ever discoverable as two lines of small mono text on the
idle orbit — "say hey arelis", "talk or type · esc to clear" — and a
scatter of QAction shortcuts that appear in the View menu if you happen to open
it. Eleven of the fifteen were written down nowhere the user would look.

The list here is the single source of truth, and a test asserts that every
QAction the window installs with a shortcut appears in it, so the sheet cannot
drift into describing an app that no longer exists.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from arelis import __license__, __source_url__, __version__

# (group, chord, what it does). Grouped in the order a person meets them:
# talking first, because that is what this app is for.
SHORTCUTS: tuple[tuple[str, str, str], ...] = (
    ("voice", "Ctrl+Shift+M", "start or stop talking"),
    ("voice", "Ctrl+M", "dictate into the composer without sending"),
    ("conversation", "Enter", "send — or allow, when a card is open"),
    ("conversation", "Esc", "stop the turn, clear the box, or go back to the orbit"),
    ("conversation", "Ctrl+Shift+A", "attach files"),
    ("panels", "Ctrl+1", "thinking — what she is doing, in detail"),
    ("panels", "Ctrl+2", "workspace — the desk: notes and files she made"),
    ("panels", "Ctrl+3", "history — past conversations"),
    ("panels", "Ctrl+4", "notifications"),
    ("panels", "Ctrl+5", "camera"),
    ("panels", "Ctrl+6", "contacts"),
    ("panels", "Ctrl+7", "calendar"),
    ("panels", "Ctrl+8", "Reality — plate"),
    ("window", "Ctrl+,", "settings — audio, window scale, allow"),
    ("window", "F11", "fullscreen"),
    ("window", "F1", "this sheet"),
    ("text", "Ctrl+=", "larger chat text"),
    ("text", "Ctrl+-", "smaller chat text"),
    ("text", "Ctrl+0", "reset chat text size"),
)


def about_line() -> str:
    """What the app is, in one line, for the foot of the sheet.

    A user who never opens a terminal has no other way to answer "which version
    is this" before reporting a bug, and no other prompt that the source they
    are entitled to under the licence exists somewhere.
    """
    return f"arelis {__version__} · {__license__} · {__source_url__}"


def groups() -> list[tuple[str, list[tuple[str, str]]]]:
    """SHORTCUTS as ordered groups, without repeating the group name."""
    out: list[tuple[str, list[tuple[str, str]]]] = []
    for group, chord, what in SHORTCUTS:
        if not out or out[-1][0] != group:
            out.append((group, []))
        out[-1][1].append((chord, what))
    return out


def chords() -> set[str]:
    """Normalised chords, for the drift check against the window's actions."""
    return {normalise(chord) for _group, chord, _what in SHORTCUTS}


def normalise(chord: str) -> str:
    """One spelling per chord, so Ctrl++ and Ctrl+= do not read as two.

    QKeySequence prints "Ctrl+=" for what a keyboard calls plus, and the window
    installs both spellings on the same action.
    """
    text = (chord or "").strip().lower().replace(" ", "")
    return {"ctrl++": "ctrl+=", "ctrl+plus": "ctrl+="}.get(text, text)


class ShortcutsSheet(QDialog):
    """A plain reading surface. Nothing here is configurable, on purpose."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ShortcutsSheet")
        self.setWindowTitle("Shortcuts")
        self.setModal(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)

        title = QLabel("shortcuts")
        title.setObjectName("ShortcutsTitle")
        outer.addWidget(title)

        for group, rows in groups():
            block = QWidget(self)
            grid = QGridLayout(block)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(20)
            grid.setVerticalSpacing(6)

            heading = QLabel(group.upper())
            heading.setObjectName("ShortcutsGroup")
            grid.addWidget(heading, 0, 0, 1, 2)

            for row, (chord, what) in enumerate(rows, start=1):
                key = QLabel(chord)
                key.setObjectName("ShortcutsChord")
                key.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                key.setMinimumWidth(120)
                text = QLabel(what)
                text.setObjectName("ShortcutsWhat")
                text.setWordWrap(True)
                grid.addWidget(key, row, 0)
                grid.addWidget(text, row, 1)

            grid.setColumnStretch(1, 1)
            outer.addWidget(block)

        outer.addStretch(1)

        about = QLabel(about_line())
        about.setObjectName("ShortcutsAbout")
        about.setWordWrap(True)
        about.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        about.setOpenExternalLinks(False)
        outer.addWidget(about)

        self.resize(520, 640)


__all__ = ["SHORTCUTS", "ShortcutsSheet", "about_line", "chords", "groups", "normalise"]
