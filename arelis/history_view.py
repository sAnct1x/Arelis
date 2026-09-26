"""One way to read a turn history, whatever shape it arrived in.

History reaches the pre-parsers as ``ChatMessage`` objects from ``SessionMemory``
and as plain dicts from the eval harness and the tests. Three modules grew their
own reader for that: ``sms_complete`` and ``email_complete`` held byte-identical
copies, and ``attachments`` a third that differed only by tolerating ``None``.

This lives above ``arelis.core`` on purpose. Several core modules import
``arelis.attachments`` at import time, so a shared helper underneath ``core``
would have closed a cycle the moment attachments reached for it.
"""

from __future__ import annotations

from typing import Any


def history_pairs(history: list[Any] | None) -> list[tuple[str, str]]:
    """Return (role, content) from ChatMessage-like objects or dicts.

    Anything that is neither is skipped rather than coerced: a stray entry is a
    caller's bug, and inventing a role for it would put words in someone's mouth.
    """
    out: list[tuple[str, str]] = []
    for item in history or []:
        if hasattr(item, "role") and hasattr(item, "content"):
            out.append((str(item.role), str(item.content or "")))
        elif isinstance(item, dict):
            out.append(
                (str(item.get("role") or ""), str(item.get("content") or ""))
            )
    return out
