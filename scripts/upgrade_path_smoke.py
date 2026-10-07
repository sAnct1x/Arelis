"""Real installer upgrade on a clean Windows runner.

Builds the checkout at its real version and again with the patch number
bumped only inside the built tree, installs published v0.3.0, upgrades
to the current build, then takes the in-app updater's backup path to the
fake next version. Not part of ci.yml. A red run here does not fail the
every-push tests or the installer publish workflow.

What a green run proves
=======================

* Inno Setup can replace the published v0.3.0 install with this checkout
  and leave the seeded records byte-for-byte.
* The installed app reaches its event loop offscreen and exits 0 without
  binding port 8766.
* ``backup_before_upgrade`` from the installed tree writes beside the data
  folder, skips secrets, leaves no half-finished folder, and keeps two.
* A backup that cannot create its folder returns no path, and the real
  update prompt does not start the installer.
* The real ``start_installer`` then installs the fake next version.
* A wipe uninstall removes the app and the data folder and leaves the
  backup folder in place.

What it does not prove
======================

* The daily update check, the download, or the yes/no question. Those stay
  off on purpose.
* A person clicking through SmartScreen.
* The post-install relaunch is stopped after ``start_installer`` returns,
  so it does not sit on the runner. The headless probe is a separate start.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
PUBLISHED_TAG = "v0.3.0"
PUBLISHED_SETUP = "Arelis-0.3.0-win64-setup.exe"
MARKER = "UPGRADE-PATH-MARKER"
SENTINEL = "FAKE-TOKEN-DO-NOT-COPY"
APP_ID = "{8F4C2D31-6A5E-4B7C-9E1D-3A2F5B8C7D40}"
UNINSTALL_KEY = f"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{APP_ID}_is1"
SETUP_NAME_RE = re.compile(
    r"^Arelis-(?P<ver>\d+\.\d+\.\d+)-win64-setup\.exe$",
    re.IGNORECASE,
)
SHA256_LINE_RE = re.compile(r"^([0-9a-f]{64})\s+(\S+)\s*$", re.IGNORECASE)
VERSION_LINE_RE = re.compile(
    r'^(?P<prefix>__version__\s*=\s*)(?P<quote>["\'])(?P<ver>[^"\']+)(?P=quote)',
    re.MULTILINE,
)
INSTALL_TIMEOUT_S = 1200
BUILD_TIMEOUT_S = 7200
OUT = Path(os.environ.get("UPGRADE_OUT", "upgrade-out")).resolve()
INSTALLERS = Path(os.environ.get("UPGRADE_INSTALLERS", "upgrade-installers")).resolve()
SUMMARY_PATH = OUT / "summary.json"
TRACKED = (
    "memory.db",
    "rooms.yaml",
    "contacts.yaml",
    "profile.yaml",
    "lessons.yaml",
    "config.local.yaml",
    "secrets.yaml",
)

HEADLESS_PY = """
    import os
    import sys

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["ARELIS_ALLOW_OFFSCREEN"] = "1"
    os.environ.pop("ARELIS_DATA_DIR", None)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def _install_exec_hook() -> None:
        original = QApplication.exec

        def _exec(*args, **kwargs):
            print("headless_reached_exec", flush=True)
            app = args[0] if args else QApplication.instance()
            if app is not None:
                QTimer.singleShot(1500, app.quit)
            # PySide6's exec is static and rejects the instance we were given.
            return original()

        QApplication.exec = _exec

    _install_exec_hook()

    from arelis.main import main

    sys.exit(main([]))
"""

SEED_MEMORY_PY = """
    import sys

    from arelis.memory.store import MemoryStore

    marker = sys.argv[1]
    store = MemoryStore()
    store.start_session()
    store.on_message("user", marker + " chat line")
    fact_id = store.add_fact(marker, source="explicit", status="active")
    store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store.close()
    if fact_id is None:
        print("seed failed: fact was not stored", flush=True)
        sys.exit(1)
    print("seeded fact=%s" % fact_id, flush=True)
"""

INSPECT_PY = """
    import sys

    from arelis.config import load_config
    from arelis.memory.store import MemoryStore

    needle = sys.argv[1]
    cfg = load_config()
    ui = cfg.get("ui") or {}
    updates = cfg.get("updates") or {}
    voice = cfg.get("voice") or {}
    location = cfg.get("location") or {}
    presence = cfg.get("presence") or {}
    print("theme=" + str(ui.get("theme")), flush=True)
    print("updates_check=" + str(updates.get("check")), flush=True)
    print("voice_enabled=" + str(voice.get("enabled")), flush=True)
    print("location_enabled=" + str(location.get("enabled")), flush=True)
    print("ipc_enabled=" + str(presence.get("ipc_enabled")), flush=True)
    store = MemoryStore()
    try:
        facts = store.list_facts(status="active", limit=50)
        texts = [str(row.get("text") or "") for row in facts]
        print("fact_hit=" + str(any(needle in text for text in texts)), flush=True)
        rows = store._conn.execute(
            "SELECT content FROM messages WHERE content LIKE ?",
            ("%" + needle + "%",),
        ).fetchall()
        print("message_hit=" + str(bool(rows)), flush=True)
    finally:
        store.close()
"""

KEEP_PY = """
    import sys
    import time

    from arelis.backup import backup_before_upgrade

    for ver in sys.argv[1:]:
        dest = backup_before_upgrade(ver)
        print("backup %s %s" % (ver, dest), flush=True)
        if dest is None:
            sys.exit(2)
        time.sleep(1.1)
"""

UPDATER_PY = """
    import sys
    from pathlib import Path

    from arelis import __version__
    from arelis.backup import backup_before_upgrade
    from arelis.update import start_installer

    dest = backup_before_upgrade(__version__)
    print("backup %s %s" % (__version__, dest), flush=True)
    if dest is None:
        sys.exit(2)
    start_installer(Path(sys.argv[1]))
    print("started", flush=True)
