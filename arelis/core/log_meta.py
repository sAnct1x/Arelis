"""Non-content metadata for log lines.

User text and tool error messages stay in the chat. The files get a length
and, for text that is only being correlated, a short hash.
"""

from __future__ import annotations

import hashlib


def text_sha12(text: str) -> str:
    """First 12 hex chars of sha256 over the exact string."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]
