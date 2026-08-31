"""Ceilings for records that are not her papers.

Launch runs this once. Fat-tool writes prune the scrape cache on the way.
Nothing here touches secrets, memory.db, rooms, or config. The browser
profile is not wiped on launch — only its Cache / GPU / crash pads — so a
sign-in survives. A full reset is ``python -m arelis.housekeep --reset-browser``.
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from arelis.core.receipts import prune_action_ledger
from arelis.core.tool_results import prune_tool_cache
from arelis.memory.backup import prune_memory_backups
from arelis.paths import logs_dir, outputs_dir, state_dir

log = logging.getLogger(__name__)

VOICE_REPLY_KEEP = 8
DROPS_KEEP_DAYS = 7
LOGS_KEEP_DAYS = 14
TURNS_JSONL_KEEP_DAYS = 14
TAKES_KEEP = 4
BROWSER_CACHE_DIR_NAMES = frozenset(
    {
        "Cache",
        "Code Cache",
        "GPUCache",
        "GrShaderCache",
        "ShaderCache",
        "DawnCache",
        "DawnGraphiteCache",
        "DawnWebGPUCache",
        "GraphiteDawnCache",
        "Crashpad",
        "BrowserMetrics",
        "optimization_guide_hint_cache",
        "CacheStorage",
        "ScriptCache",
    }
)


def prune_voice_replies(*, keep: int = VOICE_REPLY_KEEP, directory: Path | None = None) -> int:
    """Newest spoken-reply wavs stay. Prove / probe / settings clips do not."""
    root = directory if directory is not None else outputs_dir() / "voice"
    if not root.is_dir():
        return 0
    removed = 0
    try:
        clips = sorted(
            (p for p in root.glob("reply_*.wav") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
    except OSError:
        clips = []
    for stale in clips[: max(0, len(clips) - max(0, int(keep)))]:
        if _unlink(stale):
            removed += 1
    try:
        extras = [
            p
            for p in root.iterdir()
            if p.is_file() and p.suffix.lower() == ".wav" and not p.name.startswith("reply_")
        ]
    except OSError:
        extras = []
    for stale in extras:
        if _unlink(stale):
            removed += 1
    return removed


def prune_drops(*, days: int = DROPS_KEEP_DAYS, directory: Path | None = None) -> int:
    """Attachment staging is a landing pad, not a filing cabinet."""
    root = directory if directory is not None else state_dir() / "drops"
    if not root.is_dir():
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=max(1, int(days)))
    removed = 0
    try:
        children = list(root.iterdir())
    except OSError:
        return 0
    for folder in children:
        if not folder.is_dir():
            continue
        day = _day_folder_stamp(folder.name)
        if day is None or day >= cutoff.date():
            continue
        try:
            files = [p for p in folder.rglob("*") if p.is_file()]
        except OSError:
            files = []
        shutil.rmtree(folder, ignore_errors=True)
        if not folder.exists():
            removed += len(files) or 1
    return removed


def prune_logs(*, days: int = LOGS_KEEP_DAYS, directory: Path | None = None) -> int:
    """Drop log files whose mtime is older than ``days``. Active logs stay."""
    root = directory if directory is not None else logs_dir()
    if not root.is_dir():
        return 0
    cutoff = datetime.now(UTC).timestamp() - max(1, int(days)) * 86400
    removed = 0
    try:
        children = list(root.iterdir())
    except OSError:
        return 0
    for path in children:
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        if _unlink(path):
            removed += 1
    return removed


def prune_turns_jsonl(
    *,
    days: int = TURNS_JSONL_KEEP_DAYS,
    path: Path | None = None,
) -> int:
    """Same ceiling as the action ledger. ``stamp`` is local wall time."""
    out = path if path is not None else logs_dir() / "turns.jsonl"
    if not out.is_file():
        return 0
    cutoff = datetime.now() - timedelta(days=max(1, int(days)))
    try:
        raw = out.read_text(encoding="utf-8")
    except OSError:
        return 0
    kept: list[str] = []
    removed = 0
    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
            stamp = datetime.strptime(str(row.get("stamp") or ""), "%Y-%m-%dT%H:%M:%S")
            if stamp < cutoff:
                removed += 1
                continue
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        kept.append(text)
    if not removed:
        return 0
    tmp = out.with_suffix(out.suffix + ".tmp")
    try:
        tmp.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
        tmp.replace(out)
    except OSError:
        log.debug("turns.jsonl prune failed", exc_info=True)
        try:
            tmp.unlink()
        except OSError:
            pass
        return 0
    return removed


def prune_browser_caches(*, root: Path | None = None) -> int:
    """Chromium cache trees only. Cookies and login data stay."""
    target = root if root is not None else state_dir() / "browser-profile"
    if not target.is_dir():
        return 0
    removed = 0
    try:
        doomed = [
            path
            for path in target.rglob("*")
            if path.is_dir() and path.name in BROWSER_CACHE_DIR_NAMES
        ]
    except OSError:
        return 0
    for path in doomed:
        if not path.exists():
            continue
        n = _count_files(path)
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            removed += n or 1
    return removed


def reset_browser_profile(*, root: Path | None = None) -> int:
    """Delete her Chrome profile. The next open is a new window."""
    target = root if root is not None else state_dir() / "browser-profile"
    if not target.exists():
        return 0
    n = _count_files(target)
    shutil.rmtree(target, ignore_errors=True)
    return n if not target.exists() else max(0, n - _count_files(target))


def run_startup_housekeep() -> dict[str, int]:
    """Best-effort prune. Failures are logged and do not block launch."""
    counts = {
        "tool_cache": 0,
        "ledger": 0,
        "voice": 0,
        "takes": 0,
        "backups": 0,
        "drops": 0,
        "logs": 0,
        "turns_jsonl": 0,
        "browser_cache": 0,
    }
    steps = (
        ("tool_cache", prune_tool_cache),
        ("ledger", prune_action_ledger),
        ("voice", prune_voice_replies),
        ("backups", prune_memory_backups),
        ("drops", prune_drops),
        ("logs", prune_logs),
        ("turns_jsonl", prune_turns_jsonl),
        ("browser_cache", prune_browser_caches),
    )
    for key, fn in steps:
        try:
            counts[key] = int(fn() or 0)
        except Exception:
            log.debug("%s prune failed", key, exc_info=True)
    try:
        from arelis.spatial.takes import prune_takes

        counts["takes"] = len(prune_takes(keep_last=TAKES_KEEP))
    except Exception:
        log.debug("takes prune failed", exc_info=True)
    return counts


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--reset-browser" in args:
        n = reset_browser_profile()
        log.info("reset browser profile (%s file(s))", n)
        print(f"browser profile reset ({n} files)")
    counts = run_startup_housekeep()
    print("housekeep " + " ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


def _unlink(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except OSError:
        return False


def _count_files(root: Path) -> int:
    try:
        return sum(1 for p in root.rglob("*") if p.is_file())
    except OSError:
        return 0


def _day_folder_stamp(name: str):
    try:
        return datetime.strptime(name, "%Y%m%d").date()
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
