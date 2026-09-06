"""Live tab watch — poll while Arelis is open. Stop cancels. Notify on hit."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from arelis.browser.wait_for import has_wait_needle, page_needles_hit

WATCH_LINE = "Watching"
HitSink = Callable[[dict[str, Any]], None]

_watching = False
_hit_sink: HitSink | None = None
_bound: Any | None = None


def is_watching() -> bool:
    return _watching


def set_hit_sink(sink: HitSink | None) -> None:
    global _hit_sink
    _hit_sink = sink


def bind_session(session: Any | None) -> None:
    global _bound
    _bound = session


def mark_watching(on: bool) -> None:
    global _watching
    _watching = bool(on)


def cancel() -> None:
    """Stop the live watch from Stop / a new conversation. Safe if idle."""
    mark_watching(False)
    session = _bound
    if session is not None:
        stopper = getattr(session, "cancel_watch", None)
        if callable(stopper):
            stopper()


def emit_hit(data: dict[str, Any]) -> None:
    mark_watching(False)
    sink = _hit_sink
    if sink is None:
        return
    try:
        sink(data)
    except Exception:
        return


def watch_wanted(*, url: str = "", text: str = "", heading: str = "") -> str:
    bits = []
    if str(url or "").strip():
        bits.append(f"url={url.strip()}")
    if str(heading or "").strip():
        bits.append(f"heading={heading.strip()}")
    if str(text or "").strip():
        bits.append(f"text={text.strip()}")
    return ", ".join(bits)


def watching_output(*, url: str = "", text: str = "", heading: str = "") -> str:
    wanted = watch_wanted(url=url, text=text, heading=heading)
    return f"Watching for {wanted}." if wanted else "Watching."


def signals_hit(
    signals: dict[str, str],
    *,
    url: str = "",
    text: str = "",
    heading: str = "",
) -> bool:
    if not has_wait_needle(url=url, text=text, heading=heading):
        return False
    return page_needles_hit(
        landed_url=signals.get("url") or "",
        title=signals.get("title") or "",
        heading=signals.get("heading") or "",
        page_text=signals.get("text") or "",
        want_url=url,
        want_text=text,
        want_heading=heading,
    )


async def sleep_watch(seconds: float) -> None:
    from arelis.browser.hold import cooperative_wait

    await cooperative_wait(seconds)
