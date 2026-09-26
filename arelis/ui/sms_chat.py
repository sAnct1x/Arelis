"""Per-person SMS chat tiles — video-game whisper windows over real texts."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QMouseEvent, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from arelis.contacts import (
    load_contacts,
    match_contact_label,
    normalize_phone,
    resolve_contact,
    to_e164,
)
from arelis.notify.center import Notice
from arelis.sms_media import (
    body_is_only_image_url,
    body_needs_rich_text,
    iter_http_urls,
    looks_like_photo_body,
    sms_body_html,
)
from arelis.ui.foreground import process_owns_foreground
from arelis.ui.glass import GlassFrame, advance_rim_pulse, seal_tool_window
from arelis.ui.icons import window_close_icon, window_minimize_icon
from arelis.ui.sms_store import cap_messages, load_threads, save_threads
from arelis.ui.theme import GLASS, METRICS, SPACE, space_box
from arelis.ui.window_resize import enable_win32_resize_frame, handle_native_resize

MAX_TILES = 8
MAX_IMAGE_WIDTH = 400
TILE_WIDTH = 480
TILE_HEIGHT = 640
Direction = Literal["in", "out", "system"]
SendStatus = Literal["sent", "pending", "failed"]
RoomPresence = Literal["hidden", "visible", "focused"]
ATTENTION_BREATH_S = 6.0


def room_owns_doorbell(state: str) -> bool:
    """A visible room swallows that person's pill, inbox unread, and voice."""
    return state in {"visible", "focused"}


@dataclass
class SmsChatMessage:
    direction: Direction
    body: str
    t: float = field(default_factory=time.time)
    media_path: str = ""
    media_kind: str = ""
    status: SendStatus = "sent"
    error: str = ""

    def as_row(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "body": self.body,
            "t": self.t,
            "media_path": self.media_path,
            "media_kind": self.media_kind,
            "status": self.status,
            "error": self.error,
        }

    @classmethod
    def from_row(cls, raw: dict[str, Any]) -> SmsChatMessage:
        direction = str(raw.get("direction") or "in")
        if direction not in {"in", "out", "system"}:
            direction = "in"
        status = str(raw.get("status") or "sent")
        if status not in {"sent", "pending", "failed"}:
            status = "sent"
        try:
            stamp = float(raw.get("t") or time.time())
        except (TypeError, ValueError):
            stamp = time.time()
        return cls(
            direction=direction,  # type: ignore[arg-type]
            body=str(raw.get("body") or ""),
            t=stamp,
            media_path=str(raw.get("media_path") or ""),
            media_kind=str(raw.get("media_kind") or ""),
            status=status,  # type: ignore[arg-type]
            error=str(raw.get("error") or ""),
        )


def format_bubble_time(stamp: float, *, now: datetime | None = None) -> str:
    when = datetime.fromtimestamp(stamp)
    present = now or datetime.now()
    clock = when.strftime("%H:%M")
    if when.date() == present.date():
        return clock
    return f"{when.strftime('%b')} {when.day} · {clock}"


def parse_message_time(raw: str = "") -> float:
    text = (raw or "").strip()
    if text:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return time.time()


def thread_keys(*, alias: str = "", phone: str = "", sender: str = "") -> tuple[str, ...]:
    """Identity keys for one person. Alias and digits map to the same room."""
    keys: list[str] = []
    name = (alias or "").strip().lower()
    if name:
        keys.append(f"alias:{name}")
    digits = normalize_phone(phone or sender)
    if digits:
        keys.append(f"digits:{digits}")
    if not keys:
        raw = (sender or phone or "").strip().lower()
        if raw:
            keys.append(f"raw:{raw}")
    return tuple(keys)


def seed_bodies(notice: Notice | None, *, fallback: str = "") -> list[str]:
    """Bodies already stacked on the SMS notice, oldest first."""
    if notice is not None:
        raw = notice.data.get("bodies")
        if isinstance(raw, list) and raw:
            return [str(item) for item in raw if str(item).strip()]
        text = (notice.body or "").strip()
        if text:
            return [text]
    text = (fallback or "").strip()
    return [text] if text else []


def bubble_plain_text(widget: QWidget | None) -> str:
    """Visible text inside a bubble, whether it is a QLabel or a photo stack."""
    if widget is None:
        return ""
    if isinstance(widget, QLabel):
        return str(widget.text() or "")
    bits: list[str] = []
    for label in widget.findChildren(QLabel):
        if label.objectName() == "SmsBubbleTime":
            continue
        text = str(label.text() or "").strip()
        if text:
            bits.append(text)
    return "\n".join(bits)


