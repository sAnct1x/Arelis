"""MotionGrant: pose is allowed only in the physics room, while tracking is on."""

from __future__ import annotations

from dataclasses import dataclass

from arelis.paths import is_source_checkout
from arelis.spatial import PHYSICS_ROOM_ID


@dataclass(frozen=True)
class MotionGrant:
    room_id: str
    tracking: bool

    @property
    def allowed(self) -> bool:
        return (
            world_stage_allowed()
            and self.room_id == PHYSICS_ROOM_ID
            and self.tracking
        )


def world_stage_allowed() -> bool:
    """World plate, solar sim, and C920 stage. Source checkout only.

    An installer tree (unins000.exe at install_root) and a wheel in
    site-packages must not offer the stage. The physics *room* still
    exists there for chat, CAS, and Horizons observer tables.
    """
    from arelis.update import install_root

    if install_root() is not None:
        return False
    return is_source_checkout()


def grant_for(room_id: str | None, tracking: bool) -> MotionGrant:
    return MotionGrant(room_id=str(room_id or ""), tracking=bool(tracking))


def must_revoke(room_id: str | None) -> bool:
    return str(room_id or "") != PHYSICS_ROOM_ID
