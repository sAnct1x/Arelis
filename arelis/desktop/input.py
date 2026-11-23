"""Win32 SendInput, type, press, hotkey, click, scroll. Pause-aware."""

from __future__ import annotations

import sys
from typing import Any

from arelis.browser.hold import cooperative_wait

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
WHEEL_DELTA = 120

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

_VK = {
    "enter": 0x0D,
    "return": 0x0D,
    "escape": 0x1B,
    "esc": 0x1B,
    "tab": 0x09,
    "space": 0x20,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "pageup": 0x21,
    "pagedown": 0x22,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "shift": 0x10,
    "win": 0x5B,
    "cmd": 0x5B,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
}


def _win() -> Any:
    if sys.platform != "win32":
        raise RuntimeError("Desktop input is Windows-only.")
    import ctypes
    from ctypes import Structure, Union, c_ulonglong, sizeof, wintypes

    ulong_ptr = c_ulonglong if sizeof(ctypes.c_void_p) == 8 else wintypes.DWORD

    class MouseInput(Structure):
        _fields_ = (
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ulong_ptr),
        )

    class KeyBdInput(Structure):
        _fields_ = (
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ulong_ptr),
        )

    class InputUnion(Union):
        _fields_ = (("mi", MouseInput), ("ki", KeyBdInput))

    class InputStruct(Structure):
        _fields_ = (("type", wintypes.DWORD), ("union", InputUnion))

    return ctypes, wintypes, InputStruct, ctypes.windll.user32


def _send(inputs: list[Any]) -> None:
    ctypes, _wintypes, input_cls, user32 = _win()
    arr = (input_cls * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(input_cls))
    if sent != len(inputs):
        raise OSError("SendInput did not deliver every event.")


def _utf16_units(ch: str) -> tuple[int, ...]:
    """Return 16-bit UTF-16LE code units for a character (surrogate pairs for >U+FFFF)."""
    raw = ch.encode("utf-16-le")
    return tuple(int.from_bytes(raw[i : i + 2], "little") for i in range(0, len(raw), 2))


def _key_event(
    vk: int,
    *,
    up: bool = False,
    unicode_char: str = "",
    scan_unit: int | None = None,
) -> Any:
    _ctypes, _wintypes, input_cls, _user32 = _win()
    ev = input_cls()
    ev.type = INPUT_KEYBOARD
    if scan_unit is not None:
        ev.union.ki.wVk = 0
        ev.union.ki.wScan = int(scan_unit) & 0xFFFF
        flags = KEYEVENTF_UNICODE
    elif unicode_char:
        ev.union.ki.wVk = 0
        ev.union.ki.wScan = _utf16_units(unicode_char)[0]
        flags = KEYEVENTF_UNICODE
    else:
        ev.union.ki.wVk = vk
        ev.union.ki.wScan = 0
        flags = 0
        if vk in {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2E}:
            flags |= KEYEVENTF_EXTENDEDKEY
    if up:
        flags |= KEYEVENTF_KEYUP
    ev.union.ki.dwFlags = flags
    ev.union.ki.time = 0
    ev.union.ki.dwExtraInfo = 0
    return ev


def cursor_pos() -> tuple[int, int]:
    ctypes, wintypes, _input_cls, user32 = _win()
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def mouse_moved_since(origin: tuple[int, int], *, slack: int = 16) -> bool:
    x, y = cursor_pos()
    return abs(x - origin[0]) + abs(y - origin[1]) > slack


def _abs_coords(x: float, y: float) -> tuple[int, int]:
    _ctypes, _wintypes, _input_cls, user32 = _win()
    vx = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
    vy = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
    vw = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    vh = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    if vw <= 0 or vh <= 0:
        vx, vy = 0, 0
        vw = int(user32.GetSystemMetrics(0))
        vh = int(user32.GetSystemMetrics(1))
    if vw <= 0 or vh <= 0:
        return 0, 0
    ax = round((float(x) - vx) * 65535 / max(vw - 1, 1))
    ay = round((float(y) - vy) * 65535 / max(vh - 1, 1))
    return max(0, min(65535, ax)), max(0, min(65535, ay))


_TYPE_CHUNK_CHARS = 32


async def type_text(text: str) -> None:
    await cooperative_wait(0.05)
    if not text:
        return
    for start in range(0, len(text), _TYPE_CHUNK_CHARS):
        chunk = text[start : start + _TYPE_CHUNK_CHARS]
        events = []
        for ch in chunk:
            if ch == "\r":
                continue
            if ch == "\n":
                events.append(_key_event(0x0D, up=False))
                events.append(_key_event(0x0D, up=True))
                continue
            if ch == "\t":
                events.append(_key_event(0x09, up=False))
                events.append(_key_event(0x09, up=True))
                continue
            units = _utf16_units(ch)
            for unit in units:
                events.append(_key_event(0, up=False, scan_unit=unit))
            for unit in units:
                events.append(_key_event(0, up=True, scan_unit=unit))
        if events:
            _send(events)
        if start + _TYPE_CHUNK_CHARS < len(text):
            await cooperative_wait(0.01)


def parse_key(name: str) -> int | None:
    raw = (name or "").strip().lower()
    if not raw:
        return None
    if raw in _VK:
        return _VK[raw]
    if len(raw) == 1:
        ch = raw.upper()
        if "A" <= ch <= "Z":
            return ord(ch)
        if "0" <= ch <= "9":
            return ord(ch)
    return None


