from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent, QTextCursor
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from arelis.ui.markdown import render_markdown
from arelis.ui.theme import COLORS
from arelis.ui.void_idle import OrbitIdle

# The assistant bubble is built in two pieces because it is painted twice per
# turn. While tokens arrive it is left open and text is appended as fast plain
# text. When the turn ends the whole thing is replaced with rendered markdown.
# Rendering per token is not an option: a half-typed "**" would flicker between
# literal asterisks and bold on every keystroke.
_ACCENT = COLORS["accent"]
_TEXT = COLORS["text"]
_TEXT_DIM = COLORS["text_dim"]
_AMBER = COLORS.get("status_amber", COLORS["amber"])
_STATUS_WHITE = COLORS.get("status_white", COLORS["text"])
_BUBBLE = COLORS["bubble_wash"]
_ASSISTANT_LABEL = (
    '<div style="margin:14px 18% 3px 0;">'
    f'<div style="color:{_TEXT_DIM};font-size:11px;'
    f'letter-spacing:0.08em;margin-bottom:3px;">arelis</div></div>'
)
_ASSISTANT_OPEN = (
    '<div style="margin:0 18% 8px 0;">'
    f'<div style="background:{_BUBBLE};padding:8px 12px;border-radius:8px;color:{_TEXT};">'
)
_ASSISTANT_CLOSE = "</div></div>"