"""

FAILURE_PY = """
    import json
    import os
    import sys
    import time
    from pathlib import Path

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["ARELIS_ALLOW_OFFSCREEN"] = "1"
    os.environ.pop("ARELIS_DATA_DIR", None)

    result = {
        "direct_backup_none": False,
        "install_started": False,
        "start_calls": [],
        "error": "",
    }
    out_path = Path(sys.argv[2])

    def _write() -> None:
        out_path.write_text(json.dumps(result), encoding="utf-8")

    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QDialog, QWidget

        from arelis import __version__
        from arelis.backup import backup_before_upgrade
        from arelis.ui import update_prompt

        direct = backup_before_upgrade(__version__)
        result["direct_backup_none"] = direct is None
        result["from_version"] = __version__
        print("direct_backup_none %s" % (direct is None), flush=True)

        calls = []

        def tripwire(installer):
            calls.append(str(installer))
            result["start_calls"] = list(calls)
            print("start_installer_called", flush=True)
            _write()

        update_prompt.start_installer = tripwire

        def dismiss():
            app = QApplication.instance()
            if app is None:
                QTimer.singleShot(100, dismiss)
                return
            # Offscreen Qt can leave the notice up without reporting it visible.
            # accept() still ends the modal wait, which is the only thing blocking.
            found = False
            for widget in list(app.allWidgets()):
                if isinstance(widget, QDialog):
                    widget.accept()
                    found = True
            if not found:
                QTimer.singleShot(100, dismiss)

        app = QApplication.instance() or QApplication([])
        QTimer.singleShot(100, dismiss)
        window = QWidget()
        prompt = update_prompt.UpdatePrompt(window)
        prompt._on_downloaded(Path(sys.argv[1]))
        deadline = time.time() + 75
        while time.time() < deadline and not prompt._install_started:
            app.processEvents()
            time.sleep(0.05)
        settle = time.time() + 5
        while time.time() < settle:
            app.processEvents()
            time.sleep(0.05)
        result["install_started"] = bool(prompt._install_started)
        result["start_calls"] = list(calls)
        print(
            "done install_started=%s calls=%s"
            % (result["install_started"], len(calls)),
            flush=True,
        )
        if not (result["direct_backup_none"] and result["install_started"] and not calls):
            sys.exit(1)
    except Exception as exc:
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
        _write()
        raise
    finally:
        _write()
"""

CHILD_SCRIPTS = {
    "headless_launch.py": HEADLESS_PY,
    "seed_memory.py": SEED_MEMORY_PY,
    "inspect_state.py": INSPECT_PY,
    "backup_keep.py": KEEP_PY,
    "updater_launch.py": UPDATER_PY,
    "failure_probe.py": FAILURE_PY,
}


def child_source(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


def compiled_child_scripts() -> dict[str, str]:
    sources = {name: child_source(text) for name, text in CHILD_SCRIPTS.items()}
    for name, source in sources.items():
        ast.parse(source, filename=name)
    return sources


def next_patch_version(version: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version.strip())
    if match is None:
        raise ValueError(f"not a plain version: {version!r}")
    major, minor, patch = (int(match.group(index)) for index in range(1, 4))
    return f"{major}.{minor}.{patch + 1}"


def version_assignment(text: str) -> str:
    match = VERSION_LINE_RE.search(text)
    if match is None:
        raise ValueError("no __version__ assignment")
    return match.group("ver")


def rewrite_version_assignment(text: str, new_version: str) -> str:
    if re.fullmatch(r"\d+\.\d+\.\d+", new_version) is None:
        raise ValueError(f"not a plain version: {new_version!r}")
    match = VERSION_LINE_RE.search(text)
    if match is None:
        raise ValueError("no __version__ assignment")
    replacement = (
        f"{match.group('prefix')}{match.group('quote')}{new_version}{match.group('quote')}"
    )
    return text[: match.start()] + replacement + text[match.end() :]


def bump_tree_version(init_py: Path, new_version: str, repo_root: Path) -> None:
    """Edit one built-tree ``__init__.py``. Never the checkout copy."""
    repo_init = (repo_root / "arelis" / "__init__.py").resolve()
    if init_py.resolve() == repo_init:
        raise RuntimeError("refusing to change the checkout version")
    updated = rewrite_version_assignment(init_py.read_text(encoding="utf-8"), new_version)
    init_py.write_bytes(updated.encode("utf-8"))
    cache = init_py.parent / "__pycache__"
    if cache.is_dir():
        for stale in cache.glob("__init__*.pyc"):
            stale.unlink()


def version_line_has(text: str, version: str) -> bool:
    stripped = text.strip()
    return f"arelis {version} " in text or stripped == f"arelis {version}"


def parse_sha256_line(text: str) -> tuple[str, str]:
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = SHA256_LINE_RE.match(line)
        if match:
            return match.group(1).lower(), match.group(2)
    raise ValueError("no sha256 digest line found")


def setup_version_from_name(name: str) -> str:
    match = SETUP_NAME_RE.match(Path(name).name)
    if match is None:
        raise ValueError(f"unrecognised installer name: {name}")
    return match.group("ver")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def snapshot_files(state: Path, names: tuple[str, ...] = TRACKED) -> dict[str, str]:
    found: dict[str, str] = {}
    for name in names:
        path = state / name
        found[name] = sha256_file(path) if path.is_file() else "MISSING"
    return found


def same_hashes(before: dict[str, str], after: dict[str, str], names: tuple[str, ...]) -> list[str]:
    problems = []
    for name in names:
        left = before.get(name, "MISSING")
        right = after.get(name, "MISSING")
        if left != right:
            problems.append(f"{name} changed")
    return problems


def audit_backup_folder(backups: Path, data_root: Path) -> list[str]:
    """#117 checks that do not need Windows. Empty list means the folder is ok."""
    problems: list[str] = []
    if not backups.is_dir():
        return ["backup folder is missing"]
    try:
        backup_resolved = backups.resolve()
        data_resolved = data_root.resolve()
        expected = (data_root.parent / f"{data_root.name}-backups").resolve()
    except OSError as exc:
        return [f"could not resolve backup folder: {exc}"]
    if backup_resolved == data_resolved or backup_resolved.is_relative_to(data_resolved):
        problems.append("backup folder is inside the data folder")
    if backup_resolved != expected:
        problems.append("backup folder is not beside the data folder")
    pre_folders = []
    for child in backups.iterdir():
        if ".partial" in child.name or (child.name.startswith(".") and child.is_dir()):
            problems.append(f"half-finished folder: {child.name}")
        if child.is_dir() and child.name.startswith("pre-") and ".partial" not in child.name:
            pre_folders.append(child)
    if len(pre_folders) > 2:
        problems.append(
            f"{len(pre_folders)} pre-upgrade folders kept; only the newest two should remain"
        )
    sentinel = SENTINEL.encode("utf-8")
    for path in backups.rglob("*"):
        if ".partial" in path.name:
            note = f"half-finished folder: {path.name}"
            if note not in problems:
                problems.append(note)
        if not path.is_file():
            continue
        if path.name.lower() == "secrets.yaml":
            problems.append(f"secrets.yaml inside {path.parent.name}")
            continue
        try:
            blob = path.read_bytes()
        except OSError:
            continue
        if sentinel in blob:
            problems.append(f"secret token copied into {path.parent.name}/{path.name}")
    return problems


