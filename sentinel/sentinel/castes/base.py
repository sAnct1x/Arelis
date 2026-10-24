"""Narrow, single-purpose Sentinel Caste plugins and dynamic CasteRegistry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from sentinel.core.bus import EventBus
    from sentinel.core.fsm import SentinelUnit, WorldNode
    from sentinel.core.receipts import ReceiptLedger



class PermissionViolationError(RuntimeError):
    """Raised if a Sentinel attempts an action outside its narrow Caste contract."""


@dataclass(frozen=True)
class CasteDescriptor:
    caste_id: str
    code_prefix: str
    title: str
    single_purpose: str
    allowed_capabilities: frozenset[str]
    version: str = "1.0.0"
    orbit_radius: float = 18.0
    orbit_y_band: float = 0.0
    speed_mult: float = 1.0
    eye_color: str = "#ff2a3a"
    laser_kind: str = "harvest"
    doctrine: str = "HUNTER-SEEKER"

    def assert_capability(self, capability: str) -> None:
        if capability not in self.allowed_capabilities:
            raise PermissionViolationError(
                f"Caste {self.caste_id!r} is strictly locked to {sorted(self.allowed_capabilities)} "
                f"and cannot execute {capability!r}."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "caste_id": self.caste_id,
            "code_prefix": self.code_prefix,
            "title": self.title,
            "single_purpose": self.single_purpose,
            "allowed_capabilities": sorted(self.allowed_capabilities),
            "version": self.version,
            "orbit_radius": self.orbit_radius,
            "orbit_y_band": self.orbit_y_band,
            "speed_mult": self.speed_mult,
            "eye_color": self.eye_color,
            "laser_kind": self.laser_kind,
            "doctrine": self.doctrine,
        }


class CasteHandler(Protocol):
    descriptor: CasteDescriptor

    async def execute(
        self,
        unit: SentinelUnit,
        task_payload: dict[str, Any],
        *,
        bus: EventBus,
        ledger: ReceiptLedger,
        nodes: dict[str, WorldNode],
    ) -> dict[str, Any]: ...


class CasteRegistry:
    """Dynamic registry for Sentinel castes. Supports hot-registration, version upgrades, and dynamic removal."""

    def __init__(self) -> None:
        self._handlers: dict[str, CasteHandler] = {}

    def register(self, handler: CasteHandler) -> None:
        cid = handler.descriptor.caste_id.lower()
        self._handlers[cid] = handler

    def unregister(self, caste_id: str) -> bool:
        cid = (caste_id or "").strip().lower()
        return self._handlers.pop(cid, None) is not None

    def get(self, caste_id: str) -> CasteHandler:
        cid = (caste_id or "").strip().lower()
        if cid not in self._handlers:
            raise KeyError(f"Unknown Sentinel caste: {caste_id!r}")
        return self._handlers[cid]

    def descriptors(self) -> list[dict[str, Any]]:
        return [h.descriptor.to_dict() for h in self._handlers.values()]

    @property
    def caste_ids(self) -> tuple[str, ...]:
        return tuple(self._handlers.keys())

