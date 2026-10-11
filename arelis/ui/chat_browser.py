"""Chat transcript browser.

Math images and a later chart image share one resource hook. The HTML only
names ``arelis-math://f/<sha1>`` or ``arelis-chart://c/<token>``. Colour and
size stay out of the address, so a theme change recolours and a text-scale
change parses again without rewriting the document.

Copying a math image puts its formula source on the clipboard. The picture
itself is one private-use character, which is useless to paste.
"""

from __future__ import annotations

import hashlib
import math

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QImage, QTextCursor, QTextDocument, QTextFormat
from PySide6.QtWidgets import QTextBrowser

from arelis.ui.math_images import (
    MATH_SCHEME,
    image_for_url,
    latex_for_copy,
    set_target,
)
from arelis.ui.theme import COLORS, SPACE

CHART_SCHEME = "arelis-chart"
_IMAGE = int(QTextDocument.ResourceType.ImageResource)


def _blank_math_image() -> QImage:
    image = QImage(1, 1, QImage.Format.Format_ARGB32)
    image.fill(0)
    return image


class ChatBrowser(QTextBrowser):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._math_px = 14
        self._math_color = ""
        self._charts: dict[str, str] = {}

    def arm_math(self) -> None:
        """Point the renderer at the current ink, size, and bubble width."""
        self._math_color = COLORS.get("text") or "#f8f1ea"
        self._push_target()

    def refresh_math(self, color: str, px: int) -> None:
        """Recolour or resize formulas already in the document."""
        self._math_px = max(1, int(px))
        self._math_color = color or COLORS.get("text") or "#f8f1ea"
        self._push_target()
        document = self.document()
        urls = self._math_urls()
        for name in urls:
            image = image_for_url(name)
            if image is None:
                continue
            document.addResource(_IMAGE, QUrl(name), image)
        if urls:
            document.markContentsDirty(0, document.characterCount())

    def _push_target(self) -> None:
        set_target(
            color=self._math_color or COLORS.get("text") or "#f8f1ea",
            px=self._math_px,
            dpr=self.raster_dpr(),
            max_width=self.formula_width(),
            family=self.font().family(),
        )

    def raster_dpr(self) -> float:
        ratio = self.devicePixelRatioF() or 1.0
        return float(max(2, math.ceil(ratio)))

    def formula_width(self) -> float:
        """Bubble content width. Zero when the view has not been laid out."""
        width = self.viewport().width()
        if width <= 1:
            width = self.width()
        if width <= 1:
            return 0.0
        inner = width * 0.82 - 2 * SPACE["inset"]
        return max(0.0, float(inner))

    def register_chart(self, path: str) -> str:
        """Remember a chart file. Only registered tokens are served."""
        token = hashlib.sha1(path.encode("utf-8")).hexdigest()
        self._charts[token] = path
        return token

    def math_source_at(self, pos: int) -> str | None:
        """Formula source under a cursor, for a later find.

        The image is one private-use character, so a plain document search
        cannot see the formula. The alt text is the source.
        """
        document = self.document()
        if pos < 0 or pos >= document.characterCount():
            return None
        cursor = QTextCursor(document)
        cursor.setPosition(pos)
        moved = cursor.movePosition(
            QTextCursor.MoveOperation.NextCharacter,
            QTextCursor.MoveMode.KeepAnchor,
        )
        if not moved:
            return None
        fmt = cursor.charFormat()
        if not fmt.isImageFormat():
            return None
        name = fmt.toImageFormat().name()
        if not name.startswith(f"{MATH_SCHEME}:"):
            return None
        alt = fmt.stringProperty(QTextFormat.Property.ImageAltText)
        return alt or fmt.toolTip() or None

    def loadResource(self, typ, name):
        url = name if isinstance(name, QUrl) else QUrl(str(name))
        scheme = (url.scheme() or "").lower()
        if scheme in {MATH_SCHEME, CHART_SCHEME}:
            if int(typ) != _IMAGE:
                return None
            if scheme == MATH_SCHEME:
                self.arm_math()
                image = image_for_url(url.toString())
                # A miss must not paint the broken-image icon. The HTML only
                # names a formula we already accepted, so a later failure is
                # a blank pixel, not a missing file.
                if image is None or image.isNull():
                    return _blank_math_image()
                return image
            return self._chart_image(url)
        return super().loadResource(typ, name)

    def createMimeDataFromSelection(self):
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        if start == end:
            return super().createMimeDataFromSelection()
        parts: list[str] = []
        block = self.document().findBlock(start)
        while block.isValid() and block.position() <= end:
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                frag_start = fragment.position()
                frag_end = frag_start + fragment.length()
                lo = max(frag_start, start)
                hi = min(frag_end, end)
                if lo < hi:
                    parts.append(self._fragment_text(fragment, lo, hi, frag_start))
                iterator += 1
            nxt = block.next()
            if nxt.isValid() and nxt.position() <= end:
                parts.append("\n")
            block = nxt
        mime = QMimeData()
        mime.setText("".join(parts).replace("\u2029", "\n"))
        return mime

    def _fragment_text(self, fragment, lo: int, hi: int, frag_start: int) -> str:
        fmt = fragment.charFormat()
        if not fmt.isImageFormat():
            return fragment.text()[lo - frag_start : hi - frag_start]
        image_fmt = fmt.toImageFormat()
        name = image_fmt.name()
        alt = fmt.stringProperty(QTextFormat.Property.ImageAltText)
        if name.startswith(f"{MATH_SCHEME}:"):
            return latex_for_copy(name, alt, fmt.toolTip())
        return alt or fragment.text()[lo - frag_start : hi - frag_start]

    def _chart_image(self, url: QUrl) -> QImage | None:
        token = (url.path() or "").strip("/").split("/")[-1]
        path = self._charts.get(token)
        if not path:
            return None
        image = QImage(path)
        if image.isNull():
            return None
        return image

    def _math_urls(self) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        block = self.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                fmt = fragment.charFormat()
                if fmt.isImageFormat():
                    name = fmt.toImageFormat().name()
                    if name.startswith(f"{MATH_SCHEME}:") and name not in seen:
                        seen.add(name)
                        found.append(name)
                iterator += 1
            block = block.next()
        return found
