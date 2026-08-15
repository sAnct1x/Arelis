from __future__ import annotations

from PySide6.QtCore import Qt
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

    def append(self, text: str, kind: str = "trace") -> None:
        prefix = {
            "model": "model",
            "tool": "tool ",
            "status": "status",
            "trace": "trace",
        }.get(kind, "trace")
        line = text.rstrip()
        if line.startswith("[") and "]" in line[:24]:
            self.view.appendPlainText(line)
        else:
            self.view.appendPlainText(f"{prefix}  {line}")
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear(self) -> None:
        self.view.clear()
