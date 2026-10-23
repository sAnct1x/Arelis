"""Durable conversation memory.

Jobs stay on YAML under data/; twenty thousand chat messages do not. This
package is the SQLite store those messages need, plus the tools that read it.
"""

from __future__ import annotations

from arelis.memory.indexer import DEFAULT_EMBED_MODEL, MemoryIndexer
from arelis.memory.store import MemoryStore, SearchHit

__all__ = [
    "DEFAULT_EMBED_MODEL",
    "MemoryIndexer",
    "MemoryStore",
    "SearchHit",
    "flush_background_writes",
]


def flush_background_writes(
    *,
    store: MemoryStore | None = None,
    indexer: MemoryIndexer | None = None,
    timeout_s: float = 3.0,
) -> None:
    """Join in-flight memory writes and flush the log. Bounded; never hangs quit."""
    import time

    from arelis.logging_setup import flush_logs

    try:
        budget = max(0.0, float(timeout_s))
    except (TypeError, ValueError):
        budget = 3.0
    deadline = time.monotonic() + budget
    if indexer is not None:
        indexer.join_writes(timeout_s=max(0.0, deadline - time.monotonic()))
    if store is not None:
        store.flush()
    flush_logs()
