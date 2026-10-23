"""Resolve the system default browser and launch Chrome/Edge with CDP."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from urllib.request import urlopen

from arelis.paths import library_cache_dir, state_dir, user_data_dir

log = logging.getLogger(__name__)

# Her Chrome only. Daily Chrome/Edge profiles are never launched or taskkilled.
_GAP = 16
# One desk, not the 1/2/3 span. A 3-monitor HWND is not a browser size.
_DESK_FRACTION = 0.60
_MIN_W = 720
_MIN_H = 520
_anchor: tuple[int, int, int, int] | None = None
_screen: tuple[int, int, int, int] | None = None
_last_arelis_proc: subprocess.Popen[bytes] | None = None
# Set only in launch_chromium_cdp after Popen. Quit skips the leftover
# profile pid scan when this process never started her Chrome.
_owned_browser_launched = False

BrowserName = Literal["chrome", "edge", "firefox"]

# Where a new window lands when nothing is being restored.
FRESH_START_URL = "https://www.google.com"

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
    mac = library_cache_dir()
    if mac is not None:
        return mac / "browsers"
    return user_data_dir() / "browsers"


def pin_browsers_path() -> None:
    """Point Playwright's downloads at the data root, before Playwright loads.

    Not a correctness fix, and worth being clear about that: Playwright's default
    is a per-user cache under %LOCALAPPDATA%, which is writable and outside the
    install directory, so nothing breaks without this. It is so that everything
    Arelis downloads after install lands under one root, beside the voice weights,
    which already work this way, where a user can find it, count it, and delete it.
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


def cdp_port_is_arelis(cdp_url: str) -> bool | None:
    """True when her profile holds this CDP port. None if we cannot tell.

    An empty process scan is unknown, not "foreign." CIM often returns no
    rows while Chrome is up; treating that as False hops off a live 9222.
    """
    if sys.platform != "win32":
        return None
    rows = _chrome_cmdlines()
    if not rows:
        return None
    port = parse_cdp_port(cdp_url)
    marker = str(arelis_user_data_dir().resolve()).replace("/", "\\").lower()
    needle = f"--remote-debugging-port={port}"
    for _pid, cmd in rows:
        low = (cmd or "").replace("/", "\\").lower()
        if marker in low and needle in low:
            return True
    return False


def prefer_cdp_url(preferred: str) -> str:
    """Keep her window. If 9222 is someone else's Chrome, pick another port."""
    raw = (preferred or "").strip() or "http://127.0.0.1:9222"
    if not cdp_is_up(raw):
        return raw
    owned = cdp_port_is_arelis(raw)
    if owned is True or owned is None:
        return raw
    parsed = urlparse(raw)
    host = parsed.hostname or "127.0.0.1"
    for port in range(9333, 9343):
        url = f"http://{host}:{port}"
        if cdp_is_up(url) and cdp_port_is_arelis(url) is True:
            return url
        if not cdp_is_up(url):
            return url
    return f"http://{host}:9333"


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


def _mac_browser_paths() -> list[str]:
    """Chrome and Chromium in /Applications and the user Applications folder.

    A GUI launch on Mac often does not have Homebrew on PATH. These are checked
    as files, not via PATH.
    """
    bundles = (
        ("Google Chrome.app", "Google Chrome"),
        ("Chromium.app", "Chromium"),
    )
    roots = (Path("/Applications"), Path.home() / "Applications")
    found: list[str] = []
    for root in roots:
        for bundle, binary in bundles:
            found.append((root / bundle / "Contents" / "MacOS" / binary).as_posix())
    return found


