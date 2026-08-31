"""MotionGrant: pose is allowed in Reality, or on filament with the Hands chip."""

from __future__ import annotations

from dataclasses import dataclass

from arelis.paths import is_source_checkout
from arelis.spatial import PHYSICS_ROOM_ID


@dataclass(frozen=True)
class MotionGrant:
    room_id: str
    tracking: bool
    filament: bool = False
    chip: bool = False

    @property
    def allowed(self) -> bool:
        if not world_stage_allowed() or not self.tracking:
            return False
        if self.filament and self.chip:
            return True
        return self.room_id == PHYSICS_ROOM_ID


def world_stage_allowed() -> bool:
    """Reality plate, solar sim, and C920 stage. Source checkout only.

    An installer tree (unins000.exe at install_root) and a wheel in
    site-packages must not offer the stage. The physics *room* still
    exists there for chat, CAS, and Horizons observer tables.
    """
    from arelis.update import install_root

    if install_root() is not None:
        return False
    return is_source_checkout()


def grant_for(
    room_id: str | None,
    tracking: bool,
    *,
    filament: bool = False,
    chip: bool = False,
) -> MotionGrant:
    return MotionGrant(
        room_id=str(room_id or ""),
        tracking=bool(tracking),
        filament=bool(filament),
        chip=bool(chip),
    )


def must_revoke(
    room_id: str | None,
    *,
    filament: bool = False,
    chip: bool = False,
) -> bool:
    """Leave Reality kills sodium Track. Filament + chip survives a room change."""
    if filament and chip:
        return False
    return str(room_id or "") != PHYSICS_ROOM_ID
