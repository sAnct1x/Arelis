"""Pre-upgrade backup copies only an allowlist, and never secrets.yaml."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from arelis import backup
from arelis.paths import DATA_DIR_ENV, state_dir
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
        details.append(str(kwargs.get("detail", "")))

    def fake_start(installer: Path) -> None:
        order.append("install")

    quits: list[str] = []
    details: list[str] = []

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
        assert details == [update_prompt.BACKUP_FAILED_DETAIL]
        assert "memory and settings" in update_prompt.BACKUP_FAILED_NOTICE
        assert "tomorrow" in update_prompt.BACKUP_FAILED_NOTICE.lower()
        assert "still go ahead" not in update_prompt.BACKUP_FAILED_NOTICE.lower()
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


def _backup_names(backups: Path) -> set[str]:
    if not backups.is_dir():
        return set()
    return {path.name for path in backups.iterdir()}


def _pump_until(qt_app: object, predicate: object, timeout_s: float = 3.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:  # type: ignore[operator]
        qt_app.processEvents()  # type: ignore[union-attr]
        time.sleep(0.01)


def test_backup_timeout_stops_the_upgrade_without_starting_installer(
    qt_app, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Timeout must stop the update. Fails if the installer starts on timeout,
    or if the backup timer is removed so the hung copy never finishes.
    """
    from PySide6.QtWidgets import QWidget

    # The production constant must still be the 60s fallback; the test shortens it.
    assert update_prompt._BACKUP_TIMEOUT_MS == 60_000
    monkeypatch.setattr(update_prompt, "_BACKUP_TIMEOUT_MS", 50)

    order: list[str] = []
    notices: list[str] = []
    details: list[str] = []
    gate = threading.Event()

    def hung_backup(from_version: str, to_version: str | None = None) -> Path | None:
        order.append("backup")
        gate.wait(timeout=5)
        return None

    def fake_notice(*args: object, **kwargs: object) -> None:
        order.append("notice")
        notices.append(str(args[2]) if len(args) > 2 else str(kwargs.get("message", "")))
        details.append(str(kwargs.get("detail", "")))

    def fake_start(installer: Path) -> None:
        order.append("install")

    quits: list[str] = []

    monkeypatch.setattr(update_prompt, "backup_before_upgrade", hung_backup)
    monkeypatch.setattr(update_prompt, "notice", fake_notice)
    monkeypatch.setattr(update_prompt, "start_installer", fake_start)
    monkeypatch.setattr(
        update_prompt.QApplication, "quit", staticmethod(lambda: quits.append("quit"))
    )

    # Guard: the handoff must still arm a single-shot timer with the constant.
    src = Path(update_prompt.__file__).read_text(encoding="utf-8")
    assert "_backup_timer.start(_BACKUP_TIMEOUT_MS)" in src
    assert "_on_backup_timeout" in src

    window = QWidget()
    prompt = update_prompt.UpdatePrompt(window)
    try:
        prompt._on_downloaded(tmp_path / "setup.exe")
        _pump_until(qt_app, lambda: "notice" in order, timeout_s=3.0)
        assert "backup" in order
        assert order.count("notice") == 1
        assert "install" not in order
        assert quits == []
        assert notices == [update_prompt.BACKUP_FAILED_NOTICE]
        assert details == [update_prompt.BACKUP_FAILED_DETAIL]
        # Timeout leaves the copy running, but not as a child. Deleting the
        # window while it is still parented aborts the process.
        assert prompt._backup is not None
        assert prompt._backup.isRunning()
        assert prompt._backup.parent() is None
    finally:
        gate.set()
        window.deleteLater()


