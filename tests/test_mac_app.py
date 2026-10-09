"""Mac app: the update is a page you open, and the bundle describes itself.

Nothing here talks to GitHub or builds a disk image. Release payloads are
fixtures. The plist text is produced by the build helper on any machine.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from packaging.version import Version

from arelis import update

ROOT = Path(__file__).resolve().parents[1]


def _build_module():
    path = ROOT / "mac-installer" / "build.py"
    spec = importlib.util.spec_from_file_location("mac_installer_build", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release() -> update.Release:
    payload = {
        "tag_name": "v0.9.0",
        "draft": False,
        "prerelease": False,
        "html_url": "https://github.com/sAnct1x/arelis/releases/tag/v0.9.0",
        "assets": [
            {
                "name": "Arelis-0.9.0-win64-setup.exe",
                "browser_download_url": "https://example.invalid/setup.exe",
                "size": 1000,
            },
            {
                "name": "Arelis-0.9.0-win64-setup.exe.sha256",
                "browser_download_url": "https://example.invalid/setup.exe.sha256",
                "size": 80,
            },
        ],
    }
    release = update.parse_release(payload)
    assert release is not None
    return release


def _mac_bundle(tmp_path: Path) -> Path:
    """A fake .app deep enough that the package sits where the real one does."""
    package = (
        tmp_path
        / "Arelis.app"
        / "Contents"
        / "Resources"
        / "python"
        / "lib"
        / "python3.13"
        / "site-packages"
        / "arelis"
    )
    package.mkdir(parents=True)
    info = tmp_path / "Arelis.app" / "Contents" / "Info.plist"
    info.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<plist><dict><key>CFBundleIdentifier</key>"
        "<string>app.arelis</string></dict></plist>\n",
        encoding="utf-8",
    )
    return package


def test_a_mac_install_may_look_for_a_newer_release(monkeypatch, tmp_path: Path) -> None:
    """An installed Mac copy is allowed to ask. It still must not download."""
    package = _mac_bundle(tmp_path)
    monkeypatch.setattr(update.sys, "platform", "darwin")
    monkeypatch.setattr(update, "is_source_checkout", lambda: False)
    monkeypatch.setattr(update, "PACKAGE_ROOT", package)
    supported, why = update.updates_supported()
    assert supported is True, why
    assert update.downloads_the_installer() is False


def test_linux_still_has_no_installer(monkeypatch) -> None:
    monkeypatch.setattr(update.sys, "platform", "linux")
    supported, why = update.updates_supported()
    assert supported is False
    assert why == "the Arelis installer is Windows-only"


def test_windows_still_downloads_the_setup_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(update.sys, "platform", "win32")
    monkeypatch.setattr(update, "is_source_checkout", lambda: False)
    monkeypatch.setattr(update, "install_root", lambda: tmp_path)
    assert update.updates_supported() == (True, "")
    assert update.downloads_the_installer() is True


def test_the_mac_window_names_the_release_page_and_does_not_download(
    qt_app, monkeypatch
) -> None:
    from PySide6.QtWidgets import QWidget

    from arelis.ui import update_prompt

    release = _release()
    assert release.version == Version("0.9.0")
    notices: list[tuple[tuple, dict]] = []
    confirms: list[object] = []
    downloads: list[object] = []

    monkeypatch.setattr(update_prompt.sys, "platform", "darwin")
    monkeypatch.setattr(
        update_prompt,
        "notice",
        lambda *args, **kwargs: notices.append((args, kwargs)),
    )
    monkeypatch.setattr(
        update_prompt,
        "confirm",
        lambda *args, **kwargs: confirms.append(args) or False,
    )
    monkeypatch.setattr(
        update_prompt,
        "download",
        lambda *args, **kwargs: downloads.append(args),
    )

    window = QWidget()
    try:
        prompt = update_prompt.UpdatePrompt(window)
        prompt._show_offer(release)
    finally:
        window.deleteLater()
        qt_app.processEvents()

    assert confirms == []
    assert downloads == []
    assert len(notices) == 1
    text = " ".join(str(part) for part in notices[0][0])
    text += " " + str(notices[0][1].get("detail", ""))
    assert release.page_url in text
    assert "available" in text.lower()


def test_windows_still_asks_before_it_installs(qt_app, monkeypatch) -> None:
    from PySide6.QtWidgets import QWidget

    from arelis.ui import update_prompt

    release = _release()
    confirms: list[dict] = []
    downloads: list[object] = []

    monkeypatch.setattr(update_prompt.sys, "platform", "win32")
    monkeypatch.setattr(
        update_prompt,
        "confirm",
        lambda *args, **kwargs: confirms.append(kwargs) or False,
    )
    monkeypatch.setattr(
        update_prompt,
        "download",
        lambda *args, **kwargs: downloads.append(args),
    )

    window = QWidget()
    try:
        prompt = update_prompt.UpdatePrompt(window)
        prompt._show_offer(release)
    finally:
        window.deleteLater()
        qt_app.processEvents()

    assert downloads == []
    assert confirms
    assert confirms[0].get("confirm_text") == "Download and install"


def test_info_plist_names_the_app_and_the_permissions() -> None:
    build = _build_module()
    text = build.info_plist_xml("0.3.1")
    assert "app.arelis" in text
    assert ">0.3.1<" in text
    assert "LSMinimumSystemVersion" in text
    assert "NSMicrophoneUsageDescription" in text
    assert "NSCameraUsageDescription" in text
    assert "<key>LSUIElement</key>" in text
    assert "<false/>" in text
    assert "\u2014" not in text
    assert "\u2013" not in text


def test_the_launcher_runs_the_bundled_interpreter() -> None:
    build = _build_module()
    script = build.launcher_script()
    assert "-m arelis" in script
    assert "Resources/python/bin/python3" in script


def test_the_disk_image_is_named_from_the_version() -> None:
    build = _build_module()
    assert build.disk_image_name("0.3.1") == "Arelis-0.3.1.dmg"


def _launch_module():
    path = ROOT / "mac-installer" / "launch_check.py"
    spec = importlib.util.spec_from_file_location("mac_installer_launch_check", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_launch_profile_keeps_the_first_run_quiet(tmp_path: Path) -> None:
    launch = _launch_module()
    launch.seed_launch_profile(tmp_path)
    text = (tmp_path / "data" / "config.local.yaml").read_text(encoding="utf-8")
    assert "ipc_enabled: false" in text
    assert "ipc_port: 18766" in text
    assert "check: false" in text
    marker = (tmp_path / "data" / "first-run.json").read_text(encoding="utf-8")
    assert '"complete": true' in marker


def test_qt_stays_under_the_same_cap() -> None:
    build = _build_module()
    lock = (ROOT / "mac-installer" / "requirements-macos-arm64-cp313.txt").read_text(
        encoding="utf-8"
    )
    assert build.qt_major_minor_under_cap(lock, cap=(6, 12)) is True
    bumped = lock.replace("PySide6==6.11.2", "PySide6==6.12.0")
    assert build.qt_major_minor_under_cap(bumped, cap=(6, 12)) is False
