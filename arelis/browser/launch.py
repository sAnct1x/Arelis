"""Resolve the system default browser and launch Chrome/Edge with CDP."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from urllib.request import urlopen

from arelis.paths import state_dir, user_data_dir

log = logging.getLogger(__name__)

# Her Chrome only. Daily Chrome/Edge profiles are never launched or taskkilled.
_GAP = 16
_DEFAULT_W = 1100
_DEFAULT_H = 800
_anchor: tuple[int, int, int, int] | None = None
_screen: tuple[int, int, int, int] | None = None
_last_arelis_proc: subprocess.Popen[bytes] | None = None

BrowserName = Literal["chrome", "edge", "firefox"]

_CHROME_PROG_IDS = {
    "chromehtml",
    "chromehtm",
    "google chrome",
    "chromiumhtm",
}
_EDGE_PROG_IDS = {
    "msedgehtm",
    "msedgehtmm",
    "appxqecl46btdkg8nb3w4jyaxywqnwn4m6",
}
_FIREFOX_PROG_IDS = {
    "firefoxurl",
    "firefoxurl-308046b0af4a39cb",
    "firefoxhtml",
}


def browsers_path() -> Path:
    """Where Playwright keeps the browsers it downloads for itself."""
    return user_data_dir() / "browsers"


def pin_browsers_path() -> None:
    """Point Playwright's downloads at the data root, before Playwright loads.

    Not a correctness fix, and worth being clear about that: Playwright's default
    is a per-user cache under %LOCALAPPDATA%, which is writable and outside the
    install directory, so nothing breaks without this. It is so that everything
    Arelis downloads after install lands under one root — beside the voice weights,
    which already work this way — where a user can find it, count it, and delete it.
    Several hundred megabytes of browser in a directory nobody associates with this
    application is the kind of thing that gets discovered years later.

    setdefault rather than an assignment, because somebody who has already pointed
    this somewhere has a reason and it is not ours to overrule. The directory is
    left to Playwright to create; there is no sense making an empty one on a
    machine that never installs a browser.

    Must run before ``playwright`` is imported, which is why it is a separate
    function rather than something done at the point of use.
    """
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers_path()))


def playwright_available() -> bool:
    pin_browsers_path()
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def cdp_is_up(cdp_url: str, *, timeout_s: float = 0.8) -> bool:
    """True when the CDP HTTP endpoint answers (browser already controlled)."""
    base = cdp_url.rstrip("/")
    # Playwright connect_over_cdp wants http://host:port — probe /json/version.
    probe = base + "/json/version"
    try:
        with urlopen(probe, timeout=timeout_s) as resp:
            return 200 <= getattr(resp, "status", 200) < 500
    except Exception:
        return False


def parse_cdp_port(cdp_url: str) -> int:
    parsed = urlparse(cdp_url)
    if parsed.port:
        return int(parsed.port)
    return 9222


def detect_default_browser() -> BrowserName:
    """Best-effort system default → chrome | edge | firefox."""
    if sys.platform == "win32":
        prog = _windows_http_prog_id()
        if prog:
            low = prog.lower()
            if any(low.startswith(p) or p in low for p in _CHROME_PROG_IDS):
                return "chrome"
            if any(low.startswith(p) or p in low for p in _EDGE_PROG_IDS):
                return "edge"
            if any(low.startswith(p) or p in low for p in _FIREFOX_PROG_IDS):
                return "firefox"
    # Non-Windows or unknown: prefer Chrome when installed, else Edge, else Firefox.
    if chrome_executable():
        return "chrome"
    if edge_executable():
        return "edge"
    if firefox_executable():
        return "firefox"
    return "chrome"


def resolve_browser_choice(choice: str | None) -> BrowserName:
    raw = (choice or "default").strip().lower()
    if raw in {"", "default", "system"}:
        return detect_default_browser()
    if raw in {"chrome", "google-chrome", "chromium"}:
        return "chrome"
    if raw in {"edge", "msedge", "microsoft-edge"}:
        return "edge"
    if raw in {"firefox", "ff"}:
        return "firefox"
    return detect_default_browser()


def chrome_executable() -> str | None:
    return _first_existing(
        [
            os.environ.get("ARELIS_CHROME"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            shutil.which("chrome"),
            shutil.which("google-chrome"),
        ]
    )


def edge_executable() -> str | None:
    return _first_existing(
        [
            os.environ.get("ARELIS_EDGE"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            shutil.which("msedge"),
            shutil.which("microsoft-edge"),
        ]
    )


def firefox_executable() -> str | None:
    return _first_existing(
        [
            os.environ.get("ARELIS_FIREFOX"),
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
            shutil.which("firefox"),
        ]
    )


def arelis_user_data_dir() -> Path:
    """Dedicated Chromium profile Arelis owns, beside the rest of its state."""
    return state_dir() / "browser-profile"


def set_arelis_anchor(
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    screen: tuple[int, int, int, int] | None = None,
) -> None:
    """Remember the Arelis window so her Chrome can match size and sit beside it."""
    global _anchor, _screen
    _anchor = (int(x), int(y), max(400, int(w)), max(300, int(h)))
    if screen is not None:
        _screen = (
            int(screen[0]),
            int(screen[1]),
            max(640, int(screen[2])),
            max(480, int(screen[3])),
        )


def window_placement() -> tuple[int, int, int, int]:
    """x, y, w, h — same size as Arelis, parked to the right (or left) of chat."""
    if _anchor is not None:
        ax, ay, aw, ah = _anchor
    else:
        ax, ay, aw, ah = (80, 80, _DEFAULT_W, _DEFAULT_H)
    right = (ax + aw + _GAP, ay, aw, ah)
    left = (ax - _GAP - aw, ay, aw, ah)
    if _screen is None:
        return right
    sx, _sy, sw, _sh = _screen
    if right[0] + aw <= sx + sw:
        return right
    if left[0] >= sx:
        return left
    # Not enough desk: slight cascade so the title bars stay distinct.
    return (ax + 80, ay + 80, aw, ah)


def profile_has_sign_in(user_data: Path | None = None) -> bool:
    root = Path(user_data) if user_data is not None else arelis_user_data_dir()
    return (root / "Default" / "Preferences").is_file()


def _intro_marker(user_data: Path) -> Path:
    return user_data / ".arelis-intro-shown"


def first_run_note(user_data: Path | None = None) -> str:
    """Once per profile — Chrome writes Preferences on first launch, so that is not the signal."""
    root = Path(user_data) if user_data is not None else arelis_user_data_dir()
    if _intro_marker(root).is_file():
        return ""
    return (
        "This is Arelis' Chrome — not your daily browser. "
        "Sign into Google and Maps here once; those logins stay in this window."
    )


def mark_intro_shown(user_data: Path | None = None) -> None:
    root = Path(user_data) if user_data is not None else arelis_user_data_dir()
    try:
        root.mkdir(parents=True, exist_ok=True)
        _intro_marker(root).write_text("1\n", encoding="utf-8")
    except OSError:
        log.warning("could not write browser intro marker under %s", root)


def open_url_in_browser(
    url: str,
    browser: str | None = "default",
) -> tuple[bool, str, dict[str, str]]:
    """Open a URL in Chrome/Edge/Firefox like a normal click — no CDP, no kill.

    If that browser is already running with the usual profile, the OS/browser
    typically adds a tab/window and keeps the user signed in.
    """
    name = resolve_browser_choice(browser)
    exe: str | None
    if name == "chrome":
        exe = chrome_executable()
    elif name == "edge":
        exe = edge_executable()
    else:
        exe = firefox_executable()
    try:
        if exe:
            # --new-window so the tab is not buried behind other Chrome instances.
            argv = [exe, "--new-window", url] if name in {"chrome", "edge"} else [exe, url]
            subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            return (
                True,
                f"Opened {url} in {name}.",
                {"mode": "os_open", "browser": name, "url": url},
            )
        import webbrowser

        if webbrowser.open(url):
            return (
                True,
                f"Opened {url} in the system browser.",
                {"mode": "os_open", "browser": "system", "url": url},
            )
        return False, f"Could not open {url}.", {"code": "OPEN_FAILED"}
    except Exception as exc:
        log.exception("open_url_in_browser failed")
        return False, f"Could not open {url}: {exc}", {"code": "OPEN_FAILED"}


def launch_chromium_cdp(
    browser: BrowserName,
    *,
    cdp_url: str,
    restore_session: bool = True,
) -> subprocess.Popen[bytes] | None:
    """Start Arelis Chrome/Edge with her profile + CDP. Never the daily profile."""
    global _last_arelis_proc
    if browser == "firefox":
        return None
    exe = chrome_executable() if browser == "chrome" else edge_executable()
    if not exe:
        return None
    port = parse_cdp_port(cdp_url)
    user_data = arelis_user_data_dir()
    user_data.mkdir(parents=True, exist_ok=True)
    x, y, w, h = window_placement()
    args = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        f"--window-size={w},{h}",
        f"--window-position={x},{y}",
    ]
    if restore_session and profile_has_sign_in(user_data):
        args.append("--restore-last-session")
    log.info("Launching Arelis %s with CDP on port %s profile=%s", browser, port, user_data)
    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _last_arelis_proc = proc
    return proc


def wait_for_cdp(cdp_url: str, *, timeout_s: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if cdp_is_up(cdp_url):
            return True
        time.sleep(0.25)
    return False


def profile_appears_locked(browser: BrowserName) -> bool:
    """True when Arelis' profile is running (not daily Chrome)."""
    if browser == "firefox":
        return False
    return bool(_pids_using_arelis_profile())


