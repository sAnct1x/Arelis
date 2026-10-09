"""Build an unsigned Arelis.app and wrap it in a disk image.

A real interpreter, not a frozen executable. Scheduled jobs and
``python -m arelis`` need ``-m``. The interpreter is python-build-standalone,
checked against a pinned digest, and installed at
``Arelis.app/Contents/Resources/python``.

This file only produces the app when it is run on macOS. The helpers that
write Info.plist and the launcher are pure Python so they can be tested
anywhere.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
CACHE = HERE / ".cache"
BUILD = HERE / "build"
DIST = HERE / "dist"
APP = DIST / "Arelis.app"
LOCK = HERE / "requirements-macos-arm64-cp313.txt"

PYTHON_VERSION = "3.13.16"
PYTHON_RELEASE = "20261003"
PYTHON_ARCHIVE = (
    f"cpython-{PYTHON_VERSION}+{PYTHON_RELEASE}-aarch64-apple-darwin-"
    "install_only_stripped.tar.gz"
)
# Digest from that release's SHA256SUMS. A change to what we ship is a diff.
PYTHON_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    f"{PYTHON_RELEASE}/{PYTHON_ARCHIVE}"
)
PYTHON_SHA256 = "9e01f63bbb08576cd9c8bc2d0564d098cb30c8453a0cd4bcf6aef458f6d2a147"

BUNDLE_ID = "app.arelis"
MIN_SYSTEM = "13.0"
SDIST_ONLY = ("jieba",)

# 3.13, not 3.14: onnxruntime publishes no macOS cp314 wheel, and voice is
# part of the installer extra. Qt stays on 6.11.2, the same pin as Windows,
# which is under the PySide6<6.12 cap in pyproject.toml.


def say(message: str) -> None:
    print(message, flush=True)


def run(command: list[str], what: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        command, capture_output=True, text=True, cwd=str(cwd) if cwd else None
    )
    if result.returncode != 0:
        sys.stderr.write(f"\n{what} failed (exit {result.returncode}).\n\n")
        sys.stderr.write((result.stdout or "").strip() + "\n")
        sys.stderr.write((result.stderr or "").strip() + "\n")
        raise SystemExit(result.returncode)
    return result.stdout


def package_version() -> str:
    text = (REPO_ROOT / "arelis" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("could not read the package version")
    return match.group(1)


def disk_image_name(version: str) -> str:
    return f"Arelis-{version}.dmg"


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def info_plist_xml(version: str) -> str:
    """Info.plist for the unsigned app. LSUIElement false keeps a Dock icon."""
    safe = _xml(version)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>Arelis</string>
  <key>CFBundleDisplayName</key>
  <string>Arelis</string>
  <key>CFBundleIdentifier</key>
  <string>{BUNDLE_ID}</string>
  <key>CFBundleVersion</key>
  <string>{safe}</string>
  <key>CFBundleShortVersionString</key>
  <string>{safe}</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleExecutable</key>
  <string>Arelis</string>
  <key>LSMinimumSystemVersion</key>
  <string>{MIN_SYSTEM}</string>
  <key>LSUIElement</key>
  <false/>
  <key>NSMicrophoneUsageDescription</key>
  <string>Arelis uses the microphone so you can talk to her.</string>
  <key>NSCameraUsageDescription</key>
  <string>Arelis uses the camera when you ask her to look.</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
"""


def launcher_script() -> str:
    """Contents/MacOS/Arelis. Runs the bundled interpreter with -m arelis."""
    return """#!/bin/bash
here="$(cd "$(dirname "$0")" && pwd)"
py="$here/../Resources/python/bin/python3"
if [ ! -x "$py" ]; then
  echo "Arelis could not find its Python." >&2
  exit 1
fi
export PYTHONNOUSERSITE=1
exec "$py" -m arelis "$@"
"""


