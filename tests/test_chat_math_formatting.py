"""Chat math stays readable: symbols, stars, pipes, minus signs, list numbers."""

from __future__ import annotations

import pytest

from arelis.ui.markdown import render_markdown

_EM = "\u2014"
_EN = "\u2013"


@pytest.fixture(autouse=True)
def _qt(qt_app):
    """Offscreen app from conftest, before any document is built."""
    return qt_app


def _blocks(src: str) -> list[str]:
    from PySide6.QtGui import QTextDocument

    doc = QTextDocument()
    doc.setHtml(render_markdown(src))
    out: list[str] = []
    block = doc.begin()
    while block.isValid():
        listing = block.textList()
        prefix = (listing.itemText(block) + " ") if listing else ""
        out.append(prefix + block.text())
        block = block.next()
    return [line for line in out if line.strip()]


def _vis(src: str) -> str:
    return " | ".join(_blocks(src))


def test_spaced_single_name_is_flattened() -> None:
    visible = _vis("Value is $ x $ here.")
    assert "$" not in visible
    assert "x" in visible


