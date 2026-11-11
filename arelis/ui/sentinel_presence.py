"""Inset geometry and Arelis/orbit presence fade for the Sentinels window.

Numbers come from Iris pass 5: window (40, 44) 2110x1306 on a 2560x1392 plate,
Arelis and the orbit tree at 20 percent while it is open, 650 ms in and 500 ms
out, 200 ms when motion is reduced. Chat is hidden and disabled for that same
span, and restored when the window closes.
"""

from __future__ import annotations

from typing import Any

DESIGN_W = 2560
DESIGN_H = 1392
INSET_X = 40
INSET_Y = 44
INSET_W = 2110
INSET_H = 1306
RIGHT_UNCOVERED = DESIGN_W - INSET_X - INSET_W  # 410
FADE_OPEN = 0.20
FADE_CLOSED = 1.0
FADE_OPEN_MS = 650
FADE_CLOSE_MS = 500
REDUCED_MS = 200
MOTE_X = 1250
MOTE_Y = 1090
CLOSE_INSET_X = 46
CLOSE_INSET_Y = 48


def inset_geometry(owner_w: int, owner_h: int) -> tuple[int, int, int, int]:
    """Map the approved inset onto the owner window size."""
    ow = max(1, int(owner_w))
    oh = max(1, int(owner_h))
    x = round(INSET_X * ow / DESIGN_W)
    y = round(INSET_Y * oh / DESIGN_H)
    w = round(INSET_W * ow / DESIGN_W)
    h = round(INSET_H * oh / DESIGN_H)
    return x, y, max(1, w), max(1, h)


def right_uncovered(owner_w: int, geom: tuple[int, int, int, int]) -> int:
    x, _y, w, _h = geom
    return int(owner_w) - x - w


def mote_pos(owner_w: int, owner_h: int) -> tuple[int, int]:
    return (
        round(MOTE_X * max(1, int(owner_w)) / DESIGN_W),
        round(MOTE_Y * max(1, int(owner_h)) / DESIGN_H),
    )


def fade_duration_ms(*, opening: bool, reduced: bool) -> int:
    if reduced:
        return REDUCED_MS
    return FADE_OPEN_MS if opening else FADE_CLOSE_MS



def _chat_suspend_targets(owner: Any) -> list[Any]:
    """Composer, transcript, and the Filament chat tile, if those widgets exist."""
    widgets: list[Any] = []
    conv = getattr(owner, "conversation", None)
    if conv is not None:
        widgets.append(conv)
        chat = getattr(conv, "chat", None)
        if chat is not None:
            widgets.append(chat)
            view = getattr(chat, "view", None)
            if view is not None:
                widgets.append(view)
        composer = getattr(conv, "_composer", None)
        if composer is not None:
            widgets.append(composer)
        for name in ("input", "send_btn"):
            widget = getattr(conv, name, None)
            if widget is not None:
                widgets.append(widget)
    tile = getattr(owner, "_filament_chat_tile", None)
    if tile is not None:
        widgets.append(tile)
    seen: set[int] = set()
    unique: list[Any] = []
    for widget in widgets:
        ident = id(widget)
        if ident not in seen:
            seen.add(ident)
            unique.append(widget)
    return unique


def suspend_chat_for_overseer(owner: Any) -> None:
    """Hide and disable the main-window chat, and park per-token painting."""
    if owner is None or getattr(owner, "_overseer_chat_suspend", None) is not None:
        return
    conv = getattr(owner, "conversation", None)
    chat = getattr(conv, "chat", None) if conv is not None else None
    targets = _chat_suspend_targets(owner)
    snapshot = [(w, w.isHidden(), w.isEnabled()) for w in targets]
    parked = bool(getattr(chat, "_view_parked", False)) if chat is not None else False
    owner._overseer_chat_suspend = {"widgets": snapshot, "view_parked": parked}
    if chat is not None:
        chat.set_view_parked(True)
    for widget in targets:
        clearer = getattr(widget, "clearFocus", None)
        if callable(clearer):
            clearer()
        widget.setEnabled(False)
        widget.hide()


def restore_chat_after_overseer(owner: Any) -> None:
    """Put the chat back exactly as it was before the Overseer opened."""
    if owner is None:
        return
    snap = getattr(owner, "_overseer_chat_suspend", None)
    if not snap:
        return
    owner._overseer_chat_suspend = None
    conv = getattr(owner, "conversation", None)
    chat = getattr(conv, "chat", None) if conv is not None else None
    if chat is not None:
        chat.set_view_parked(bool(snap.get("view_parked")))
    from shiboken6 import isValid

    for widget, hidden, enabled in snap.get("widgets") or []:
        if widget is None or not isValid(widget):
            continue
        widget.setEnabled(enabled)
        widget.setVisible(not hidden)


class PresenceController:
    """Holds the live presence opacity. Restore on close, quit, or error."""

    def __init__(self) -> None:
        self.opacity = FADE_CLOSED
        self.open = False
        self.last_reason = "init"
        self.tick_scale = 1.0

    def open_window(self, *, reduced: bool = False) -> int:
        self.open = True
        self.opacity = FADE_OPEN
        self.tick_scale = 0.25
        self.last_reason = "open"
        return fade_duration_ms(opening=True, reduced=reduced)

    def restore(self, reason: str = "close", *, reduced: bool = False) -> int:
        self.open = False
        self.opacity = FADE_CLOSED
        self.tick_scale = 1.0
        self.last_reason = reason
        return fade_duration_ms(opening=False, reduced=reduced)

    def apply_to(self, surface: Any) -> None:
        """Write presenceOpacity onto a QuickSurface root, if present."""
        root = surface
        getter = getattr(surface, "rootObject", None)
        if callable(getter):
            root = getter() or surface
        setter = getattr(root, "setProperty", None)
        if callable(setter):
            setter("presenceOpacity", float(self.opacity))
            setter("presenceTick", float(self.tick_scale))
            return
        if hasattr(root, "presenceOpacity"):
            root.presenceOpacity = float(self.opacity)
        if hasattr(root, "presenceTick"):
            root.presenceTick = float(self.tick_scale)