def qt_major_minor_under_cap(lock_text: str, cap: tuple[int, int] = (6, 12)) -> bool:
    """True when the lock's PySide6 pin is older than ``cap``."""
    version = ""
    for raw in lock_text.splitlines():
        line = raw.strip()
        if not line.startswith("PySide6=="):
            continue
        pin = line.split("--hash", 1)[0].strip()
        version = pin.split("==", 1)[1]
        break
    if not version:
        return False
    parts = version.split(".")
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0
    return (major, minor) < cap


def digest_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, destination: Path, expected: str) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and digest_of(destination) == expected:
        say(f"  cached: {destination.name}")
        return destination
    say(f"  downloading {destination.name}")
    partial = destination.with_suffix(destination.suffix + ".part")
    urllib.request.urlretrieve(url, partial)
    got = digest_of(partial)
    if got != expected:
        partial.unlink(missing_ok=True)
        raise SystemExit(f"digest mismatch for {destination.name}: {got}")
    partial.replace(destination)
    return destination


def python_bin(app: Path = APP) -> Path:
    return app / "Contents" / "Resources" / "python" / "bin" / "python3"


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def lock_without_sdist_only(lock_text: str, names: tuple[str, ...] = SDIST_ONLY) -> str:
    drop = {_normalise(name) for name in names}
    lines = lock_text.splitlines()
    kept: list[str] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#"):
            kept.append(lines[index])
            index += 1
            continue
        match = re.match(r"([A-Za-z0-9._-]+)\s*==\s*", stripped)
        if match and _normalise(match.group(1)) in drop:
            index += 1
            continue
        kept.append(lines[index])
        index += 1
    return "\n".join(kept) + "\n"


def unpack_interpreter(archive: Path, app: Path) -> None:
    resources = app / "Contents" / "Resources"
    if resources.exists():
        shutil.rmtree(resources)
    resources.mkdir(parents=True)
    with tarfile.open(archive) as tar:
        tar.extractall(resources, filter="data")
    binary = python_bin(app)
    if not binary.exists():
        raise SystemExit(f"unpacked interpreter has no {binary}")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)


def install_dependencies(app: Path) -> None:
    binary = python_bin(app)
    lock_text = LOCK.read_text(encoding="utf-8")
    if not qt_major_minor_under_cap(lock_text):
        raise SystemExit("the Mac lock pins PySide6 at 6.12 or newer")

    BUILD.mkdir(parents=True, exist_ok=True)
    wheelhouse = BUILD / "sdist-wheels"
    if wheelhouse.exists():
        shutil.rmtree(wheelhouse)
    wheelhouse.mkdir(parents=True)
    for name in SDIST_ONLY:
        body = ""
        for raw in lock_text.splitlines():
            if raw.strip().lower().startswith(f"{name}=="):
                body = raw + "\n"
                break
        if not body:
            raise SystemExit(f"{name} is missing from the Mac lock")
        req = BUILD / f"requirements-{name}.txt"
        req.write_text(body, encoding="utf-8", newline="\n")
        run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--require-hashes",
                "--no-binary",
                name,
                "-r",
                str(req),
                "--wheel-dir",
                str(wheelhouse),
            ],
            f"Building a wheel for {name}",
        )
        wheels = sorted(wheelhouse.glob(f"{name}-*.whl"))
        if len(wheels) != 1 or not wheels[0].name.endswith("-py3-none-any.whl"):
            raise SystemExit(f"{name} did not build to one pure wheel: {wheels}")
        run(
            [
                str(binary),
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-index",
                "--find-links",
                str(wheelhouse),
                "--no-warn-script-location",
                f"{name}=={body.split('==', 1)[1].split()[0]}",
            ],
            f"Installing {name} into the app",
        )

    filtered = BUILD / "requirements-binary.txt"
    filtered.write_text(lock_without_sdist_only(lock_text), encoding="utf-8", newline="\n")
    run(
        [
            str(binary),
            "-m",
            "pip",
            "install",
            "--require-hashes",
            "--only-binary",
            ":all:",
            "--no-warn-script-location",
            "-r",
            str(filtered),
        ],
        "Installing the locked dependency set",
    )


