"""Reality plate host. ArelisWindow only toggles this behind the stage grant.

Offering the plate still goes through ``world_stage_allowed`` — installer
trees and wheels must not show the chip, the View item, or the window.
Attach lives here so the main window does not build the plate itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from arelis.spatial import PHYSICS_ROOM_ID
from arelis.spatial.grant import world_stage_allowed

if TYPE_CHECKING:
    from arelis.spatial.scene import WorldScene
    from arelis.ui.world_window import WorldWindow


def world_available() -> bool:
    """The plate exists in this copy. Wraps ``world_stage_allowed``."""
    return world_stage_allowed()


def should_offer_world(room_id: str | None) -> bool:
    """Reality and a source-checkout stage. Else the chip stays dark."""
    return str(room_id or "") == PHYSICS_ROOM_ID and world_available()


def attach_world(scene: WorldScene, parent: Any = None) -> WorldWindow:
    """Build the floating plate. Hidden until the window toggles it."""
    from arelis.ui.world_window import WorldWindow

    window = WorldWindow(scene, parent)
    window.hide()
    return window


def show_world(
    window: WorldWindow,
    owner_geo: Any,
    *,
    page: str = "",
    placed: bool = False,
) -> bool:
    """Place (once), show, and open the chooser / solar / hands page."""
    if not placed:
        window.move(owner_geo.x() + 48, owner_geo.y() + 48)
        placed = True
    window.show()
    window.raise_()
    if page == "solar":
        window.enter_solar()
    elif page == "hands":
        window.enter_hands()
    else:
        window.show_chooser()
        window.panel.refresh()
    return placed


def hide_world(window: WorldWindow | None) -> None:
    """Put the plate away. Does not reset the sandbox scene."""
    if window is None:
        return
    window.hide()