async def press_key(name: str) -> str | None:
    vk = parse_key(name)
    if vk is None:
        return f"Unknown key {name!r}."
    await cooperative_wait(0.05)
    _send([_key_event(vk, up=False), _key_event(vk, up=True)])
    return None


async def press_hotkey(combo: str) -> str | None:
    parts = [p.strip().lower() for p in (combo or "").replace("-", "+").split("+") if p.strip()]
    if not parts:
        return "Need a hotkey (e.g. ctrl+s)."
    vks: list[int] = []
    for part in parts:
        vk = parse_key(part)
        if vk is None:
            return f"Unknown key {part!r}."
        vks.append(vk)
    await cooperative_wait(0.05)
    events = [_key_event(vk, up=False) for vk in vks]
    events.extend(_key_event(vk, up=True) for vk in reversed(vks))
    _send(events)
    return None


async def click_xy(x: float, y: float) -> None:
    await cooperative_wait(0.08)
    ax, ay = _abs_coords(x, y)
    _ctypes, _wintypes, input_cls, _user32 = _win()
    move = input_cls()
    move.type = INPUT_MOUSE
    move.union.mi.dx = ax
    move.union.mi.dy = ay
    move.union.mi.dwFlags = (
        MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    )
    down = input_cls()
    down.type = INPUT_MOUSE
    down.union.mi.dwFlags = MOUSEEVENTF_LEFTDOWN
    up = input_cls()
    up.type = INPUT_MOUSE
    up.union.mi.dwFlags = MOUSEEVENTF_LEFTUP
    _send([move, down, up])


async def dblclick_xy(x: float, y: float) -> None:
    await click_xy(x, y)
    await cooperative_wait(0.04)
    _ctypes, _wintypes, input_cls, _user32 = _win()
    down = input_cls()
    down.type = INPUT_MOUSE
    down.union.mi.dwFlags = MOUSEEVENTF_LEFTDOWN
    up = input_cls()
    up.type = INPUT_MOUSE
    up.union.mi.dwFlags = MOUSEEVENTF_LEFTUP
    _send([down, up])


async def right_click_xy(x: float, y: float) -> None:
    await cooperative_wait(0.08)
    ax, ay = _abs_coords(x, y)
    _ctypes, _wintypes, input_cls, _user32 = _win()
    move = input_cls()
    move.type = INPUT_MOUSE
    move.union.mi.dx = ax
    move.union.mi.dy = ay
    move.union.mi.dwFlags = (
        MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    )
    down = input_cls()
    down.type = INPUT_MOUSE
    down.union.mi.dwFlags = MOUSEEVENTF_RIGHTDOWN
    up = input_cls()
    up.type = INPUT_MOUSE
    up.union.mi.dwFlags = MOUSEEVENTF_RIGHTUP
    _send([move, down, up])


async def hover_xy(x: float, y: float) -> None:
    await cooperative_wait(0.05)
    ax, ay = _abs_coords(x, y)
    _ctypes, _wintypes, input_cls, _user32 = _win()
    move = input_cls()
    move.type = INPUT_MOUSE
    move.union.mi.dx = ax
    move.union.mi.dy = ay
    move.union.mi.dwFlags = (
        MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    )
    _send([move])


async def drag_xy(x1: float, y1: float, x2: float, y2: float) -> None:
    await cooperative_wait(0.08)
    ax1, ay1 = _abs_coords(x1, y1)
    ax2, ay2 = _abs_coords(x2, y2)
    _ctypes, _wintypes, input_cls, _user32 = _win()
    move1 = input_cls()
    move1.type = INPUT_MOUSE
    move1.union.mi.dx = ax1
    move1.union.mi.dy = ay1
    move1.union.mi.dwFlags = (
        MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    )
    down = input_cls()
    down.type = INPUT_MOUSE
    down.union.mi.dwFlags = MOUSEEVENTF_LEFTDOWN
    _send([move1, down])
    await cooperative_wait(0.04)
    mid_x = (ax1 + ax2) // 2
    mid_y = (ay1 + ay2) // 2
    move_mid = input_cls()
    move_mid.type = INPUT_MOUSE
    move_mid.union.mi.dx = mid_x
    move_mid.union.mi.dy = mid_y
    move_mid.union.mi.dwFlags = (
        MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    )
    move2 = input_cls()
    move2.type = INPUT_MOUSE
    move2.union.mi.dx = ax2
    move2.union.mi.dy = ay2
    move2.union.mi.dwFlags = (
        MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    )
    up = input_cls()
    up.type = INPUT_MOUSE
    up.union.mi.dwFlags = MOUSEEVENTF_LEFTUP
    _send([move_mid, move2, up])


async def scroll(direction: str, *, amount: int = 3) -> None:
    await cooperative_wait(0.05)
    delta = WHEEL_DELTA * max(1, min(abs(int(amount or 3)), 12))
    wheel = delta if (direction or "").strip().lower() in {"up", "left"} else -delta
    _ctypes, _wintypes, input_cls, _user32 = _win()
    ev = input_cls()
    ev.type = INPUT_MOUSE
    ev.union.mi.mouseData = wheel & 0xFFFFFFFF
    ev.union.mi.dwFlags = MOUSEEVENTF_WHEEL
    _send([ev])
