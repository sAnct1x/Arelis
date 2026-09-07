"""Your-turn walls on the desk: pay, delete, password, hands, UAC."""

from __future__ import annotations

from dataclasses import dataclass

from arelis.browser.walls import pay_cta_label
from arelis.desktop.sanctuary import (
    destructive_label,
    elevation_label,
    is_uac_title,
)

YOUR_TURN = "YOUR_TURN"

_MESSAGES = {
    "pay": "Your turn — you click Book / Pay / Order. I stop on this screen.",
    "delete": "Your turn — I do not delete, format, or uninstall without you.",
    "password": (
        "Your turn — I do not type passwords. Hit Go when you are in."
    ),
    "hands": "Your turn — you have the mouse. I will not click over you.",
    "uac": "Your turn — I never click Yes on User Account Control.",
    "stuck": "Your turn — I cannot find the next control. The window stays.",
}


@dataclass(frozen=True)
class Wall:
    kind: str
    reason: str
    message: str


def wall_message(kind: str) -> str:
    return _MESSAGES.get(kind, _MESSAGES["stuck"])


def label_wall(label: str, *, window_title: str = "") -> Wall | None:
    """Refuse or pause on a click/type/press label."""
    text = (label or "").strip()
    if is_uac_title(window_title) or elevation_label(text):
        return Wall("uac", "elevation", wall_message("uac"))
    if pay_cta_label(text) is not None:
        return Wall("pay", "pay", wall_message("pay"))
    if destructive_label(text):
        return Wall("delete", "delete", wall_message("delete"))
    return None
