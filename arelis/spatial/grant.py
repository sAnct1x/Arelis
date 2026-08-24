"""MotionGrant: pose is allowed only in the physics room, while tracking is on."""

from __future__ import annotations

from dataclasses import dataclass

from arelis.spatial import PHYSICS_ROOM_ID


@dataclass(frozen=True)
class MotionGrant:
    room_id: str
    tracking: bool

    @property
    def allowed(self) -> bool:
        return self.room_id == PHYSICS_ROOM_ID and self.tracking


def grant_for(room_id: str | None, tracking: bool) -> MotionGrant:
    return MotionGrant(room_id=str(room_id or ""), tracking=bool(tracking))


def must_revoke(room_id: str | None) -> bool:
    return str(room_id or "") != PHYSICS_ROOM_ID
