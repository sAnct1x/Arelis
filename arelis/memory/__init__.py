"""Durable conversation memory.

Jobs stay on YAML under data/; twenty thousand chat messages do not. This
package is the SQLite store those messages need, plus the tools that read it.
"""

from __future__ import annotations

from arelis.memory.indexer import DEFAULT_EMBED_MODEL, MemoryIndexer
from arelis.memory.store import MemoryStore, SearchHit

__all__ = ["DEFAULT_EMBED_MODEL", "MemoryIndexer", "MemoryStore", "SearchHit"]
