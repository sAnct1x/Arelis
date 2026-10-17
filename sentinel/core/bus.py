"""High-throughput asynchronous EventBus for Sentinel Hive & 60 Hz Overseer telemetry."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

log = logging.getLogger("sentinel.bus")


class EventTopic(StrEnum):
    UNIT_SPAWNED = "unit.spawned"
    UNIT_UPGRADED = "unit.upgraded"
    UNIT_RETIRED = "unit.retired"
    UNIT_STATE = "unit.state"
    MISSION_STARTED = "mission.started"
    MISSION_COMPLETED = "mission.completed"
    NODE_SPAWNED = "node.spawned"
    NODE_UPDATED = "node.updated"
    NODE_REMOVED = "node.removed"
    SECURITY_ALERT = "security.alert"
    PAYLOAD_QUARANTINED = "payload.quarantined"
    RECEIPT_MINTED = "receipt.minted"
    THEME_CHANGED = "ui.theme_changed"
    EMP_TRIGGERED = "emp.triggered"
    EMP_RESET = "emp.reset"
    CASTE_REGISTERED = "caste.registered"
    CASTE_UNREGISTERED = "caste.unregistered"
    AUTHORITY_REQUEST = "authority.request"
    AUTHORITY_DECISION = "authority.decision"
    ENVELOPE_EMITTED = "envelope.emitted"


@dataclass(frozen=True)
class HiveEvent:
    topic: EventTopic | str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    envelope: Any = None  # Optional typed SentinelBaseEnvelope


    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": str(self.topic),
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


Subscriber = Callable[[HiveEvent], Awaitable[None] | None]


class EventBus:
    """Non-blocking event bus with bounded history ring buffer for late-joining UI clients."""

    def __init__(self, *, history_limit: int = 300) -> None:
        self._subscribers: dict[str, list[Subscriber]] = defaultdict(list)
        self._wildcard: list[Subscriber] = []
        self._history: deque[HiveEvent] = deque(maxlen=history_limit)
        self._bg_tasks: set[asyncio.Task[Any]] = set()

    @property
    def recent_events(self) -> list[HiveEvent]:
        return list(self._history)

    def subscribe(self, topic: EventTopic | str, callback: Subscriber) -> Callable[[], None]:
        key = str(topic)
        if key == "*":
            self._wildcard.append(callback)
            return lambda: self._wildcard.remove(callback) if callback in self._wildcard else None
        self._subscribers[key].append(callback)
        return lambda: (
            self._subscribers[key].remove(callback)
            if callback in self._subscribers[key]
            else None
        )

    def publish_nowait(self, topic: EventTopic | str, payload: dict[str, Any] | None = None) -> HiveEvent:
        event = HiveEvent(topic=str(topic), payload=dict(payload or {}))
        self._history.append(event)
        callbacks = list(self._subscribers.get(str(topic), ())) + list(self._wildcard)
        for cb in callbacks:
            try:
                res = cb(event)
                if asyncio.iscoroutine(res):
                    try:
                        loop = asyncio.get_running_loop()
                        task = loop.create_task(res)
                        self._bg_tasks.add(task)
                        task.add_done_callback(self._bg_tasks.discard)
                    except RuntimeError:
                        res.close()
            except Exception:
                log.exception("Subscriber error on topic %s", topic)
        return event

    async def publish(self, topic: EventTopic | str, payload: dict[str, Any] | None = None) -> HiveEvent:
        event = HiveEvent(topic=str(topic), payload=dict(payload or {}))
        self._history.append(event)
        callbacks = list(self._subscribers.get(str(topic), ())) + list(self._wildcard)
        for cb in callbacks:
            try:
                res = cb(event)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                log.exception("Subscriber error on topic %s", topic)
        return event