def _ensure_out() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    INSTALLERS.mkdir(parents=True, exist_ok=True)


def _summary() -> dict[str, Any]:
    if not SUMMARY_PATH.is_file():
        return {"steps": []}
    try:
        data = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"steps": []}
    if "steps" not in data:
        data["steps"] = []
    return data


def _write_step_summary(data: dict[str, Any]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not path:
        return
    lines = [
        "### Upgrade path",
        "",
        "Not part of the every-push tests. A red result does not fail those.",
        "",
        "| Step | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for step in data.get("steps", []):
        detail = str(step.get("detail", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {step.get('name', '')} | {step.get('status', '')} | {detail} |")
    lines.extend(
        [
            "",
            "Not proven: the daily update check, the download, and the yes/no question.",
            "The relaunch after a real installer start is stopped so it does not keep running.",
        ]
    )
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def say(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def record(name: str, status: str, detail: str = "") -> None:
    status = status.upper()
    if status not in {"PASS", "FAIL", "INFO"}:
        raise ValueError(f"bad status: {status}")
    _ensure_out()
    data = _summary()
    data["steps"].append({"name": name, "status": status, "detail": detail})
    SUMMARY_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    say(f"[{status}] {name}: {detail}")
    _write_step_summary(data)


def fail(name: str, detail: str) -> int:
    record(name, "FAIL", detail)
    return 1


def _tail(path: Path, limit: int = 4000) -> str:
    if not path.is_file():
        return ""
    data = path.read_bytes()
    if len(data) > limit:
        data = data[-limit:]
    return data.decode("utf-8", errors="replace")


def _is_windows() -> bool:
    return sys.platform == "win32"


def local_appdata() -> Path:
    return Path(os.environ["LOCALAPPDATA"])


def install_dir() -> Path:
    return local_appdata() / "Programs" / "Arelis"


def data_root() -> Path:
    return local_appdata() / "Arelis"


def state_dir() -> Path:
    return data_root() / "data"


def backups_dir() -> Path:
    return local_appdata() / "Arelis-backups"


def repo_init_path() -> Path:
    return REPO / "arelis" / "__init__.py"


def tree_init_path() -> Path:
    return (
        REPO
        / "win-installer"
        / "dist"
        / "Arelis"
        / "Lib"
        / "site-packages"
        / "arelis"
        / "__init__.py"
    )


def tree_backup_py() -> Path:
    return (
        REPO
        / "win-installer"
        / "dist"
        / "Arelis"
        / "Lib"
        / "site-packages"
        / "arelis"
        / "backup.py"
    )


def installed_backup_py() -> Path:
    return install_dir() / "Lib" / "site-packages" / "arelis" / "backup.py"


def find_iscc() -> Path | None:
    import shutil as sh

    found = sh.which("ISCC.exe") or sh.which("iscc")
    if found:
        return Path(found)
    parents = (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
    )
    for parent in parents:
        if not parent.is_dir():
            continue
        for directory in sorted(parent.glob("Inno Setup*"), reverse=True):
            candidate = directory / "ISCC.exe"
            if candidate.is_file():
                return candidate
    return None


def run_logged(
    cmd: list[str],
    log_path: Path,
    *,
    cwd: Path | None = None,
    timeout: float | None = None,
) -> int:
    _ensure_out()
    say(" ".join(cmd))
    handle = log_path.open("w", encoding="utf-8", errors="replace")

    def _pump(stream: Any) -> None:
        try:
            for line in stream:
                handle.write(line)
                handle.flush()
                print(line, end="", flush=True)
        finally:
            handle.close()

    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    reader = threading.Thread(target=_pump, args=(proc.stdout,), daemon=True)
    reader.start()
    reader.join(timeout)
    if reader.is_alive():
        kill_tree(proc.pid)
        reader.join(30)
        proc.wait(timeout=30)
        return 124
    return int(proc.wait(timeout=30))


def base_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("ARELIS_DATA_DIR", None)
    env.pop("PYTHONPATH", None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    if extra:
        env.update(extra)
    return env


def kill_tree(pid: int) -> None:
    if pid <= 0:
        return
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )


def run_installed(
    args: list[str],
    *,
    timeout: float,
    env_extra: dict[str, str] | None = None,
    log_stem: str | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [str(install_dir() / "python.exe"), "-I", *args]
    proc = subprocess.Popen(
        cmd,
        cwd=str(install_dir()),
        env=base_env(env_extra),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        code = int(proc.returncode or 0)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc.pid)
        stdout, stderr = proc.communicate(timeout=30)
        code = 124
    if log_stem:
        _ensure_out()
        (OUT / f"{log_stem}-stdout.txt").write_text(stdout or "", encoding="utf-8")
        (OUT / f"{log_stem}-stderr.txt").write_text(stderr or "", encoding="utf-8")
    if timed_out:
        stderr = (stderr or "") + "\nTIMEOUT\n"
    return subprocess.CompletedProcess(cmd, code, stdout or "", stderr or "")


def write_child(name: str) -> Path:
    _ensure_out()
    path = OUT / name
    path.write_text(compiled_child_scripts()[name], encoding="utf-8", newline="\n")
    return path


def installed_version_line() -> str:
    done = run_installed(["-m", "arelis", "--version"], timeout=90, log_stem="version")
    text = ((done.stdout or "") + "\n" + (done.stderr or "")).strip()
    if done.returncode != 0:
        raise RuntimeError(f"--version failed ({done.returncode}): {text}")
    return (done.stdout or "").strip()


def display_version() -> str:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        value, _kind = winreg.QueryValueEx(key, "DisplayVersion")
    return str(value)


def uninstall_key_present() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY):
            return True
    except OSError:
        return False


def start_menu_dir() -> Path:
    return (
        Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Arelis"
    )


def process_image(pid: int) -> str:
    if not _is_windows() or pid <= 0:
        return ""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def listening_pids(port: int) -> list[int]:
    done = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )
    found: list[int] = []
    for line in (done.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        if parts[3].upper() != "LISTENING":
            continue
        local = parts[1]
        if local.startswith("["):
            _host, _sep, port_text = local.rpartition("]:")
        else:
            _host, _sep, port_text = local.rpartition(":")
        if port_text.isdigit() and int(port_text) == port and parts[-1].isdigit():
            found.append(int(parts[-1]))
    return found


def install_is_listening(port: int) -> list[int]:
    root = str(install_dir().resolve()).lower()
    owned: list[int] = []
    for pid in listening_pids(port):
        image = process_image(pid).lower()
        if image.startswith(root):
            owned.append(pid)
    return owned


def pids_under(root: Path) -> list[int]:
    if not _is_windows() or not root.exists():
        return []
    prefix = str(root.resolve()).lower()
    script = OUT / "_pids.ps1"
    _ensure_out()
    script.write_text(
        "\n".join(
            [
                f"$root = '{prefix}'",
                "Get-CimInstance Win32_Process | ForEach-Object {",
                "  $path = $_.ExecutablePath",
                "  if ($path -and $path.ToLower().StartsWith($root)) { $_.ProcessId }",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    done = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )
    pids = []
    for line in (done.stdout or "").splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def pids_named(exe_name: str) -> list[int]:
    script = OUT / "_named.ps1"
    _ensure_out()
    # The name is one of our setup filenames, not user input.
    script.write_text(
        "\n".join(
            [
                f"$name = '{exe_name}'",
                "$suffix = '\\' + $name",
                "Get-CimInstance Win32_Process | ForEach-Object {",
                "  $path = $_.ExecutablePath",
                "  if ($_.Name -eq $name -or ($path -and $path.EndsWith($suffix))) { $_.ProcessId }",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    done = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )
    pids = []
    for line in (done.stdout or "").splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def stop_install_processes() -> None:
    for pid in pids_under(install_dir()):
        kill_tree(pid)


def silent_install(setup: Path, log_name: str) -> int:
    log_path = OUT / log_name
    cmd = [
        str(setup),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-",
        "/CURRENTUSER",
        f"/LOG={log_path}",
    ]
    say("install " + setup.name)
    done = subprocess.run(cmd, check=False, timeout=INSTALL_TIMEOUT_S)
    return int(done.returncode)


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "arelis-upgrade-path"})
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with (
                urllib.request.urlopen(request, timeout=120) as response,
                dest.open("wb") as handle,
            ):
                shutil.copyfileobj(response, handle)
            return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            say(f"download attempt {attempt} failed: {exc}")
            time.sleep(5 * attempt)
    raise RuntimeError(f"download failed: {url}: {last_error}")


def unblock(path: Path) -> None:
    script = OUT / "_unblock.ps1"
    _ensure_out()
    script.write_text(
        "param([string]$Path)\nUnblock-File -LiteralPath $Path\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            str(path),
        ],
        check=False,
        timeout=30,
    )


def fetch_published() -> Path:
    base = f"https://github.com/sAnct1x/Arelis/releases/download/{PUBLISHED_TAG}"
    exe = INSTALLERS / f"published-{PUBLISHED_SETUP}"
    sidecar = INSTALLERS / f"published-{PUBLISHED_SETUP}.sha256"
    download(f"{base}/{PUBLISHED_SETUP}", exe)
    download(f"{base}/{PUBLISHED_SETUP}.sha256", sidecar)
    digest, _name = parse_sha256_line(sidecar.read_text(encoding="utf-8"))
    got = sha256_file(exe)
    if got != digest:
        raise RuntimeError(f"published installer hash mismatch: {got} != {digest}")
    unblock(exe)
    (OUT / "published-sha256.txt").write_text(f"{got}  {PUBLISHED_SETUP}\n", encoding="ascii")
    return exe


def config_text(workspace: Path) -> str:
    quoted = json.dumps(str(workspace))
    return "\n".join(
        [
            "updates:",
            "  check: false",
            "voice:",
            "  enabled: false",
            "  stt:",
            "    enabled: false",
            "    allow_download: false",
            "  tts:",
            "    enabled: false",
            "    allow_download: false",
            "location:",
            "  enabled: false",
            "presence:",
            "  ipc_enabled: false",
            "  close_to_tray: false",
            "  core_tray: false",
            "agent:",
            "  auto_lessons: false",
            "tools:",
            "  email:",
            "    enabled: false",
            "  sms:",
            "    enabled: false",
            "    inbound:",
            "      ingest:",
            "        enabled: false",
            "memory:",
            "  docs:",
            "    enabled: false",
            "  mail:",
            "    enabled: false",
            "ui:",
            "  theme: filament",
            "models:",
            '  fast: "qwen3.5:9b"',
            '  research: "qwen3.5:9b"',
            "workspace:",
            "  roots:",
            f"    - {quoted}",
            "",
        ]
    )


def seed_files() -> None:
    state = state_dir()
    state.mkdir(parents=True, exist_ok=True)
    workspace = data_root() / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    marker = {
        "version": 1,
        "workspace_root": str(workspace),
        "answered_at": now,
        "model_setup": {"complete": True, "tag": "qwen3.5:9b", "completed_at": now},
    }
    (state / "first-run.json").write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    (state / "config.local.yaml").write_text(config_text(workspace), encoding="utf-8")
    (state / "rooms.yaml").write_text('rooms: {}\nlast_active: ""\n', encoding="utf-8")
    (state / "contacts.yaml").write_text(
        "\n".join(
            [
                "contacts:",
                "  fixture:",
                "    name: Upgrade Fixture",
                '    phone: ""',
                '    email: ""',
                "    aliases: []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (state / "profile.yaml").write_text(
        "\n".join(
            [
                "user:",
                "  name: Upgrade Fixture",
                "  answer_style: short",
                "location:",
                "  city: Fixture City",
                '  region: ""',
                '  country: ""',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (state / "lessons.yaml").write_text("lessons: []\n", encoding="utf-8")
    (state / "secrets.yaml").write_text(f"token: {SENTINEL}\n", encoding="utf-8")


def seed_memory() -> subprocess.CompletedProcess[str]:
    script = write_child("seed_memory.py")
    return run_installed(
        ["-u", str(script), MARKER],
        timeout=120,
        log_stem="seed-memory",
    )


def inspect_state(stem: str) -> dict[str, str]:
    script = write_child("inspect_state.py")
    done = run_installed(
        ["-u", str(script), MARKER],
        timeout=120,
        log_stem=stem,
    )
    info: dict[str, str] = {"exit": str(done.returncode)}
    for line in (done.stdout or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key.strip()] = value.strip()
    info["stderr"] = (done.stderr or "")[-1500:]
    return info


def pre_folders() -> list[str]:
    root = backups_dir()
    if not root.is_dir():
        return []
    names = [
        path.name
        for path in root.iterdir()
        if path.is_dir() and path.name.startswith("pre-") and ".partial" not in path.name
    ]
    return sorted(names)


def backup_problems() -> list[str]:
    return audit_backup_folder(backups_dir(), data_root())


def marker_in_file(path: Path) -> bool:
    if not path.is_file():
        return False
    return MARKER.encode("utf-8") in path.read_bytes()


def sentinel_in_tree(root: Path) -> bool:
    if not root.exists():
        return False
    needle = SENTINEL.encode("utf-8")
    for path in root.rglob("*"):
        if path.is_file() and needle in path.read_bytes():
            return True
    return False


def headless(stem: str) -> tuple[int, str]:
    script = write_child("headless_launch.py")
    stdout_path = OUT / f"{stem}-stdout.txt"
    stderr_path = OUT / f"{stem}-stderr.txt"
    env = base_env(
        {
            "QT_QPA_PLATFORM": "offscreen",
            "ARELIS_ALLOW_OFFSCREEN": "1",
        }
    )
    cmd = [str(install_dir() / "python.exe"), "-I", "-u", str(script)]
    stdout = stdout_path.open("w", encoding="utf-8", errors="replace")
    stderr = stderr_path.open("w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        cmd,
        cwd=str(install_dir()),
        env=env,
        stdout=stdout,
        stderr=stderr,
    )
    deadline = time.time() + 120
    bound: list[int] = []
    reached = False
    try:
        while time.time() < deadline:
            text = _tail(stdout_path, limit=8000)
            if "headless_reached_exec" in text:
                reached = True
            bound = install_is_listening(8766)
            if bound:
                break
            if proc.poll() is not None:
                break
            time.sleep(0.25)
        if proc.poll() is None:
            kill_tree(proc.pid)
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                pass
            code = 124
        else:
            code = int(proc.returncode or 0)
    finally:
        stdout.close()
        stderr.close()
    detail = (
        f"exit={code} reached={reached} port8766={bound or 'clear'} "
        f"stderr={_tail(stderr_path, limit=500)!r}"
    )
    if bound:
        return 1, detail
    if code != 0 or not reached:
        return 1, detail
    return 0, detail


def wait_for_version(version: str, setup_name: str) -> str:
    deadline = time.time() + INSTALL_TIMEOUT_S
    last = ""
    while time.time() < deadline:
        if pids_named(setup_name):
            time.sleep(5)
            continue
        # The setup process has exited. Stop the relaunch it may have started
        # before asking the new tree what version it is.
        stop_install_processes()
        try:
            last = installed_version_line()
        except Exception as exc:
            last = f"error: {exc}"
            time.sleep(3)
            continue
        if version_line_has(last, version):
            return last
        time.sleep(3)
    raise TimeoutError(f"version did not become {version}; last={last}")


def assert_repo_untouched(before: bytes) -> str | None:
    after = repo_init_path().read_bytes()
    if after != before:
        return "arelis/__init__.py on the checkout changed"
    return None


def build_pair(checkout_version: str, next_version: str) -> tuple[Path, Path] | int:
    iscc = find_iscc()
    if iscc is None:
        return fail("inno-setup", "ISCC.exe was not found")
    record("inno-setup", "PASS", str(iscc))
    code = run_logged(
        [sys.executable, "-u", str(REPO / "win-installer" / "build.py")],
        OUT / "build-current.log",
        cwd=REPO,
        timeout=BUILD_TIMEOUT_S,
    )
    if code != 0:
        return fail("build-current", f"build.py exited {code}; see build-current.log")
    current_name = f"Arelis-{checkout_version}-win64-setup.exe"
    current_built = REPO / "win-installer" / "dist" / current_name
    if not current_built.is_file():
        found = sorted((REPO / "win-installer" / "dist").glob("*-setup.exe"))
        return fail("build-current", f"missing {current_name}; found {[p.name for p in found]}")
    current = INSTALLERS / f"current-{current_name}"
    shutil.copy2(current_built, current)
    record(
        "build-current",
        "PASS",
        f"{current_name} sha256={sha256_file(current)[:12]}",
    )
    if not tree_init_path().is_file():
        return fail("build-next", f"built tree has no {tree_init_path()}")
    try:
        bump_tree_version(tree_init_path(), next_version, REPO)
    except Exception as exc:
        return fail("build-next", f"version bump failed: {exc}")
    tree_python = REPO / "win-installer" / "dist" / "Arelis" / "python.exe"
    probe = subprocess.run(
        [str(tree_python), "-c", "import arelis; print(arelis.__version__)"],
        cwd=str(tree_python.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
    )
    probed = (probe.stdout or "").strip()
    if probe.returncode != 0 or probed != next_version:
        return fail(
            "build-next",
            f"tree version probe {probed!r} exit={probe.returncode} stderr={probe.stderr!r}",
        )
    code = run_logged(
        [sys.executable, "-u", str(REPO / "win-installer" / "build.py"), "--installer-only"],
        OUT / "build-next.log",
        cwd=REPO,
        timeout=BUILD_TIMEOUT_S,
    )
    if code != 0:
        return fail("build-next", f"build.py --installer-only exited {code}; see build-next.log")
    next_name = f"Arelis-{next_version}-win64-setup.exe"
    nxt_built = REPO / "win-installer" / "dist" / next_name
    if not nxt_built.is_file():
        found = sorted((REPO / "win-installer" / "dist").glob("*-setup.exe"))
        return fail("build-next", f"missing {next_name}; found {[p.name for p in found]}")
    nxt = INSTALLERS / f"next-{next_name}"
    shutil.copy2(nxt_built, nxt)
    record("build-next", "PASS", f"{next_name} sha256={sha256_file(nxt)[:12]}")
    return current, nxt


def block_backups() -> Path | None:
    """Replace the backups folder with a file so the real copy cannot start.

    The previous folder is renamed aside and put back by ``restore_backups``.
    """
    live = backups_dir()
    held = live.parent / "Arelis-backups.held"
    if held.exists():
        shutil.rmtree(held) if held.is_dir() else held.unlink()
    if live.exists():
        live.rename(held)
    else:
        held = None
    live.write_text("blocked\n", encoding="utf-8")
    return held


def restore_backups(held: Path | None) -> None:
    live = backups_dir()
    if live.is_file():
        live.unlink()
    elif live.is_dir():
        shutil.rmtree(live)
    if held is not None and held.exists():
        held.rename(live)


def cmd_run() -> int:
    if not _is_windows():
        print("This upgrade path runs on Windows.", file=sys.stderr)
        return 2
    _ensure_out()
    checkout_before = repo_init_path().read_bytes()
    try:
        checkout_version = version_assignment(checkout_before.decode("utf-8"))
        next_version = next_patch_version(checkout_version)
    except ValueError as exc:
        return fail("checkout-version", str(exc))
    record(
        "checkout-version",
        "INFO",
        f"real={checkout_version} fake_next={next_version} published={PUBLISHED_TAG}",
    )
    try:
        published = fetch_published()
    except Exception as exc:
        return fail("download-v0.3.0", str(exc))
    record("download-v0.3.0", "PASS", f"{published.name} sha256={sha256_file(published)[:12]}")

    built = build_pair(checkout_version, next_version)
    if isinstance(built, int):
        return built
    current_setup, next_setup = built
    untouched = assert_repo_untouched(checkout_before)
    if untouched:
        return fail("checkout-version-untouched", untouched)
    record("checkout-version-untouched", "PASS", "arelis/__init__.py was not edited")

    tree_hash = sha256_file(tree_backup_py()) if tree_backup_py().is_file() else ""
    stop_install_processes()
    code = silent_install(published, "setup-published.log")
    if code != 0:
        return fail(
            "install-v0.3.0", f"exit {code}; log tail: {_tail(OUT / 'setup-published.log')}"
        )
    try:
        published_line = installed_version_line()
    except Exception as exc:
        return fail("install-v0.3.0", str(exc))
    if not version_line_has(published_line, "0.3.0"):
        return fail("install-v0.3.0", f"unexpected version {published_line!r}")
    published_backup = installed_backup_py().read_text(encoding="utf-8")
    if "pre_upgrade_backups_dir" in published_backup:
        return fail(
            "install-v0.3.0",
            "published v0.3.0 already has the sibling backup helper; the baseline moved",
        )
    record("install-v0.3.0", "PASS", published_line)

    seed_files()
    seeded = seed_memory()
    if seeded.returncode != 0:
        return fail("seed-data", f"exit {seeded.returncode}; stderr={seeded.stderr[-800:]!r}")
    if not marker_in_file(state_dir() / "memory.db"):
        return fail("seed-data", "memory.db does not contain the marker")
    if SENTINEL.encode("utf-8") not in (state_dir() / "secrets.yaml").read_bytes():
        return fail("seed-data", "secrets.yaml is missing the fake token")
    snap_seed = snapshot_files(state_dir())
    if "MISSING" in snap_seed.values():
        return fail("seed-data", f"incomplete seed: {snap_seed}")
    record("seed-data", "PASS", "memory marker, settings files, fake secrets.yaml")

    code = silent_install(current_setup, "setup-current.log")
    if code != 0:
        return fail(
            "upgrade-to-current", f"exit {code}; log tail: {_tail(OUT / 'setup-current.log')}"
        )
    try:
        current_line = installed_version_line()
        shown = display_version()
    except Exception as exc:
        return fail("upgrade-to-current", str(exc))
    installed_hash = sha256_file(installed_backup_py())
    sibling = "pre_upgrade_backups_dir" in installed_backup_py().read_text(encoding="utf-8")
    # Main is still 0.3.0, so the version string matches the published installer.
    # The backup.py hash is what shows this tree replaced it.
    version_ok = version_line_has(current_line, checkout_version) and shown == checkout_version
    if not version_ok or not sibling or installed_hash != tree_hash:
        return fail(
            "upgrade-to-current",
            f"line={current_line!r} display={shown!r} sibling={sibling} "
            f"backup_py_match={installed_hash == tree_hash}",
        )
    record(
        "upgrade-to-current",
        "PASS",
        f"{current_line}; display {shown}; backup.py matches this build"
        + (
            "; version string is still the published number, file hash shows the new tree"
            if checkout_version == "0.3.0"
            else ""
        ),
    )
    snap_upgraded = snapshot_files(state_dir())
    drifted = same_hashes(snap_seed, snap_upgraded, TRACKED)
    if drifted:
        return fail("data-intact-after-inno", ", ".join(drifted))
    record("data-intact-after-inno", "PASS", "tracked files byte-identical across the installer")

    looked = inspect_state("inspect-current")
    if (
        looked.get("exit") != "0"
        or looked.get("fact_hit") != "True"
        or looked.get("message_hit") != "True"
    ):
        return fail("data-readable", f"{looked}")
    if looked.get("theme") != "filament" or looked.get("updates_check") != "False":
        return fail("data-readable", f"settings not applied: {looked}")
    if looked.get("voice_enabled") != "False" or looked.get("location_enabled") != "False":
        return fail("data-readable", f"voice/location not off: {looked}")
    if looked.get("ipc_enabled") != "False":
        return fail("data-readable", f"ipc not off: {looked}")
    record("data-readable", "PASS", "marker, chat line, theme, voice/location/update/ipc off")

    head_code, head_detail = headless("headless-current")
    if head_code != 0:
        return fail("headless-start", head_detail)
    record("headless-start", "PASS", head_detail)
    record("port-8766", "PASS", "installed process did not listen on 8766")

    looked_after = inspect_state("inspect-after-headless")
    if looked_after.get("fact_hit") != "True" or looked_after.get("message_hit") != "True":
        return fail("data-after-headless", f"marker missing after start: {looked_after}")
    if sha256_file(state_dir() / "secrets.yaml") != snap_seed["secrets.yaml"]:
        return fail("data-after-headless", "secrets.yaml changed when the app started")
    record("data-after-headless", "PASS", "marker still readable; secrets.yaml unchanged")

    keep_script = write_child("backup_keep.py")
    kept = run_installed(
        ["-u", str(keep_script), "ci.1", "ci.2", "ci.3"],
        timeout=180,
        log_stem="backup-keep",
    )
    if kept.returncode != 0:
        return fail("backup-keep-two", f"exit {kept.returncode}; stderr={kept.stderr[-800:]!r}")
    names = pre_folders()
    problems = backup_problems()
    if names != ["pre-ci.2", "pre-ci.3"] or problems:
        return fail("backup-keep-two", f"folders={names} problems={problems}")
    record(
        "backup-keep-two",
        "PASS",
        "three copies, only pre-ci.2 and pre-ci.3 remain, beside the data folder, no secrets",
    )

    held = block_backups()
    try:
        failure_script = write_child("failure_probe.py")
        result_path = OUT / "failure-result.json"
        probed = run_installed(
            ["-u", str(failure_script), str(next_setup), str(result_path)],
            timeout=150,
            env_extra={
                "QT_QPA_PLATFORM": "offscreen",
                "ARELIS_ALLOW_OFFSCREEN": "1",
            },
            log_stem="failure-probe",
        )
        if result_path.is_file():
            failure = json.loads(result_path.read_text(encoding="utf-8"))
        else:
            failure = {"error": "no result file", "stderr": probed.stderr[-800:]}
    finally:
        restore_backups(held)
    calls = failure.get("start_calls") or []
    if not failure.get("direct_backup_none") or calls or not failure.get("install_started"):
        return fail(
            "backup-failure-stops-update",
            f"result={failure} exit={probed.returncode} stderr={probed.stderr[-600:]!r}",
        )
    try:
        still = installed_version_line()
    except Exception as exc:
        return fail(
            "backup-failure-stops-update", f"version read failed after blocked backup: {exc}"
        )
    if not version_line_has(still, checkout_version):
        return fail("backup-failure-stops-update", f"version changed anyway: {still!r}")
    if pre_folders() != ["pre-ci.2", "pre-ci.3"] or backup_problems():
        return fail(
            "backup-failure-stops-update",
            f"backup folder disturbed: {pre_folders()} {backup_problems()}",
        )
    record(
        "backup-failure-stops-update",
        "PASS",
        "real backup returned no folder; update prompt did not start the installer",
    )

    snap_before_next = snapshot_files(state_dir())
    updater = write_child("updater_launch.py")
    launched = run_installed(
        ["-u", str(updater), str(next_setup)],
        timeout=180,
        log_stem="updater-launch",
    )
    if launched.returncode != 0:
        return fail(
            "updater-backup-and-install",
            f"exit {launched.returncode}; stdout={launched.stdout[-400:]!r} "
            f"stderr={launched.stderr[-800:]!r}",
        )
    try:
        next_line = wait_for_version(next_version, next_setup.name)
        shown_next = display_version()
    except Exception as exc:
        stop_install_processes()
        return fail("updater-backup-and-install", str(exc))
    stop_install_processes()
    if not version_line_has(next_line, next_version) or shown_next != next_version:
        return fail(
            "updater-backup-and-install",
            f"line={next_line!r} display={shown_next!r}",
        )
    record(
        "updater-backup-and-install",
        "PASS",
        f"{next_line}; display {shown_next}; real start_installer",
    )
    snap_after_next = snapshot_files(state_dir())
    # The pre-upgrade copy can checkpoint memory.db. The installer must not
    # change the yaml records. The marker is the memory check.
    yaml_names = tuple(name for name in TRACKED if name != "memory.db")
    drifted = same_hashes(snap_before_next, snap_after_next, yaml_names)
    if drifted:
        return fail("data-intact-after-next", ", ".join(drifted))
    if not marker_in_file(state_dir() / "memory.db"):
        return fail("data-intact-after-next", "marker missing from memory.db")
    record(
        "data-intact-after-next",
        "PASS",
        "settings files byte-identical across the second installer; memory marker kept",
    )

    expected_pre = f"pre-{checkout_version}"
    names = pre_folders()
    problems = backup_problems()
    pre_dir = backups_dir() / expected_pre
    copied_yaml = (
        "rooms.yaml",
        "contacts.yaml",
        "profile.yaml",
        "lessons.yaml",
        "config.local.yaml",
    )
    yaml_mismatch = [
        name
        for name in copied_yaml
        if (state_dir() / name).is_file()
        and (
            not (pre_dir / name).is_file()
            or sha256_file(pre_dir / name) != sha256_file(state_dir() / name)
        )
    ]
    if (
        expected_pre not in names
        or len(names) > 2
        or problems
        or yaml_mismatch
        or not marker_in_file(pre_dir / "memory.db")
        or sentinel_in_tree(backups_dir())
    ):
        return fail(
            "backup-after-next",
            f"folders={names} problems={problems} yaml_mismatch={yaml_mismatch}",
        )
    record(
        "backup-after-next",
        "PASS",
        f"{expected_pre} beside the data folder; folders={names}; no secrets; no partial",
    )

    head_code, head_detail = headless("headless-next")
    if head_code != 0:
        return fail("headless-next", head_detail)
    record("headless-next", "PASS", head_detail)
    if sha256_file(state_dir() / "secrets.yaml") != snap_seed["secrets.yaml"]:
        return fail("headless-next", "secrets.yaml changed")
    looked_next = inspect_state("inspect-next")
    if looked_next.get("fact_hit") != "True":
        return fail("headless-next", f"marker not readable: {looked_next}")
    record("data-after-next-start", "PASS", "marker readable; secrets.yaml still unchanged")

    if not start_menu_dir().exists():
        record("start-menu-before-wipe", "INFO", "start menu folder was already absent")
    else:
        record("start-menu-before-wipe", "INFO", str(start_menu_dir()))
    stop_install_processes()
    unins = install_dir() / "unins000.exe"
    if not unins.is_file():
        return fail("uninstall-wipe", "unins000.exe is missing")
    log_path = OUT / "uninstall.log"
    done = subprocess.run(
        [
            str(unins),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/wipe=yes",
            f"/LOG={log_path}",
        ],
        check=False,
        timeout=INSTALL_TIMEOUT_S,
    )
    if done.returncode != 0:
        return fail("uninstall-wipe", f"exit {done.returncode}; log tail: {_tail(log_path)}")
    deadline = time.time() + 60
    while install_dir().exists() and time.time() < deadline:
        time.sleep(1)
    if install_dir().exists() or uninstall_key_present() or data_root().exists():
        return fail(
            "uninstall-wipe",
            f"install_exists={install_dir().exists()} key={uninstall_key_present()} "
            f"data_exists={data_root().exists()}",
        )
    if start_menu_dir().exists():
        return fail("uninstall-wipe", f"start menu folder still present: {start_menu_dir()}")
    if pids_under(install_dir()):
        return fail("uninstall-wipe", "a process is still running from the install folder")
    record(
        "uninstall-wipe",
        "PASS",
        "install folder, data folder, registry key, and start menu are gone",
    )

    names = pre_folders()
    problems = backup_problems()
    if (
        expected_pre not in names
        or problems
        or not marker_in_file(backups_dir() / expected_pre / "memory.db")
        or sentinel_in_tree(backups_dir())
        or (state_dir() / "secrets.yaml").exists()
    ):
        return fail(
            "backup-survives-wipe",
            f"folders={names} problems={problems} data_still={data_root().exists()}",
        )
    record(
        "backup-survives-wipe",
        "PASS",
        f"{expected_pre} still beside where the data folder was; secrets were not in it",
    )
    untouched = assert_repo_untouched(checkout_before)
    if untouched:
        return fail("checkout-version-untouched-final", untouched)
    record("done", "PASS", "upgrade path finished")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="upgrade_path_smoke.py")
    parser.add_argument("command", nargs="?", default="run", choices=("run",))
    parser.parse_args(argv)
    try:
        return cmd_run()
    except Exception as exc:
        record("unexpected", "FAIL", f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