def install_arelis(app: Path) -> None:
    wheelhouse = BUILD / "wheel"
    if wheelhouse.exists():
        shutil.rmtree(wheelhouse)
    wheelhouse.mkdir(parents=True)
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(wheelhouse),
            str(REPO_ROOT),
        ],
        "Building the arelis wheel",
    )
    wheels = sorted(wheelhouse.glob("arelis-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected one arelis wheel, found {wheels}")
    run(
        [
            str(python_bin(app)),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-warn-script-location",
            str(wheels[0]),
        ],
        "Installing arelis into the app",
    )


def drop_absolute_launchers(app: Path) -> None:
    """pip writes the build machine's path into script launchers. Delete those.

    The Dock launcher runs ``python3 -m arelis``, so the scripts are unused.
    A shebang that names this runner would start the wrong interpreter, or none.
    """
    prefix = app / "Contents" / "Resources" / "python"
    needle = str(prefix)
    bindir = prefix / "bin"
    if not bindir.is_dir():
        return
    for path in list(bindir.iterdir()):
        if path.name.startswith("python") or path.is_symlink():
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if needle in text:
            path.unlink()


def write_bundle_metadata(app: Path, version: str) -> None:
    contents = app / "Contents"
    macos = contents / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    (contents / "Info.plist").write_text(info_plist_xml(version), encoding="utf-8")
    launcher = macos / "Arelis"
    launcher.write_text(launcher_script(), encoding="utf-8", newline="\n")
    launcher.chmod(0o755)


def make_disk_image(app: Path, version: str) -> Path:
    stage = BUILD / "dmg-root"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    staged = stage / "Arelis.app"
    shutil.move(str(app), str(staged))
    applications = stage / "Applications"
    try:
        os.symlink("/Applications", applications)
        image = DIST / disk_image_name(version)
        if image.exists():
            image.unlink()
        run(
            [
                "hdiutil",
                "create",
                "-volname",
                "Arelis",
                "-srcfolder",
                str(stage),
                "-ov",
                "-format",
                "UDZO",
                str(image),
            ],
            "Building the disk image",
        )
        return image
    finally:
        if staged.exists():
            shutil.move(str(staged), str(app))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the unsigned Mac app.")
    parser.add_argument(
        "--no-dmg",
        action="store_true",
        help="Stop after Arelis.app. Do not run hdiutil.",
    )
    parser.add_argument(
        "--keep-tree",
        action="store_true",
        help="Reuse an existing interpreter tree instead of unpacking a clean one.",
    )
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        raise SystemExit(
            "This builds a Mac app with the interpreter that will ship, so it has "
            "to run on macOS."
        )
    if not LOCK.exists():
        raise SystemExit(f"no lock at {LOCK}. Run: python mac-installer/lock.py")

    version = package_version()
    say(f"Arelis {version}")
    if not args.keep_tree and DIST.exists():
        say(f"Clearing {DIST}...")
        shutil.rmtree(DIST)
    APP.parent.mkdir(parents=True, exist_ok=True)
    (APP / "Contents").mkdir(parents=True, exist_ok=True)

    if args.keep_tree and python_bin().exists():
        say("Keeping the existing interpreter.")
    else:
        say(f"Interpreter: CPython {PYTHON_VERSION} ({PYTHON_RELEASE})")
        archive = download(PYTHON_URL, CACHE / PYTHON_ARCHIVE, PYTHON_SHA256)
        unpack_interpreter(archive, APP)

    say("Libraries")
    install_dependencies(APP)
    install_arelis(APP)
    drop_absolute_launchers(APP)
    write_bundle_metadata(APP, version)
    say(f"App: {APP}")
    if args.no_dmg:
        return 0
    image = make_disk_image(APP, version)
    say(f"Disk image: {image}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
