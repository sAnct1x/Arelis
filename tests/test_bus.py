import asyncio

import pytest

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType


@pytest.mark.asyncio
async def test_bus_delivers_event():
    bus = EventBus()
    seen = []

    async def handler(event: Event) -> None:
        seen.append(event.type)

    bus.subscribe(EventType.STATUS, handler)
    task = asyncio.create_task(bus.run())
    await bus.publish(Event(EventType.STATUS, {"message": "hi"}))
    await bus.drain()
    bus.stop()
    task.cancel()
    assert EventType.STATUS in seen
