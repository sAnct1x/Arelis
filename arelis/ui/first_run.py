"""The one question Arelis asks before it starts.

Which folder it may work in, stated in the terms that actually apply: read,
create, change, delete. That wording is not padding. A user agreeing to "choose a
workspace folder" has agreed to something filing-cabinet shaped; a user agreeing
that Arelis "can read, create, change and delete files here" has agreed to what is
really being granted, and can weigh it. Anything vaguer would be collecting a
click rather than consent.

Deliberately not a tour of the product. There is exactly one permission on
this glass: the folder. Model setup is a separate dialog after this, because
that is a recommendation, not a grant. No account, no phone number.

See ``arelis.onboarding`` for what gets written down; this module is only the
asking.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QWidget

from arelis import onboarding
from arelis.ui.dialog import GlassDialog


class FirstRunDialog(GlassDialog):
    """Confirm or change the folder Arelis may work in.

    On the same glass as the rest of the app rather than a native dialog,
    because this is the first thing anyone sees and a grey Windows box in front
    of a black window is a first impression of two programs, not one.
    """

    def __init__(self, suggested: Path, parent: QWidget | None = None) -> None:
        super().__init__("Welcome to Arelis", parent=parent, width=520)
        self._root = suggested

        self.add_text("Choose the folder Arelis may work in", role="DialogHeading")
        # The permission in plain words. "Work in" is friendly and imprecise, so
        # the sentence that follows says exactly what it means, including delete.
        self.add_text(
            "Arelis can read, create, change and delete files inside this "
            "folder, and nowhere else on your PC. Everything it makes for you — "
            "reports, screenshots, voice clips — is saved here too.\n\n"
            "You can change this later, or add more folders, in "
            "Settings → Roots."
        )

        self._path_label = self.add_text(str(self._root), role="DialogPath")
        # Selectable so it can be copied. Someone deciding whether to grant this
        # may well want to go and look at the folder first.
        self._path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.add_text(
            "This folder will be created if it does not exist yet. Your "
            "settings, contacts and conversation history are kept separately, "
            "outside it.",
            role="DialogNote",
        )

        change = self.add_button("Choose a different folder…", leading=True)
        change.clicked.connect(self._choose)
        accept = self.add_button("Continue", primary=True)
        accept.clicked.connect(self.accept)
        accept.setDefault(True)
        accept.setFocus()

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
