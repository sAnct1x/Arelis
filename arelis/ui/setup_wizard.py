"""Glass: look at this PC, recommend one model, pull it, then a short how-to.

Folder consent is a different dialog. This one is not a permission. Escape on
the recommendation accepts it — same reason as first-run: re-asking trains
people to dismiss without reading, and the recommendation is already on screen.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from arelis.setup.catalog import (
    CATALOG,
    EMBED_TAG,
    CatalogModel,
    by_tag,
    disk_needed_gb,
    family_groups,
    recommend,
    why,
)
from arelis.setup.engine import (
    already_pulled,
    download_ollama_setup,
    find_ollama_exe,
    ollama_reachable,
    pull_tag,
    run_ollama_setup,
    runtime_dir,
    start_ollama,
)
from arelis.setup.hardware import HardwareSnapshot, probe_hardware
from arelis.setup.state import needs_model_setup, record_model_choice
from arelis.ui.dialog import GlassDialog


class _ProbeWorker(QThread):
    finished_with = Signal(object)

    def run(self) -> None:
        try:
            self.finished_with.emit(probe_hardware())
        except Exception as exc:
            snap = HardwareSnapshot(notes=(str(exc),))
            self.finished_with.emit(snap)


class _PrepareWorker(QThread):
    progressed = Signal(str, int, int)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, tag: str, parent=None) -> None:
        super().__init__(parent)
        self._tag = tag
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            self._run()
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)

    def _report(self, status: str, done: int = 0, total: int = 0) -> None:
        if not self._cancel:
            self.progressed.emit(status, done, total)

    def _run(self) -> None:
        if self._cancel:
            return
        if not ollama_reachable():
            exe = find_ollama_exe()
            if exe is None:
                self._report("Downloading the local engine…")
                setup = runtime_dir() / "OllamaSetup.exe"
                download_ollama_setup(setup, progress=self._report)
                if self._cancel:
                    return
                self._report("Installing the local engine…")
                problem = run_ollama_setup(setup)
                if problem:
                    self.failed.emit(problem)
                    return
            problem = start_ollama()
            if problem:
                self.failed.emit(problem)
                return
        if self._cancel:
            return
        if already_pulled(self._tag):
            self._report(f"{self._tag} is already on this PC.")
        else:
            self._report(f"Getting {self._tag}…")
            pull_tag(self._tag, progress=self._report)
        if self._cancel:
            return
        if already_pulled(EMBED_TAG):
            self._report("The small recall model is already on this PC.")
        else:
            self._report("Getting the small recall model…")
            pull_tag(EMBED_TAG, progress=self._report)
        if self._cancel:
            return
        try:
            from arelis.voice.prepare import missing_voice_parts, prepare_voice_files

            if missing_voice_parts(allowed_only=True):
                self._report("Getting the voice files…")
                prepare_voice_files(progress=self._report)
        except Exception:
            # Typing still works. The window will try again and say so.
            pass
        if self._cancel:
            return
        self.finished_ok.emit()


class ModelSetupDialog(GlassDialog):
    def __init__(self, parent=None) -> None:
        super().__init__("Arelis", parent=parent, width=560, closable=True)
        self._hardware = HardwareSnapshot()
        self._picked: CatalogModel = CATALOG[1]
        self._probe: _ProbeWorker | None = None
        self._prepare: _PrepareWorker | None = None

        self._stack = QStackedWidget()
        self.body.addWidget(self._stack)

        self._detect = QWidget()
        detect_l = QVBoxLayout(self._detect)
        detect_l.setContentsMargins(0, 8, 0, 8)
        looking = QLabel("Looking at this PC…")
        looking.setObjectName("DialogHeading")
        note = QLabel(
            "Graphics memory, system memory, and free disk. This stays on "
            "this machine."
        )
        note.setObjectName("DialogNote")
        note.setWordWrap(True)
        detect_l.addWidget(looking)
        detect_l.addWidget(note)
        detect_l.addStretch(1)
        self._stack.addWidget(self._detect)

        self._rec = QWidget()
        rec_l = QVBoxLayout(self._rec)
        rec_l.setContentsMargins(0, 4, 0, 4)
        rec_l.setSpacing(10)
        self._rec_title = QLabel("")
        self._rec_title.setObjectName("DialogHeading")
        self._rec_title.setWordWrap(True)
        self._rec_why = QLabel("")
        self._rec_why.setObjectName("DialogBody")
        self._rec_why.setWordWrap(True)
        self._rec_warn = QLabel("")
        self._rec_warn.setObjectName("DialogWarning")
        self._rec_warn.setWordWrap(True)
        self._rec_warn.hide()
        rec_l.addWidget(self._rec_title)
        rec_l.addWidget(self._rec_why)
        rec_l.addWidget(self._rec_warn)
        rec_l.addStretch(1)
        self._stack.addWidget(self._rec)

        self._pick = QWidget()
        pick_l = QVBoxLayout(self._pick)
        pick_l.setContentsMargins(0, 0, 0, 0)
        intro = QLabel("One model at a time. Pick the one she should think with.")
        intro.setObjectName("DialogNote")
        intro.setWordWrap(True)
        pick_l.addWidget(intro)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        inner_l = QVBoxLayout(inner)
        inner_l.setContentsMargins(0, 8, 0, 8)
        inner_l.setSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._radios: dict[str, QRadioButton] = {}
        for family, models in family_groups():
            head = QLabel(family)
            head.setObjectName("DialogHeading")
            inner_l.addWidget(head)
            for model in models:
                row = QRadioButton(f"{model.title}  ·  {model.download_gb:g} GB")
                row.setObjectName("SetupChoice")
                row.setToolTip(model.summary)
                self._group.addButton(row)
                self._radios[model.tag] = row
                inner_l.addWidget(row)
        inner_l.addStretch(1)
        scroll.setWidget(inner)
        pick_l.addWidget(scroll, stretch=1)
        self._pick_note = QLabel("")
        self._pick_note.setObjectName("DialogNote")
        self._pick_note.setWordWrap(True)
        pick_l.addWidget(self._pick_note)
        self._stack.addWidget(self._pick)

        self._ready = QWidget()
        ready_l = QVBoxLayout(self._ready)
        ready_l.setContentsMargins(0, 8, 0, 8)
        self._ready_title = QLabel("Getting ready")
        self._ready_title.setObjectName("DialogHeading")
        self._ready_status = QLabel("Starting…")
        self._ready_status.setObjectName("DialogBody")
        self._ready_status.setWordWrap(True)
        self._bar = QProgressBar()
        self._bar.setObjectName("DialogProgress")
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        ready_l.addWidget(self._ready_title)
        ready_l.addWidget(self._ready_status)
        ready_l.addWidget(self._bar)
        ready_l.addStretch(1)
        self._stack.addWidget(self._ready)

        self._tour = QWidget()
        tour_l = QVBoxLayout(self._tour)
        tour_l.setContentsMargins(0, 8, 0, 8)
        tour_l.setSpacing(10)
        t1 = QLabel("She's ready")
        t1.setObjectName("DialogHeading")
        t2 = QLabel(
            "Type in the box under the ring. The window will say when "
            "she's listening — then say Hey Arelis.\n\n"
            "When she wants to send a text, send mail, or change a file, "
            "two buttons: allow and deny.\n\n"
            "Mail, phone, and calendar can wait. They live in Settings "
            "when you want them."
        )
        t2.setObjectName("DialogBody")
        t2.setWordWrap(True)
        tour_l.addWidget(t1)
        tour_l.addWidget(t2)
        tour_l.addStretch(1)
        self._stack.addWidget(self._tour)

        self._use = self.add_button("Use this model", primary=True)
        self._other = self.add_button("Choose a different one")
        self._back = self.add_button("Back", leading=True)
        self._go = self.add_button("Let's go", primary=True)
        self._use.clicked.connect(self._begin_prepare)
        self._other.clicked.connect(self._show_picker)
        self._back.clicked.connect(self._show_recommend)
        self._go.clicked.connect(self.accept)
        self._group.buttonClicked.connect(self._sync_pick_note)
        self._hide_footer()

        self._stack.setCurrentIndex(0)
        self._probe = _ProbeWorker(self)
        self._probe.finished_with.connect(self._on_probed)
        self._probe.start()

    def _hide_footer(self) -> None:
        for btn in (self._use, self._other, self._back, self._go):
            btn.hide()

    def _show_recommend(self) -> None:
        self._stack.setCurrentIndex(1)
        self._hide_footer()
        self._use.setText("Use this model")
        self._use.show()
        self._other.show()
        self._use.setDefault(True)
        self._use.setFocus()

    def _show_picker(self) -> None:
        self._stack.setCurrentIndex(2)
        self._hide_footer()
        self._use.setText("Use this model")
        self._use.show()
        self._back.show()
        radio = self._radios.get(self._picked.tag)
        if radio is not None:
            radio.setChecked(True)
        self._sync_pick_note()

    def _sync_pick_note(self) -> None:
        tag = self._selected_tag()
        model = by_tag(tag) if tag else None
        if model is None:
            return
        self._picked = model
        self._pick_note.setText(why(model, self._hardware))

    def _selected_tag(self) -> str:
        for tag, radio in self._radios.items():
            if radio.isChecked():
                return tag
        return self._picked.tag

    def _begin_prepare(self) -> None:
        if self._stack.currentIndex() == 2:
            tag = self._selected_tag()
            model = by_tag(tag)
            if model is not None:
                self._picked = model
        self._stack.setCurrentIndex(3)
        self._hide_footer()
        for btn in (self._use, self._other, self._back, self._go):
            btn.setEnabled(False)
        close = self.findChild(QPushButton, "SettingsClose")
        if close is not None:
            close.setEnabled(False)
        self._ready_status.setText(f"Getting {self._picked.title}…")
        self._bar.setRange(0, 0)
        self._prepare = _PrepareWorker(self._picked.tag, self)
        self._prepare.progressed.connect(self._on_progress)
        self._prepare.finished_ok.connect(self._on_ready)
        self._prepare.failed.connect(self._on_failed)
        self._prepare.start()

    def _on_progress(self, status: str, done: int, total: int) -> None:
        self._ready_status.setText(status)
        if total > 0:
            self._bar.setRange(0, 100)
            self._bar.setValue(int(done * 100 / total))
        else:
            self._bar.setRange(0, 0)

    def _on_ready(self) -> None:
        record_model_choice(self._picked.tag)
        for btn in (self._use, self._other, self._back, self._go):
            btn.setEnabled(True)
        close = self.findChild(QPushButton, "SettingsClose")
        if close is not None:
            close.setEnabled(True)
        self._stack.setCurrentIndex(4)
        self._hide_footer()
        self._go.show()
        self._go.setDefault(True)
        self._go.setFocus()

    def _on_failed(self, message: str) -> None:
        for btn in (self._use, self._other, self._back, self._go):
            btn.setEnabled(True)
        close = self.findChild(QPushButton, "SettingsClose")
        if close is not None:
            close.setEnabled(True)
        self._ready_status.setText(message)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._hide_footer()
        self._use.setText("Try again")
        self._use.show()
        self._back.show()

    def _on_probed(self, snap: object) -> None:
        if isinstance(snap, HardwareSnapshot):
            self._hardware = snap
        self._picked = recommend(self._hardware)
        self._rec_title.setText(f"Recommended: {self._picked.title}")
        self._rec_why.setText(why(self._picked, self._hardware))
        need = disk_needed_gb(self._picked)
        free = self._hardware.disk_free_gb
        if free is not None and free < need:
            self._rec_warn.setText(
                f"This download needs about {need:.0f} GB. This PC has about "
                f"{free:.0f} GB free. Free some space, or pick a smaller model."
            )
            self._rec_warn.show()
        radio = self._radios.get(self._picked.tag)
        if radio is not None:
            radio.setChecked(True)
        if not ollama_reachable() and find_ollama_exe() is None:
            extra = (
                "The local engine (Ollama, free) is not on this PC yet. "
                "Using this model will download it first, about 1.4 GB, "
                "then the model itself."
            )
            self._rec_why.setText(why(self._picked, self._hardware) + " " + extra)
        self._show_recommend()

    def reject(self) -> None:  # type: ignore[override]
        # Recommendation on screen: accepting it is the decision. Mid-download
        # we ignore Escape so a stray key does not leave a half-pulled model
        # and a mute window.
        if self._stack.currentIndex() == 0:
            return
        if self._stack.currentIndex() == 3 and (
            self._prepare is not None and self._prepare.isRunning()
        ):
            return
        if self._stack.currentIndex() in {0, 1, 2}:
            if self._stack.currentIndex() == 2:
                tag = self._selected_tag()
                model = by_tag(tag)
                if model is not None:
                    self._picked = model
            self._begin_prepare()
            return
        super().reject()


def prompt_for_model_setup(parent: QWidget | None = None) -> str | None:
    """Show the model glass when needed. Returns the tag, or None if skipped."""
    if not needs_model_setup():
        return None
    dialog = ModelSetupDialog(parent)
    dialog.exec()
    return dialog._picked.tag if dialog._picked else None