_CARET_GLYPHS = {"▍", "|", "▌"}


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

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class ChatPanel(QWidget):
    """Message surface. When embedded=True, lives inside ConversationStage glass.

    Assistant messages are written twice. The streaming pass appends plain text
    so tokens appear as they arrive, and the final pass deletes that draft and
    re-inserts it as rendered markdown. Both passes are anchored: the document
    position taken before the bubble is drawn is what lets the draft be removed
    exactly, whether it is being replaced with the finished answer or discarded
    because the model turned out to be calling a tool.
    """

    session_clicked = Signal(str)
    # An opening suggestion from the empty orbit, on its way to the composer.
    suggestion_clicked = Signal(str)
    # The thinking line above the composer: open Thinking, or pulse it.
    progress_clicked = Signal()

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
        layout.addWidget(self.empty, stretch=1)

        self.view = QTextBrowser()
        self.view.setObjectName("ChatView")
        self.view.setReadOnly(True)
        self.view.setOpenExternalLinks(True)
        self.view.hide()
        layout.addWidget(self.view, stretch=1)

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
        self._pending_notices: list[str] = []
        self._caret_timer = QTimer(self)
        self._caret_timer.setInterval(530)
        self._caret_timer.timeout.connect(self._blink_caret)
        # Owned by the panel so they die with it. See _scroll: these used to be
        # anonymous single-shots holding the scroll bar, and a panel destroyed
        # inside their 50ms window left them pointing at freed memory.
        self._settle_now = QTimer(self)
        self._settle_now.setSingleShot(True)
        self._settle_now.setInterval(0)
        self._settle_now.timeout.connect(self._pin_to_bottom)
        self._settle_soon = QTimer(self)
        self._settle_soon.setSingleShot(True)
        self._settle_soon.setInterval(50)
        self._settle_soon.timeout.connect(self._pin_to_bottom)
        self._text_scale = 1.0
        self._parked_gutter = 0

    @property
    def has_messages(self) -> bool:
        return self._has_messages

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

    def _apply_view_style(self) -> None:
        body = max(10, min(24, round(14 * self._text_scale)))
        # Inner pad only. The parked orbit uses layout contentsMargins, because
        # Qt rich-text tables ignore stylesheet padding-right.
        self.view.setStyleSheet(f"font-size: {body}px; padding-right: 16px;")

    def _ensure_view(self) -> None:
        if not self._has_messages:
            self.empty.hide()
            self.view.show()
            self._has_messages = True

    def add_user(
        self,
        text: str,
        *,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        """User text is shown exactly as typed, never as markdown.

        Echoing back a rendered version of someone's own message hides what they
        actually sent, which matters most for slash commands where the literal
        characters are the whole point. Optional attachments render as chips
        under the bubble (read-only).
        """
        self._stop_caret()
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
        self.view.append(_user_bubble_html(text, attachments=attachments))
        self._scroll(follow=follow)

    def begin_assistant(self) -> None:
        follow = self._near_bottom()
        self._close_stream()
        self._ensure_view()
        self._anchor = self._end_position()
        self._stream_text = []
        self._last_assistant_body = None
        self.view.append(_ASSISTANT_LABEL)
        self.view.append(_ASSISTANT_OPEN)
        self._stream_open = True
        self._start_caret()
        self._scroll(follow=follow)

    def append_delta(self, text: str) -> None:
        if not self._stream_open:
            self.begin_assistant()
        follow = self._near_bottom()
        self._stream_text.append(text)
        self._strip_caret()
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self._insert_caret()
        self._scroll(follow=follow)

    def finish_assistant(self, text: str | None = None) -> None:
        """Replace the streamed draft with the rendered answer.

        text is the authoritative final answer from ASSISTANT_DONE. It is
        preferred over the accumulated deltas because the agent loop may have
        appended to it after streaming ended, which is how the Sources list
        gets added.
        """
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
        if not self._stream_open:
            self._ensure_view()
            self._anchor = self._end_position()
        self._replace_from_anchor(_assistant_bubble_html(body))
        self._stream_open = False
        self._stream_text = []
        self._anchor = None
        self._last_assistant_body = body
        self._flush_pending_notices()
        self._scroll(follow=follow)

    def discard_stream(self) -> None:
        """Remove the streaming bubble without leaving a trace of it.

        Used when a round that looked like an answer turns out to be a preamble
        to a tool call. The text is not lost: the agent loop puts it in the
        thinking dock, which is where reasoning belongs.
        """
        self._stop_caret()
        if not self._stream_open:
            return
        self._replace_from_anchor("")
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

    def show_progress(self, text: str = "✦ Generating image…") -> None:
        """Shimmering status gate while a long tool (e.g. Comfy) runs."""
        self._ensure_view()
        self.progress.setText(text)
        appearing = not self.progress.isVisible()
        self.progress.show()
        if appearing:
            self._progress_fx.setOpacity(1.0)
            self._shimmer_dir = -1
        if not self._shimmer_timer.isActive():
            self._shimmer_timer.start()

    def clear_progress(self) -> None:
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
        self._stop_caret()
        self.clear_progress()
        self._stream_open = False
        self._has_messages = False
        self._anchor = None
        self._stream_text = []
        self._last_assistant_body = None
        self._pending_notices = []
        self.view.clear()
        self.view.hide()
        self.empty.show()

    def load_messages(self, messages: list[dict[str, str]]) -> None:
        """Paint an archived transcript. Notes stay off-screen; they are for the model.

        Built as one HTML document rather than N appends: long History reloads
        used to accumulate QTextEdit merge quirks so markdown drifted (L2).
        """
        self.clear()
        chunks: list[str] = []
        last_assistant: str | None = None
        for message in messages:
            role = str(message.get("role") or "")
            content = str(message.get("content") or "")
            if not content:
                continue
            if role == "user":
                chunks.append(_user_bubble_html(content))
            elif role == "assistant":
                chunks.append(_assistant_bubble_html(content))
                last_assistant = content
            elif role in {"notice", "system"}:
                chunks.append(_notice_html(content))
        if not chunks:
            return
        self._ensure_view()
        self.view.setHtml("".join(chunks))
        self._last_assistant_body = last_assistant
        self._scroll(follow=True)

    def _flush_pending_notices(self) -> None:
        """Paint notices that arrived while an assistant bubble was open."""
        pending = self._pending_notices
        self._pending_notices = []
        if not pending:
            return
        self._ensure_view()
        for line in pending:
            text = (line or "").strip()
            if text:
                self.view.append(_notice_html(text))

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

    def _start_caret(self) -> None:
        self._caret_on = True
        self._insert_caret()
        self._caret_timer.start()

    def _stop_caret(self) -> None:
        self._caret_timer.stop()
        self._strip_caret()
        self._caret_on = False

    def _blink_caret(self) -> None:
        if not self._stream_open:
            return
        self._strip_caret()
        self._caret_on = not self._caret_on
        if self._caret_on:
            self._insert_caret()

    def _insert_caret(self) -> None:
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(f'<span id="arelisCaret" style="color:{_ACCENT};">▍</span>')

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

    def _scroll(self, *, follow: bool = True) -> None:
        """Follow the stream only when the caller says we were near the bottom.

        Callers must sample `_near_bottom` *before* mutating the document;
        otherwise a stick-to-bottom user loses the trail after max grows.
        """
        if not follow:
            return
        self._pin_to_bottom()
        # QTextBrowser often updates max one event later; without this the
        # viewport sticks mid-thread after a long tool turn.
        self._settle_now.start()
        self._settle_soon.start()

    def _pin_to_bottom(self) -> None:
        """Put the viewport back at the end, if there is still a viewport.

        Reached from two timers, so the panel can be part-way through clear() or
        gone entirely by the time it runs.
        """
        try:
            bar = self.view.verticalScrollBar()
            bar.setValue(bar.maximum())
        except RuntimeError:
            pass


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def _notice_html(text: str) -> str:
    return (
        f'<p style="color:{_AMBER};font-size:12px;margin:10px 8%;text-align:center;">'
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
        parts: list[str] = []
        for item in attachments:
            name = _esc(str(item.get("name") or item.get("path") or "file"))
            parts.append(
                f'<span style="margin:2px 0 0 4px;padding:2px 0;'
                f'font-size:11px;color:{_TEXT_DIM};">'
                f"{name}</span>"
            )
        gap = "6px" if body else "0"
        chips = (
            f'<div style="margin-top:{gap};" align="right">'
            + "".join(parts)
            + "</div>"
        )
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
        '<td></td>'
        '<td align="right" valign="top" style="width:1%;">'
        # Nested table shrink-wraps; a lone block div still fills the row in Qt.
        '<table cellspacing="0" cellpadding="0" align="right">'
        "<tr><td align=\"right\">"
        f'<div style="color:{_TEXT_DIM};font-size:11px;letter-spacing:0.08em;margin:0 2px 3px 0;" '
        f'align="right">you</div>'
        f'<div style="background:{_BUBBLE};padding:8px 12px;'
        f'border-radius:8px;color:{_TEXT_DIM};text-align:left;">'
        f"{inner}</div>"
        "</td></tr></table>"
        "</td></tr></table>"
    )


def _assistant_bubble_html(body: str) -> str:
    return (
        _ASSISTANT_LABEL
        + _ASSISTANT_OPEN
        + render_markdown(body)
        + _ASSISTANT_CLOSE
    )