def chrome_executable() -> str | None:
    return _first_existing(
        [
            os.environ.get("ARELIS_CHROME"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            shutil.which("chrome"),
            shutil.which("google-chrome"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
            shutil.which("google-chrome-stable"),
            "/snap/bin/chromium",
            str(
                Path.home()
                / ".local"
                / "share"
                / "flatpak"
                / "exports"
                / "bin"
                / "com.google.Chrome"
            ),
            str(
                Path.home()
                / ".local"
                / "share"
                / "flatpak"
                / "exports"
                / "bin"
                / "org.chromium.Chromium"
            ),
            "/var/lib/flatpak/exports/bin/com.google.Chrome",
            "/var/lib/flatpak/exports/bin/org.chromium.Chromium",
            *_mac_browser_paths(),
        ]
    )


def edge_executable() -> str | None:
    candidates: list[str | None] = [
        os.environ.get("ARELIS_EDGE"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("msedge"),
        shutil.which("microsoft-edge"),
    ]
    if sys.platform != "win32":
        candidates.append(shutil.which("microsoft-edge-stable"))
    return _first_existing(candidates)


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
    """Remember Arelis so her Chrome can sit beside chat on the same desk.

    ``screen`` is one monitor's work area, never the 1/2/3 span union.
    Chrome size comes from that desk, not from the Arelis HWND.
    """
    global _anchor, _screen
    _anchor = (int(x), int(y), max(400, int(w)), max(300, int(h)))
    if screen is not None:
        _screen = (
            int(screen[0]),
            int(screen[1]),
            max(640, int(screen[2])),
            max(480, int(screen[3])),
        )


def _one_desk() -> tuple[int, int, int, int]:
    """Work area of one monitor. Never the three-desk union."""
    if _screen is not None:
        return _screen
    return (0, 0, 1920, 1080)


def _desk_window_size(sw: int, sh: int) -> tuple[int, int]:
    w = max(_MIN_W, int(sw * _DESK_FRACTION))
    h = max(_MIN_H, int(sh * _DESK_FRACTION))
    return min(w, max(_MIN_W, sw - 32)), min(h, max(_MIN_H, sh - 32))


def _clamp_to_desk(
    x: int, y: int, w: int, h: int, sx: int, sy: int, sw: int, sh: int
) -> tuple[int, int, int, int]:
    w = min(w, sw)
    h = min(h, sh)
    x = min(max(x, sx), sx + sw - w)
    y = min(max(y, sy), sy + sh - h)
    return (x, y, w, h)


def should_park_window(*, fresh_launch: bool, already_placed: bool) -> bool:
    """True only for a Chrome we just started. Never after they move it."""
    return bool(fresh_launch) and not bool(already_placed)


def raise_arelis_chrome(*, restore: bool = True) -> bool:
    """Put her Chrome above Arelis without taking the keyboard.

    Launch leaves Chrome behind the glass. Clicks go through CDP and do
    not need the window focused, they need to see it. HWND_TOP +
    no-activate keeps the mic on Arelis.
    """
    if sys.platform != "win32":
        return False
    pids = set(_pids_using_arelis_profile())
    if _last_arelis_proc is not None and _last_arelis_proc.poll() is None:
        pids.add(int(_last_arelis_proc.pid))
    if not pids:
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False

    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _each(hwnd: int, _lp: int) -> bool:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) not in pids:
            return True
        if user32.GetWindow(hwnd, 4):  # GW_OWNER — skip popups
            return True
        buf = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, buf, 64)
        if buf.value != "Chrome_WidgetWin_1":
            return True
        if not user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            return True
        found.append(int(hwnd))
        return True

    user32.EnumWindows(_each, 0)
    if not found:
        return False

    swp_nomove = 0x0002
    swp_nosize = 0x0001
    swp_noactivate = 0x0010
    hwnd_top = 0
    hwnd_topmost = -1
    hwnd_notopmost = -2
    sw_restore = 9
    sw_shownoactivate = 4
    flags = swp_nomove | swp_nosize | swp_noactivate
    raised = False
    for hwnd in found:
        if restore and user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, sw_restore)
        else:
            user32.ShowWindow(hwnd, sw_shownoactivate)
        user32.SetWindowPos(hwnd, hwnd_topmost, 0, 0, 0, 0, flags)
        user32.SetWindowPos(hwnd, hwnd_notopmost, 0, 0, 0, 0, flags)
        user32.SetWindowPos(hwnd, hwnd_top, 0, 0, 0, 0, flags)
        raised = True
    return raised


