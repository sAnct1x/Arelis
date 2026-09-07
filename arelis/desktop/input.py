"""Win32 SendInput — type, press, hotkey, click, scroll. Pause-aware."""

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
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
WHEEL_DELTA = 120

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


def _key_event(vk: int, *, up: bool = False, unicode_char: str = "") -> Any:
    _ctypes, _wintypes, input_cls, _user32 = _win()
    ev = input_cls()
    ev.type = INPUT_KEYBOARD
    if unicode_char:
        ev.union.ki.wVk = 0
        ev.union.ki.wScan = ord(unicode_char)
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
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    if sw <= 0 or sh <= 0:
        return 0, 0
    ax = int(x * 65535 / max(sw - 1, 1))
    ay = int(y * 65535 / max(sh - 1, 1))
    return ax, ay


async def type_text(text: str) -> None:
    await cooperative_wait(0.05)
    events = []
    for ch in text:
        if ch == "\n":
            events.append(_key_event(0x0D, up=False))
            events.append(_key_event(0x0D, up=True))
            continue
        if ch == "\t":
            events.append(_key_event(0x09, up=False))
            events.append(_key_event(0x09, up=True))
            continue
        events.append(_key_event(0, unicode_char=ch))
        events.append(_key_event(0, up=True, unicode_char=ch))
    if events:
        _send(events)


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
    move.union.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
    down = input_cls()
    down.type = INPUT_MOUSE
    down.union.mi.dwFlags = MOUSEEVENTF_LEFTDOWN
    up = input_cls()
    up.type = INPUT_MOUSE
    up.union.mi.dwFlags = MOUSEEVENTF_LEFTUP
    _send([move, down, up])


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
