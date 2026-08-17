"""Compact readiness chips under the glass title bar.

Only Ollama stays on the strip. Model pin, Allow gates, and the rest live
under Systems ▾ so the strip does not compete with the composer role picker
(UI polish).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QWidget,
    QWidgetAction,
)

from arelis.presence.readiness import ChipLevel, ReadinessChip, ReadinessSnapshot

# Always on the strip.
_PRIMARY_KEYS = ("ollama",)
# Nested under Systems ▾ (aggregate status on the Systems chip).
_SYSTEMS_KEYS = (
    "models",
    "role",  # hot/pinned model — not the composer reply-role picker
    "confirm",  # Allow-gate config — not a second confirm UI
    "calendar",
    "sms",
    "mail",
    "embed",
    "search",
    "ocr",
    "image",
)


def _rank(status: str) -> int:
    # Attention-first: warn beats off beats ok for the Systems summary.
    return {"ok": 0, "off": 1, "warn": 2, "wait": 3, "wait_dim": 3}.get(status, 0)


def _aggregate(statuses: list[str]) -> str:
    if not statuses:
        return ChipLevel.OFF.value
    return max(statuses, key=_rank)


class ReadinessStrip(QWidget):
    """Thin row: Ollama chip + Systems menu."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ReadinessStrip")
        self.setFixedHeight(26)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 2, 12, 2)
        layout.setSpacing(6)

        self._chips: dict[str, QLabel] = {}
        self._systems_details: dict[str, ReadinessChip] = {}
        self._confirm_waiting = False
        self._systems_base_status = ChipLevel.OFF.value
        self._pulse_on = False
        self._pulse = QTimer(self)
        self._pulse.setInterval(700)
        self._pulse.timeout.connect(self._tick_confirm_pulse)

        chip = QLabel("Ollama")
        chip.setObjectName("ReadinessChip")
        chip.setProperty("status", ChipLevel.OFF.value)
        chip.setCursor(Qt.CursorShape.WhatsThisCursor)
        chip.setToolTip("Checking…")
        layout.addWidget(chip)
        self._chips["ollama"] = chip

        self.systems_btn = QToolButton()
        self.systems_btn.setObjectName("ReadinessSystems")
        self.systems_btn.setText("Systems ▾")
        self.systems_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.systems_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.systems_btn.setToolTip("Models, allow gates, calendar, SMS, mail…")
        self.systems_btn.setProperty("status", ChipLevel.OFF.value)
        self._systems_menu = QMenu(self.systems_btn)
        self._systems_menu.setObjectName("ReadinessSystemsMenu")
        self.systems_btn.setMenu(self._systems_menu)
        layout.addWidget(self.systems_btn)

        layout.addStretch(1)

        self.notify_chip = QToolButton()
        self.notify_chip.setObjectName("ReadinessNotifyChip")
        self.notify_chip.setProperty("status", "warn")
        self.notify_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.notify_chip.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.notify_chip.setAutoRaise(True)
        self.notify_chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.notify_chip.hide()
        layout.addWidget(self.notify_chip)

    def set_notify_chip(self, text: str, visible: bool) -> None:
        """Maximized home for the live notification pill."""
        label = (text or "").strip()
        self.notify_chip.setText(label)
        self.notify_chip.setToolTip(label or "Notifications")
        self.notify_chip.setVisible(bool(visible and label))
        style = self.notify_chip.style()
        self.notify_chip.setProperty("status", "warn")
        style.unpolish(self.notify_chip)
        style.polish(self.notify_chip)
        self.notify_chip.update()

    def set_confirm_waiting(self, waiting: bool) -> None:
        """Pulse Systems while an Allow card is open in chat."""
        self._confirm_waiting = bool(waiting)
        self._refresh_systems_label()
        self._rebuild_systems_menu()
        if self._confirm_waiting:
            if not self._pulse.isActive():
                self._pulse_on = True
                self._pulse.start()
                self._tick_confirm_pulse()
        else:
            self._pulse.stop()
            self._pulse_on = False
            self._set_status(self.systems_btn, self._systems_base_status)

    def apply(self, snapshot: ReadinessSnapshot) -> None:
        """Update Ollama + rebuild the Systems menu."""
        by_key = {item.key: item for item in snapshot.chips}
        self._systems_details = {
            key: by_key[key] for key in _SYSTEMS_KEYS if key in by_key
        }

        for key in _PRIMARY_KEYS:
            widget = self._chips[key]
            item = by_key.get(key)
            if item is None:
                widget.setToolTip("No signal.")
                self._set_status(widget, ChipLevel.OFF.value)
                continue
            widget.setText(item.label.lower())
            widget.setToolTip(item.detail)
            self._set_status(widget, item.status.value)

        sys_statuses = [item.status.value for item in self._systems_details.values()]
        for key in _SYSTEMS_KEYS:
            if key not in self._systems_details:
                sys_statuses.append(ChipLevel.OFF.value)
        if self._confirm_waiting:
            sys_statuses.append("wait")
        agg = _aggregate(sys_statuses)
        self._systems_base_status = agg
        self._refresh_systems_label()
        if not self._confirm_waiting:
            self._set_status(self.systems_btn, agg)
        self._rebuild_systems_menu()

    def _refresh_systems_label(self) -> None:
        warn_n = sum(
            1
            for item in self._systems_details.values()
            if item.status == ChipLevel.WARN
        )
        label = "systems ▾"
        if self._confirm_waiting:
            label = "systems · allow ▾"
        elif warn_n:
            label = f"systems · {warn_n} ▾"
        self.systems_btn.setText(label)
        tip_bits = [
            f"{item.label}: {item.status.value} — {item.detail}"
            for item in self._systems_details.values()
        ]
        if self._confirm_waiting:
            tip_bits.insert(0, "Allow card open — Allow or Skip in the chat")
        self.systems_btn.setToolTip(
            "\n".join(tip_bits) if tip_bits else "No system signals yet."
        )

    def _rebuild_systems_menu(self) -> None:
        self._systems_menu.clear()
        # Every row below is disabled, because this menu reports and does not
        # act — the things it names are changed in Settings, not here. Saying so
        # at the top is cheaper than making eight status lines clickable and
        # then having to decide where each one should go.
        caption = QLabel("status · read only")
        caption.setObjectName("ReadinessSystemsCaption")
        header = QWidgetAction(self._systems_menu)
        header.setDefaultWidget(caption)
        header.setEnabled(False)
        self._systems_menu.addAction(header)
        if self._confirm_waiting:
            allow = QAction("Allow card open — decide in chat", self._systems_menu)
            allow.setEnabled(False)
            self._systems_menu.addAction(allow)
            self._systems_menu.addSeparator()
        for key in _SYSTEMS_KEYS:
            item = self._systems_details.get(key)
            if item is None:
                # Friendly labels when the probe has not reported yet.
                labels = {
                    "role": "Model",
                    "confirm": "Allow gates",
                }
                name = labels.get(key, key)
                text = f"{name}  ·  off  —  No signal."
                tip = "No signal."
            else:
                text = f"{item.label}  ·  {item.status.value}  —  {item.detail}"
                tip = item.detail
            action = QAction(text, self._systems_menu)
            action.setToolTip(tip)
            action.setEnabled(False)
            self._systems_menu.addAction(action)

    def _tick_confirm_pulse(self) -> None:
        if not self._confirm_waiting:
            return
        self._pulse_on = not self._pulse_on
        self._set_status(
            self.systems_btn, "wait" if self._pulse_on else "wait_dim"
        )

    @staticmethod
    def _set_status(widget: QWidget, status: str) -> None:
        widget.setProperty("status", status)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()