def window_placement() -> tuple[int, int, int, int]:
    """x, y, w, h, ~60% of one monitor, never maximized across the span.

    Sits to the right (or left) of a single-desk Arelis window when that
    still fits. A 1/2/3 filament HWND is ignored for size; Chrome is
    centered on the home desk instead.
    """
    sx, sy, sw, sh = _one_desk()
    w, h = _desk_window_size(sw, sh)
    cx = sx + (sw - w) // 2
    cy = sy + (sh - h) // 2
    if _anchor is not None:
        ax, ay, aw, ah = _anchor
        on_this_desk = aw <= sw * 1.15 and ah <= sh * 1.15
        if on_this_desk:
            right = ax + aw + _GAP
            if right + w <= sx + sw:
                return _clamp_to_desk(right, ay, w, h, sx, sy, sw, sh)
            left = ax - _GAP - w
            if left >= sx:
                return _clamp_to_desk(left, ay, w, h, sx, sy, sw, sh)
    return _clamp_to_desk(cx, cy, w, h, sx, sy, sw, sh)


def profile_has_sign_in(user_data: Path | None = None) -> bool:
    root = Path(user_data) if user_data is not None else arelis_user_data_dir()
    return (root / "Default" / "Preferences").is_file()


def _intro_marker(user_data: Path) -> Path:
    return user_data / ".arelis-intro-shown"


