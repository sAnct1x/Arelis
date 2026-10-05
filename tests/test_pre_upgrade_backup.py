"""Pre-upgrade backup copies only an allowlist, and never secrets.yaml."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from arelis import backup
from arelis.memory.backup import prune_memory_backups
from arelis.paths import DATA_DIR_ENV, pre_upgrade_backups_dir, state_dir, user_data_dir
from arelis.ui import update_prompt

SENTINEL = "p08-secrets-sentinel-do-not-copy-7f3a1c"


def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))
    root = state_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_sqlite(path: Path, body: str = "remember this") -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
        conn.execute("INSERT INTO notes (body) VALUES (?)", (body,))
        conn.commit()
    finally:
        conn.close()


def _seed_records(root: Path) -> None:
    _write_sqlite(root / "memory.db")
    (root / "rooms.yaml").write_text("rooms: []\n", encoding="utf-8")
    (root / "jobs.yaml").write_text("jobs: []\n", encoding="utf-8")
    (root / "config.local.yaml").write_text("ui: {}\n", encoding="utf-8")
    (root / "secrets.yaml").write_text(f"mail_password: {SENTINEL}\n", encoding="utf-8")
    (root / "sms_pair.json").write_text('{"secret": "pair-token"}\n', encoding="utf-8")
    (root / "sms_threads.json").write_text("[]\n", encoding="utf-8")
    (root / "action_ledger.jsonl").write_text("{}\n", encoding="utf-8")
    profile = root / "browser-profile"
    profile.mkdir()
    (profile / "Cookies").write_bytes(b"cookie-bytes")
    media = root / "sms_media"
    media.mkdir()
    (media / "clip.bin").write_bytes(b"clip")


def test_pre_upgrade_backup_lands_outside_the_wipe_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A successful copy must not sit under records or the uninstall wipe root."""
    root = _isolate_state(monkeypatch, tmp_path)
    (root / "rooms.yaml").write_text("rooms: []\n", encoding="utf-8")

    dest = backup.backup_before_upgrade("0.2.9")
    assert dest is not None
    assert dest.name == "pre-0.2.9"
    dest_resolved = dest.resolve()
    assert not dest_resolved.is_relative_to(root.resolve())
    assert not dest_resolved.is_relative_to(state_dir().resolve())
    assert not dest_resolved.is_relative_to(user_data_dir().resolve())
    assert (root / "backups" / "pre-0.2.9").exists() is False


