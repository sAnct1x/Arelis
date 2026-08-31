"""Startup prune of caches that are not papers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from arelis.housekeep import (
    prune_browser_caches,
    prune_drops,
    prune_logs,
    prune_turns_jsonl,
    prune_voice_replies,
    reset_browser_profile,
    run_startup_housekeep,
)


def test_prune_voice_replies_keeps_newest_and_drops_probes(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"reply_{i:04d}_000.wav").write_bytes(b"RIFF")
    (tmp_path / "settings_test.wav").write_bytes(b"RIFF")
    (tmp_path / "kokoro_prove.wav").write_bytes(b"RIFF")
    assert prune_voice_replies(keep=2, directory=tmp_path) == 5
    names = sorted(p.name for p in tmp_path.glob("*.wav"))
    assert names == ["reply_0003_000.wav", "reply_0004_000.wav"]


def test_prune_drops_removes_old_day_folders(tmp_path: Path) -> None:
    old = tmp_path / "20260101"
    old.mkdir()
    (old / "clip.png").write_bytes(b"x")
    fresh = tmp_path / datetime.now(UTC).strftime("%Y%m%d")
    fresh.mkdir()
    (fresh / "keep.png").write_bytes(b"y")
    assert prune_drops(days=7, directory=tmp_path) >= 1
    assert not old.exists()
    assert (fresh / "keep.png").is_file()


def test_prune_logs_drops_stale_files(tmp_path: Path) -> None:
    stale = tmp_path / "voice.log.3"
    stale.write_text("old", encoding="utf-8")
    age = (datetime.now(UTC) - timedelta(days=20)).timestamp()
    import os

    os.utime(stale, (age, age))
    fresh = tmp_path / "arelis.log"
    fresh.write_text("now", encoding="utf-8")
    assert prune_logs(days=14, directory=tmp_path) == 1
    assert not stale.exists()
    assert fresh.exists()


def test_prune_turns_jsonl_drops_old_stamps(tmp_path: Path) -> None:
    path = tmp_path / "turns.jsonl"
    old = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%S")
    new = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    path.write_text(
        f'{{"stamp": "{old}", "id": "a"}}\n{{"stamp": "{new}", "id": "b"}}\n',
        encoding="utf-8",
    )
    assert prune_turns_jsonl(days=14, path=path) == 1
    assert '"id": "b"' in path.read_text(encoding="utf-8")
    assert '"id": "a"' not in path.read_text(encoding="utf-8")


def test_prune_browser_caches_leaves_cookies(tmp_path: Path) -> None:
    default = tmp_path / "Default"
    cache = default / "Cache"
    cache.mkdir(parents=True)
    (cache / "data_0").write_bytes(b"blob")
    cookies = default / "Cookies"
    cookies.write_bytes(b"jar")
    login = default / "Login Data"
    login.write_bytes(b"logins")
    assert prune_browser_caches(root=tmp_path) >= 1
    assert not cache.exists()
    assert cookies.is_file()
    assert login.is_file()


def test_reset_browser_profile_removes_tree(tmp_path: Path) -> None:
    profile = tmp_path / "browser-profile"
    (profile / "Default").mkdir(parents=True)
    (profile / "Default" / "Cookies").write_bytes(b"jar")
    assert reset_browser_profile(root=profile) >= 1
    assert not profile.exists()


def test_startup_housekeep_is_safe_when_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    counts = run_startup_housekeep()
    assert set(counts) == {
        "tool_cache",
        "ledger",
        "voice",
        "takes",
        "backups",
        "drops",
        "logs",
        "turns_jsonl",
        "browser_cache",
    }
    assert all(isinstance(n, int) and n == 0 for n in counts.values())
