"""UI Automation snapshot of the focused window, refs like the browser DOM."""

from __future__ import annotations

import sys
from dataclasses import dataclass

SNAPSHOT_LIMIT = 40

_CONTROL_NAMES = {
    50000: "button",
    50002: "checkbox",
    50003: "combo",
    50004: "edit",
    50005: "link",
    50006: "list",
    50007: "listitem",
    50008: "menu",
    50011: "menuitem",
    50013: "radiobutton",
    50015: "slider",
    50016: "spinner",
    50018: "tab",
    50019: "tabitem",
    50020: "text",
    50023: "tree",
    50024: "treeitem",
    50025: "custom",
    50029: "headeritem",
    50030: "document",
    50031: "splitbutton",
    50033: "pane",
}


UIA_VALUE_VALUE_PROPERTY_ID = 30045
UIA_TOGGLE_STATE_PROPERTY_ID = 30086


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
    value: str = ""
    state: str = ""

    def line(self) -> str:
        bits = [f"[{self.ref}]", self.role, f"{self.name!r}"]
        if self.state:
            bits.append(f"state={self.state}")
        if self.value and not self.is_password and self.value != self.name:
            short = " ".join(self.value.split())[:80]
            if short:
                bits.append(f"value={short!r}")
        return " ".join(bits)


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


def _foreground_root(uia: object) -> object | None:
    """Bind UI Automation to the foreground top-level HWND, not a leaf control."""
    try:
        import ctypes

        hwnd = int(ctypes.windll.user32.GetForegroundWindow() or 0)
        if hwnd:
            root = uia.ElementFromHandle(hwnd)  # type: ignore[attr-defined]
            if root is not None:
                return root
    except Exception:
        # HWND lookup or ElementFromHandle failed; fall back to focused/root element.
        pass
    try:
        return uia.GetFocusedElement() or uia.GetRootElement()  # type: ignore[attr-defined]
    except Exception:
        # COM UIA root unavailable.
        return None


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
    root = _foreground_root(uia)
    if root is None:
        return []
    found = root.FindAll(TreeScope_Descendants, uia.CreateTrueCondition())  # type: ignore[attr-defined]
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
        val = ""
        if not secret:
            try:
                raw_val = el.GetCurrentPropertyValue(UIA_VALUE_VALUE_PROPERTY_ID)
                if isinstance(raw_val, str) and raw_val.strip():
                    val = raw_val.strip()[:600]
            except Exception:
                # Control does not support ValuePattern.
                val = ""
        state = ""
        if ctype in {50002, 50013}:
            try:
                tstate = el.GetCurrentPropertyValue(UIA_TOGGLE_STATE_PROPERTY_ID)
                if tstate == 1:
                    state = "checked"
                elif tstate == 0:
                    state = "unchecked"
            except Exception:
                # Control does not support TogglePattern.
                state = ""
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
                value=val,
                state=state,
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
            "Named-control snapshot is unavailable. Call screenshot of the monitor instead.",
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
    lines = [r.line() for r in rows]
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
    lines: list[str] = []
    for r in list(refs.values())[:80]:
        if r.value and not r.is_password and r.value != r.name:
            lines.append(f"{r.name}: {r.value[:240]}")
        elif r.name:
            lines.append(r.name)
    return "\n".join(lines) or "(empty)"


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
        exact = [r for r in refs.values() if r.name.lower() == needle]
        prefix = [
            r
            for r in refs.values()
            if r.name.lower().startswith(needle) and r not in exact
        ]
        contain = [
            r
            for r in refs.values()
            if needle in r.name.lower() and r not in exact and r not in prefix
        ]
        hits = exact or prefix or contain
        if nth > 0 and len(hits) >= nth:
            return hits[nth - 1]
        return hits[0] if hits else None
    if nth > 0:
        ordered = list(refs.values())
        if nth <= len(ordered):
            return ordered[nth - 1]
    return None
