"""Quiet Python highlighting — one lamp, not a rainbow IDE."""

from __future__ import annotations

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)

from arelis.ui.theme import color

_KEYWORDS = (
    "and as assert async await break class continue def del elif else except "
    "finally for from global if import in is lambda nonlocal not or pass raise "
    "return try while with yield True False None"
).split()


def _fmt(name: str, *, italic: bool = False) -> QTextCharFormat:
    out = QTextCharFormat()
    tint = color(name)
    if isinstance(tint, QColor):
        out.setForeground(tint)
    if italic:
        out.setFontItalic(True)
    return out


class QuietPythonHighlighter(QSyntaxHighlighter):
    """Keywords a little warmer, strings a little creamier, comments dimmer."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._on = True
        self._keyword = _fmt("hint")
        self._keyword.setFontWeight(QFont.Weight.DemiBold)
        self._string = _fmt("accent2")
        self._comment = _fmt("dim")
        self._comment.setFontItalic(True)
        self._number = _fmt("accent2")
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        for word in _KEYWORDS:
            self._rules.append(
                (QRegularExpression(rf"\b{word}\b"), self._keyword)
            )
        self._rules.append(
            (QRegularExpression(r"\b[0-9]+(?:\.[0-9]+)?\b"), self._number)
        )
        self._string_rx = QRegularExpression(
            r"'''(?:\\.|[^'\\])*'''|\"\"\"(?:\\.|[^\"\\])*\"\"\""
            r"|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\""
        )
        self._comment_rx = QRegularExpression(r"#[^\n]*")

    def set_enabled(self, on: bool) -> None:
        if on == self._on:
            return
        self._on = on
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # Qt override
        if not self._on:
            return
        for regex, fmt in self._rules:
            it = regex.globalMatch(text)
            while it.hasNext():
                hit = it.next()
                self.setFormat(hit.capturedStart(), hit.capturedLength(), fmt)
        it = self._comment_rx.globalMatch(text)
        while it.hasNext():
            hit = it.next()
            self.setFormat(hit.capturedStart(), hit.capturedLength(), self._comment)
        it = self._string_rx.globalMatch(text)
        while it.hasNext():
            hit = it.next()
            self.setFormat(hit.capturedStart(), hit.capturedLength(), self._string)
