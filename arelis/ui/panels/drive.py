"""Glass Drive strip — Stop / Pause / status while she drives her Chrome."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolButton

from arelis.ui.glass import GlassFrame


class DriveStrip(GlassFrame):
    """Thin cockpit above the composer. Hidden unless she is driving her Chrome."""

    pause_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(
            parent,
            object_name="DriveStrip",
            fill_alpha=96,
            radius=10.0,
            pulse_rim=False,
        )
        self.setFixedHeight(38)
        self._paused = False
        self._your_turn = False
        self._line = ""

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 4, 8, 4)
        row.setSpacing(8)

        brand = QLabel("Arelis Chrome")
        brand.setObjectName("DriveBrand")
        row.addWidget(brand)

        self.status = QLabel("")
        self.status.setObjectName("DriveStatus")
        self.status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        row.addWidget(self.status, stretch=1)

        self.pause_btn = QToolButton()
        self.pause_btn.setObjectName("PauseButton")
        self.pause_btn.setText("pause")
        self.pause_btn.setFixedHeight(28)
        self.pause_btn.setMinimumWidth(52)
        self.pause_btn.setToolTip("freeze mid-drive — the page stays")
        self.pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_btn.setAutoRaise(True)
        self.pause_btn.clicked.connect(self._toggle_pause)
        row.addWidget(self.pause_btn)

        self.stop_btn = QToolButton()
        self.stop_btn.setObjectName("StopButton")
        self.stop_btn.setText("stop")
        self.stop_btn.setFixedHeight(28)
        self.stop_btn.setMinimumWidth(52)
        self.stop_btn.setToolTip("abort this turn — the page stays")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setAutoRaise(True)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        row.addWidget(self.stop_btn)

        self.hide()

    def is_paused(self) -> bool:
        return self._paused

    def set_status(self, text: str) -> None:
        self._line = (text or "").strip()
        self._paint_status()

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        if not self._paused:
            self._your_turn = False
        if self._paused:
            self.pause_btn.setText("go")
            self.pause_btn.setToolTip("continue from here")
            self.pause_btn.setObjectName("GoButton")
        else:
            self.pause_btn.setText("pause")
            self.pause_btn.setToolTip("freeze mid-drive — the page stays")
            self.pause_btn.setObjectName("PauseButton")
        self.pause_btn.style().unpolish(self.pause_btn)
        self.pause_btn.style().polish(self.pause_btn)
        self._paint_status()

    def set_your_turn(self, message: str) -> None:
        self._your_turn = True
        self.set_status(message)
        self.set_paused(True)

    def set_driving(self, driving: bool) -> None:
        if driving:
            self.show()
        else:
            self._your_turn = False
            self.set_paused(False)
            self._line = ""
            self._paint_status()
            self.hide()

    def _paint_status(self) -> None:
        if self._your_turn and self._paused:
            self.status.setText(self._line or "your turn — page stays")
        elif self._paused:
            self.status.setText("paused — page stays")
        else:
            self.status.setText(self._line)

    def _toggle_pause(self) -> None:
        if self._paused:
            self.set_paused(False)
            self.resume_requested.emit()
        else:
            self.set_paused(True)
            self.pause_requested.emit()
