"""Sweep live-pass probe facts out of durable memory."""

from __future__ import annotations

import atexit

LIVE_PASS_FACT_MARKERS = (
    "271828",
    "overnight live pass token",
    "live-pass ran a real tool",
)


def is_live_pass_fact(text: str) -> bool:
    """True when a fact is a live-pass probe, not real user knowledge."""
    low = (text or "").lower()
    return any(marker.lower() in low for marker in LIVE_PASS_FACT_MARKERS)


def forget_live_pass_facts(store) -> int:
    """Reject matching *active* facts. Returns how many rows changed."""
    changed = 0
    for text in store.active_fact_texts(limit=200):
        if is_live_pass_fact(text):
            changed += store.forget_fact(text)
    return changed


def bind_live_pass_store(store):
    """Register atexit cleanup, return the same store. Do not close the store."""

    def _cleanup() -> None:
        try:
            n = forget_live_pass_facts(store)
        except Exception as exc:
            print(f"WARN  live-pass memory cleanup: {exc}")
            return
        if n:
            print(f"cleaned {n} live-pass fact(s) from memory")

    atexit.register(_cleanup)
    return store
