"""Hard refuses: shells, OS trees, elevation. Not a confirm — not her job."""

from __future__ import annotations

import os
import re
from pathlib import Path

from arelis.paths import user_data_dir

# Basenames only. notepad.exe lives in System32 — that folder is not the ban.
DENIED_EXES = frozenset(
    {
        "cmd",
        "cmd.exe",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
        "wscript",
        "wscript.exe",
        "cscript",
        "cscript.exe",
        "mshta",
        "mshta.exe",
        "regedit",
        "regedit.exe",
        "reg",
        "reg.exe",
        "gpedit",
        "gpedit.msc",
        "secpol",
        "secpol.msc",
        "lusrmgr",
        "lusrmgr.msc",
        "diskpart",
        "diskpart.exe",
        "format",
        "format.com",
        "bcdedit",
        "bcdedit.exe",
        "netsh",
        "netsh.exe",
        "sc",
        "sc.exe",
        "taskmgr",
        "taskmgr.exe",
        "mmc",
        "mmc.exe",
    }
)

# Inbox aliases may resolve to these even though they sit under System32.
INBOX_LAUNCH = frozenset(
    {
        "notepad",
        "notepad.exe",
        "calc",
        "calc.exe",
        "calculator",
        "explorer",
        "explorer.exe",
        "mspaint",
        "mspaint.exe",
        "snippingtool",
        "snippingtool.exe",
    }
)

_RAW_PATH = re.compile(r"^[A-Za-z]:[\\/]|^\\\\|[/\\].+\.(?:exe|msc|bat|cmd|ps1)$")
_DELETE_LABEL = re.compile(
    r"(?i)^\s*("
    r"delete( permanently)?|"
    r"empty (recycle bin|trash)|"
    r"uninstall|"
    r"format( disk)?|"
    r"erase|wipe|"
    r"turn off (windows )?defender|"
    r"turn off (the )?firewall"
    r")\s*$"
)
_UAC_LABEL = re.compile(
    r"(?i)^\s*(yes|ok|allow|elevate|run as administrator|administrator)\s*$"
)
_PASSWORD_INTO = re.compile(r"(?i)\b(password|passwd|pin|otp|one[- ]?time|passcode)\b")


def exe_basename(value: str) -> str:
    raw = (value or "").strip().replace("/", "\\")
    if not raw:
        return ""
    leaf = raw.rsplit("\\", 1)[-1].strip().lower()
    return leaf


def looks_like_raw_path(target: str) -> bool:
    raw = (target or "").strip()
    if not raw:
        return False
    if _RAW_PATH.search(raw):
        return True
    return False


def is_denied_exe(name: str) -> bool:
    leaf = exe_basename(name)
    if not leaf:
        return False
    if leaf in DENIED_EXES:
        return True
    stem = leaf.rsplit(".", 1)[0]
    return stem in DENIED_EXES or f"{stem}.exe" in DENIED_EXES


def is_inbox_launch(name: str) -> bool:
    leaf = exe_basename(name)
    if leaf in INBOX_LAUNCH:
        return True
    stem = leaf.rsplit(".", 1)[0] if leaf else ""
    return stem in INBOX_LAUNCH


def _windows_dir() -> Path:
    return Path(os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows")


def denied_file_prefixes() -> list[Path]:
    win = _windows_dir().resolve()
    prefixes = [
        win,
        win / "System32",
        win / "SysWOW64",
        win / "WinSxS",
        user_data_dir() / "secrets.yaml",
    ]
    users = Path(os.environ.get("SystemDrive", "C:") + r"\Users")
    home = Path.home()
    if users.is_dir():
        prefixes.append(users)
        # Home itself is not a browse target for desktop open-as-file;
        # other profiles stay denied even if we later allow Documents.
        for child in users.iterdir() if users.exists() else ():
            try:
                if child.resolve() != home.resolve():
                    prefixes.append(child)
            except OSError:
                prefixes.append(child)
    return prefixes


def is_denied_file_path(path: str | Path) -> bool:
    """True when this is an OS / secrets / other-user path, not an app launch."""
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return True
    secrets = (user_data_dir() / "secrets.yaml").resolve()
    if resolved == secrets:
        return True
    win = _windows_dir().resolve()
    try:
        resolved.relative_to(win)
        return True
    except ValueError:
        pass
    users = Path(os.environ.get("SystemDrive", "C:") + r"\Users")
    home = Path.home().resolve()
    try:
        resolved.relative_to(users.resolve())
    except (ValueError, OSError):
        return False
    try:
        resolved.relative_to(home)
        return False
    except ValueError:
        return True


def refuse_launch_target(target: str) -> str | None:
    """Reason to hard-refuse an open/focus target, or None to continue."""
    raw = (target or "").strip()
    if not raw:
        return "Need a target (e.g. notepad, calculator)."
    if looks_like_raw_path(raw):
        return (
            "Raw paths are refused. Use an app name (notepad, calculator) "
            "or a Start Menu title — not an .exe path."
        )
    if is_denied_exe(raw):
        return f"{exe_basename(raw) or raw!r} is not something I start."
    return None


def refuse_resolved_exe(path: str, *, alias: str = "") -> str | None:
    """After we resolved an alias / shortcut, refuse dangerous binaries."""
    leaf = exe_basename(path)
    if is_denied_exe(leaf):
        return f"{leaf} is not something I start."
    if is_inbox_launch(leaf) or is_inbox_launch(alias):
        return None
    if path and is_denied_file_path(path):
        return "That program sits in a system tree I will not open."
    return None


def destructive_label(label: str) -> bool:
    return bool(_DELETE_LABEL.match((label or "").strip()))


def elevation_label(label: str) -> bool:
    return bool(_UAC_LABEL.match((label or "").strip()))


def is_uac_title(title: str) -> bool:
    return "user account control" in (title or "").lower()


def password_field(into: str = "", name: str = "") -> bool:
    blob = f"{into} {name}".strip()
    return bool(blob and _PASSWORD_INTO.search(blob))


def refuse_secret_type(*, into: str = "", name: str = "", is_password: bool = False) -> str | None:
    if is_password or password_field(into, name):
        return (
            "Your turn — I do not type passwords, PINs, or OTP codes. "
            "Hit Go when you are done."
        )
    return None
