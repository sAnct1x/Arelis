"""UI Automation snapshot of the focused window — refs like the browser DOM."""

from __future__ import annotations

import sys
from dataclasses import dataclass

SNAPSHOT_LIMIT = 40

_CONTROL_NAMES = {
    50000: "button",
    50004: "edit",
    50005: "link",
    50006: "list",
    50007: "listitem",
    50008: "menu",
    50011: "menuitem",
    50013: "tabitem",
    50018: "text",
    50020: "treeitem",
    50025: "combo",
    50029: "headeritem",
    50033: "hyperlink",
}


@dataclass
class DeskRef:
    ref: str
    name: str
    role: str
    x: float
    y: float
    w: float
    h: float
    is_password: bool = False


def uia_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import comtypes.client  # noqa: F401
    except ImportError:
        return False
    return True


def _uia_client() -> object:
    import comtypes.client

    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen.UIAutomationClient import IUIAutomation

    return comtypes.client.CreateObject(
        "{ff48dba4-60ef-4201-aa87-54103eef594e}",
        interface=IUIAutomation,
    )


def _walk_uia(limit: int = SNAPSHOT_LIMIT) -> list[DeskRef]:
    from comtypes.gen.UIAutomationClient import (
        TreeScope_Descendants,
        UIA_AutomationIdPropertyId,
        UIA_BoundingRectanglePropertyId,
        UIA_ControlTypePropertyId,
        UIA_IsOffscreenPropertyId,
        UIA_IsPasswordPropertyId,
        UIA_NamePropertyId,
    )

    uia = _uia_client()
    root = uia.GetFocusedElement() or uia.GetRootElement()
    if root is None:
        return []
    found = root.FindAll(TreeScope_Descendants, uia.CreateTrueCondition())
    count = int(found.Length) if found is not None else 0
    rows: list[DeskRef] = []
    for i in range(min(count, 240)):
        el = found.GetElement(i)
        try:
            if bool(el.GetCurrentPropertyValue(UIA_IsOffscreenPropertyId)):
                continue
        except Exception:
            pass
        try:
            name = str(el.GetCurrentPropertyValue(UIA_NamePropertyId) or "").strip()
        except Exception:
            name = ""
        try:
            auto_id = str(
                el.GetCurrentPropertyValue(UIA_AutomationIdPropertyId) or ""
            ).strip()
        except Exception:
            auto_id = ""
        label = name or auto_id
        if not label:
            continue
        try:
            ctype = int(el.GetCurrentPropertyValue(UIA_ControlTypePropertyId) or 0)
        except Exception:
            ctype = 0
        try:
            rect = el.GetCurrentPropertyValue(UIA_BoundingRectanglePropertyId)
            left, top, width, height = (float(v) for v in rect)
        except Exception:
            continue
        if width <= 0 or height <= 0:
            continue
        try:
            secret = bool(el.GetCurrentPropertyValue(UIA_IsPasswordPropertyId))
        except Exception:
            secret = False
        rows.append(
            DeskRef(
                ref=f"d{len(rows) + 1}",
                name=label[:80],
                role=_CONTROL_NAMES.get(ctype, "control"),
                x=left + width / 2,
                y=top + height / 2,
                w=width,
                h=height,
                is_password=secret,
            )
        )
        if len(rows) >= limit:
            break
    return rows


def snapshot_window() -> tuple[str, dict[str, DeskRef], str | None]:
    """Return (text, refs, error)."""
    if sys.platform != "win32":
        return "", {}, "Desktop snapshot is Windows-only in this slice."
    if not uia_available():
        return (
            "",
            {},
            "UI Automation needs the desktop extra (pip install -e \".[desktop]\").",
        )
    try:
        rows = _walk_uia()
    except Exception as exc:
        return "", {}, f"UI Automation failed: {exc}"
    if not rows:
        return (
            "No named controls in the focused window. "
            "Call screenshot then vision, then click with x,y this turn.",
            {},
            None,
        )
    lines = [f"[{r.ref}] {r.role} {r.name!r}" for r in rows]
    refs = {r.ref: r for r in rows}
    return "\n".join(lines), refs, None


def read_window(refs: dict[str, DeskRef]) -> str:
    if not refs:
        text, new_refs, err = snapshot_window()
        if err:
            return err
        refs = new_refs
        if text.startswith("No named"):
            return text
    names = [r.name for r in refs.values() if r.name]
    return "\n".join(names[:80]) or "(empty)"


def find_ref(
    refs: dict[str, DeskRef],
    *,
    ref: str = "",
    text: str = "",
    nth: int = 0,
) -> DeskRef | None:
    if ref and ref in refs:
        return refs[ref]
    needle = (text or "").strip().lower()
    if needle:
        hits = [r for r in refs.values() if needle in r.name.lower()]
        if nth > 0 and len(hits) >= nth:
            return hits[nth - 1]
        return hits[0] if hits else None
    if nth > 0:
        ordered = list(refs.values())
        if nth <= len(ordered):
            return ordered[nth - 1]
    return None
