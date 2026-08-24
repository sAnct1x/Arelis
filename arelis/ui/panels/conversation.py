from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QImage,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QShortcut,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QPlainTextEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from arelis.attachments import stage_files, stage_image_bytes
from arelis.core.confirm_speech import classify_confirm_utterance
from arelis.ui.attach_bar import AttachBar, DropOverlay
from arelis.ui.glass import GlassFrame, Hairline
from arelis.ui.icons import (
    conversation_icon,
    microphone_icon,
    paperclip_icon,
    signal_flare_icon,
)
from arelis.ui.notify_overlay import NotifyOverlay
from arelis.ui.panels.chat import ChatPanel
from arelis.ui.panels.confirm import ConfirmCard
from arelis.ui.panels.drive import DriveStrip
from arelis.ui.panels.room import RoomStrip
from arelis.ui.stage import paint_corner_ticks
from arelis.ui.theme import METRICS, polish_combo_popup
from arelis.ui.void_idle import OrbitCanvas


class _ComposerLineEdit(QPlainTextEdit):
    """Idle prompt grows and wraps; workbench row stays a single field.

    Enter sends. Shift+Enter inserts a newline while idle. Image paste is
    intercepted before the edit eats Ctrl+V.
    """

    returnPressed = Signal()  # noqa: N815 — Qt signal
    image_paste_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._idle = False
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.document().setDocumentMargin(2)
        self.setCursorWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(METRICS["control"])

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:
        self.setPlainText(text)

    def cursorPosition(self) -> int:
        return self.textCursor().position()

    def setCursorPosition(self, pos: int) -> None:
        cursor = self.textCursor()
        cursor.setPosition(max(0, min(int(pos), len(self.toPlainText()))))
        self.setTextCursor(cursor)

    def setClearButtonEnabled(self, _on: bool) -> None:
        return

    def setAlignment(self, alignment) -> None:  # type: ignore[override]
        option = self.document().defaultTextOption()
        option.setAlignment(Qt.Alignment(alignment))
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.document().setDefaultTextOption(option)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Paste):
            clipboard = QApplication.clipboard()
            mime = clipboard.mimeData() if clipboard is not None else None
            if mime is not None and mime.hasImage():
                self.image_paste_requested.emit()
                event.accept()
                return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._idle and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                super().keyPressEvent(event)
                return
            self.returnPressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)
        self.ensureCursorVisible()


_STAGE_MARGIN_TOP = 14