def first_run_note(user_data: Path | None = None, *, fresh: bool = False) -> str:
    """Once per profile, Chrome writes Preferences on first launch, so that is not the signal.

    A fresh-profile window keeps no sign-ins, so there is nothing to explain.
    """
    if fresh:
        return ""
    root = Path(user_data) if user_data is not None else arelis_user_data_dir()
    if _intro_marker(root).is_file():
        return ""
    return (
        "This is Arelis' Chrome, not your daily browser. "
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
    """Open a URL in Chrome/Edge/Firefox like a normal click, no CDP, no kill.

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


def reset_arelis_profile(user_data: Path | None = None) -> bool:
    """Delete her Chrome profile so the next window has no tabs, cookies or history.

    Only ever removes a directory named ``browser-profile``. The caller must have
    stopped (or never started) the Chrome that holds it.
    """
    root = Path(user_data) if user_data is not None else arelis_user_data_dir()
    if root.name != "browser-profile":
        log.warning("refusing to wipe unexpected browser profile path %s", root)
        return False
    shutil.rmtree(root, ignore_errors=True)
    return not root.exists()


def launch_chromium_cdp(
    browser: BrowserName,
    *,
    cdp_url: str,
    restore_session: bool = True,
    fresh_profile: bool = False,
) -> subprocess.Popen[bytes] | None:
    """Start Arelis Chrome/Edge with her profile + CDP. Never the daily profile.

    ``fresh_profile`` wipes that profile first and starts on google.com: no
    restored tabs, history, cookies or autofill from an earlier run.
    """
    global _last_arelis_proc, _owned_browser_launched
    if browser == "firefox":
        return None
    exe = chrome_executable() if browser == "chrome" else edge_executable()
    if not exe:
        return None
    port = parse_cdp_port(cdp_url)
    user_data = arelis_user_data_dir()
    if fresh_profile:
        restore_session = False
        reset_arelis_profile(user_data)
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
    if not restore_session:
        args.extend(["--disable-session-crashed-bubble", "--hide-crash-restore-bubble"])
        args.append(FRESH_START_URL)
    log.info("Launching Arelis %s with CDP on port %s profile=%s", browser, port, user_data)
    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _last_arelis_proc = proc
    _owned_browser_launched = True
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
    stop_owned_browser(timeout_s=15.0, settle_s=0.6)


def _pid_is_alive(pid: int) -> bool:
    """True when that OS process still exists. Never ``os.kill(pid, 0)``."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            process_query_limited = 0x1000
            still_active = 259
            access_denied = 5
            kernel32.SetLastError(0)
            handle = kernel32.OpenProcess(process_query_limited, False, int(pid))
            if not handle:
                return int(kernel32.GetLastError()) == access_denied
            try:
                code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return True
                return int(code.value) == still_active
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            # Probe failed. Treat the pid as gone rather than guess.
            return False
    procfs = Path("/proc")
    if (procfs / "self" / "status").is_file():
        return (procfs / str(int(pid))).is_dir()
    try:
        import ctypes
        import errno as errno_mod

        libc = ctypes.CDLL(None, use_errno=True)
        libc.kill.argtypes = [ctypes.c_int, ctypes.c_int]
        libc.kill.restype = ctypes.c_int
        if libc.kill(int(pid), 0) == 0:
            return True
        return ctypes.get_errno() == errno_mod.EPERM
    except Exception:
        # Probe failed. Treat the pid as gone rather than guess.
        return False


def _as_timeout_s(timeout_s: float) -> float:
    try:
        return max(0.0, float(timeout_s))
    except (TypeError, ValueError):
        return 3.0


def _left_s(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _taskkill_tree(pid: int, *, timeout_s: float) -> None:
    """Windows process tree for one owned pid. Never by image name."""
    if pid <= 0 or timeout_s <= 0:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
        )
    except Exception:
        log.exception("Failed to stop Arelis browser pid %s", pid)


def _signal_owned_pid(
    pid: int, *, force: bool = False, timeout_s: float = 3.0
) -> None:
    """Stop one pid we already know is ours. Never by image name."""
    if pid <= 0:
        return
    if sys.platform == "win32":
        _taskkill_tree(pid, timeout_s=max(0.0, float(timeout_s)))
        return
    try:
        if force:
            os.kill(int(pid), signal.SIGKILL)
        else:
            os.kill(int(pid), signal.SIGTERM)
    except OSError:
        return


def stop_owned_browser(*, timeout_s: float = 3.0, settle_s: float = 0.0) -> None:
    """Stop the Chrome or Edge this process started. Bounded. Owner only.

    ``launch_chromium_cdp`` is the one starter. Browser tool, scrape that
    then opens the page, and Google sign-in in her window all go through
    it. Calendar OAuth uses the system browser and is not ours.
    Never ``taskkill /IM chrome.exe``. On Windows the owned pid is
    ``taskkill /PID n /T /F`` so renderer and GPU children die with it.
    The leftover profile pid scan runs only after this process spawned
    her Chrome. A session that never launched skips that scan.
    """
    global _last_arelis_proc
    deadline = time.monotonic() + _as_timeout_s(timeout_s)
    proc = _last_arelis_proc
    left = _left_s(deadline)
    if _owned_browser_launched and left > 0:
        pids = set(_pids_using_arelis_profile(timeout_s=left))
    else:
        pids = set()
    if proc is not None and proc.poll() is None:
        pids.add(int(proc.pid))
        if sys.platform == "win32":
            _signal_owned_pid(int(proc.pid), timeout_s=_left_s(deadline))
        else:
            try:
                proc.terminate()
            except Exception:
                log.exception("Failed to stop Arelis browser pid %s", proc.pid)
    for pid in pids:
        if proc is not None and pid == int(proc.pid):
            continue
        left = _left_s(deadline)
        if left <= 0:
            break
        _signal_owned_pid(pid, force=False, timeout_s=left)
    if proc is not None and proc.poll() is None:
        try:
            proc.wait(timeout=_left_s(deadline))
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":
                _signal_owned_pid(int(proc.pid), timeout_s=_left_s(deadline))
            else:
                try:
                    proc.kill()
                except Exception:
                    log.exception("Failed to kill Arelis browser pid %s", proc.pid)
            try:
                proc.wait(timeout=_left_s(deadline))
            except subprocess.TimeoutExpired:
                log.warning(
                    "Arelis browser pid %s still running after quit budget",
                    proc.pid,
                )
    for pid in pids:
        if not _pid_is_alive(pid):
            continue
        left = _left_s(deadline)
        if left <= 0:
            break
        _signal_owned_pid(pid, force=True, timeout_s=left)
    if settle_s > 0 and pids:
        time.sleep(min(float(settle_s), _left_s(deadline)))
    _last_arelis_proc = None


def _parse_pid_cmd_lines(out: str) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    for line in (out or "").splitlines():
        if "\t" not in line:
            continue
        pid_s, cmd = line.split("\t", 1)
        try:
            rows.append((int(pid_s.strip()), cmd or ""))
        except ValueError:
            continue
    return rows


_SCAN_S = 12.0


def _chrome_cmdlines(*, timeout_s: float | None = None) -> list[tuple[int, str]] | None:
    """Chrome/Edge pid + command line. None when every scan failed."""
    if sys.platform != "win32":
        return []
    if timeout_s is not None and timeout_s <= 0:
        return []
    budget = _SCAN_S if timeout_s is None else float(timeout_s)
    started = time.monotonic()
    primary = _chrome_cmdlines_cim(timeout_s=budget)
    if primary:
        return primary
    leftover = (
        _SCAN_S if timeout_s is None else budget - (time.monotonic() - started)
    )
    if leftover <= 0:
        return primary if primary is not None else []
    fallback = _chrome_cmdlines_wmic(timeout_s=leftover)
    if fallback:
        return fallback
    if primary is None and fallback is None:
        return None
    return []


def _chrome_cmdlines_cim(*, timeout_s: float = _SCAN_S) -> list[tuple[int, str]] | None:
    if timeout_s <= 0:
        return None
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "Get-CimInstance -ClassName Win32_Process "
                    "-Filter \"Name='chrome.exe' OR Name='msedge.exe'\" | "
                    "ForEach-Object { '{0}`t{1}' -f $_.ProcessId, $_.CommandLine }"
                ),
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
        )
    except Exception:
        return None
    return _parse_pid_cmd_lines(out)


