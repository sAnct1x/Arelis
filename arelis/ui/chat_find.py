"""Find in this chat.

The bar walks the document itself. A formula drawn as a picture still matches,
because the picture keeps its source as alt text and as a title. Nothing here
knows how the transcript was drawn.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import (
    QKeyEvent,
    QKeySequence,
    QShortcut,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QWidget,
)

from arelis.ui.theme import SPACE, color

_SEP = "\0"


class ChatFindBar(QWidget):
    """A slim bar: type to highlight, Enter and Shift+Enter to move, Esc to close."""

    def __init__(self, view, parent=None) -> None:
        super().__init__(parent)
        self.view = view
        self.setObjectName("ChatFindBar")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE["gap"], SPACE["micro"], SPACE["gap"], SPACE["micro"])
        row.setSpacing(SPACE["gap"])

        self.edit = QLineEdit()
        self.edit.setObjectName("InstrumentSearch")
        self.edit.setPlaceholderText("find in this chat")
        self.edit.setToolTip("find in this chat (Ctrl+F)")
        self.edit.setAccessibleName("find in this chat")
        self.edit.setFixedHeight(28)
        self.edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.edit.textChanged.connect(self._on_text)
        self.edit.installEventFilter(self)
        row.addWidget(self.edit, stretch=1)

        self.count = QLabel("")
        self.count.setObjectName("ChatFindCount")
        self.count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.count.setMinimumWidth(72)
        row.addWidget(self.count)

        self.prev_btn = QPushButton("previous")
        self.prev_btn.setObjectName("InstrumentAction")
        self.prev_btn.setToolTip("previous match (Shift+Enter)")
        self.prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.prev_btn.clicked.connect(self._previous)
        row.addWidget(self.prev_btn)

        self.next_btn = QPushButton("next")
        self.next_btn.setObjectName("InstrumentAction")
        self.next_btn.setToolTip("next match (Enter)")
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.next_btn.clicked.connect(self._next)
        row.addWidget(self.next_btn)

        # Widget context beats the composer's window-wide Esc, so closing the
        # bar does not also clear the box or stop a turn.
        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        esc.activated.connect(self.close_find)
        self._esc = esc

        self._query = ""
        self._rev = -1
        self._hits: list[tuple[int, int]] = []
        self._index = -1
        self.hide()

    def show_find(self) -> None:
        """Open the bar for the current chat and select whatever is already typed."""
        self.edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.show()
        self.edit.setFocus()
        self.edit.selectAll()
        self._on_text(self.edit.text())

    def find(self, text: str) -> bool:
        """Select the next match. Wraps at the end. False when nothing matches."""
        changed = self._recompute(text)
        if not self._hits:
            self._index = -1
            self._show(False)
            return False
        if changed or self._index < 0:
            self._index = 0
        else:
            self._index = (self._index + 1) % len(self._hits)
        self._show(True)
        return True

    def find_previous(self, text: str) -> bool:
        """Select the previous match. Wraps at the start."""
        changed = self._recompute(text)
        if not self._hits:
            self._index = -1
            self._show(False)
            return False
        if changed or self._index < 0:
            self._index = len(self._hits) - 1
        else:
            self._index = (self._index - 1) % len(self._hits)
        self._show(True)
        return True

    def close_find(self) -> None:
        """Hide the bar and drop every highlight."""
        self.edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hide()
        focus = QApplication.focusWidget()
        if focus is not None and (focus is self or self.isAncestorOf(focus)):
            focus.clearFocus()
        self._hits = []
        self._index = -1
        self._rev = -1
        self.view.setExtraSelections([])
        cursor = self.view.textCursor()
        if cursor.hasSelection():
            cursor.clearSelection()
            self.view.setTextCursor(cursor)
        self.count.setText("")

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if obj is not self.edit or not self.isVisible():
            return super().eventFilter(obj, event)
        kind = event.type()
        if kind not in {QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride}:
            return super().eventFilter(obj, event)
        if not isinstance(event, QKeyEvent):
            return super().eventFilter(obj, event)
        action = self._key_action(event)
        if action is None:
            return super().eventFilter(obj, event)
        event.accept()
        if kind == QEvent.Type.ShortcutOverride:
            return True
        if event.isAutoRepeat() and event.key() == Qt.Key.Key_Escape:
            return True
        action()
        return True

    def _key_action(self, event: QKeyEvent):
        key = event.key()
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if key == Qt.Key.Key_Escape:
            return self.close_find
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            return self._previous if shift else self._next
        if key == Qt.Key.Key_F3:
            return self._previous if shift else self._next
        return None

    def _on_text(self, text: str) -> None:
        self._recompute(text, force=True)
        self._index = 0 if self._hits else -1
        self._show(bool(self._hits))

    def _next(self) -> None:
        self.find(self.edit.text())

    def _previous(self) -> None:
        self.find_previous(self.edit.text())

    def _recompute(self, text: str, *, force: bool = False) -> bool:
        """Rebuild hits when the words or the document changed. True if they did."""
        rev = self.view.document().revision()
        if not force and text == self._query and rev == self._rev:
            return False
        self._query = text
        self._rev = rev
        self._hits = match_ranges(self.view.document(), text)
        return True

    def _show(self, have: bool) -> None:
        self._paint()
        if have and 0 <= self._index < len(self._hits):
            start, end = self._hits[self._index]
            cursor = QTextCursor(self.view.document())
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            self.view.setTextCursor(cursor)
            self.view.ensureCursorVisible()
        elif not have:
            cursor = self.view.textCursor()
            if cursor.hasSelection():
                cursor.clearSelection()
                self.view.setTextCursor(cursor)
        self._update_count()

    def _paint(self) -> None:
        paint = QTextCharFormat()
        paint.setBackground(color("selection"))
        document = self.view.document()
        selections = []
        for start, end in self._hits:
            cursor = QTextCursor(document)
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            extra = QTextEdit.ExtraSelection()
            extra.cursor = cursor
            extra.format = paint
            selections.append(extra)
        self.view.setExtraSelections(selections)

    def _update_count(self) -> None:
        if not self._query.strip():
            self.count.setText("")
            return
        total = len(self._hits)
        if total == 0:
            self.count.setText("none")
            return
        shown = self._index + 1 if self._index >= 0 else 1
        self.count.setText(f"{shown} of {total}")


def match_ranges(document, query: str) -> list[tuple[int, int]]:
    """Document ranges for query. Image alt text and title count as text."""
    needle = (query or "").strip()
    if not needle:
        return []
    haystack, spans = _search_text(document)
    if not haystack:
        return []
    pattern = re.compile(re.escape(needle), re.IGNORECASE)
    found: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for match in pattern.finditer(haystack):
        span = _span_for(spans, match.start(), match.end())
        if span is None or span in seen:
            continue
        seen.add(span)
        found.append(span)
    return found


def _search_text(document) -> tuple[str, list[tuple[int, int]]]:
    """Flat text plus the document range each character stands for.

    A negative range is a separator. Matches are not allowed to cross one,
    so words on either side of a picture do not glue to its source.
    """
    chars: list[str] = []
    spans: list[tuple[int, int]] = []

    def sep() -> None:
        if chars and spans[-1] != (-1, -1):
            chars.append(_SEP)
            spans.append((-1, -1))

    def add(text: str, start: int, end: int, *, each: bool) -> None:
        if not text:
            return
        sep()
        if each and len(text) == end - start:
            for offset, ch in enumerate(text):
                chars.append(ch)
                spans.append((start + offset, start + offset + 1))
            return
        for ch in text:
            chars.append(ch)
            spans.append((start, end))

    block = document.begin()
    first_block = True
    while block.isValid():
        if not first_block:
            sep()
        first_block = False
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            if fragment.isValid():
                fmt = fragment.charFormat()
                pos = fragment.position()
                length = fragment.length()
                if fmt.isImageFormat():
                    for source in _image_sources(fmt):
                        add(source, pos, pos + max(length, 1), each=False)
                else:
                    add(fragment.text(), pos, pos + length, each=True)
            it += 1
        block = block.next()
    return "".join(chars), spans


def _image_sources(fmt) -> list[str]:
    """Alt text and title, in that order, without repeating the same string."""
    image = fmt.toImageFormat()
    blobs: list[str] = []
    alt = image.stringProperty(QTextFormat.Property.ImageAltText) or ""
    tips = [image.toolTip() or "", fmt.toolTip() or ""]
    title_id = getattr(QTextFormat.Property, "ImageTitle", None)
    if title_id is not None:
        tips.append(image.stringProperty(title_id) or "")
    for blob in (alt, *tips):
        if blob and blob not in blobs:
            blobs.append(blob)
    return blobs


def _span_for(spans: list[tuple[int, int]], start: int, end: int) -> tuple[int, int] | None:
    doc_start = None
    doc_end = None
    for index in range(start, end):
        left, right = spans[index]
        if left < 0 or right <= left:
            return None
        doc_start = left if doc_start is None else min(doc_start, left)
        doc_end = right if doc_end is None else max(doc_end, right)
    if doc_start is None or doc_end is None or doc_end <= doc_start:
        return None
    return doc_start, doc_end


def open_chat_find(window) -> None:
    """Open find for the chat on this window."""
    chat = getattr(window, "chat", None)
    if chat is None:
        return
    bar = chat.findChild(ChatFindBar)
    if bar is not None:
        bar.show_find()


__all__ = ["ChatFindBar", "match_ranges", "open_chat_find"]
