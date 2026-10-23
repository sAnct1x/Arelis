from __future__ import annotations

import html
import math
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer, QUrl, QUrlQuery, Signal
from PySide6.QtGui import (
    QBrush,
    QDesktopServices,
    QGuiApplication,
    QMouseEvent,
    QTextCursor,
    QTextFormat,
    QTextTable,
)
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from arelis.attachments import (
    parse_attachments_from_turn,
    resolve_staged_path,
    split_attachments_turn,
)
from arelis.core.document_refs import files_in_turn
from arelis.local_open import open_local_file, reveal_local_file
from arelis.ui.attach_bar import ATTACH_TILE
from arelis.ui.chat_browser import CHART_SCHEME, ChatBrowser
from arelis.ui.chat_find import ChatFindBar
from arelis.ui.markdown import render_markdown
from arelis.ui.math_images import math_html, prewarm
from arelis.ui.theme import COLORS, SPACE, color
from arelis.ui.void_idle import OrbitIdle


# The assistant bubble is painted through render_markdown. Deltas arm a short
# timer if one is not already waiting, so a fast stream still paints instead
# of waiting for a pause. Each paint is one full render of the reply so far.
# A slow paint raises the interval so it stays under about a quarter of the
# GUI thread. Finish, a chart that arrives while the bubble is open, and a
# tool retract all update immediately. The finished paint does not use the
# streaming image rule. The plate waits for a visible character. Until then
# the paint is the caret alone.
def _ink(name: str, fallback: str = "") -> str:
    return COLORS.get(name) or COLORS.get(fallback) or COLORS["text"]


def _assistant_label() -> str:
    dim = _ink("text_dim")
    return (
        '<table width="100%" cellspacing="0" cellpadding="0" style="margin:14px 0 3px 0;">'
        "<tr>"
        f'<td style="color:{dim};font-size:11px;letter-spacing:0.08em;">'
        "arelis</td>"
        '<td width="18%"></td>'
        "</tr></table>"
    )


_BUBBLE_MARK = "bubble"


def _marked_bubble(fmt) -> bool:
    name = fmt.property(QTextFormat.Property.AnchorName)
    if isinstance(name, str):
        return name == _BUBBLE_MARK
    if isinstance(name, (list, tuple)):
        return _BUBBLE_MARK in name
    return False


def wash_message_cells(document) -> None:
    """One translucent coat behind each message.

    A CSS background paints again on every line under the words. ``bgcolor``
    is a single rectangle and it drops alpha, which is the hard black plate.
    The cell brush keeps the wash's alpha, so something bright behind the
    transcript dims and the type stays readable.
    """
    wash = color("bubble_wash")
    want = wash.getRgb()

    def walk(frame) -> None:
        it = frame.begin()
        while not it.atEnd():
            child = it.currentFrame()
            it += 1
            if not isinstance(child, QTextTable):
                continue
            for row in range(child.rows()):
                for col in range(child.columns()):
                    cell = child.cellAt(row, col)
                    fmt = cell.format()
                    if not _marked_bubble(fmt):
                        continue
                    if fmt.background().color().getRgb() != want:
                        fmt.setBackground(QBrush(wash))
                        cell.setFormat(fmt)
            walk(child)

    walk(document.rootFrame())


def _assistant_open() -> str:
    """Open the assistant message.

    A table cell is one block, so the answer stays a column instead of a
    full-width bar. The cell is marked and left unfilled here; the wash is
    a brush applied once, because a CSS background paints per line and
    ``bgcolor`` cannot carry alpha.
    """
    pad = SPACE["gap"]
    inset = SPACE["inset"]
    return (
        '<table width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 8px 0;">'
        "<tr>"
        f'<td id="{_BUBBLE_MARK}" valign="top" width="82%" '
        f'style="color:{_ink("text")};">'
        f'<div style="padding:{pad}px {inset}px;">'
    )


_ASSISTANT_CLOSE = '</div></td><td width="18%"></td></tr></table>'


def _acts_html() -> str:
    dim = _ink("text_dim")
    return (
        f'<div style="margin:0 18% 12px 0;color:{dim};font-size:11px;'
        f'letter-spacing:0.08em;">'
        f'<a href="arelis-act://copy" style="color:{dim};text-decoration:none;">'
        f"copy</a>"
        f'<span style="color:{dim};"> · </span>'
        f'<a href="arelis-act://again" style="color:{dim};text-decoration:none;">'
        f"again</a>"
        f'<span style="color:{dim};"> · </span>'
        f'<a href="arelis-act://export" style="color:{dim};text-decoration:none;">'
        f"export conversation</a>"
        f"</div>"
    )


_CARET_GLYPHS = {"▍", "|", "▌"}
# Floor for the stream timer. A burst paints at most about 20 times a second.
# A slow full paint raises the interval so one paint stays under a quarter of the thread.
_STREAM_PAINT_MS = 50
_STREAM_BUDGET = 0.25
_STREAM_PAINT_MAX_MS = 2000
_CHEVRON_CLOSED = ">"
_CHEVRON_OPEN = "v"


def _thought_has_body(thought) -> bool:
    """True when the block holds reasoning, not just the timer."""
    if any(line.strip() for line in thought.lines):
        return True
    return bool(thought.stream.strip())


def _thought_phrase(seconds: float, done: bool) -> str:
    whole = int(seconds)
    if whole < 0:
        whole = 0
    if whole >= 60:
        body = f"{whole // 60}m {whole % 60}s"
    else:
        body = f"{whole}s"
    if done:
        return f"Thought for {body}"
    return f"Thinking for {body}"


