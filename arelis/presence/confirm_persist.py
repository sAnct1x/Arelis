"""Bus helper: mirror send confirms into PendingConfirmStore."""

from __future__ import annotations

import logging

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.presence.pending_confirms import (
    PendingConfirmStore,
    pending_from_event_payload,
)

log = logging.getLogger(__name__)


class ConfirmPersister:
    """Subscribe to TOOL_CONFIRM / replies and keep the on-disk queue in sync."""

    def __init__(self, bus: EventBus, store: PendingConfirmStore) -> None:
        self.bus = bus
        self.store = store
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.bus.subscribe(EventType.TOOL_CONFIRM, self.on_confirm)
        self.bus.subscribe(EventType.TOOL_CONFIRM_REPLY, self.on_reply)
        self.bus.subscribe(EventType.TURN_CANCEL, self.on_cancel)
        self._started = True

    async def on_confirm(self, event: Event) -> None:
        item = pending_from_event_payload(event.payload or {})
        if item is not None:
            self.store.upsert(item)
            log.info(
                "Parked confirm id=%s tool=%s path=%s",
                item.id,
                item.tool,
                self.store.path,
            )

    async def on_reply(self, event: Event) -> None:
        confirm_id = str((event.payload or {}).get("id") or "")
        decision = str((event.payload or {}).get("decision") or "")
        if confirm_id:
            self.store.remove(confirm_id)
            log.info(
                "Cleared parked confirm id=%s decision=%s",
                confirm_id,
                decision or "-",
            )

    async def on_cancel(self, event: Event) -> None:
        # UI should also publish TOOL_CONFIRM_REPLY for the open card. Parked
        # core drafts (no live waiter) stay on disk until the UI opens them.
        log.info("Turn cancel while confirms may be open (parked drafts kept)")