def _chrome_cmdlines_wmic(*, timeout_s: float = _SCAN_S) -> list[tuple[int, str]] | None:
    """Second shape when CIM returns no rows. No extra package."""
    if timeout_s <= 0:
        return None
    try:
        out = subprocess.check_output(
            [
                "wmic",
                "process",
                "where",
                "name='chrome.exe' or name='msedge.exe'",
                "get",
                "ProcessId,CommandLine",
                "/format:csv",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
        )
    except Exception:
        return None
    rows: list[tuple[int, str]] = []
    for line in (out or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3 or parts[-1].lower() == "processid":
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        cmd = ",".join(parts[1:-1]).strip()
        rows.append((pid, cmd))
    return rows


def _pids_using_arelis_profile(*, timeout_s: float | None = None) -> list[int]:
    if timeout_s is not None and timeout_s <= 0:
        return []
    marker = str(arelis_user_data_dir().resolve()).replace("/", "\\").lower()
    if not marker:
        return []
    rows = _chrome_cmdlines(timeout_s=timeout_s)
    if not rows:
        return []
    pids: list[int] = []
    for pid, cmd in rows:
        low = (cmd or "").replace("/", "\\").lower()
        if marker not in low:
            continue
        pids.append(pid)
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
        if not path.is_file():
            continue
        # Windows keeps the resolved path. Elsewhere, resolving a snap
        # launcher turns it into the snap command and drops the app name.
        if sys.platform == "win32":
            return str(path.resolve())
        return str(path)
    return None