@dataclass
class _Thought:
    id: str
    lines: list[str] = field(default_factory=list)
    stream: str = ""
    started: float = 0.0
    sealed_at: float | None = None
    open: bool = False
    start: int | None = None
    end: int | None = None
    live: bool = True
    painted: str = ""


class ChatProgress(QLabel):
    """Turn-status line above the composer. Looks like copy; click is a control."""

    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ChatProgress")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setToolTip("show thinking")
        self.setAccessibleName("show thinking")
        self.setAccessibleDescription("show thinking")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class ChatPanel(QWidget):
    """Message surface. When embedded=True, lives inside ConversationStage glass.

    Assistant messages are written twice, and both times go through the same
    markdown renderer. The streaming pass repaints the open bubble as tokens
    arrive. The plate waits until the draft has a visible character; the caret
    is what shows before that. The final pass deletes that draft and re-inserts
    the authoritative answer. Both passes are anchored: the document position
    taken before the bubble is drawn is what lets the draft be removed exactly,
    whether it is being replaced with the finished answer or discarded because
    a later retract withdrew a draft that will not be the reply.
    """

    session_clicked = Signal(str)
    # An opening suggestion from the empty orbit, on its way to the composer.
    suggestion_clicked = Signal(str)
    new_requested = Signal()
    # The thinking line above the composer: open Thinking, or pulse it.
    progress_clicked = Signal()
    again_requested = Signal()
    export_requested = Signal()
    desk_requested = Signal(str)

    def __init__(self, parent=None, *, embedded: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("ChatPanelInner")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.empty = OrbitIdle()
        self.empty_title = self.empty.listen_word
        self.empty_hint = self.empty.listen_word
        self.empty.session_clicked.connect(self._on_idle_session)
        self.empty.suggestion_clicked.connect(self.suggestion_clicked.emit)
        self.empty.new_requested.connect(self.new_requested.emit)
        layout.addWidget(self.empty, stretch=1)

        self.view = ChatBrowser()
        self.view.setObjectName("ChatView")
        self.view.setReadOnly(True)
        # A visible I-beam in the transcript reads as leftover carets between
        # bubbles. Selection still works; the cursor does not need to blink.
        self.view.setCursorWidth(0)
        # Custom arelis-file: links (Open / Show in folder) must not go through
        # Windows "choose an app". http/https/mailto are opened in _on_anchor.
        self.view.setOpenExternalLinks(False)
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._on_anchor)
        self._washing = False
        self.view.document().contentsChange.connect(self._wash_bubbles)
        self.view.hide()
        layout.addWidget(self.view, stretch=1)
        layout.addWidget(ChatFindBar(self.view, self))

        # In-chat loading gate — shimmer, not a console window. Clickable so
        # the Thinking dock can stay closed until she asks for it.
        self.progress = ChatProgress()
        self.progress.hide()
        self.progress.clicked.connect(self.progress_clicked.emit)
        self._progress_fx = QGraphicsOpacityEffect(self.progress)
        self.progress.setGraphicsEffect(self._progress_fx)
        self._progress_fx.setOpacity(1.0)
        self._shimmer_dir = -1
        self._shimmer_timer = QTimer(self)
        self._shimmer_timer.setInterval(70)
        self._shimmer_timer.timeout.connect(self._tick_shimmer)
        layout.addWidget(self.progress)

        self._stream_open = False
        self._has_messages = False
        self._caret_on = False
        # Document position immediately before the streaming bubble began, and
        # the raw text streamed into it. Both are None/empty when no bubble is open.
        self._anchor: int | None = None
        self._stream_text: list[str] = []
        # Exact body of the last finalized assistant bubble. A second finish
        # with the same text (ASSISTANT_DONE after _close_stream raced) must not
        # append a duplicate copy below the user line.
        self._last_assistant_body: str | None = None
        self._last_user_text = ""
        self._last_user_attachments: list[dict[str, Any]] = []
        self._acts_pos: int | None = None
        self._pending_notices: list[str] = []
        self._pending_files: list[tuple[str, str]] = []
        self._pending_charts: list[tuple[str, str]] = []
        # Absolute paths of charts this transcript is showing. The reply
        # renderer uses them so ![name](name) is not drawn a second time.
        self._shown_charts: list[str] = []
        self._file_tokens: dict[str, tuple[str, str]] = {}
        self._caret_timer = QTimer(self)
        self._caret_timer.setInterval(530)
        self._caret_timer.timeout.connect(self._blink_caret)
        # Single-shot. Armed only when idle, so a fast stream paints on the
        # interval instead of pushing the paint out until the tokens pause.
        self._stream_paint = QTimer(self)
        self._stream_paint.setSingleShot(True)
        self._stream_paint.setInterval(_STREAM_PAINT_MS)
        self._stream_paint.timeout.connect(self._repaint_stream)
        # Stick-to-bottom: rangeChanged is the moment the bar's maximum is
        # current. Pinning earlier leaves the last line under the viewport,
        # and a later timer then fights the user if they try to scroll.
        self._follow_bottom = True
        self._pinning_scroll = False
        bar = self.view.verticalScrollBar()
        bar.rangeChanged.connect(self._on_scroll_range)
        bar.valueChanged.connect(self._on_scroll_value)
        self._text_scale = 1.0
        self._parked_gutter = 0
        self._thoughts: list[_Thought] = []
        self._label_at: int | None = None
        self._turn_busy = False
        self._progress_from_turn = False
        self._thought_timer = QTimer(self)
        self._thought_timer.setInterval(1000)
        self._thought_timer.timeout.connect(self._tick_thought)
        self._idle_note_timer = QTimer(self)
        self._idle_note_timer.setSingleShot(True)
        self._idle_note_timer.setInterval(6000)
        self._idle_note_timer.timeout.connect(self._clear_idle_note)
        prewarm()

    @property
    def has_messages(self) -> bool:
        return self._has_messages

    def _wash_bubbles(self, *_args) -> None:
        if self._washing:
            return
        self._washing = True
        try:
            wash_message_cells(self.view.document())
        finally:
            self._washing = False

    def refresh_bubble_wash(self) -> None:
        """Repaint message scrims after a theme change."""
        self._wash_bubbles()
        for thought in self._thoughts:
            thought.painted = ""
            if thought.start is not None:
                self._repaint_thought(thought)
        body = max(10, min(24, round(14 * self._text_scale)))
        self.view.refresh_math(COLORS["text"], body)

    def _on_idle_session(self, session_id: str) -> None:
        self.session_clicked.emit(session_id)

    def set_parked_gutter(self, px: int) -> None:
        """Reserve the right edge so chat text misses the parked orbit.

        CSS padding-right on QTextBrowser does not inset HTML tables (the
        right-aligned ``you`` bubbles), so this is a real layout margin.
        The orbit sits in that strip; it is not painted over the transcript.
        """
        want = max(0, int(px))
        # Notify/readiness polls (~30s) re-place the orbit even when nothing
        # moved. Restyling QTextBrowser there shoves the transcript up a line.
        if want == self._parked_gutter:
            return
        follow = self._near_bottom()
        self._parked_gutter = want
        lay = self.layout()
        if lay is not None:
            lay.setContentsMargins(0, 0, self._parked_gutter, 0)
            # Inset the view now rather than on the next event-loop pass. The
            # orbit is positioned in the same turn as this reservation, so a
            # deferred relayout leaves one frame where the orbit overlaps the
            # transcript instead of sitting in the strip reserved for it.
            lay.activate()
        self._apply_view_style()
        self._scroll(follow=follow)

    def set_text_scale(self, scale: float) -> None:
        """Scale chat body (Ctrl+Plus / Settings). Idle type stays small."""
        self._text_scale = max(0.75, min(1.75, float(scale)))
        self._apply_view_style()
        body = max(10, min(24, round(14 * self._text_scale)))
        font = self.view.font()
        font.setPointSize(body)
        self.view.setFont(font)
        self.view.refresh_math(COLORS["text"], body)

    def _apply_view_style(self) -> None:
        body = max(10, min(24, round(14 * self._text_scale)))
        # Inner pad only. The parked orbit uses layout contentsMargins, because
        # Qt rich-text tables ignore stylesheet padding-right.
        self.view.setStyleSheet(f"font-size: {body}px; padding-right: {SPACE['plate']}px;")

    def _fade_new_message(self, start: int) -> None:
        """Ease a just-inserted message in. Images in that range stay as they are."""
        from arelis.ui.motion import fade_new_transcript

        fade_new_transcript(self.view, start)

    def _cancel_message_fade(self) -> None:
        from arelis.ui.motion import cancel_transcript_fade

        cancel_transcript_fade(self.view, restore=False)

    def _ensure_view(self) -> None:
        if not self._has_messages:
            self.empty.hide()
            self.view.show()
            self._has_messages = True

    def mark_turn(self, busy: bool) -> None:
        self._turn_busy = bool(busy)
        if busy:
            self._ensure_thought()
            if not self._thought_timer.isActive():
                self._thought_timer.start()
            return
        self._seal_live_thought()
        live = self._live_thought()
        if live is not None:
            live.live = False
        self._thought_timer.stop()

    def add_thought_line(self, text: str, *, keep_internal: bool = False) -> None:
        line = (text or "").strip()
        if not line:
            return
        from arelis.ui.panels.thinking import internal_status

        if internal_status(line) and not keep_internal:
            return
        thought = self._ensure_thought()
        thought.lines.append(line)
        self._repaint_thought(thought)

    def extend_thought(self, chunk: str) -> None:
        if not chunk:
            return
        thought = self._ensure_thought()
        thought.stream += chunk
        self._repaint_thought(thought)

    def seal_thought(self) -> None:
        self._seal_live_thought()

    def expand_thinking(self) -> None:
        thought = self._live_thought()
        if thought is None and self._thoughts:
            thought = self._thoughts[-1]
        if thought is None:
            return
        if not thought.open:
            thought.open = True
            self._repaint_thought(thought)
        self._scroll_to_thought(thought)

    def show_idle_note(self, text: str) -> None:
        if self._progress_from_turn and self.progress.isVisible():
            return
        self._progress_from_turn = False
        self.empty.set_phone_note(text)
        self._idle_note_timer.start(6000)

    def _clear_idle_note(self) -> None:
        if self._progress_from_turn:
            return
        self.empty.set_phone_note("")

    def _live_thought(self) -> _Thought | None:
        for thought in reversed(self._thoughts):
            if thought.live:
                return thought
        return None

    def _ensure_thought(self) -> _Thought:
        live = self._live_thought()
        if live is not None:
            return live
        thought = _Thought(id=uuid4().hex, started=time.monotonic())
        self._thoughts.append(thought)
        self._place_thought(thought)
        if self._turn_busy:
            self._thought_timer.start()
        return thought

    def _seal_live_thought(self) -> None:
        thought = self._live_thought()
        if thought is None or thought.sealed_at is not None:
            return
        # The timer can sit on screen while a turn is open. Sealing that
        # empty block is what left "Thought for 0s" after a quiet reply.
        if not _thought_has_body(thought):
            self._discard_empty_thought(thought)
            return
        thought.sealed_at = time.monotonic()
        self._repaint_thought(thought)

    def _discard_empty_thought(self, thought: _Thought) -> None:
        self._detach_thought(thought)
        if thought in self._thoughts:
            self._thoughts.remove(thought)
        thought.live = False
        if self._live_thought() is None:
            self._thought_timer.stop()
        self._restore_idle_if_blank()

    def _restore_idle_if_blank(self) -> None:
        if self._stream_open or self._thoughts:
            return
        if self.view.toPlainText().strip():
            return
        self._has_messages = False
        self._anchor = None
        self.view.clear()
        self.view.hide()
        self.empty.show()

    def _tick_thought(self) -> None:
        thought = self._live_thought()
        if thought is None or thought.sealed_at is not None or not self._turn_busy:
            self._thought_timer.stop()
            return
        follow = self._near_bottom()
        self._repaint_thought(thought)
        self._scroll(follow=follow)

    def _thought_html(self, thought: _Thought) -> str:
        dim = _ink("text_dim")
        rule = _ink("hairline_mid", "text_dim")
        now = thought.sealed_at if thought.sealed_at is not None else time.monotonic()
        phrase = _thought_phrase(now - thought.started, thought.sealed_at is not None)
        chevron = _CHEVRON_OPEN if thought.open else _CHEVRON_CLOSED
        href = f"arelis-act://thought/{thought.id}"
        head = (
            f'<div style="margin:2px 18% 4px 2px;">'
            f'<a href="{href}" style="color:{dim};text-decoration:none;font-size:12px;">'
            f"{chevron} {_esc(phrase)}</a></div>"
        )
        if not thought.open:
            return head
        parts = [_esc(line) for line in thought.lines]
        if thought.stream:
            parts.append(_esc(thought.stream))
        body = "<br>".join(parts)
        return (
            head
            + '<table width="82%" cellspacing="0" cellpadding="0" style="margin:0 0 8px 10px;">'
            + "<tr>"
            + f'<td width="3" style="background-color:{rule};">&nbsp;</td>'
            + f'<td style="color:{dim};font-size:12px;padding:2px 8px;">{body}</td>'
            + "</tr></table>"
        )

    def _place_thought(self, thought: _Thought) -> None:
        self._ensure_view()
        if self._stream_open and self._anchor is not None:
            pos = self._anchor
        else:
            pos = self._end_position()
        html = self._thought_html(thought)
        end = self._insert_html(pos, html)
        thought.start = pos
        thought.end = end
        thought.painted = html
        self._bump_after(pos, end - pos, skip=thought)

    def _repaint_thought(self, thought: _Thought) -> None:
        html = self._thought_html(thought)
        if thought.start is not None and html == thought.painted:
            return
        if thought.start is None:
            self._place_thought(thought)
            return
        start = thought.start
        old_end = thought.end if thought.end is not None else start
        cursor = self.view.textCursor()
        cursor.setPosition(min(start, self._end_position()))
        cursor.setPosition(min(old_end, self._end_position()), QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertHtml(html)
        new_end = cursor.position()
        thought.end = new_end
        thought.painted = html
        self._bump_after(old_end, new_end - old_end, skip=thought)

    def _detach_thought(self, thought: _Thought) -> None:
        if thought.start is None or thought.end is None:
            return
        start = thought.start
        end = thought.end
        cursor = self.view.textCursor()
        cursor.setPosition(min(start, self._end_position()))
        cursor.setPosition(min(end, self._end_position()), QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self._bump_after(end, start - end, skip=thought)
        thought.start = None
        thought.end = None
        thought.painted = ""

    def _insert_html(self, pos: int, html: str) -> int:
        cursor = self.view.textCursor()
        cursor.setPosition(min(pos, self._end_position()))
        cursor.insertHtml(html)
        return cursor.position()

    def _bump_after(self, pos: int, delta: int, skip: _Thought | None = None) -> None:
        if not delta:
            return
        if self._anchor is not None and self._anchor >= pos:
            self._anchor += delta
        if self._acts_pos is not None and self._acts_pos >= pos:
            self._acts_pos += delta
        if self._label_at is not None and self._label_at >= pos:
            self._label_at += delta
        for item in self._thoughts:
            if item is skip:
                continue
            if item.start is not None and item.start >= pos:
                item.start += delta
            if item.end is not None and item.end >= pos:
                item.end += delta

    def _scroll_to_thought(self, thought: _Thought) -> None:
        if thought.start is None:
            return
        cursor = self.view.textCursor()
        cursor.setPosition(min(thought.start, self._end_position()))
        self.view.setTextCursor(cursor)
        self.view.ensureCursorVisible()

    def toggle_thought(self, thought_id: str) -> None:
        for thought in self._thoughts:
            if thought.id == thought_id:
                thought.open = not thought.open
                self._repaint_thought(thought)
                return

    def _drop_dangling_label(self) -> None:
        if self._label_at is None:
            return
        live = self._live_thought()
        cut = live.start if live is not None and live.start is not None else self._end_position()
        start = self._label_at
        self._label_at = None
        if start >= cut:
            return
        cursor = self.view.textCursor()
        cursor.setPosition(min(start, self._end_position()))
        cursor.setPosition(min(cut, self._end_position()), QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self._bump_after(cut, start - cut)

    def add_user(
        self,
        text: str,
        *,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        """User text is shown exactly as typed, never as markdown.

        Echoing back a rendered version of someone's own message hides what they
        actually sent, which matters most for slash commands where the literal
        characters are the whole point. Optional attachments render as
        thumbnails under the bubble (read-only).
        """
        self._stop_caret()
        live = self._live_thought()
        if live is not None:
            self._seal_live_thought()
            live.live = False
        # If a stream is open, _close_stream finalizes it and keeps
        # _last_assistant_body so a following ASSISTANT_DONE with the same text
        # does not append a second bubble. Clear the guard only when there was
        # no open stream, so a later turn may legitimately repeat a short reply.
        follow = self._near_bottom()
        had_stream = self._stream_open
        self._close_stream()
        if not had_stream:
            self._last_assistant_body = None
        self._ensure_view()
        self._strip_last_acts()
        self._last_user_text = text
        self._last_user_attachments = list(attachments or [])
        origin = self._end_position()
        self.view.append(_user_bubble_html(text, attachments=attachments))
        self._fade_new_message(origin)
        self._scroll(follow=follow)

    def begin_assistant(self) -> None:
        follow = self._near_bottom()
        self._close_stream()
        self._strip_last_acts()
        self._ensure_view()
        live = self._live_thought()
        if live is not None and live.start is not None:
            self._detach_thought(live)
        self._label_at = self._end_position()
        self.view.append(_assistant_label())
        if live is not None and _thought_has_body(live):
            self._place_thought(live)
        self._anchor = self._end_position()
        self._stream_text = []
        self._last_assistant_body = None
        self._stream_open = True
        self._caret_on = True
        self._caret_timer.start()
        self._stream_paint.setInterval(_STREAM_PAINT_MS)
        self._repaint_stream(follow=follow)

    def append_delta(self, text: str) -> None:
        if not self._stream_open:
            self.begin_assistant()
        self._seal_live_thought()
        self._stream_text.append(text)
        self._schedule_stream_paint()

    def _schedule_stream_paint(self) -> None:
        """Arm the short timer unless one is already waiting.

        ``start`` on a running single-shot timer resets the countdown.
        Tokens faster than the interval would then never paint, and the
        caret would sit still until the stream paused. Leaving the
        running timer alone caps the rate at one paint per interval.
        """
        if not self._stream_paint.isActive():
            self._stream_paint.start()

    def _cancel_stream_paint(self) -> None:
        self._stream_paint.stop()

    def _note_paint_cost(self, seconds: float) -> None:
        """Lengthen the interval when a full paint would hog the GUI thread.

        The floor stays ``_STREAM_PAINT_MS``. A long reply waits long enough
        that the paint is under about a quarter of the thread. The next
        cheaper paint puts the floor back.
        """
        need = math.ceil(seconds * 1000 / _STREAM_BUDGET) if seconds > 0 else 0
        interval = need if need > _STREAM_PAINT_MS else _STREAM_PAINT_MS
        if interval > _STREAM_PAINT_MAX_MS:
            interval = _STREAM_PAINT_MAX_MS
        if self._stream_paint.interval() != interval:
            self._stream_paint.setInterval(interval)

    def _flush_stream_paint(self) -> None:
        """Paint the open bubble now.

        Finish writes the authoritative answer itself. A chart that arrives
        while the bubble is open cannot wait for the timer, or the image
        mark stays up after the picture is already known.
        """
        self._cancel_stream_paint()
        self._repaint_stream()

    def _repaint_stream(self, *, follow: bool | None = None) -> None:
        """Repaint the open bubble from the reply so far.

        One full render, the same pass the finished answer uses. The caret
        rides in that HTML. Scroll follow is sampled here, before the
        replacement, unless the caller already sampled it. Nothing visible
        yet means the caret alone: the plate is the cell, and writing it
        empty is the flash before the words.
        """
        if not self._stream_open:
            return
        started = time.perf_counter()
        if follow is None:
            follow = self._near_bottom()
        # Latch before the replace. rangeChanged during the rewrite would
        # otherwise pin a user who already scrolled up.
        self._follow_bottom = follow
        parked = None
        if not follow:
            parked = self.view.verticalScrollBar().value()
        self.view.arm_math()
        body = "".join(self._stream_text)
        if body.strip():
            html = _assistant_body_html(
                body,
                self._shown_charts,
                caret=self._caret_on,
                streaming=True,
            )
        else:
            html = _caret_html() if self._caret_on else ""
        self._replace_from_anchor(html)
        if parked is not None:
            self._pin_to(parked)
        self._scroll(follow=follow)
        self._note_paint_cost(time.perf_counter() - started)

    def finish_assistant(self, text: str | None = None) -> None:
        """Replace the streamed draft with the rendered answer.

        text is the authoritative final answer from ASSISTANT_DONE. It is
        preferred over the accumulated deltas because the agent loop may have
        appended to it after streaming ended, which is how the Sources list
        gets added.
        """
        self._cancel_stream_paint()
        self._stop_caret()
        body = text or "".join(self._stream_text)
        if not self._stream_open and not body:
            self._flush_pending_notices()
            return
        # _close_stream may have already finalized the same draft when a spoken
        # user line arrived between the last delta and ASSISTANT_DONE. Appending
        # again is what produced arelis → you → arelis with identical answers.
        if not self._stream_open and self._last_assistant_body == body:
            self._flush_pending_notices()
            return
        follow = self._near_bottom()
        self.view.arm_math()
        if not self._stream_open:
            self._ensure_view()
            self._label_at = self._end_position()
            self._anchor = self._end_position()
        origin = self._anchor if self._anchor is not None else self._end_position()
        shown = self._shown_charts
        if not self._stream_open:
            self._replace_from_anchor(_assistant_bubble_html(body, shown_files=shown))
        else:
            self._replace_from_anchor(_assistant_body_html(body, shown))
        self._label_at = None
        self._stream_open = False
        self._stream_text = []
        self._anchor = None
        self._last_assistant_body = body
        self._flush_pending_notices()
        self._place_last_acts()
        self._fade_new_message(origin)
        self._scroll(follow=follow)

    def discard_stream(self) -> None:
        """Remove the streaming bubble without leaving a trace of it.

        Used when a round that looked like an answer turns out to be a preamble
        to a tool call. The text is not lost: the agent loop puts it in the
        thinking dock, which is where reasoning belongs.
        """
        self._cancel_stream_paint()
        self._stop_caret()
        if not self._stream_open:
            return
        self._replace_from_anchor("")
        self._drop_dangling_label()
        self._stream_open = False
        self._stream_text = []
        self._anchor = None
        self._flush_pending_notices()
        self._scroll(follow=True)

    def add_system(self, text: str) -> None:
        if self._stream_open:
            # Inbound SMS (and other notices) must not land inside an open
            # assistant bubble. Hold until the answer is finalized.
            self._pending_notices.append(text)
            return
        follow = self._near_bottom()
        self._stop_caret()
        self._close_stream()
        self._ensure_view()
        self.view.append(_notice_html(text))
        self._scroll(follow=follow)

    def add_file_card(self, name: str, path: str) -> None:
        """A clickable open / show-in-folder chip for a file she just wrote."""
        label = (name or Path(path).name).strip() or "file"
        abs_path = (path or "").strip()
        if not abs_path:
            return
        if self._stream_open:
            self._pending_files.append((label, abs_path))
            return
        follow = self._near_bottom()
        self._stop_caret()
        self._close_stream()
        self._ensure_view()
        self.view.append(self._file_card_html(label, abs_path))
        self._scroll(follow=follow)

    def _file_card_html(self, name: str, path: str) -> str:
        open_token = uuid4().hex
        reveal_token = uuid4().hex
        desk_token = uuid4().hex
        self._file_tokens[open_token] = ("open", path)
        self._file_tokens[reveal_token] = ("reveal", path)
        self._file_tokens[desk_token] = ("desk", path)
        open_href = f"arelis-file://local/?t={open_token}"
        reveal_href = f"arelis-file://local/?t={reveal_token}"
        desk_href = f"arelis-file://local/?t={desk_token}"
        return (
            f'<table width="100%" cellspacing="0" cellpadding="0" style="margin:2px 0 12px 0;">'
            "<tr>"
            f'<td id="{_BUBBLE_MARK}" valign="top" width="82%" '
            f'style="color:{_ink("text")};">'
            f'<div style="padding:{SPACE["gap"]}px {SPACE["inset"]}px;">'
            f'<div style="color:{_ink("text")};font-size:13px;margin-bottom:4px;">'
            f"{_esc(name)}</div>"
            f'<a href="{open_href}" style="color:{_ink("accent")};text-decoration:none;">'
            f"open</a>"
            f'<span style="color:{_ink("text_dim")};"> · </span>'
            f'<a href="{desk_href}" style="color:{_ink("accent")};text-decoration:none;">'
            f"on desk</a>"
            f'<span style="color:{_ink("text_dim")};"> · </span>'
            f'<a href="{reveal_href}" style="color:{_ink("accent")};text-decoration:none;">'
            f"show in folder</a>"
            f'</div></td><td width="18%"></td></tr></table>'
        )

    def add_chart_image(self, name: str, path: str) -> None:
        """Show a chart PNG in the transcript.

        The file card is a separate chip. This is the picture. While a
        bubble is open the picture waits, same as a file card, so finishing
        or retracting that bubble cannot delete it.
        """
        abs_path = (path or "").strip()
        if not abs_path:
            return
        label = (name or Path(path).name or "chart").strip() or "chart"
        if abs_path not in self._shown_charts:
            self._shown_charts.append(abs_path)
        if self._stream_open:
            self._pending_charts.append((label, abs_path))
            # The reply may already contain the image mark. Paint it now
            # that this chart is one the renderer knows about.
            self._flush_stream_paint()
            return
        self._append_chart_image(label, abs_path)

    def _append_chart_image(self, name: str, path: str) -> None:
        token = self.view.register_chart(path)
        label = html.escape(name, quote=True)
        self._ensure_view()
        follow = self._near_bottom()
        self.view.append(
            f'<p style="margin:4px 0 4px 0;">'
            f'<img src="{CHART_SCHEME}://c/{token}" alt="{label}" /></p>'
        )
        self._scroll(follow=follow)

    def _on_anchor(self, url: QUrl) -> None:
        scheme = (url.scheme() or "").lower()
        if scheme in {"http", "https", "mailto"}:
            QDesktopServices.openUrl(url)
            return
        if scheme == "arelis-act":
            host = (url.host() or url.path() or "").strip("/").lower()
            if host == "copy":
                self._copy_last()
            elif host == "again":
                self.again_requested.emit()
            elif host == "export":
                self.export_requested.emit()
            elif host == "thought":
                self.toggle_thought((url.path() or "").strip("/"))
            return
        if scheme != "arelis-file":
            return
        token = QUrlQuery(url).queryItemValue("t")
        action, path = self._file_tokens.get(token, ("", ""))
        if not path:
            return
        try:
            if action == "desk":
                self.desk_requested.emit(path)
                return
            if action == "reveal":
                reveal_local_file(path)
            else:
                open_local_file(path)
        except OSError:
            leaf = Path(path).name or "that file"
            self.add_system(f"I could not open {leaf}.")

    def _copy_last(self) -> None:
        body = self._last_assistant_body
        if not body:
            return
        clip = QGuiApplication.clipboard()
        if clip is not None:
            clip.setText(body)

    def _place_last_acts(self) -> None:
        self._strip_last_acts()
        if not self._last_assistant_body:
            return
        self._ensure_view()
        self._acts_pos = self._end_position()
        self.view.append(_acts_html())

    def _strip_last_acts(self) -> None:
        if self._acts_pos is None:
            return
        cursor = self.view.textCursor()
        end = self._end_position()
        if self._acts_pos > end:
            self._acts_pos = None
            return
        cursor.setPosition(self._acts_pos)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self.view.setTextCursor(cursor)
        self._acts_pos = None

    def show_progress(self, text: str = "✦ making a picture…") -> None:
        """Shimmering status gate while a long tool (e.g. Comfy) runs."""
        from arelis.ui.status_copy import THINKING_STATUS, WARMING_STATUS

        if text in {THINKING_STATUS, WARMING_STATUS}:
            return
        self._ensure_view()
        from arelis.i18n import tr

        self._progress_from_turn = True
        self._idle_note_timer.stop()
        self.progress.setText(tr(text) if text else text)
        appearing = not self.progress.isVisible()
        self.progress.show()
        if appearing:
            self._progress_fx.setOpacity(1.0)
            self._shimmer_dir = -1
        if not self._shimmer_timer.isActive():
            self._shimmer_timer.start()

    def clear_progress(self) -> None:
        self._progress_from_turn = False
        self._idle_note_timer.stop()
        self._shimmer_timer.stop()
        self.progress.hide()
        self.progress.setText("")
        self._progress_fx.setOpacity(1.0)

    def _tick_shimmer(self) -> None:
        if not self.progress.isVisible():
            self._shimmer_timer.stop()
            return
        op = float(self._progress_fx.opacity()) + self._shimmer_dir * 0.04
        if op <= 0.62:
            op = 0.62
            self._shimmer_dir = 1
        elif op >= 1.0:
            op = 1.0
            self._shimmer_dir = -1
        self._progress_fx.setOpacity(op)

    def clear(self) -> None:
        """Empty the surface and reset every streaming bookkeeping field.

        Loading a past session has to wipe the draft state too: an open stream
        anchor from the previous conversation would delete the wrong bytes on
        the next finish, and a stale _last_assistant_body would swallow a
        legitimate repeated reply.
        """
        self._cancel_stream_paint()
        self._stop_caret()
        self._stream_paint.setInterval(_STREAM_PAINT_MS)
        self.clear_progress()
        self._cancel_message_fade()
        self._stream_open = False
        self._has_messages = False
        self._anchor = None
        self._stream_text = []
        self._last_assistant_body = None
        self._last_user_text = ""
        self._last_user_attachments = []
        self._acts_pos = None
        self._pending_notices = []
        self._pending_files = []
        self._pending_charts = []
        self._shown_charts = []
        self._file_tokens = {}
        self._thoughts = []
        self._label_at = None
        self._thought_timer.stop()
        self.view.clear()
        self.view.hide()
        self.empty.show()

    def load_messages(self, messages: list[dict[str, str]]) -> None:
        """Paint an archived transcript. Notes stay off-screen; they are for the model.

        Built as one HTML document rather than N appends: long History reloads
        used to accumulate QTextEdit merge quirks so markdown drifted (L2).
        Document paths in the note still rebuild the open / show-in-folder chip.
        """
        self.clear()
        self.view.arm_math()
        chunks: list[str] = []
        last_assistant: str | None = None
        last_user = ""
        last_atts: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role") or "")
            content = str(message.get("content") or "")
            note = str(message.get("note") or "")
            if not content and role != "assistant":
                continue
            if role == "user":
                if not content:
                    continue
                stored = parse_attachments_from_turn(content)
                if stored:
                    _block, ask = split_attachments_turn(content)
                    chunks.append(_user_bubble_html(ask, attachments=stored))
                    last_user, last_atts = ask, stored
                else:
                    chunks.append(_user_bubble_html(content))
                    last_user, last_atts = content, []
            elif role == "assistant":
                if content:
                    chunks.append(_assistant_bubble_html(content))
                    last_assistant = content
                for name, path in files_in_turn(content, note):
                    chunks.append(self._file_card_html(name, path))
            elif role in {"notice", "system"}:
                if content:
                    chunks.append(_notice_html(content))
        if not chunks:
            return
        self._ensure_view()
        self.view.setHtml("".join(chunks))
        self._last_assistant_body = last_assistant
        self._last_user_text = last_user
        self._last_user_attachments = last_atts
        if last_assistant:
            self._place_last_acts()
        self._scroll(follow=True)

    def _flush_pending_notices(self) -> None:
        """Paint notices that arrived while an assistant bubble was open."""
        pending = self._pending_notices
        files = self._pending_files
        charts = self._pending_charts
        self._pending_notices = []
        self._pending_files = []
        self._pending_charts = []
        if not pending and not files and not charts:
            return
        self._ensure_view()
        for line in pending:
            text = (line or "").strip()
            if text:
                self.view.append(_notice_html(text))
        for name, path in files:
            self.view.append(self._file_card_html(name, path))
        for name, path in charts:
            self._append_chart_image(name, path)

    def _end_position(self) -> int:
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        return cursor.position()

    def _replace_from_anchor(self, html: str) -> None:
        """Delete everything written since the anchor, then optionally re-insert.

        The anchor was taken before QTextEdit.append inserted its paragraph
        break, so the selection covers that break too and the document is left
        exactly as it was before the bubble started.
        """
        if self._anchor is None:
            if html:
                self.view.append(html)
            return
        cursor = self.view.textCursor()
        cursor.setPosition(self._anchor)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self.view.setTextCursor(cursor)
        if html:
            self.view.append(html)

    def _stop_caret(self) -> None:
        self._caret_timer.stop()
        self._strip_caret()
        self._caret_on = False

    def _blink_caret(self) -> None:
        if not self._stream_open:
            return
        self._caret_on = not self._caret_on
        # A delta paint already pending will pick up the caret. Painting
        # again here would be a second full render in the same breath.
        if self._stream_paint.isActive():
            return
        self._repaint_stream()

    def _strip_caret(self) -> None:
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, 1)
        if cursor.selectedText() in _CARET_GLYPHS:
            cursor.removeSelectedText()

    def _close_stream(self) -> None:
        """Finish an open bubble because something else needs to be written.

        Reached when a new message arrives while a turn is still streaming, so
        the draft is rendered rather than discarded: it is the best answer there
        is at that point.
        """
        if self._stream_open:
            self.finish_assistant()

    def _near_bottom(self) -> bool:
        """True when the viewport is already following the latest content."""
        if not self.view.isVisible():
            return True
        bar = self.view.verticalScrollBar()
        if bar.maximum() <= 0:
            return True
        return (bar.maximum() - bar.value()) <= 48

    def _on_scroll_range(self, _lo: int, hi: int) -> None:
        """Pin after the bar's maximum is current, not before layout updates it."""
        if self._follow_bottom:
            self._pin_to(hi)

    def _on_scroll_value(self, value: int) -> None:
        """Leaving the bottom stops follow. A shrink that lands on the user does not resume it."""
        if self._pinning_scroll:
            return
        try:
            bar = self.view.verticalScrollBar()
        except RuntimeError:
            return
        if bar.maximum() <= 0:
            return
        if (bar.maximum() - value) > 48:
            self._follow_bottom = False

    def _scroll(self, *, follow: bool = True) -> None:
        """Follow the stream only when the caller says we were near the bottom.

        Callers must sample `_near_bottom` *before* mutating the document;
        otherwise a stick-to-bottom user loses the trail after max grows.
        A later rangeChanged pin uses that same follow flag so a late max
        update still lands on the last line, without a timer that fights
        a user who already scrolled away.
        """
        self._follow_bottom = follow
        if follow:
            self._pin_to_bottom()

    def _pin_to_bottom(self) -> None:
        """Put the viewport at the current bar maximum, if the view is alive."""
        try:
            bar = self.view.verticalScrollBar()
            self._pin_to(bar.maximum())
        except RuntimeError:
            pass

    def _pin_to(self, value: int) -> None:
        try:
            bar = self.view.verticalScrollBar()
            self._pinning_scroll = True
            bar.setValue(value)
        except RuntimeError:
            pass
        finally:
            self._pinning_scroll = False


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
    )


def _attachment_html(item: dict[str, Any]) -> str:
    """Thumbnail when the staged image is still on disk; otherwise the filename."""
    name = str(item.get("name") or Path(str(item.get("path") or "")).name or "file")
    kind = str(item.get("kind") or "")
    found = resolve_staged_path(str(item.get("path") or ""))
    if found is None:
        found = resolve_staged_path(str(item.get("source_path") or ""))
    if kind == "image" and found is not None:
        uri = (
            found.resolve()
            .as_uri()
            .replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
        )
        return (
            f'<img src="{uri}" height="{ATTACH_TILE}" '
            f'style="margin:2px 0 0 4px;vertical-align:middle;" />'
        )
    return (
        f'<span style="margin:2px 0 0 4px;font-size:11px;color:{_ink("text_dim")};">'
        f"{_esc(name)}</span>"
    )


def _notice_html(text: str) -> str:
    return (
        f'<p style="color:{_ink("status_amber", "amber")};'
        f'font-size:12px;margin:10px 8%;text-align:center;">'
        f"{_esc(text)}</p>"
    )


def _user_bubble_html(
    text: str,
    *,
    attachments: list[dict[str, Any]] | None = None,
) -> str:
    """Right-side user bubble.

    Qt rich text stretches block divs to the full row width, so a left-aligned
    label+body inside ``margin-left:18%`` reads as a wide empty bar. A 100%
    table with a right-aligned cell keeps the chip/text packed to the right
    under the ``you`` label (CSS ``inline-block`` is unreliable here).
    """
    body = _esc(text) if text.strip() else ""
    chips = ""
    if attachments:
        parts = [_attachment_html(item) for item in attachments]
        gap = "6px" if body else "0"
        chips = f'<div style="margin-top:{gap};" align="right">' + "".join(parts) + "</div>"
    if not body and not chips:
        body = "(attachment)"
    inner = body
    if body and chips:
        inner = f"{body}{chips}"
    elif chips:
        inner = chips
    return (
        '<table width="100%" cellspacing="0" cellpadding="0" style="margin:12px 0 8px 0;">'
        "<tr>"
        "<td></td>"
        '<td align="right" valign="top" style="width:1%;">'
        # Nested table shrink-wraps; a lone block div still fills the row in Qt.
        '<table cellspacing="0" cellpadding="0" align="right">'
        '<tr><td align="right">'
        f'<div style="color:{_ink("text_dim")};font-size:11px;'
        f'letter-spacing:0.08em;margin:0 2px 3px 0;" '
        f'align="right">you</div>'
        f'<table cellspacing="0" cellpadding="{SPACE["gap"]}" align="right">'
        "<tr>"
        f'<td id="{_BUBBLE_MARK}" align="left" '
        f'style="color:{_ink("text_dim")};text-align:left;">'
        f"{inner}</td></tr></table>"
        "</td></tr></table>"
        "</td></tr></table>"
    )


def _caret_html() -> str:
    return f'<span id="arelisCaret" style="color:{_ink("accent")};">▍</span>'


def _assistant_body_html(
    body: str,
    shown_files: Iterable[str] | None = None,
    *,
    caret: bool = False,
    streaming: bool = False,
) -> str:
    """The answer cell. Streaming and finish both come through here."""
    mark = _caret_html() if caret else ""
    return (
        _assistant_open()
        + render_markdown(
            body,
            math=math_html,
            shown_files=shown_files,
            streaming=streaming,
        )
        + mark
        + _ASSISTANT_CLOSE
    )


def _assistant_bubble_html(
    body: str,
    shown_files: Iterable[str] | None = None,
) -> str:
    return _assistant_label() + _assistant_body_html(body, shown_files)
