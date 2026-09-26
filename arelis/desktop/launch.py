"""Resolve an app name and start or focus it. Never a shell for the model."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from arelis.desktop.aliases import resolve_app
from arelis.desktop.sanctuary import refuse_launch_target, refuse_resolved_exe
from arelis.desktop.windows import focus_window, match_window


def _app_paths_exe(launch_key: str) -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    leaf = launch_key if launch_key.lower().endswith(".exe") else f"{launch_key}.exe"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(
                hive,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\\" + leaf,
            )
        except OSError:
            continue
        try:
            value, _ = winreg.QueryValueEx(key, "")
        except OSError:
            value = None
        finally:
            winreg.CloseKey(key)
        if value:
            path = Path(str(value)).expanduser()
            if path.is_file():
                return str(path)
    return None


def _shortcut_target(lnk: Path) -> str:
    if sys.platform != "win32":
        return ""
    try:
        return _shortcut_target_com(lnk)
    except Exception:
        return str(lnk)


def _shortcut_target_com(lnk: Path) -> str:
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return ""

    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    clsid = _guid("00021401-0000-0000-C000-000000000046")
    iid_link = _guid("000214F9-0000-0000-C000-000000000046")
    iid_file = _guid("0000010b-0000-0000-C000-000000000046")
    unk = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(
        ctypes.byref(clsid),
        None,
        1,  # CLSCTX_INPROC_SERVER
        ctypes.byref(iid_link),
        ctypes.byref(unk),
    )
    if hr != 0 or not unk.value:
        return ""
    # IPersistFile.Load then IShellLinkW.GetPath via vtable would be long;
    # os.startfile on a matched .lnk is enough after the basename deny check.
    # We still try GetPath through a tiny IPersistFile QueryInterface.
    persist = ctypes.c_void_p()
    # unk is IShellLinkW*; QueryInterface is slot 0 of IUnknown
    vtbl = ctypes.cast(unk, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    query = ctypes.WINFUNCTYPE(
        ctypes.HRESULT,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    )(vtbl[0])
    hr = query(unk, ctypes.byref(iid_file), ctypes.byref(persist))
    if hr != 0 or not persist.value:
        return str(lnk)
    pv = ctypes.cast(persist, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    load = ctypes.WINFUNCTYPE(
        ctypes.HRESULT,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        wintypes.DWORD,
    )(pv[5])
    load(persist, str(lnk), 0)
    get_path = ctypes.WINFUNCTYPE(
        ctypes.HRESULT,
        ctypes.c_void_p,
        wintypes.LPWSTR,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )(vtbl[3])
    buf = ctypes.create_unicode_buffer(260)
    get_path(unk, buf, 260, None, 0)
    return (buf.value or "").strip() or str(lnk)


def _guid(text: str) -> object:
    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    u = uuid.UUID(text)
    g = GUID()
    g.Data1 = u.time_low
    g.Data2 = u.time_mid
    g.Data3 = u.time_hi_version
    for i, b in enumerate(u.bytes[8:]):
        g.Data4[i] = b
    return g


def _start_menu_dirs() -> list[Path]:
    home = Path.home()
    program = Path(os.environ.get("ProgramData") or r"C:\ProgramData")
    return [
        home / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        program / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]


def _find_start_menu_lnk(name: str) -> Path | None:
    needle = (name or "").strip().lower()
    if not needle:
        return None
    compact = needle.replace(" ", "")
    hits: list[Path] = []
    for root in _start_menu_dirs():
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("*.lnk"):
                stem = path.stem.lower()
                if stem == needle or stem.replace(" ", "") == compact:
                    hits.append(path)
                elif needle in stem:
                    hits.append(path)
        except OSError:
            continue
    return hits[0] if hits else None


def _shell_open(verb_target: str) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Desktop launch is Windows-only.")
    import ctypes

    hwnd = ctypes.windll.shell32.ShellExecuteW(
        None, "open", verb_target, None, None, 1
    )
    if int(hwnd) <= 32:
        raise OSError(f"ShellExecute failed ({hwnd}) for {verb_target!r}")


def open_app(
    target: str,
    *,
    aliases: dict[str, str] | None = None,
) -> tuple[str | None, str | None]:
    """Start or focus. Returns (receipt, error)."""
    if sys.platform != "win32":
        return None, "Desktop drive is Windows-only in this slice."
    blocked = refuse_launch_target(target)
    if blocked:
        return None, blocked
    existing = match_window(target)
    if existing is not None:
        focus_window(existing.hwnd)
        return f"Focused {existing.title}.", None
    key, err = resolve_app(target, aliases=aliases)
    if err or not key:
        return None, err or "Need an app name."
    blocked = refuse_launch_target(key)
    if blocked:
        return None, blocked
    existing = match_window(key)
    if existing is not None:
        focus_window(existing.hwnd)
        return f"Focused {existing.title}.", None

    exe = _app_paths_exe(key)
    if exe:
        blocked = refuse_resolved_exe(exe, alias=key)
        if blocked:
            return None, blocked
        _shell_open(exe)
        return f"Opened {key}.", None

    lnk = _find_start_menu_lnk(target) or _find_start_menu_lnk(key)
    if lnk is not None:
        dest = _shortcut_target(lnk)
        blocked = refuse_resolved_exe(dest or lnk.name, alias=key)
        if blocked:
            return None, blocked
        _shell_open(str(lnk))
        return f"Opened {lnk.stem}.", None

    # Inbox names (notepad, calc) are on the App Paths / PATH story.
    blocked = refuse_resolved_exe(f"{key}.exe", alias=key)
    if blocked:
        return None, blocked
    _shell_open(key)
    return f"Opened {key}.", None
