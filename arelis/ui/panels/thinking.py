from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget


class ThinkingPanel(QWidget):
    """The interesting part — how she thinks. Housekeeping sits under it."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.view = QPlainTextEdit()
        self.view.setObjectName("ThinkingView")
        self.view.setReadOnly(True)
        self.view.setPlaceholderText("she'll think here")
        self.view.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.view, stretch=1)
        self.footer = QLabel("")
        self.footer.setObjectName("ThinkingFooter")
        self.footer.setWordWrap(True)
        self.footer.hide()
        layout.addWidget(self.footer)
        self._stream_open = False
        self._last_status = ""
        self._last_essay = ""

    def append(self, text: str, kind: str = "trace") -> None:
        line = (text or "").strip()
        if not line:
            return
        if kind in {"status", "model"}:
            if line == self._last_status:
                return
            self._last_status = line
            self.footer.setText(line)
            self.footer.setVisible(True)
            return
        self._stream_open = False
        if line == self._last_essay:
            return
        self._last_essay = line
        self.view.appendPlainText(line)
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def extend_stream(self, chunk: str) -> None:
        """Model-think tokens as one wrapping paragraph. No console prefix."""
        if not chunk:
            return
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self._stream_open:
            existing = self.view.toPlainText()
            if existing and not existing.endswith("\n"):
                cursor.insertText("\n")
            self._stream_open = True
        cursor.insertText(chunk)
        self.view.setTextCursor(cursor)
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear(self) -> None:
        self._stream_open = False
        self._last_status = ""
        self._last_essay = ""
        self.view.clear()
        self.footer.clear()
        self.footer.hide()
