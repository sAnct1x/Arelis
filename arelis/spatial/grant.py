"""MotionGrant: pose is allowed when the Reality stage is present.

Filament plus the Hands chip still grants on a source checkout. There is
no room. room_id on the grant object is leftover from the rooms product
and is not consulted.
"""

from __future__ import annotations

from dataclasses import dataclass

from arelis.paths import is_source_checkout


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
        return True


def world_stage_allowed() -> bool:
    """Reality plate, solar sim, and C920 stage. Source checkout only.

    An installer tree (unins000.exe at install_root) and a wheel in
    site-packages must not offer the stage.
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
    """Installer trees never keep sodium Track. Filament plus chip stays."""
    del room_id
    if filament and chip:
        return False
    return not world_stage_allowed()
