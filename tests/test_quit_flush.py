"""Quitting must land in-flight memory writes instead of dropping them."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from arelis.memory import MemoryIndexer, flush_background_writes


class _NoEmbed:
    embeds = False


class _SlowDocs:
    def __init__(self, dest: Path, hold_s: float) -> None:
        self.dest = dest
        self.hold_s = hold_s
        self.started = threading.Event()

    def sync_batch(self, max_files: int = 4) -> int:
        del max_files
        self.started.set()
        time.sleep(self.hold_s)
        self.dest.write_text("kept", encoding="utf-8")
        return 1


def test_quit_flush_keeps_a_pending_memory_write(tmp_path: Path) -> None:
    """A force-quit flush must wait out a write still on the indexer worker.

    Tray Quit cancelled MemoryIndexer.run_batch and then gave the default
    executor 0.75s. A docs sync inside asyncio.to_thread kept writing after
    the process had already decided to exit, so the last memory save never
    reached disk.
    """
    dest = tmp_path / "session.txt"
    docs = _SlowDocs(dest, hold_s=1.2)
    indexer = MemoryIndexer(object(), _NoEmbed(), docs=docs, index_docs=False)  # type: ignore[arg-type]

    worker = threading.Thread(
        target=lambda: __import__("asyncio").run(indexer.run_batch()),
        name="arelis-test-index-write",
        daemon=True,
    )
    worker.start()
    assert docs.started.wait(timeout=1.0), "background write never started"

    t0 = time.monotonic()
    flush_background_writes(indexer=indexer, timeout_s=3.0)
    elapsed = time.monotonic() - t0

    assert dest.read_text(encoding="utf-8") == "kept"
    assert elapsed < 3.0
    worker.join(timeout=1.0)
