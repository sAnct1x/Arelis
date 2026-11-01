"""MotionGrant: pose is allowed when the Reality stage is present.

Filament plus the Hands chip still grants on a source checkout. There is
no room. room_id on the grant object is leftover from the rooms product
and is not consulted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from arelis.paths import is_source_checkout

# The Filament floats ask on every atmosphere tick, and the answer is three file
# checks (unins000.exe, pyproject.toml, tests/) that cost about 5% of the UI
# thread on Windows. The tree a process runs from does not change under it, so
# the answer is reused for a few seconds; the key keeps a monkeypatched probe honest.
_STAGE_TTL_S = 5.0
_stage_cache: tuple[object, float, bool] | None = None


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
    global _stage_cache
    from arelis import update

    key = (update.install_root, is_source_checkout)
    now = time.monotonic()
    cached = _stage_cache
    if cached is not None and cached[0] == key and now - cached[1] < _STAGE_TTL_S:
        return cached[2]
    allowed = update.install_root() is None and is_source_checkout()
    _stage_cache = (key, now, allowed)
    return allowed


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
