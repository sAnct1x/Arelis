"""The one question Arelis asks before it starts.

Which folder it may work in, stated in the terms that actually apply: read,
create, change, delete. That wording is not padding. A user agreeing to "choose a
workspace folder" has agreed to something filing-cabinet shaped; a user agreeing
that Arelis "can read, create, change and delete files here" has agreed to what is
really being granted, and can weigh it. Anything vaguer would be collecting a
click rather than consent.

Deliberately not a wizard. There is exactly one decision, it has a sane default
already filled in, and the fastest correct path through it is a single click. No
tour, no account, no model download, no telephone number -- everything else Arelis
needs it asks for at the moment it needs it, which is also the moment the request
makes sense.

See ``arelis.onboarding`` for what gets written down; this module is only the
asking.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from arelis import onboarding
from arelis.ui.theme import COLORS, FONTS


class FirstRunDialog(QDialog):
    """Confirm or change the folder Arelis may work in."""

    def __init__(self, suggested: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Welcome to Arelis")
        self.setModal(True)
        self._root = suggested

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        heading = QLabel("Choose the folder Arelis may work in")
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(heading)

        # The permission in plain words. "Work in" is friendly and imprecise, so
        # the sentence that follows says exactly what it means, including delete.
        body = QLabel(
            "Arelis can read, create, change and delete files inside this "
            "folder, and nowhere else on your PC. Everything it makes for you — "
            "reports, screenshots, voice clips — is saved here too.\n\n"
            "You can change this later, or add more folders, in "
            "Settings → Roots."
        )
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {COLORS['text']};")
        layout.addWidget(body)

        self._path_label = QLabel(str(self._root))
        self._path_label.setWordWrap(True)
        # Selectable so it can be copied. Someone deciding whether to grant this
        # may well want to go and look at the folder first.
        self._path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._path_label.setStyleSheet(
            f"font-family: {FONTS['mono']}; color: {COLORS['accent2']};"
            f"padding: 8px 10px; border: 1px solid {COLORS['edge']};"
            "border-radius: 6px;"
        )
        layout.addWidget(self._path_label)

        note = QLabel(
            "This folder will be created if it does not exist yet. Your "
            "settings, contacts and conversation history are kept separately, "
            "outside it."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        layout.addWidget(note)

        buttons = QHBoxLayout()
        change = QPushButton("Choose a different folder…")
        change.clicked.connect(self._choose)
        buttons.addWidget(change)
        buttons.addStretch(1)
        accept = QPushButton("Start Arelis")
        accept.setDefault(True)
        accept.clicked.connect(self.accept)
        buttons.addWidget(accept)
        layout.addLayout(buttons)

    @property
    def root(self) -> Path:
        return self._root

    def _choose(self) -> None:
        picked = QFileDialog.getExistingDirectory(
            self,
            "Choose the folder Arelis may work in",
            str(self._root.parent if self._root.parent.is_dir() else self._root),
        )
        if picked:
            self._root = Path(picked)
            self._path_label.setText(str(self._root))


def prompt_for_workspace_root(parent: QWidget | None = None) -> Path | None:
    """Ask, record the answer, and return the root. None when nothing was asked.

    Closing the window with Escape or the title bar counts as accepting the
    folder on display. That is defensible here and would not be for a broader
    permission: the default is a folder Arelis creates for itself under
    Documents, the sentence granting access is on screen beside it, and the
    alternative is re-asking on every single launch until the user engages, which
    trains people to dismiss dialogs without reading them.
    """
    if not onboarding.needs_prompt():
        return None
    dialog = FirstRunDialog(onboarding.suggested_root(), parent)
    dialog.exec()
    return onboarding.record_choice(dialog.root)
