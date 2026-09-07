"""Glass-side inbound: own ingest, or attach to a core, or take over.

A detached ``--core`` owns ``:8765``. A sibling window that already opened
that door is not a core. If this window attached and the core never answers
— or answers and then leaves — the glass binds ingest itself instead of
sitting mute until a restart.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.presence.inbound_runtime import InboundRuntime, attach_inbound
from arelis.presence.lock import (
    core_lock_path,
    find_my_ingest_port,
    lock_held_by_other,
)

log = logging.getLogger(__name__)

# Core spawn + IPC bind. Long enough for a healthy --core, short enough that
# a missing core does not look like "still starting" for a minute.
ATTACH_GRACE_S = 5.0
# After a live bridge drops, wait before stealing :8765 so a core restart
# can reclaim the lock instead of fighting this window for the port.
TAKEOVER_HOLD_S = 8.0
WATCH_TICK_S = 0.5


def should_take_ingest(
    *,
    attached: bool,
    already_own: bool,
    core_lock: bool,
    our_ingest_up: bool,
    attached_once: bool,
    waited_s: float,
    core_absent_s: float,
    grace_s: float = ATTACH_GRACE_S,
    hold_s: float = TAKEOVER_HOLD_S,
) -> bool:
    """True when this window should bind ingest instead of waiting on a core."""
    if already_own or attached or core_lock or our_ingest_up:
        return False
    if not attached_once:
        return waited_s >= grace_s
    return core_absent_s >= hold_s


def install_owned_inbound(
    window: Any,
    bus: EventBus,
    loop: asyncio.AbstractEventLoop,
    config: dict[str, Any],
    *,
    hint: str,
) -> InboundRuntime:
    """Bind ingest on this glass and wire the phone hub."""
    runtime = attach_inbound(
        bus,
        loop,
        config,
        owned=True,
        stay_open_hint=hint,
    )
    window.inbound_runtime = runtime
    window.sms_ingest = runtime.ingest
    window.sms_watcher = runtime.watcher
    window.sms_auto_reply = runtime.auto_reply
    from arelis.ui.mobile_host import bind_mobile_hub

    bind_mobile_hub(window)
    for message in runtime.status_messages:
        asyncio.run_coroutine_threadsafe(
            bus.publish(Event(EventType.STATUS, {"message": message})),
            loop,
        )
    return runtime


async def claim_orphan_ingest(
    window: Any,
    bus: EventBus,
    loop: asyncio.AbstractEventLoop,
    config: dict[str, Any],
    *,
    hint: str,
) -> bool:
    """Bind ingest now. False when someone else already serves this user."""
    runtime = getattr(window, "inbound_runtime", None)
    if (
        runtime is not None
        and getattr(runtime, "owned", False)
        and getattr(runtime, "ingest", None) is not None
    ):
        return False
    if find_my_ingest_port(config) is not None:
        await bus.publish(
            Event(
                EventType.STATUS,
                {
                    "message": (
                        "Phone ingest is already up on this PC — this window "
                        "will not bind a second listener."
                    )
                },
            )
        )
        return False
    install_owned_inbound(window, bus, loop, config, hint=hint)
    await bus.publish(
        Event(
            EventType.STATUS,
            {
                "message": (
                    "No detached core answered, so this window opened the "
                    "phone door itself."
                )
            },
        )
    )
    return True


async def watch_orphan_ingest(
    *,
    is_attached: Callable[[], bool],
    already_own: Callable[[], bool],
    core_lock: Callable[[], bool],
    our_ingest_up: Callable[[], bool],
    claim: Callable[[], Awaitable[bool]],
    stop: asyncio.Event,
    grace_s: float = ATTACH_GRACE_S,
    hold_s: float = TAKEOVER_HOLD_S,
    tick_s: float = WATCH_TICK_S,
) -> None:
    """Until stop: if the expected core never shows (or leaves), claim ingest."""
    started = asyncio.get_running_loop().time()
    attached_once = False
    core_absent_s = 0.0
    claimed = False
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=tick_s)
            break
        except TimeoutError:
            pass
        attached = bool(is_attached())
        own = bool(already_own())
        locked = bool(core_lock())
        ingest_up = bool(our_ingest_up())
        if attached:
            attached_once = True
        if attached or locked or own:
            core_absent_s = 0.0
        else:
            core_absent_s += tick_s
        if claimed:
            continue
        waited = asyncio.get_running_loop().time() - started
        if not should_take_ingest(
            attached=attached,
            already_own=own,
            core_lock=locked,
            our_ingest_up=ingest_up,
            attached_once=attached_once,
            waited_s=waited,
            core_absent_s=core_absent_s,
            grace_s=grace_s,
            hold_s=hold_s,
        ):
            continue
        try:
            await claim()
            claimed = True
        except Exception:
            log.exception("orphan ingest claim failed")


def start_orphan_watch(
    window: Any,
    bus: EventBus,
    loop: asyncio.AbstractEventLoop,
    config: dict[str, Any],
    *,
    hint: str,
) -> asyncio.Event:
    """Schedule the attach-fallback watch on the UI loop. Returns the stop flag."""
    stop = asyncio.Event()

    async def _run() -> None:
        await watch_orphan_ingest(
            is_attached=lambda: bool(
                getattr(getattr(window, "ipc_client", None), "attached", False)
            ),
            already_own=lambda: bool(
                getattr(getattr(window, "inbound_runtime", None), "owned", False)
                and getattr(getattr(window, "inbound_runtime", None), "ingest", None)
            ),
            core_lock=lambda: lock_held_by_other(core_lock_path(config)),
            our_ingest_up=lambda: find_my_ingest_port(config) is not None,
            claim=lambda: claim_orphan_ingest(
                window, bus, loop, config, hint=hint
            ),
            stop=stop,
        )

    asyncio.run_coroutine_threadsafe(_run(), loop)
    return stop
