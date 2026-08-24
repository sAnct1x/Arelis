from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget


class ThinkingPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = QPlainTextEdit()
        self.view.setObjectName("ThinkingView")
        self.view.setReadOnly(True)
        self.view.setPlaceholderText("• trace appears here — model, tools, status…")
        self.view.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.view)
        self._stream_open = False
        self._last_status = ""

    def append(self, text: str, kind: str = "trace") -> None:
        self._stream_open = False
        prefix = {
            "model": "model",
            "tool": "tool ",
            "status": "status",
            "trace": "trace",
            "think": "think",
        }.get(kind, "trace")
        line = text.rstrip()
        if kind == "status" and line and line == self._last_status:
            return
        if kind == "status":
            self._last_status = line
        if line.startswith("[") and "]" in line[:24]:
            self.view.appendPlainText(line)
        else:
            self.view.appendPlainText(f"{prefix}  {line}")
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def extend_stream(self, chunk: str) -> None:
        """Append a model-think token into one wrapping paragraph.

        Ollama yields thinking a word at a time. Each chunk used to become its
        own `trace` line. Spaces and newlines in the chunk are kept so the
        dock reads as sentences, like a Thought block.
        """
        if not chunk:
            return
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self._stream_open:
            existing = self.view.toPlainText()
            if existing and not existing.endswith("\n"):
                cursor.insertText("\n")
            cursor.insertText("think  ")
            self._stream_open = True
        cursor.insertText(chunk)
        self.view.setTextCursor(cursor)
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear(self) -> None:
        self._stream_open = False
        self._last_status = ""
        self.view.clear()
