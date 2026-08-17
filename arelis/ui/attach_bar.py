"""Composer attachment chips and drop-target overlay."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from arelis.ui.theme import METRICS


class AttachmentChip(QWidget):
    """One removable filename chip above the composer."""

    remove_requested = Signal(str)

    def __init__(self, attachment: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AttachmentChip")
        self.attachment_id = str(attachment.get("id") or "")
        name = str(attachment.get("name") or "file")
        kind = str(attachment.get("kind") or "other")
        path = str(attachment.get("path") or "")
        source = str(attachment.get("source_path") or "")
        tip = path if not source else f"{path}\nfrom {source}"

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 2, 4, 2)
        row.setSpacing(4)
        label = QLabel(f"{_kind_mark(kind)} {name}")
        label.setObjectName("AttachmentChipName")
        label.setToolTip(tip)
        btn = QToolButton()
        btn.setObjectName("AttachmentChipRemove")
        btn.setText("\u00d7")
        btn.setAutoRaise(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("Remove attachment")
        btn.clicked.connect(lambda: self.remove_requested.emit(self.attachment_id))
        row.addWidget(label)
        row.addWidget(btn)


class AttachBar(QWidget):
    """Horizontal chip strip; hidden when empty."""

    remove_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: dict[str, dict[str, Any]] = {}
        self.setVisible(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setObjectName("AttachBarScroll")
        scroll.setFixedHeight(METRICS["control"])

        self._inner = QWidget()
        self._row = QHBoxLayout(self._inner)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(6)
        self._row.addStretch(1)
        scroll.setWidget(self._inner)
        outer.addWidget(scroll)

    def attachments(self) -> list[dict[str, Any]]:
        return list(self._items.values())

    def count(self) -> int:
        return len(self._items)

    def add_many(self, items: list[dict[str, Any]]) -> None:
        for item in items:
            aid = str(item.get("id") or "")
            if not aid or aid in self._items:
                continue
            self._items[aid] = dict(item)
            chip = AttachmentChip(item, self._inner)
            chip.remove_requested.connect(self.remove)
            # Insert before the trailing stretch.
            self._row.insertWidget(self._row.count() - 1, chip)
        self.setVisible(bool(self._items))

    def remove(self, attachment_id: str) -> None:
        aid = str(attachment_id or "")
        self._items.pop(aid, None)
        for i in range(self._row.count() - 1, -1, -1):
            w = self._row.itemAt(i).widget()
            if isinstance(w, AttachmentChip) and w.attachment_id == aid:
                self._row.removeWidget(w)
                w.deleteLater()
                break
        self.setVisible(bool(self._items))
        self.remove_requested.emit(aid)

    def clear(self) -> None:
        for i in range(self._row.count() - 1, -1, -1):
            w = self._row.itemAt(i).widget()
            if isinstance(w, AttachmentChip):
                self._row.removeWidget(w)
                w.deleteLater()
        self._items.clear()
        self.setVisible(False)


class DropOverlay(QWidget):
    """Full-panel hint while dragging files over the conversation stage."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DropOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        label = QLabel("Drop files for Arelis")
        label.setObjectName("DropOverlayTitle")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        hint = QLabel("They will attach to your next message")
        hint.setObjectName("DropOverlayHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        layout.addStretch(1)
        self.hide()


def _kind_mark(kind: str) -> str:
    return {
        "text": "T",
        "data": "#",
        "pdf": "P",
        "image": "I",
        "other": "·",
    }.get(kind, "·")