def _apply_bubble_chrome(widget: QWidget, direction: Direction) -> None:
    if direction == "out":
        widget.setObjectName("SmsBubbleOut")
        align = Qt.AlignmentFlag.AlignRight
    elif direction == "system":
        widget.setObjectName("SmsBubbleSys")
        align = Qt.AlignmentFlag.AlignCenter
    else:
        widget.setObjectName("SmsBubbleIn")
        align = Qt.AlignmentFlag.AlignLeft
    if isinstance(widget, QLabel):
        widget.setAlignment(align)


def open_local_path(path: str) -> None:
    """Open a saved inbound photo in the OS viewer."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def _fill_body_label(label: QLabel, text: str) -> None:
    if body_needs_rich_text(text):
        label.setObjectName(label.objectName() or "SmsBubbleBody")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setText(sms_body_html(text))
        label.setOpenExternalLinks(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    else:
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setText(text)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)


class SmsImageLabel(QLabel):
    """Inline photo. A click opens the file so you can pinch-zoom in the viewer."""

    def __init__(self, path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = path
        self.setObjectName("SmsBubbleImage")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Open picture")
        self.setScaledContents(False)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._path:
            open_local_path(self._path)
        super().mouseReleaseEvent(event)


def _photo_pixmap(path: str) -> QPixmap | None:
    pix = QPixmap(path)
    if pix.isNull():
        return None
    if pix.width() > MAX_IMAGE_WIDTH:
        pix = pix.scaledToWidth(
            MAX_IMAGE_WIDTH, Qt.TransformationMode.SmoothTransformation
        )
    return pix


def _looks_like_phone(value: str) -> bool:
    """True when the string is a number, not a Messages title that happens to
    contain a digit (\"Mom 2\", a group name, a leftover id)."""
    raw = (value or "").strip()
    if not raw:
        return False
    stripped = "".join(ch for ch in raw if ch not in " \t()+-.–—")
    return bool(stripped) and stripped.isdigit()


def chat_target(
    *,
    alias: str = "",
    phone: str = "",
    sender: str = "",
    title: str = "",
    contacts: dict | None = None,
) -> tuple[str, str]:
    """Return (alias, e164) when a tile can send; empty e164 means do not open.

    Google Messages notices often carry a name, not a number. Match the book
    before giving up — the pill title is the same string the phone posted.
    """
    alias = (alias or "").strip()
    raw_phone = (phone or sender or "").strip()
    if _looks_like_phone(raw_phone):
        e164 = to_e164(raw_phone)
        if e164:
            return alias, e164
    book = contacts if contacts is not None else load_contacts()
    for candidate in (alias, title, phone, sender):
        text = (candidate or "").strip()
        if not text:
            continue
        contact = resolve_contact(text, book) or match_contact_label(text, book)
        if contact is not None and contact.e164:
            return contact.alias or alias, contact.e164
    return alias, ""


class SmsChatWindow(QWidget):
    """One frameless glass room for one phone number."""

    send_requested = Signal(str)
    retry_requested = Signal(str)
    closed = Signal()
    hidden = Signal()
    shown = Signal()

    def __init__(
        self,
        *,
        key: str,
        title: str,
        alias: str = "",
        phone: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.key = key
        self.alias = alias
        self.phone = phone
        self._unread = 0
        self._ready = False
        self._attention_until = 0.0
        self._base_title = title or phone or alias or "chat"
        self.setObjectName("SmsChat")
        self.setWindowTitle(self._base_title)
        self.setMinimumSize(320, 360)
        self.resize(TILE_WIDTH, TILE_HEIGHT)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        seal_tool_window(self, round_corners=True)
        self._drag_origin: QPoint | None = None
        self._rim_pulse = QTimer(self)
        self._rim_pulse.setInterval(100)
        self._rim_pulse.timeout.connect(self._tick_rim_pulse)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._plate = GlassFrame(
            self,
            object_name="NotifyInboxGlass",
            fill_alpha=int(GLASS.get("fill_float", 255)),
            radius=float(GLASS["radius"]),
            pulse_rim=False,
            round_cutout=True,
        )
        outer.addWidget(self._plate)

        root = QVBoxLayout(self._plate)
        root.setContentsMargins(*space_box("plate", "inset"))
        root.setSpacing(SPACE["gap"])

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.heading = QLabel(self._base_title)
        self.heading.setObjectName("SettingsHeading")
        self.heading.setCursor(Qt.CursorShape.OpenHandCursor)
        self.heading.setToolTip("Drag to move")
        head.addWidget(self.heading, stretch=1)
        min_btn = QToolButton()
        min_btn.setObjectName("SettingsMinimize")
        min_btn.setIcon(window_minimize_icon(12))
        min_btn.setFixedSize(METRICS["chrome"], METRICS["chrome"])
        min_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        min_btn.setToolTip("Minimize")
        min_btn.clicked.connect(self.minimize)
        close_btn = QToolButton()
        close_btn.setObjectName("SettingsClose")
        close_btn.setIcon(window_close_icon(12))
        close_btn.setFixedSize(METRICS["chrome"], METRICS["chrome"])
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setToolTip("Close")
        close_btn.clicked.connect(self.close)
        head.addWidget(min_btn)
        head.addWidget(close_btn)
        root.addLayout(head)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("SmsChatScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # AlignBottom keeps a short thread on the composer. Do not put a
        # stretch in this layout: QScrollArea then lets you scroll past the
        # last bubble into empty space, and _scroll_to_end follows that void.
        self._scroll.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom
        )
        host = QWidget()
        host.setObjectName("SmsChatThread")
        host.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._thread = QVBoxLayout(host)
        self._thread.setContentsMargins(0, 0, 4, 0)
        self._thread.setSpacing(6)
        self._thread.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self._scroll.setWidget(host)
        root.addWidget(self._scroll, stretch=1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.input = QLineEdit()
        self.input.setObjectName("InstrumentSearch")
        self.input.setPlaceholderText("text…")
        self.input.setFixedHeight(28)
        self.input.returnPressed.connect(self._send)
        send_btn = QPushButton("send")
        send_btn.setObjectName("InstrumentAction")
        send_btn.setFixedHeight(28)
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        send_btn.clicked.connect(self._send)
        row.addWidget(self.input, stretch=1)
        row.addWidget(send_btn)
        root.addLayout(row)

        # Armed last, because eventFilter() reads self.input and self.heading.
        # Adding `head` to the live plate layout reparents the heading, and Qt
        # delivers that event through the filter — which used to run before
        # self.input existed and take the constructor down with it.
        self.heading.installEventFilter(self)
        self.input.installEventFilter(self)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.minimize)

    def nativeEvent(self, eventType, message):  # type: ignore[override]
        handled = handle_native_resize(self, eventType, message)
        if handled is not None:
            return handled
        return super().nativeEvent(eventType, message)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        enable_win32_resize_frame(self)
        self._ready = True
        self._unread = 0
        self._set_heading(self._base_title)
        self.clear_attention()
        self._rim_pulse.start()
        self.input.setFocus()
        self.shown.emit()

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowActivate:
            self.clear_attention()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clear_attention()
        super().mousePressEvent(event)

    def attention(self) -> None:
        """Warm rim if this room is on screen but they are not in it.

        Qt can still report isActiveWindow() after you click into another
        app. If this process does not own the OS foreground, pulse anyway.
        """
        if not self.isVisible():
            return
        if process_owns_foreground() and self.isActiveWindow():
            return
        self._plate.set_attention(True)
        self._attention_until = time.monotonic() + ATTENTION_BREATH_S
        if not self._rim_pulse.isActive():
            self._rim_pulse.start()

    def clear_attention(self) -> None:
        self._attention_until = 0.0
        self._plate.set_attention(False)

    @property
    def has_attention(self) -> bool:
        return self._plate.has_attention

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._rim_pulse.stop()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.closed.emit()
        super().closeEvent(event)

    def minimize(self) -> None:
        self.showMinimized()
        self.hidden.emit()

    def badge(self) -> None:
        self._unread += 1
        mark = f"{self._base_title} · {self._unread}"
        self._set_heading(mark)
        self.setWindowTitle(mark)

    def append_message(self, message: SmsChatMessage, *, silent: bool = False) -> None:
        bubble = self._make_bubble(message)
        self._thread.addWidget(bubble)
        QTimer.singleShot(0, self._scroll_to_end)
        if self._ready and not self.isVisible() and not silent:
            self.badge()

    def _make_bubble(self, message: SmsChatMessage) -> QWidget:
        has_image = bool(message.media_kind == "image" and message.media_path)
        has_chip = message.media_kind == "photo_chip" or (
            looks_like_photo_body(message.body) and not has_image
        )
        caption = (message.body or "").strip()
        if looks_like_photo_body(caption) and not iter_http_urls(caption):
            caption = ""
        elif has_image and body_is_only_image_url(caption):
            caption = ""
        if not has_image and not has_chip:
            label = QLabel()
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            _fill_body_label(label, message.body)
            _apply_bubble_chrome(label, message.direction)
            return self._stamp_bubble(label, message)

        box = QWidget()
        _apply_bubble_chrome(box, message.direction)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(
            SPACE["gap"], SPACE["gap"], SPACE["gap"], SPACE["gap"]
        )
        layout.setSpacing(6)
        pixmap = _photo_pixmap(message.media_path) if has_image else None
        if pixmap is not None:
            image = SmsImageLabel(message.media_path)
            image.setPixmap(pixmap)
            layout.addWidget(image)
        elif has_chip or has_image:
            chip = QLabel("Photo")
            chip.setObjectName("SmsPhotoChip")
            chip.setAlignment(Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(chip)
        if caption:
            label = QLabel()
            label.setWordWrap(True)
            _fill_body_label(label, caption)
            layout.addWidget(label)
        box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        return self._stamp_bubble(box, message)

    def _stamp_bubble(self, inner: QWidget, message: SmsChatMessage) -> QWidget:
        wrap = QWidget()
        wrap.setObjectName("SmsBubbleStack")
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        if message.direction == "out":
            layout.setAlignment(Qt.AlignmentFlag.AlignRight)
        elif message.direction == "system":
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(inner)
        meta = format_bubble_time(message.t)
        if message.status == "pending":
            meta = f"{meta} · sending"
        elif message.status == "failed":
            meta = f"{meta} · failed"
            if message.error:
                inner.setToolTip(message.error)
        clock = QLabel(meta)
        clock.setObjectName("SmsBubbleTime")
        layout.addWidget(clock)
        if message.status == "failed" and message.direction == "out":
            retry = QPushButton("retry")
            retry.setObjectName("InstrumentAction")
            retry.setFixedHeight(24)
            retry.setCursor(Qt.CursorShape.PointingHandCursor)
            retry.clicked.connect(
                lambda _=False, body=message.body: self.retry_requested.emit(body)
            )
            layout.addWidget(retry)
        wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        return wrap

    def set_messages(self, messages: list[SmsChatMessage]) -> None:
        while self._thread.count():
            item = self._thread.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for message in messages:
            self.append_message(message, silent=True)

    def _send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.send_requested.emit(text)

    def _last_bubble(self) -> QWidget | None:
        for i in range(self._thread.count() - 1, -1, -1):
            item = self._thread.itemAt(i)
            widget = item.widget() if item is not None else None
            if widget is not None:
                return widget
        return None

    def _scroll_to_end(self) -> None:
        last = self._last_bubble()
        if last is not None:
            self._scroll.ensureWidgetVisible(last, 0, 6)
            return
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _set_heading(self, text: str) -> None:
        self.heading.setText(text)
        self.setWindowTitle(text)

    def _tick_rim_pulse(self) -> None:
        if self._plate._attention:
            self._plate.advance_attention(0.1)
            if self._attention_until and time.monotonic() >= self._attention_until:
                self._plate.set_attention(False, ember=True)
                self._attention_until = 0.0
        else:
            advance_rim_pulse(0.1)
        self._plate.update()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched is self.input and event.type() == QEvent.Type.FocusIn:
            self.clear_attention()
        if watched is self.heading:
            if event.type() == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
                if event.button() == Qt.MouseButton.LeftButton:
                    self.clear_attention()
                    self._drag_origin = (
                        event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    )
                    return True
            if event.type() == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
                if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
                    self.move(event.globalPosition().toPoint() - self._drag_origin)
                    return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_origin = None
        return super().eventFilter(watched, event)


class SmsChatRegistry:
    """Per-person rooms. Close forgets the window; the thread persists on disk."""

    def __init__(
        self,
        host: QWidget,
        *,
        persist: bool = False,
        store_path=None,
    ) -> None:
        self._host = host
        self._canon: dict[str, str] = {}
        self._buffers: dict[str, list[SmsChatMessage]] = {}
        self._meta: dict[str, dict[str, str]] = {}
        self._windows: dict[str, SmsChatWindow] = {}
        self._order: list[str] = []
        self._send = None
        self._shown = None
        self._persist_on = persist
        self._store_path = store_path
        if persist:
            self._hydrate()

    def set_send_handler(self, handler) -> None:
        self._send = handler

    def set_shown_handler(self, handler) -> None:
        self._shown = handler

    def room_state(
        self,
        *,
        alias: str = "",
        phone: str = "",
        sender: str = "",
    ) -> tuple[SmsChatWindow | None, RoomPresence]:
        key = self.resolve_key(alias=alias, phone=phone or sender, sender=sender)
        window = self._windows.get(key) if key else None
        if window is None:
            return None, "hidden"
        if not window.isVisible():
            return window, "hidden"
        if window.isActiveWindow():
            return window, "focused"
        return window, "visible"

    def resolve_key(self, *, alias: str = "", phone: str = "", sender: str = "") -> str:
        keys = list(thread_keys(alias=alias, phone=phone, sender=sender))
        if not keys:
            return ""
        primary = ""
        for key in keys:
            mapped = self._canon.get(key)
            if mapped:
                primary = mapped
                break
            if key in self._buffers or key in self._windows:
                primary = key
                break
        if not primary:
            primary = keys[0]
        for key in keys:
            self._canon[key] = primary
        return primary

    def messages(self, key: str) -> list[SmsChatMessage]:
        return list(self._buffers.get(key) or [])

    def window(self, key: str) -> SmsChatWindow | None:
        return self._windows.get(key)

    def open(
        self,
        *,
        alias: str = "",
        phone: str = "",
        sender: str = "",
        title: str = "",
        seed: list[str] | None = None,
        contacts: dict | None = None,
    ) -> SmsChatWindow | None:
        found_alias, e164 = chat_target(
            alias=alias,
            phone=phone,
            sender=sender,
            title=title,
            contacts=contacts,
        )
        if not e164:
            key = self.resolve_key(
                alias=found_alias or alias, phone=phone, sender=sender
            )
            stored = str((self._meta.get(key) or {}).get("phone") or "")
            e164 = to_e164(stored)
        if not e164:
            return None
        key = self.resolve_key(alias=found_alias or alias, phone=e164, sender=sender)
        if not key:
            return None
        if seed:
            before = len(self._buffers.get(key) or [])
            self._seed(key, seed)
            live = self._windows.get(key)
            if live is not None:
                for message in self._buffers.get(key, [])[before:]:
                    live.append_message(message)
        existing = self._windows.get(key)
        if existing is not None:
            existing.phone = e164 or existing.phone
            existing.alias = found_alias or existing.alias
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return existing
        self._evict_if_needed()
        heading = title or found_alias or e164
        window = SmsChatWindow(
            key=key,
            title=heading,
            alias=found_alias or alias,
            phone=e164,
            parent=self._host,
        )
        window.set_messages(self.messages(key))
        window.send_requested.connect(
            lambda body, k=key, a=window.alias, p=window.phone: self._emit_send(
                k, body, a, p
            )
        )
        window.retry_requested.connect(
            lambda body, k=key, a=window.alias, p=window.phone: self._emit_send(
                k, body, a, p, retry=True
            )
        )
        window.closed.connect(lambda k=key: self._forget_window(k))
        window.shown.connect(lambda w=window: self._emit_shown(w))
        self._meta[key] = {
            "alias": found_alias or alias,
            "phone": e164,
            "title": heading,
        }
        self._windows[key] = window
        self._order.append(key)
        self._place(window)
        window.show()
        window.raise_()
        return window

    def append_inbound(
        self,
        *,
        body: str,
        alias: str = "",
        phone: str = "",
        sender: str = "",
        title: str = "",
        media_path: str = "",
        media_kind: str = "",
        sent_at: str = "",
    ) -> None:
        text = (body or "").strip()
        if not text and not media_path and media_kind != "photo_chip":
            return
        key = self.resolve_key(alias=alias, phone=phone or sender, sender=sender)
        if not key:
            return
        message = SmsChatMessage(
            direction="in",
            body=text,
            t=parse_message_time(sent_at),
            media_path=media_path,
            media_kind=media_kind,
        )
        self._buffers.setdefault(key, []).append(message)
        self._persist()
        window = self._windows.get(key)
        if window is not None:
            window.append_message(message)
            if title:
                window._base_title = title
                if window.isVisible():
                    window._set_heading(title)
            if window.isVisible():
                window.attention()

    def append_outbound(
        self,
        *,
        body: str,
        alias: str = "",
        phone: str = "",
    ) -> None:
        text = (body or "").strip()
        if not text:
            return
        key = self.resolve_key(alias=alias, phone=phone, sender=phone)
        if not key or key not in self._windows:
            self._buffers.setdefault(key, []).append(
                SmsChatMessage(direction="out", body=text)
            ) if key else None
            return
        message = SmsChatMessage(direction="out", body=text, status="sent")
        self._buffers.setdefault(key, []).append(message)
        self._persist()
        window = self._windows[key]
        window.append_message(message)

    def system(self, key: str, text: str) -> None:
        message = SmsChatMessage(direction="system", body=text)
        self._buffers.setdefault(key, []).append(message)
        self._persist()
        window = self._windows.get(key)
        if window is not None:
            window.append_message(message)

    def mark_last_out(self, key: str, *, ok: bool, error: str = "") -> None:
        buf = self._buffers.get(key) or []
        for message in reversed(buf):
            if message.direction != "out":
                continue
            message.status = "sent" if ok else "failed"
            message.error = error if not ok else ""
            break
        self._persist()
        window = self._windows.get(key)
        if window is not None:
            window.set_messages(buf)

    def hide_all(self) -> None:
        for window in self._windows.values():
            window.hide()

    def _seed(self, key: str, bodies: list[str]) -> None:
        buf = self._buffers.setdefault(key, [])
        have = {item.body for item in buf if item.direction == "in"}
        changed = False
        for body in bodies:
            text = str(body).strip()
            if text and text not in have:
                buf.append(SmsChatMessage(direction="in", body=text))
                have.add(text)
                changed = True
        if changed:
            self._persist()

    def _emit_shown(self, window: SmsChatWindow) -> None:
        if self._shown is not None:
            self._shown(window.alias, window.phone)

    def _emit_send(
        self,
        key: str,
        body: str,
        alias: str,
        phone: str,
        *,
        retry: bool = False,
    ) -> None:
        text = (body or "").strip()
        if not text:
            return
        buf = self._buffers.setdefault(key, [])
        if retry:
            for message in reversed(buf):
                if message.direction == "out" and message.body == text:
                    message.status = "pending"
                    message.error = ""
                    break
            else:
                buf.append(SmsChatMessage(direction="out", body=text, status="pending"))
        else:
            buf.append(SmsChatMessage(direction="out", body=text, status="pending"))
        self._persist()
        window = self._windows.get(key)
        if window is not None:
            window.set_messages(buf)
        if self._send is not None:
            self._send(key, text, alias, phone)

    def _hydrate(self) -> None:
        stored = load_threads(self._store_path)
        for key, row in stored.items():
            messages = [
                SmsChatMessage.from_row(item)
                for item in (row.get("messages") or [])
                if isinstance(item, dict)
            ]
            if not messages:
                continue
            self._buffers[key] = messages
            self._meta[key] = {
                "alias": str(row.get("alias") or ""),
                "phone": str(row.get("phone") or ""),
                "title": str(row.get("title") or ""),
            }
            for ident in thread_keys(
                alias=str(row.get("alias") or ""),
                phone=str(row.get("phone") or ""),
            ):
                self._canon[ident] = key

    def _persist(self) -> None:
        if not self._persist_on:
            return
        payload: dict[str, dict[str, Any]] = {}
        for key, messages in self._buffers.items():
            meta = self._meta.get(key) or {}
            payload[key] = {
                "alias": meta.get("alias") or "",
                "phone": meta.get("phone") or "",
                "title": meta.get("title") or "",
                "messages": cap_messages([item.as_row() for item in messages]),
            }
        save_threads(payload, self._store_path)

    def _forget_window(self, key: str) -> None:
        self._windows.pop(key, None)
        if key in self._order:
            self._order.remove(key)

    def _evict_if_needed(self) -> None:
        if len(self._windows) < MAX_TILES:
            return
        oldest = self._order[0] if self._order else ""
        window = self._windows.get(oldest)
        if window is not None:
            window.close()

    def _place(self, window: SmsChatWindow) -> None:
        host = self._host
        index = max(0, len(self._windows) - 1)
        x = host.x() + max(40, host.width() - window.width() - 36 - index * 24)
        y = host.y() + 72 + index * 24
        window.move(x, y)
