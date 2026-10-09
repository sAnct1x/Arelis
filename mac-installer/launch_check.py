"""Start the built app once, headless, and fail if the window never comes up.

Mounts the disk image when one is present so the check is against the
artifact, not only the folder beside it. Uses the same bundled interpreter
the Dock launcher runs. Does not send any message.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"

PROBE = r"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["ARELIS_ALLOW_OFFSCREEN"] = "1"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

def _install_exec_hook() -> None:
    original = QApplication.exec

    def _exec(*args, **kwargs):
        app = args[0] if args else QApplication.instance()
        names = []
        title = ""
        if app is not None:
            for widget in app.allWidgets():
                names.append(type(widget).__name__)
                if type(widget).__name__ == "ArelisWindow":
                    title = widget.windowTitle()
        if "ArelisWindow" not in names:
            print("window_missing " + ",".join(sorted(set(names))), flush=True)
            sys.exit(2)
        print("window_built class=ArelisWindow title=%r" % (title,), flush=True)
        print("event_loop_ran", flush=True)
        if app is not None:
            QTimer.singleShot(300, app.quit)
        return original()

    QApplication.exec = _exec

_install_exec_hook()
from arelis.main import main
sys.exit(main([]))
"""


def seed_launch_profile(data_dir: Path) -> None:
    """Quiet settings and the first-run marker, so no setup dialog blocks."""
    state = data_dir / "data"
    state.mkdir(parents=True, exist_ok=True)
    workspace = data_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    config = "\n".join(
        [
            "models:",
            '  fast: "qwen3.5:9b"',
            '  research: "qwen3.5:9b"',
            "memory:",
            '  embed_model: "nomic-embed-text"',
            "workspace:",
            f'  roots: ["{workspace}"]',
            "agent:",
            "  confirm_browser: true",
            "  confirm_send: true",
            "  confirm_desktop: true",
            "presence:",
            "  ipc_enabled: false",
            "  ipc_port: 18766",
            "tools:",
            "  email:",
            "    enabled: false",
            "  sms:",
            "    enabled: false",
            "    inbound:",
            "      enabled: false",
            "voice:",
            "  enabled: false",
            "updates:",
            "  check: false",
            "",
        ]
    )
    (state / "config.local.yaml").write_text(config, encoding="utf-8", newline="\n")
    marker = {
        "version": 1,
        "workspace_root": str(workspace),
        "answered_at": "2026-10-08T16:55:00+00:00",
        "model_setup": {
            "complete": True,
            "tag": "qwen3.5:9b",
            "completed_at": "2026-10-08T16:55:00+00:00",
        },
    }
    (state / "first-run.json").write_text(
        json.dumps(marker, indent=2) + "\n", encoding="utf-8"
    )


def _mount(image: Path) -> Path:
    result = subprocess.run(
        ["hdiutil", "attach", "-nobrowse", "-readonly", str(image)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode or 1)
    mount = None
    for line in result.stdout.splitlines():
        marker = "/Volumes/"
        if marker not in line:
            continue
        mount = Path(line[line.index(marker) :].strip())
    if mount is None or not mount.is_dir():
        raise SystemExit(f"could not see a mount point in:\n{result.stdout}")
    return mount


def _detach(mount: Path) -> None:
    subprocess.run(
        ["hdiutil", "detach", str(mount)],
        capture_output=True,
        text=True,
        check=False,
    )


def _app_from(root: Path) -> Path:
    if root.suffix == ".app":
        return root
    found = sorted(root.glob("*.app"))
    if not found:
        found = sorted(root.rglob("*.app"))
    if len(found) != 1:
        raise SystemExit(f"expected one Arelis.app under {root}, found {found}")
    return found[0]


def prove(app: Path, timeout_s: int = 300) -> int:
    binary = app / "Contents" / "Resources" / "python" / "bin" / "python3"
    if not binary.is_file():
        sys.stderr.write(f"no bundled interpreter at {binary}\n")
        return 1
    data = Path(tempfile.mkdtemp(prefix="arelis-mac-launch-"))
    seed_launch_profile(data)
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["ARELIS_ALLOW_OFFSCREEN"] = "1"
    env["ARELIS_DATA_DIR"] = str(data)
    env["PYTHONNOUSERSITE"] = "1"
    env.pop("PYTHONPATH", None)
    print(f"launch_check interpreter={binary}", flush=True)
    print(f"launch_check data={data}", flush=True)
    try:
        done = subprocess.run(
            [str(binary), "-c", PROBE],
            cwd=str(app),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        sys.stderr.write("launch check timed out\n")
        if exc.stdout:
            sys.stdout.write(exc.stdout if isinstance(exc.stdout, str) else "")
        if exc.stderr:
            sys.stderr.write(exc.stderr if isinstance(exc.stderr, str) else "")
        return 1
    sys.stdout.write(done.stdout or "")
    sys.stderr.write(done.stderr or "")
    if done.returncode != 0:
        print(f"launch_check exit={done.returncode}", flush=True)
        return done.returncode or 1
    if "window_built class=ArelisWindow" not in (done.stdout or ""):
        print("launch_check missing window_built", flush=True)
        return 1
    if "event_loop_ran" not in (done.stdout or ""):
        print("launch_check missing event_loop_ran", flush=True)
        return 1
    print("launch_check ok", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    image = None
    apps = sorted(DIST.glob("*.dmg")) if DIST.is_dir() else []
    mount: Path | None = None
    try:
        if apps:
            image = apps[0]
            print(f"launch_check mounting {image.name}", flush=True)
            mount = _mount(image)
            app = _app_from(mount)
        else:
            built = DIST / "Arelis.app"
            if not built.is_dir():
                sys.stderr.write("no disk image and no Arelis.app to launch\n")
                return 1
            app = built
        return prove(app)
    finally:
        if mount is not None:
            _detach(mount)


if __name__ == "__main__":
    sys.exit(main())
