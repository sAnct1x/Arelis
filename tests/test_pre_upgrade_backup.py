"""Pre-upgrade backup copies only an allowlist, and never secrets.yaml."""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

import pytest

from arelis import backup
from arelis.memory.backup import prune_memory_backups
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

    backups = root / "backups"
    remaining = sorted(p.name for p in backups.iterdir() if p.name.startswith("pre-"))
    assert remaining == ["pre-0.2.8", "pre-0.2.9"]
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
    leftover = root / "backups" / "memory-20200101.db"
    leftover.write_bytes(b"old")
    nested = dest / "memory-nested.db"
    nested.write_bytes(b"nested")

    removed = prune_memory_backups(dest_dir=root / "backups", keep=0)
    assert removed == 1
    assert dest.is_dir()
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


def test_backup_failure_does_not_block_the_installer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    order: list[str] = []

    def boom(from_version: str, to_version: str | None = None) -> None:
        order.append("backup")
        raise RuntimeError("disk is full")

    def fake_start(installer: Path) -> None:
        order.append("install")
        assert installer.name == "setup.exe"

    monkeypatch.setattr(update_prompt, "backup_before_upgrade", boom)
    monkeypatch.setattr(update_prompt, "start_installer", fake_start)

    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"MZ")
    update_prompt.start_installer_with_pre_upgrade_backup(installer)
    assert order == ["backup", "install"]


def test_update_flow_calls_backup_before_the_installer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    order: list[str] = []

    def fake_backup(from_version: str, to_version: str | None = None) -> Path:
        order.append(f"backup:{from_version}")
        return tmp_path / "backups" / "pre-x"

    def fake_start(installer: Path) -> None:
        order.append("install")

    monkeypatch.setattr(update_prompt, "backup_before_upgrade", fake_backup)
    monkeypatch.setattr(update_prompt, "start_installer", fake_start)

    update_prompt.start_installer_with_pre_upgrade_backup(tmp_path / "setup.exe")
    assert order[0].startswith("backup:")
    assert order[1] == "install"


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
    source = update_prompt.UpdatePrompt._on_downloaded.__code__.co_names
    assert "start_installer_with_pre_upgrade_backup" in source


def test_never_raises_into_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: object, **_kwargs: object) -> Path:
        raise RuntimeError("disk is gone")

    monkeypatch.setattr(backup, "_backup_before_upgrade", boom)
    assert backup.backup_before_upgrade("0.2.9") is None