class ConversationStage(GlassFrame):
    """Single glass panel: chat + composer (screenshot-4 composition)."""

    submitted = Signal(str, str, list)  # text, role, attachments
    stop_requested = Signal()
    # Esc arrived on a turn that has not shown anything yet. The window explains
    # rather than cancelling work the user cannot see.
    stop_declined = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    confirm_decided = Signal(str, str, bool)  # id, decision, allow_turn
    dictate_toggled = Signal(bool)
    conversation_toggled = Signal(bool)
    attach_errors = Signal(list)  # list[str] for STATUS / system lines
    idle_conditions_changed = Signal()
    session_clicked = Signal(str)
    leave_room_requested = Signal()
    world_requested = Signal()

    def __init__(self, default_role: str = "fast", parent=None) -> None:
        super().__init__(
            parent,
            object_name="ChatStage",
            fill_alpha=0,
            radius=0.0,
            pulse_rim=False,
        )
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        # Gutter so corner ticks sit outside fast / send / chat labels.
        layout.setContentsMargins(22, _STAGE_MARGIN_TOP, 22, 16)
        layout.setSpacing(8)

        # Above the transcript: whose conversation this is. Hidden in general.
        self.room = RoomStrip()
        layout.addWidget(self.room)
        self.room.leave_requested.connect(self.leave_room_requested.emit)
        self.room.world_requested.connect(self.world_requested.emit)

        self.chat = ChatPanel(embedded=True)
        layout.addWidget(self.chat, stretch=1)
        self.chat.session_clicked.connect(self.session_clicked.emit)
        self.chat.suggestion_clicked.connect(self._on_suggestion)

        self.confirm = ConfirmCard()
        layout.addWidget(self.confirm)
        self.confirm.decided.connect(self._on_confirm_decided)

        self.drive = DriveStrip()
        layout.addWidget(self.drive)
        self.drive.pause_requested.connect(self.pause_requested.emit)
        self.drive.resume_requested.connect(self.resume_requested.emit)
        self.drive.stop_requested.connect(self.stop_requested.emit)

        self._hairline = Hairline()
        layout.addWidget(self._hairline)

        self.attach_bar = AttachBar()
        layout.addWidget(self.attach_bar)

        composer = QWidget()
        composer.setObjectName("ComposerInner")
        self._composer = composer
        row = QHBoxLayout(composer)
        self._composer_row = row
        row.setContentsMargins(2, 4, 2, 2)
        row.setSpacing(8)

        self.role = QComboBox()
        self.role.setObjectName("RoleSelect")
        self.role.addItems(["fast", "research"])
        if default_role in {"fast", "research"}:
            self.role.setCurrentText(default_role)
        self.role.setFixedHeight(METRICS["control"])
        # Fit longest label ("research") — avoid a wide empty popup.
        self.role.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        self.role.setFixedWidth(92)
        # Non-editable on purpose: an editable+readOnly LineEdit with NoFocus
        # was used to center the label, but on Windows it ate popup clicks so
        # the role pill looked stuck on "fast".
        self.role.setEditable(False)
        self.role.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.role.setCursor(Qt.CursorShape.PointingHandCursor)
        self.role.setToolTip(
            "Reply role for this message (fast / research). "
            "File and git work stays on fast. Auto-routing may still "
            "switch to research for a deep-dive; Systems → Model shows "
            "what is hot in VRAM."
        )
        polish_combo_popup(self.role, compact=True)

        self.input = _ComposerLineEdit()
        self.input.setObjectName("ComposerInput")
        # Same copy _sync_composer_buttons() settles on, so the two agree. The
        # idle prompt is the centered VoidIdlePlaceholder label, not this.
        self.input.setPlaceholderText("message Arelis…")
        self.input.setFixedHeight(METRICS["control"])
        self.input.image_paste_requested.connect(self._paste_clipboard_image)
        self.input.textChanged.connect(self._on_composer_text)

        # Two independent latching controls, not one overloaded button.
        # Dictation is one person filling the composer and never sends on its
        # own; conversation is hands-free and sends when you stop talking.
        # Either can be on, never both.
        _btn = METRICS["control"]
        _icon = METRICS["icon"]
        self.attach_btn = QToolButton()
        self.attach_btn.setObjectName("AttachButton")
        self.attach_btn.setIcon(paperclip_icon(_icon))
        self.attach_btn.setIconSize(QSize(_icon, _icon))
        self.attach_btn.setFixedSize(_btn, _btn)
        self.attach_btn.setToolTip("Attach files (or drag onto the chat)")
        self.attach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.attach_btn.setAutoRaise(True)
        self.attach_btn.clicked.connect(self._pick_files)

        self.mic_btn = QToolButton()
        self.mic_btn.setObjectName("MicButton")
        self.mic_btn.setCheckable(True)
        self.mic_btn.setIcon(microphone_icon(_icon))
        self.mic_btn.setIconSize(QSize(_icon, _icon))
        self.mic_btn.setFixedSize(_btn, _btn)
        self.mic_btn.setToolTip("dictate into the message box (Ctrl+M)")
        self.mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mic_btn.setAutoRaise(True)

        self.conversation_btn = QToolButton()
        self.conversation_btn.setObjectName("ConversationButton")
        self.conversation_btn.setCheckable(True)
        self.conversation_btn.setIcon(conversation_icon(_icon))
        self.conversation_btn.setIconSize(QSize(_icon, _icon))
        self.conversation_btn.setFixedSize(_btn, _btn)
        self.conversation_btn.setToolTip("hands-free conversation (Ctrl+Shift+M)")
        self.conversation_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.conversation_btn.setAutoRaise(True)

        self.stop_btn = QToolButton()
        self.stop_btn.setObjectName("StopButton")
        self.stop_btn.setText("stop")
        self.stop_btn.setFixedHeight(_btn)
        self.stop_btn.setMinimumWidth(52)
        self.stop_btn.setToolTip(
            "stop current turn — Esc also stops once she has started answering"
        )
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setAutoRaise(True)
        self.stop_btn.hide()

        self.send_btn = QToolButton()
        self.send_btn.setObjectName("SendButton")
        self.send_btn.setIcon(signal_flare_icon(_icon))
        self.send_btn.setIconSize(QSize(_icon, _icon))
        self.send_btn.setFixedSize(_btn, _btn)
        self.send_btn.setToolTip("send")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setAutoRaise(True)

        row.addWidget(self.role)
        row.addWidget(self.input, stretch=1)
        row.addWidget(self.attach_btn)
        row.addWidget(self.mic_btn)
        row.addWidget(self.conversation_btn)
        row.addWidget(self.stop_btn)
        row.addWidget(self.send_btn)
        layout.addWidget(composer)

        self._parked_orbit = OrbitCanvas(self, size=72, dim=0.42)
        self._parked_orbit.hide()

        self._drop_overlay = DropOverlay(self)
        self._drop_overlay.hide()

        self.notify_overlay = NotifyOverlay(self)
        self.notify_overlay.hide()
        self.room.changed.connect(self.notify_overlay.reposition)

        self.send_btn.clicked.connect(self._submit)
        self.input.returnPressed.connect(self._submit)
        # The stop control is the only thing that cancels unconditionally. Esc
        # runs a ladder that stops short of killing an invisible turn.
        self.stop_btn.clicked.connect(self._stop)
        self.mic_btn.toggled.connect(self._on_mic_toggled)
        self.conversation_btn.toggled.connect(self._on_conversation_toggled)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._escape)
        attach = QShortcut(QKeySequence("Ctrl+Shift+A"), self)
        attach.setContext(Qt.ShortcutContext.ApplicationShortcut)
        attach.activated.connect(self._pick_files)

        self._busy = False
        self._speaking = False
        self._turn_visible = False
        self._driving = False
        self._idle_mode = False
        self._pulse_phase = 0.0
        self._wake_acking = False
        self._ack_saved_placeholder: str | None = None
        self._listen_pulse = QTimer(self)
        self._listen_pulse.setInterval(50)
        self._listen_pulse.timeout.connect(self._tick_listen_pulse)
        self.set_voice_available(False, "")
        self.set_idle_mode(True)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        paint_corner_ticks(painter, self.rect(), inset=8, length=12)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if hasattr(self, "_parked_orbit"):
            self._place_parked_orbit()
        if getattr(self, "_idle_mode", False):
            self._fit_idle_prompt()
        if hasattr(self, "_drop_overlay"):
            self._drop_overlay.setGeometry(self.rect())
        if hasattr(self, "notify_overlay"):
            self.notify_overlay.reposition()

    def sync_notify_gutter(self, top: int = 0) -> None:
        """Open air above the room plate so the live pill does not sit on it."""
        layout = self.layout()
        if layout is None:
            return
        want = int(top) if int(top) > _STAGE_MARGIN_TOP else _STAGE_MARGIN_TOP
        margins = layout.contentsMargins()
        if margins.top() == want:
            return
        layout.setContentsMargins(
            margins.left(), want, margins.right(), margins.bottom()
        )
        layout.activate()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        mime = event.mimeData()
        if mime is not None and mime.hasUrls():
            event.acceptProposedAction()
            self._drop_overlay.setGeometry(self.rect())
            self._drop_overlay.raise_()
            self._drop_overlay.show()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # type: ignore[override]
        self._drop_overlay.hide()
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        self._drop_overlay.hide()
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            event.ignore()
            return
        paths = [Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile()]
        self._stage_paths(paths)
        event.acceptProposedAction()

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Attach files for Arelis",
            str(Path.home()),
        )
        if paths:
            self._stage_paths([Path(p) for p in paths])

    def _paste_clipboard_image(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return
        image = clipboard.image()
        if image is None or image.isNull():
            return
        data = _qimage_png_bytes(image)
        result = stage_image_bytes(data, existing_count=self.attach_bar.count())
        if result.errors:
            self.attach_errors.emit(list(result.errors))
        if result.ok:
            self.attach_bar.add_many([a.as_dict() for a in result.ok])

    def _stage_paths(self, paths: list[Path]) -> None:
        if not paths:
            return
        result = stage_files(paths, existing_count=self.attach_bar.count())
        if result.errors:
            self.attach_errors.emit(list(result.errors))
        if result.ok:
            self.attach_bar.add_many([a.as_dict() for a in result.ok])

    def set_drive(self, driving: bool, status: str = "") -> None:
        """Show the glass Drive strip while she is driving her Chrome."""
        self._driving = bool(driving)
        if status:
            self.drive.set_status(status)
        if self._idle_mode and not self.chat.has_messages:
            self.drive.hide()
            return
        self.drive.set_driving(self._driving)

    def set_drive_status(self, status: str) -> None:
        self.drive.set_status(status)

    def set_drive_paused(self, paused: bool) -> None:
        self.drive.set_paused(paused)

    def set_drive_your_turn(self, message: str) -> None:
        self._driving = True
        if self._idle_mode and not self.chat.has_messages:
            self.drive.hide()
            return
        self.drive.set_driving(True)
        self.drive.set_your_turn(message)

    def set_busy(self, busy: bool) -> None:
        """Swap the composer between send and stop for the duration of a turn.

        The input stays editable while busy so the next message can be typed
        ahead; only submission is blocked, in _submit and here.
        """
        self._busy = busy
        self._turn_visible = False
        if hasattr(self, "_parked_orbit"):
            self._parked_orbit.set_thinking(busy)
        self._sync_composer_buttons()
        self.idle_conditions_changed.emit()
        if not busy:
            self.restore_composer_caret()

    def set_turn_visible(self, visible: bool) -> None:
        """The running turn has put something on screen (tokens or a tool line).

        Esc reads this. A turn holding its answer back until the tools are done
        paints nothing at all, and an SMS turn is exactly that: the operator saw
        a blank thread, pressed Esc to clear it, and killed the send before the
        Allow card existed.
        """
        self._turn_visible = bool(visible)

    def turn_visible(self) -> bool:
        return self._turn_visible

    def set_idle_mode(self, idle: bool) -> None:
        """Orbit empty face vs workbench. Does not change tools or Allow."""
        want = bool(idle)
        if self.graphicsEffect() is not None:
            self.setGraphicsEffect(None)
        if want == self._idle_mode:
            return
        self._idle_mode = want
        self.set_fill_alpha(0)
        self.set_pulse_rim(False)
        if want and not self.chat.has_messages:
            self.chat.view.hide()
            self.chat.empty.show()
            if hasattr(self.chat.empty, "set_animating"):
                self.chat.empty.set_animating(True)
        else:
            if hasattr(self.chat.empty, "set_animating"):
                self.chat.empty.set_animating(False)
            self.chat.empty.hide()
            self.chat.view.show()
        self._place_composer(want)
        self._sync_parked_orbit(want)
        self._sync_composer_buttons()
        self.update()

    def _on_composer_text(self) -> None:
        if self._idle_mode:
            self._fit_idle_prompt()
        else:
            self._fit_workbench_prompt()

    def _fit_idle_prompt(self) -> None:
        """Widen with the sentence, then wrap — never clip the start."""
        if not self._idle_mode:
            return
        empty = getattr(self.chat, "empty", None)
        host = getattr(empty, "prompt_host", None)
        if host is None or self.input.parent() is not host:
            return
        fm = self.input.fontMetrics()
        raw = self.input.text()
        typing = bool(raw.strip())
        idle_w = empty.width() if empty is not None else 0
        avail = idle_w - 80 if idle_w > 120 else 640
        max_w = max(160, min(720, avail))
        label = getattr(empty, "idle_placeholder", None)
        if label is not None:
            label.ensurePolished()
            ph_fm = label.fontMetrics()
            ph_w = ph_fm.horizontalAdvance(label.text()) + 24
        else:
            ph_w = fm.horizontalAdvance("what are we working on") + 24
        if typing:
            need = max(fm.horizontalAdvance(line) for line in (raw.split("\n") or [raw])) + 36
            width = max(ph_w, min(max_w, need))
        else:
            width = min(max_w, max(160, ph_w))
        self.input.setFixedWidth(width)
        host.setFixedWidth(width)
        self.input.resize(width, max(36, self.input.height()))
        doc = self.input.document()
        doc.setTextWidth(max(1.0, float(width - 16)))
        line_h = max(fm.lineSpacing(), fm.height())
        inner = max(1, width - 16)
        wrapped = fm.boundingRect(QRect(0, 0, inner, 10_000), Qt.TextFlag.TextWordWrap, raw or " ")
        content_h = max(math.ceil(doc.size().height()), wrapped.height()) + 12
        height = max(36, min(line_h * 5 + 16, content_h))
        overflow = content_h > height
        self.input.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if overflow
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.input.setFixedHeight(height)
        if hasattr(empty, "fit_prompt"):
            empty.fit_prompt(width, height, typing=typing)

    def _fit_workbench_prompt(self) -> None:
        """Wrap and grow a few lines so a long draft is not clipped off-screen."""
        if self._idle_mode:
            return
        fm = self.input.fontMetrics()
        raw = self.input.text()
        line_h = max(fm.lineSpacing(), fm.height())
        inner = max(1, self.input.viewport().width() - 8)
        wrapped = fm.boundingRect(
            QRect(0, 0, inner, 10_000), Qt.TextFlag.TextWordWrap, raw or " "
        )
        content_h = wrapped.height() + 12
        rest = int(METRICS["control"])
        height = rest if not raw.strip() else max(rest, min(line_h * 5 + 16, content_h))
        overflow = bool(raw.strip()) and content_h > height
        self.input.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if overflow
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.input.setFixedHeight(height)
        self.input.ensureCursorVisible()

    def restore_composer_caret(self) -> None:
        """Put the caret back after Allow or a tool turn stole focus.

        The confirm card focuses Allow. When it hides, Qt often leaves no
        caret — the placeholder shows and typed-ahead text looks gone.
        """
        focus = QApplication.focusWidget()
        if focus is not None and focus is not self.input:
            from PySide6.QtWidgets import QLineEdit, QTextEdit

            if isinstance(focus, (QLineEdit, QPlainTextEdit, QTextEdit)):
                return
        self.input.setFocus(Qt.FocusReason.OtherFocusReason)
        self.input.ensureCursorVisible()

    def _place_composer(self, idle: bool) -> None:
        """Idle: the real editor sits under the orbit. Workbench: bottom row."""
        host = getattr(self.chat.empty, "prompt_host", None)
        focused = self.input.hasFocus()
        cursor = self.input.cursorPosition()
        moved = False
        self.input._idle = bool(idle)  # type: ignore[attr-defined]
        if idle and host is not None and not self.chat.has_messages:
            if self.input.parent() is not host:
                self._composer_row.removeWidget(self.input)
                self.input.setParent(host)
                host.layout().addWidget(self.input)
                moved = True
            self.input.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.input.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            self.input.setClearButtonEnabled(False)
            self._composer.hide()
            self._hairline.hide()
            self.drive.hide()
            self.role.hide()
            self.attach_btn.hide()
            self.send_btn.hide()
            empty = getattr(self.chat, "empty", None)
            voice_host = getattr(empty, "voice_host", None) if empty is not None else None
            if voice_host is not None:
                for btn in (self.mic_btn, self.conversation_btn):
                    if btn.parent() is not voice_host:
                        self._composer_row.removeWidget(btn)
                        btn.setParent(voice_host)
                        voice_host.layout().addWidget(btn)
                voice_host.setVisible(bool(getattr(self, "_voice_shown", False)))
            self._fit_idle_prompt()
        else:
            parked = self.input.parent() is self._composer
            if not parked:
                host_l = host.layout() if host is not None else None
                if host_l is not None:
                    host_l.removeWidget(self.input)
                self.input.setParent(self._composer)
                self._composer_row.insertWidget(1, self.input, stretch=1)
                moved = True
                self.input.setAlignment(Qt.AlignmentFlag.AlignLeft)
                self.input.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
                self.input.setMinimumWidth(0)
                self.input.setMaximumWidth(16777215)
                self.input.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
                )
            self.input.setClearButtonEnabled(True)
            self._composer.show()
            self._hairline.show()
            if self._driving:
                self.drive.set_driving(True)
            self.role.show()
            self.attach_btn.show()
            self.send_btn.show()
            visible = bool(getattr(self, "_voice_shown", False))
            for btn in (self.mic_btn, self.conversation_btn):
                if btn.parent() is not self._composer:
                    host_l = btn.parentWidget().layout() if btn.parentWidget() else None
                    if host_l is not None:
                        host_l.removeWidget(btn)
                    btn.setParent(self._composer)
                    self._composer_row.insertWidget(
                        self._composer_row.indexOf(self.stop_btn), btn
                    )
                btn.setVisible(visible)
            empty = getattr(self.chat, "empty", None)
            voice_host = getattr(empty, "voice_host", None) if empty is not None else None
            if voice_host is not None:
                voice_host.hide()
            self._fit_workbench_prompt()
        if moved and focused:
            self.input.setFocus(Qt.FocusReason.OtherFocusReason)
            self.input.setCursorPosition(cursor)
            self.input.ensureCursorVisible()

    def _sync_parked_orbit(self, idle: bool) -> None:
        """Keep a small dim orbit in the corner once a thread exists."""
        parked = not idle
        self._parked_orbit.setVisible(parked)
        self._parked_orbit.set_animating(parked)
        if parked:
            self._place_parked_orbit()
            self._parked_orbit.raise_()
            self.notify_overlay.raise_()
            self._drop_overlay.raise_()
        else:
            self.chat.set_parked_gutter(0)

    def _place_parked_orbit(self) -> None:
        if not hasattr(self, "_parked_orbit") or not hasattr(self, "chat"):
            return
        if self._parked_orbit.isHidden():
            self.chat.set_parked_gutter(0)
            return
        # Orbit lives in a reserved right strip, not over the transcript.
        # edge = gap to the window; air = gap between chat's right edge and
        # the orbit's left edge. Scrollbar stays inside the chat view.
        edge = 8
        air = 12
        orbit_w = self._parked_orbit.width()
        composer_h = self._composer.height() if self._composer.isVisible() else 0
        margin_b = 18 + composer_h
        self._parked_orbit.move(
            max(edge, self.width() - orbit_w - edge),
            max(edge, self.height() - self._parked_orbit.height() - margin_b),
        )
        self.chat.set_parked_gutter(orbit_w + air + edge)

    def set_voice_available(self, available: bool, reason: str = "") -> None:
        """Show the voice controls only when they can actually do something.

        With voice off in config the buttons are hidden outright rather than
        greyed: an affordance for a feature that is switched off is noise. When
        voice is on but the hardware or a dependency is missing they stay
        visible and disabled, because then the user asked for this and is owed
        an explanation in the tooltip.
        """
        self._voice_available = available
        # Kept, rather than recomputed by whoever needs it next. set_idle_mode rebuilds the
        # composer and has to decide this again; deriving it there from _voice_available
        # alone dropped the "on but unusable" case and hid the tooltip that is the entire
        # point of it. An unplugged microphone made the controls vanish silently.
        self._voice_shown = show = available or bool(reason)
        for button in (self.mic_btn, self.conversation_btn):
            button.setVisible(show)
            button.setEnabled(available)
        empty = getattr(self.chat, "empty", None)
        voice_host = getattr(empty, "voice_host", None) if empty is not None else None
        if voice_host is not None and self._idle_mode:
            voice_host.setVisible(show)
        if not available:
            for button in (self.mic_btn, self.conversation_btn):
                button.blockSignals(True)
                button.setChecked(False)
                button.blockSignals(False)
            self._sync_listen_pulse()
            if reason:
                self.mic_btn.setToolTip(reason)
                self.conversation_btn.setToolTip(reason)
        else:
            self.mic_btn.setToolTip("dictate into the message box (Ctrl+M)")
            self.conversation_btn.setToolTip("hands-free conversation (Ctrl+Shift+M)")

    def set_speaking(self, speaking: bool) -> None:
        """Track playback so Esc can cut her off even between turns."""
        self._speaking = speaking
        self._sync_composer_buttons()

    def confirm_open(self) -> bool:
        return bool(getattr(self.confirm, "_confirm_id", "") or "")

    def _sync_composer_buttons(self) -> None:
        blocked = self._busy or self.confirm_open()
        self.send_btn.setEnabled(not blocked)
        self.attach_btn.setEnabled(not blocked)
        self.stop_btn.setVisible(self._busy or self._speaking)
        if self.confirm_open():
            self.input.setPlaceholderText("Enter = allow · Esc = deny…")
        elif self._idle_mode:
            # Idle prompt is the centered VoidIdlePlaceholder label; Qt's own
            # placeholder paints left-aligned and shoves the line off-axis.
            self.input.setPlaceholderText("")
        else:
            self.input.setPlaceholderText("message Arelis…")

    def toggle_dictate(self) -> None:
        self.mic_btn.setChecked(not self.mic_btn.isChecked())

    def toggle_conversation(self) -> None:
        self.conversation_btn.setChecked(not self.conversation_btn.isChecked())

    def set_dictating(self, active: bool) -> None:
        self._set_toggle(self.mic_btn, active, microphone_icon(24, live=active))
        self._sync_listen_pulse()

    def set_conversing(self, active: bool) -> None:
        self._set_toggle(self.conversation_btn, active, conversation_icon(24, live=active))
        self._sync_listen_pulse()

    def ack_wake(self) -> None:
        """Receipt that the doorbell rang: icon flares, copy says listening."""
        self._wake_acking = True
        self._pulse_phase = 0.0
        if not self.conversation_btn.isChecked():
            self.set_conversing(True)
        self.conversation_btn.setToolTip("listening")
        self._apply_listening_copy(True)
        self._sync_listen_pulse()
        self._tick_listen_pulse()
        QTimer.singleShot(1200, self._end_wake_ack)

    def _end_wake_ack(self) -> None:
        self._wake_acking = False
        self._apply_listening_copy(False)
        if self.conversation_btn.isChecked():
            self.conversation_btn.setToolTip("hands-free conversation (Ctrl+Shift+M)")
        self._sync_listen_pulse()

    def _apply_listening_copy(self, listening: bool) -> None:
        empty = getattr(self.chat, "empty", None)
        if listening:
            if empty is not None and hasattr(empty, "set_voice_mode"):
                empty.set_voice_mode("ack")
            if not self._idle_mode:
                if self._ack_saved_placeholder is None:
                    self._ack_saved_placeholder = self.input.placeholderText()
                self.input.setPlaceholderText("listening")
            return
        if empty is not None and hasattr(empty, "set_voice_mode"):
            if self.conversation_btn.isChecked():
                empty.set_voice_mode("conversation")
            elif self.mic_btn.isChecked():
                empty.set_voice_mode("dictate")
            else:
                empty.set_voice_mode("off")
        if self._ack_saved_placeholder is not None:
            self.input.setPlaceholderText(self._ack_saved_placeholder)
            self._ack_saved_placeholder = None

    def _set_toggle(self, button: QToolButton, active: bool, icon) -> None:
        button.blockSignals(True)
        button.setChecked(active)
        button.blockSignals(False)
        button.setIcon(icon)

    def _on_mic_toggled(self, checked: bool) -> None:
        if checked and self.conversation_btn.isChecked():
            self.conversation_btn.setChecked(False)
        self.mic_btn.setIcon(microphone_icon(24, live=checked))
        self._sync_listen_pulse()
        self.dictate_toggled.emit(checked)
        self.idle_conditions_changed.emit()

    def _on_conversation_toggled(self, checked: bool) -> None:
        if checked and self.mic_btn.isChecked():
            self.mic_btn.setChecked(False)
        self.conversation_btn.setIcon(conversation_icon(24, live=checked))
        self._sync_listen_pulse()
        self.conversation_toggled.emit(checked)
        self.idle_conditions_changed.emit()

    def _sync_listen_pulse(self) -> None:
        live = self.mic_btn.isChecked() or self.conversation_btn.isChecked()
        if live and not self._listen_pulse.isActive():
            self._pulse_phase = 0.0
            self._listen_pulse.start()
        elif not live and self._listen_pulse.isActive():
            self._listen_pulse.stop()
            self._hairline.rest()

    def _tick_listen_pulse(self) -> None:
        if not (self.mic_btn.isChecked() or self.conversation_btn.isChecked()):
            self._listen_pulse.stop()
            return
        self._pulse_phase += 0.22 if self._wake_acking else 0.14
        if self._wake_acking:
            amp = 1.35 + 0.45 * (0.5 + 0.5 * math.sin(self._pulse_phase * 1.6))
            glow = 110
        else:
            amp = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._pulse_phase))
            glow = int(26 + 40 * (amp - 0.55) / 0.45)
        if self.mic_btn.isChecked():
            self.mic_btn.setIcon(microphone_icon(24, live=True, pulse=amp))
        if self.conversation_btn.isChecked():
            self.conversation_btn.setIcon(conversation_icon(24, live=True, pulse=amp))
        self._hairline.set_glow(glow)

    def insert_dictation(self, text: str) -> None:
        """Append transcribed speech to the composer without sending it.

        Dictation exists so a half-formed idea can be talked out and then
        edited. Sending it would defeat the point, so the text lands in the box
        and the cursor goes to the end of it.
        """
        text = text.strip()
        if not text:
            return
        existing = self.input.text().strip()
        self.input.setText(f"{existing} {text}".strip() if existing else text)
        self.input.setCursorPosition(len(self.input.text()))
        self.input.setFocus()

    def _on_suggestion(self, text: str) -> None:
        """Put an opening suggestion in the composer. Never send it.

        A first-run hint that fired a turn on one click would be the app taking
        an action nobody asked for, and the first thing it taught would be that
        clicking is dangerous. Filling the box teaches the opposite: this is
        yours to edit, and Enter is still your key.
        """
        text = (text or "").strip()
        if not text:
            return
        self.input.setText(text)
        self.input.setCursorPosition(len(text))
        self.input.setFocus()

    def ask_confirm(
        self,
        confirm_id: str,
        tool: str,
        summary: str,
        *,
        detail: str = "",
        note: str = "",
        batch_ok: bool = True,
        headline: str = "",
    ) -> None:
        self.confirm.ask(
            confirm_id,
            tool,
            summary,
            detail=detail,
            note=note,
            batch_ok=batch_ok,
            headline=headline,
        )
        self._sync_composer_buttons()
        self.idle_conditions_changed.emit()

    def dismiss_confirm(self) -> None:
        """Hide a pending confirm without answering it.

        Used when the turn ends by another route (stop, error, completion). The
        orchestrator has already resolved the waiting future by then, so leaving
        the card visible would offer a choice that no longer has an effect.
        """
        self.confirm.dismiss()
        self._sync_composer_buttons()
        self.idle_conditions_changed.emit()
        self.restore_composer_caret()

    def _on_confirm_decided(self, confirm_id: str, decision: str, allow_turn: bool) -> None:
        self._sync_composer_buttons()
        self.confirm_decided.emit(confirm_id, decision, allow_turn)
        self.restore_composer_caret()

    def _submit(self) -> None:
        # Enter on an open card: empty or yes-list = allow; no-list = deny;
        # stop cancels the turn, same as the stop control.
        if self.confirm_open():
            typed = self.input.text().strip()
            decision = classify_confirm_utterance(typed)
            if decision == "stop":
                self.input.clear()
                self.stop_requested.emit()
                return
            if decision == "skip":
                self.input.clear()
                self.confirm._skip()
                return
            if decision == "allow_turn":
                self.input.clear()
                if self.confirm.allow_turn.isVisible():
                    self.confirm.allow_turn.setChecked(True)
                self.confirm._allow()
                return
            if typed and decision is None:
                # They started a message — do not treat it as allow.
                return
            self.input.clear()
            self.confirm._allow()
            return
        if self._busy:
            return
        text = self.input.text().strip()
        attachments = self.attach_bar.attachments()
        if not text and not attachments:
            return
        role = self.role.currentText()
        self.input.clear()
        self.attach_bar.clear()
        self.submitted.emit(text, role, attachments)

    def _stop(self) -> None:
        """The stop control. Cancels whatever is running, no ladder."""
        if self._busy or self._speaking:
            self.stop_requested.emit()

    def _escape(self) -> None:
        # Fullscreen first: Esc leaves F11 mode before it touches a turn.
        win = self.window()
        if win is not None and win.isFullScreen():
            win.showNormal()
            sync = getattr(win, "_sync_chrome_state", None)
            if callable(sync):
                sync()
            return
        # Esc is one ladder: fullscreen → deny the card → collapse pill → cut
        # speech / stop a visible turn → clear the composer → back to the orbit.
        # Deny is this step only — mid-turn allow still means Esc = deny.
        if self.confirm_open():
            self.confirm._skip()
            return
        overlay = getattr(self, "notify_overlay", None)
        if overlay is not None and overlay.expanded:
            overlay.collapse()
            return
        if self._busy and not self._turn_visible and not self._speaking:
            # Nothing on screen to stop. The orbit advertises "esc to clear",
            # and clearing is not cancelling: this is where a spoken SMS turn
            # died before its Allow card. The stop control still cancels.
            self.stop_declined.emit()
            return
        if self._busy or self._speaking:
            self.stop_requested.emit()
            return
        if self.input.text():
            self.input.clear()
            return
        idle_fn = getattr(win, "_return_to_idle", None)
        if callable(idle_fn):
            idle_fn()

    def focus_input(self) -> None:
        self.input.setFocus()


def _qimage_png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    data = bytes(buffer.data())
    buffer.close()
    return data
