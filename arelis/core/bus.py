from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from arelis.core.events import Event, EventType

Handler = Callable[[Event], Awaitable[None] | None]

log = logging.getLogger(__name__)

_APP_BUS: EventBus | None = None


class EventBus:
    """Simple asyncio pub/sub hub for Arelis modules.

    Handlers run as tasks so a long turn (agent loop awaiting confirm)
    cannot block delivery of TOOL_CONFIRM / TOOL_CONFIRM_REPLY.

    Ordering: events are dispatched in publish order and a handler that never
    awaits runs to completion before the next task starts, so the UI mirror sees
    deltas in order. Handlers that do await (the orchestrator running a whole
    turn) overlap with later events by design, which is what keeps confirm and
    cancel deliverable mid-turn.

    Wildcard subscribers (the UI mirror) run before type-specific ones. The
    orchestrator awaits a full turn on USER_MESSAGE; if it ran first the mirror
    would only see that spoken line after ASSISTANT_DONE, and the chat would
    paint the answer twice (once when the late user line closed the stream, once
    on DONE).
    """

    def __init__(self) -> None:
        self._subs: dict[EventType | None, list[Handler]] = defaultdict(list)
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._running = False
        self._tasks: set[asyncio.Task[Any]] = set()

    def subscribe(self, event_type: EventType | None, handler: Handler) -> None:
        """Subscribe to a type, or None for all events."""
        self._subs[event_type].append(handler)

    async def publish(self, event: Event) -> None:
        await self._queue.put(event)

    def publish_nowait(self, event: Event) -> None:
        self._queue.put_nowait(event)

    async def _dispatch(self, event: Event) -> None:
        handlers: Iterable[Handler] = (
            list(self._subs.get(None, [])) + list(self._subs.get(event.type, []))
        )
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
                    await result  # type: ignore[arg-type]
            except asyncio.CancelledError:
                raise
            except Exception:
                # One failing subscriber must not stop the others, and must not
                # take down the dispatch task. A handler crash here used to
                # vanish into a never-retrieved task exception: no ERROR event
                # was published, so the desktop UI stayed disabled and the only
                # way out was restarting the app.
                log.exception(
                    "Event handler %r failed for %s", getattr(handler, "__qualname__", handler),
                    event.type.value,
                )

    async def _handle(self, event: Event) -> None:
        try:
            await self._dispatch(event)
        finally:
            # Always mark done, including on cancellation, or drain() hangs.
            self._queue.task_done()

    async def run(self) -> None:
        self._running = True
        while self._running:
            event = await self._queue.get()
            task = asyncio.create_task(self._handle(event))
            # Hold a reference until completion, otherwise the loop only keeps a
            # weak one and a task can be garbage collected mid-flight.
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def stop(self) -> None:
        self._running = False

    async def drain(self) -> None:
        """Wait until every published event has finished being handled."""
        await self._queue.join()


def bind_app_bus(bus: EventBus | None) -> None:
    """The desktop window binds the live bus so calendar/tasks/jobs writes wake the tile."""
    global _APP_BUS
    _APP_BUS = bus


def emit_nowait(event: Event) -> None:
    """Publish if the desktop bus is bound. No-op in headless tool tests."""
    bus = _APP_BUS
    if bus is None:
        return
    try:
        bus.publish_nowait(event)
    except Exception:
        log.debug("emit_nowait dropped %s", getattr(event, "type", event), exc_info=True)