def test_failed_backup_stops_the_upgrade(
    qt_app, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtWidgets import QWidget

    order: list[str] = []
    notices: list[str] = []

    def fail_backup(from_version: str, to_version: str | None = None) -> None:
        order.append("backup")
        return None

    def fake_notice(*args: object, **kwargs: object) -> None:
        order.append("notice")
        notices.append(str(args[2]) if len(args) > 2 else str(kwargs.get("message", "")))

    def fake_start(installer: Path) -> None:
        order.append("install")

    quits: list[str] = []

    monkeypatch.setattr(update_prompt, "backup_before_upgrade", fail_backup)
    monkeypatch.setattr(update_prompt, "notice", fake_notice)
    monkeypatch.setattr(update_prompt, "start_installer", fake_start)
    monkeypatch.setattr(
        update_prompt.QApplication, "quit", staticmethod(lambda: quits.append("quit"))
    )

    window = QWidget()
    prompt = update_prompt.UpdatePrompt(window)
    try:
        prompt._on_downloaded(tmp_path / "setup.exe")
        _pump_until(qt_app, lambda: "notice" in order)
        assert order == ["backup", "notice"]
        assert "install" not in order
        assert quits == []
        assert notices == [update_prompt.BACKUP_FAILED_NOTICE]
        assert "still go ahead" not in update_prompt.BACKUP_FAILED_NOTICE.lower()
        assert "stopped" in update_prompt.BACKUP_FAILED_NOTICE.lower()
    finally:
        window.deleteLater()


def test_pre_upgrade_backup_never_contains_the_secrets_sentinel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _isolate_state(monkeypatch, tmp_path)
    _seed_records(root)

    dest = backup.backup_before_upgrade("0.2.9")
    assert dest is not None
    names = {path.name for path in dest.iterdir()}
    assert names == {"memory.db", "rooms.yaml", "jobs.yaml", "config.local.yaml"}
    assert "secrets.yaml" not in names
    assert "sms_pair.json" not in names
    assert not (dest / "browser-profile").exists()
    assert not (dest / "sms_threads.json").exists()
    assert not (dest / "sms_media").exists()
    assert not (dest / "action_ledger.jsonl").exists()

    haystack = b""
    for path in dest.rglob("*"):
        if path.is_file():
            haystack += path.read_bytes()
    assert SENTINEL.encode("utf-8") not in haystack
    assert SENTINEL.lower().encode("utf-8") not in haystack

    conn = sqlite3.connect(str(dest / "memory.db"))
    try:
        row = conn.execute("SELECT body FROM notes").fetchone()
    finally:
        conn.close()
    assert row == ("remember this",)


def test_allowlist_cannot_force_secrets_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = _isolate_state(monkeypatch, tmp_path)
    (root / "rooms.yaml").write_text("rooms: []\n", encoding="utf-8")
    (root / "secrets.yaml").write_text(f"token: {SENTINEL}\n", encoding="utf-8")
    monkeypatch.setattr(
        backup,
        "PRE_UPGRADE_ALLOWLIST",
        (*backup.PRE_UPGRADE_ALLOWLIST, "secrets.yaml"),
    )

    with caplog.at_level(logging.ERROR, logger="arelis.backup"):
        dest = backup.backup_before_upgrade("0.2.9")

    assert dest is not None
    assert not (dest / "secrets.yaml").exists()
    assert SENTINEL.encode("utf-8") not in (dest / "rooms.yaml").read_bytes()
    assert any("secrets.yaml" in rec.getMessage() for rec in caplog.records)


def test_retention_keeps_newest_two_pre_folders_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _isolate_state(monkeypatch, tmp_path)
    (root / "rooms.yaml").write_text("rooms: []\n", encoding="utf-8")
    marker_in_state = root / "do-not-delete.txt"
    marker_in_state.write_text("stay", encoding="utf-8")
    marker_outside = tmp_path / "outside-backup.txt"
    marker_outside.write_text("stay", encoding="utf-8")
    sibling = tmp_path / "not-backups" / "pre-0.2.6"
    sibling.mkdir(parents=True)
    (sibling / "rooms.yaml").write_text("keep\n", encoding="utf-8")

    first = backup.backup_before_upgrade("0.2.7")
    assert first is not None
    os.utime(first, (1_000_000, 1_000_000))
    second = backup.backup_before_upgrade("0.2.8")
    assert second is not None
    os.utime(second, (2_000_000, 2_000_000))
    third = backup.backup_before_upgrade("0.2.9")
    assert third is not None

    backups = pre_upgrade_backups_dir()
    remaining = sorted(p.name for p in backups.iterdir() if p.name.startswith("pre-"))
    assert remaining == ["pre-0.2.8", "pre-0.2.9"]
    assert not (root / "backups").exists()
    assert marker_in_state.read_text(encoding="utf-8") == "stay"
    assert marker_outside.read_text(encoding="utf-8") == "stay"
    assert (sibling / "rooms.yaml").read_text(encoding="utf-8") == "keep\n"


def test_prune_memory_backups_leaves_pre_upgrade_folders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _isolate_state(monkeypatch, tmp_path)
    (root / "rooms.yaml").write_text("rooms: []\n", encoding="utf-8")
    dest = backup.backup_before_upgrade("0.2.9")
    assert dest is not None
    memory_backups = root / "backups"
    memory_backups.mkdir(parents=True, exist_ok=True)
    leftover = memory_backups / "memory-20200101.db"
    leftover.write_bytes(b"old")
    nested = dest / "memory-nested.db"
    nested.write_bytes(b"nested")

    removed = prune_memory_backups(dest_dir=memory_backups, keep=0)
    assert removed == 1
    assert dest.is_dir()
    assert not dest.resolve().is_relative_to(root.resolve())
    assert (dest / "rooms.yaml").is_file()
    assert nested.is_file()
    assert not leftover.exists()


def test_does_not_follow_a_symlink_out_of_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _isolate_state(monkeypatch, tmp_path)
    outside = tmp_path / "outside.yaml"
    outside.write_text("secret-outside\n", encoding="utf-8")
    link = root / "rooms.yaml"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available here")

    dest = backup.backup_before_upgrade("0.2.9")
    assert dest is not None
    assert not (dest / "rooms.yaml").exists()


def test_backup_failure_does_not_start_the_installer(
    qt_app, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtWidgets import QWidget

    order: list[str] = []

    def boom(from_version: str, to_version: str | None = None) -> None:
        order.append("backup")
        raise RuntimeError("disk is full")

    def fake_start(installer: Path) -> None:
        order.append("install")
        assert installer.name == "setup.exe"

    monkeypatch.setattr(update_prompt, "backup_before_upgrade", boom)
    monkeypatch.setattr(update_prompt, "start_installer", fake_start)
    monkeypatch.setattr(update_prompt, "notice", lambda *_a, **_k: order.append("notice"))
    monkeypatch.setattr(update_prompt.QApplication, "quit", staticmethod(lambda: None))

    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"MZ")
    window = QWidget()
    prompt = update_prompt.UpdatePrompt(window)
    try:
        prompt._on_downloaded(installer)
        _pump_until(qt_app, lambda: "notice" in order)
        assert order == ["backup", "notice"]
        assert "install" not in order
    finally:
        window.deleteLater()


def test_update_flow_calls_backup_before_the_installer(
    qt_app, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtWidgets import QWidget

    order: list[str] = []

    def fake_backup(from_version: str, to_version: str | None = None) -> Path:
        order.append(f"backup:{from_version}")
        return tmp_path / "backups" / "pre-x"

    def fake_start(installer: Path) -> None:
        order.append("install")

    monkeypatch.setattr(update_prompt, "backup_before_upgrade", fake_backup)
    monkeypatch.setattr(update_prompt, "start_installer", fake_start)
    monkeypatch.setattr(update_prompt, "notice", lambda *_a, **_k: order.append("notice"))
    monkeypatch.setattr(update_prompt.QApplication, "quit", staticmethod(lambda: None))

    window = QWidget()
    prompt = update_prompt.UpdatePrompt(window)
    try:
        prompt._on_downloaded(tmp_path / "setup.exe")
        _pump_until(qt_app, lambda: "install" in order)
        assert order[0].startswith("backup:")
        assert order[1] == "install"
        assert "notice" not in order
    finally:
        window.deleteLater()


def test_optional_records_copy_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _isolate_state(monkeypatch, tmp_path)
    (root / "contacts.yaml").write_text("contacts: []\n", encoding="utf-8")
    (root / "profile.yaml").write_text("name: example\n", encoding="utf-8")
    (root / "lessons.yaml").write_text("lessons: []\n", encoding="utf-8")
    dest = backup.backup_before_upgrade("0.2.9")
    assert dest is not None
    assert (dest / "contacts.yaml").read_text(encoding="utf-8") == "contacts: []\n"
    assert (dest / "profile.yaml").read_text(encoding="utf-8") == "name: example\n"
    assert (dest / "lessons.yaml").read_text(encoding="utf-8") == "lessons: []\n"


def test_on_downloaded_handoff_is_the_backup_then_installer() -> None:
    downloaded = update_prompt.UpdatePrompt._on_downloaded.__code__.co_names
    finished = update_prompt.UpdatePrompt._finish_backup_and_install.__code__.co_names
    assert "_BackupThread" in downloaded
    assert "start_installer" not in downloaded
    assert "start_installer" in finished


def test_never_raises_into_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: object, **_kwargs: object) -> Path:
        raise RuntimeError("disk is gone")

    monkeypatch.setattr(backup, "_backup_before_upgrade", boom)
    assert backup.backup_before_upgrade("0.2.9") is None


def _backup_names(backups: Path) -> set[str]:
    if not backups.is_dir():
        return set()
    return {path.name for path in backups.iterdir()}


def _pump_until(qt_app: object, predicate: object, timeout_s: float = 3.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:  # type: ignore[operator]
        qt_app.processEvents()  # type: ignore[union-attr]
        time.sleep(0.01)


def test_interrupted_copy_removes_its_temp_folder_right_away(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _isolate_state(monkeypatch, tmp_path)
    _seed_records(root)
    real_copy = backup._copy_allowlisted
    seen = {"n": 0}

    def boom(name: str, dest_dir: Path, records: Path) -> None:
        seen["n"] += 1
        if seen["n"] >= 2:
            raise OSError("disk full mid-copy")
        real_copy(name, dest_dir, records)

    monkeypatch.setattr(backup, "_copy_allowlisted", boom)
    dest = backup.backup_before_upgrade("0.2.9")
    assert dest is None
    backups = pre_upgrade_backups_dir()
    names = _backup_names(backups)
    assert not any(name.startswith("pre-") and not name.endswith(".partial") for name in names)
    temps = [
        path
        for path in backups.iterdir()
        if path.name.startswith(".") or path.name.endswith(".partial")
    ]
    assert temps == []

    monkeypatch.setattr(backup, "_copy_allowlisted", real_copy)
    dest = backup.backup_before_upgrade("0.2.9")
    assert dest is not None
    assert dest.name == "pre-0.2.9"
    leftover = [
        path
        for path in dest.parent.iterdir()
        if path.name.startswith(".") or path.name.endswith(".partial")
    ]
    assert leftover == []


def test_temp_folders_do_not_count_toward_retention(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _isolate_state(monkeypatch, tmp_path)
    (root / "rooms.yaml").write_text("rooms: []\n", encoding="utf-8")
    first = backup.backup_before_upgrade("0.2.7")
    assert first is not None
    os.utime(first, (1_000_000, 1_000_000))
    second = backup.backup_before_upgrade("0.2.8")
    assert second is not None
    os.utime(second, (2_000_000, 2_000_000))

    backups = pre_upgrade_backups_dir()
    zombie = backups / "pre-zombie.partial"
    zombie.mkdir()
    (zombie / "rooms.yaml").write_text("stale\n", encoding="utf-8")
    os.utime(zombie, (9_000_000, 9_000_000))
    dotted = backups / ".pre-stale.partial"
    dotted.mkdir()
    os.utime(dotted, (9_000_001, 9_000_001))

    third = backup.backup_before_upgrade("0.2.9")
    assert third is not None
    remaining = sorted(p.name for p in backups.iterdir() if p.is_dir())
    assert remaining == ["pre-0.2.8", "pre-0.2.9"]


def test_hard_linked_allowlisted_file_is_skipped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _isolate_state(monkeypatch, tmp_path)
    secrets = root / "secrets.yaml"
    secrets.write_text(f"mail_password: {SENTINEL}\n", encoding="utf-8")
    rooms = root / "rooms.yaml"
    try:
        os.link(secrets, rooms)
    except OSError:
        pytest.skip("hard links are not available here")
    (root / "jobs.yaml").write_text("jobs: []\n", encoding="utf-8")

    dest = backup.backup_before_upgrade("0.2.9")
    assert dest is not None
    assert not (dest / "rooms.yaml").exists()
    haystack = b""
    for path in dest.rglob("*"):
        if path.is_file():
            haystack += path.read_bytes()
    assert SENTINEL.encode("utf-8") not in haystack


def test_symlink_allowlisted_source_is_skipped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _isolate_state(monkeypatch, tmp_path)
    (root / "jobs.yaml").write_text("jobs: []\n", encoding="utf-8")
    link = root / "rooms.yaml"
    try:
        link.symlink_to(root / "jobs.yaml")
    except OSError:
        pytest.skip("symlinks are not available here")

    dest = backup.backup_before_upgrade("0.2.9")
    assert dest is not None
    assert not (dest / "rooms.yaml").exists()
    assert (dest / "jobs.yaml").read_text(encoding="utf-8") == "jobs: []\n"


def test_update_prompt_has_no_done_wait() -> None:
    text = Path(update_prompt.__file__).read_text(encoding="utf-8")
    assert "done.wait" not in text


def test_installer_waits_for_backup_thread(
    qt_app, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtWidgets import QWidget

    monkeypatch.setattr(update_prompt, "_BACKUP_WAIT_S", 0.0, raising=False)
    started: list[str] = []
    gate = threading.Event()

    def slow_backup(from_version: str, to_version: str | None = None) -> Path:
        gate.wait(timeout=5)
        return tmp_path / "backups" / "pre-x"

    def fake_start(installer: Path) -> None:
        started.append("install")

    monkeypatch.setattr(update_prompt, "backup_before_upgrade", slow_backup)
    monkeypatch.setattr(update_prompt, "start_installer", fake_start)
    monkeypatch.setattr(update_prompt, "notice", lambda *_a, **_k: None)
    monkeypatch.setattr(update_prompt.QApplication, "quit", staticmethod(lambda: None))

    window = QWidget()
    prompt = update_prompt.UpdatePrompt(window)
    try:
        prompt._on_downloaded(tmp_path / "setup.exe")
        qt_app.processEvents()
        assert started == []
        gate.set()
        _pump_until(qt_app, lambda: started == ["install"])
        assert started == ["install"]
    finally:
        gate.set()
        window.deleteLater()


def test_failed_backup_shows_notice_once_and_does_not_start_installer(
    qt_app, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtWidgets import QWidget

    order: list[str] = []
    notices: list[str] = []

    def fail_backup(from_version: str, to_version: str | None = None) -> None:
        order.append("backup")
        return None

    def fake_notice(*args: object, **kwargs: object) -> None:
        order.append("notice")
        notices.append(str(args[2]) if len(args) > 2 else str(kwargs.get("message", "")))

    def fake_start(installer: Path) -> None:
        order.append("install")

    monkeypatch.setattr(update_prompt, "backup_before_upgrade", fail_backup)
    monkeypatch.setattr(update_prompt, "notice", fake_notice)
    monkeypatch.setattr(update_prompt, "start_installer", fake_start)
    monkeypatch.setattr(update_prompt.QApplication, "quit", staticmethod(lambda: None))

    window = QWidget()
    prompt = update_prompt.UpdatePrompt(window)
    try:
        prompt._on_downloaded(tmp_path / "setup.exe")
        _pump_until(qt_app, lambda: "notice" in order)
        assert order == ["backup", "notice"]
        assert "install" not in order
        assert notices == [update_prompt.BACKUP_FAILED_NOTICE]
    finally:
        window.deleteLater()