def terminate_browser_processes(browser: BrowserName) -> None:
    """Relaunch: stop Arelis Chrome only. Never ``taskkill /IM chrome.exe``."""
    del browser
    terminate_arelis_browser()


def terminate_arelis_browser() -> None:
    """Kill only processes whose command line uses data/browser-profile."""
    global _last_arelis_proc
    pids = set(_pids_using_arelis_profile())
    if _last_arelis_proc is not None and _last_arelis_proc.poll() is None:
        pids.add(int(_last_arelis_proc.pid))
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
        except Exception:
            log.exception("Failed to stop Arelis browser pid %s", pid)
    _last_arelis_proc = None
    if pids:
        time.sleep(0.6)


def _pids_using_arelis_profile() -> list[int]:
    marker = str(arelis_user_data_dir().resolve()).replace("/", "\\").lower()
    if sys.platform != "win32" or not marker:
        return []
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "Get-CimInstance Win32_Process | "
                    "Where-Object { $_.Name -match '^(chrome|msedge)\\.exe$' } | "
                    "ForEach-Object { '{0}`t{1}' -f $_.ProcessId, $_.CommandLine }"
                ),
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=12,
        )
    except Exception:
        return []
    pids: list[int] = []
    for line in out.splitlines():
        if "\t" not in line:
            continue
        pid_s, cmd = line.split("\t", 1)
        low = (cmd or "").replace("/", "\\").lower()
        if marker not in low:
            continue
        try:
            pids.append(int(pid_s.strip()))
        except ValueError:
            continue
    return pids


def _windows_http_prog_id() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        )
        try:
            value, _ = winreg.QueryValueEx(key, "ProgId")
            return str(value) if value else None
        finally:
            winreg.CloseKey(key)
    except OSError:
        return None


def _first_existing(candidates: list[str | None]) -> str | None:
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw)
        if path.is_file():
            return str(path.resolve())
    return None
