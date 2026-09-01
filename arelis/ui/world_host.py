"""Reality plate host. ArelisWindow only toggles this behind the stage grant.

Offering the plate still goes through ``world_stage_allowed`` — installer
trees and wheels must not show the chip, the View item, or the window.
Attach lives here so the main window does not build the plate itself.
Verb and tile handlers take ``window`` first so the integrator can drop
the ArelisWindow mirrors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from arelis.spatial import PHYSICS_ROOM_ID
from arelis.spatial.grant import world_stage_allowed
from arelis.spatial.verbs import (
    PhysicsAct,
    classify_physics_act,
    is_time_verb,
    is_toy_verb,
    speech_body_names,
)

if TYPE_CHECKING:
    from arelis.spatial.scene import WorldScene
    from arelis.ui.world_window import WorldWindow

_DOCK_TILES = (
    "thinking",
    "workspace",
    "history",
    "notifications",
    "camera",
    "contacts",
    "calendar",
)


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


def open_world(window) -> None:
    window.act_world.setChecked(True)
    toggle_world(window, True)


def toggle_world(window, checked: bool, page: str = "", *, force: bool = False) -> None:
    from arelis.ui.idle_host import note_engagement, sync_idle_mode
    from arelis.ui.theme import active_theme

    note_engagement(window)
    if not world_available():
        window.act_world.setChecked(False)
        if checked:
            window.thinking.append(
                "Reality's plate is a source-checkout stage — not in the installer.",
                kind="status",
            )
        return
    if checked:
        if not force and not should_offer_world(window.conversation.room.room_id):
            window.act_world.setChecked(False)
            window.thinking.append(
                "Reality is that room. Say let's work on Reality first.",
                kind="status",
            )
            return
        window._world_placed = show_world(
            window.world_window,
            window.frameGeometry(),
            page=page,
            placed=getattr(window, "_world_placed", False),
        )
        if active_theme() == "filament":
            window._filament_dress_tile(window.world_window, "reality")
            window._filament_place_near_title(window.world_window, "reality")
    else:
        if active_theme() == "filament":
            from arelis.ui.filament_tile import flush_tile_geom

            flush_tile_geom(window.world_window)
        hide_world(window.world_window)
    sync_idle_mode(window)


def hide_and_reset_world(window) -> None:
    """Reset the sandbox scene and hide the Reality plate."""
    window.world_scene.reset()
    if hasattr(window, "world_depth"):
        window.world_depth.reset()
    hide_world(getattr(window, "world_window", None))
    plate = getattr(window, "world_window", None)
    if plate is not None:
        plate.panel.refresh()
    if hasattr(window, "act_world"):
        window.act_world.setChecked(False)


def try_physics_verb(window, text: str) -> bool:
    """Closed lexicon in this room. True when it must not start a turn."""
    act = classify_physics_act(text, names=speech_body_names())
    if not act:
        return False
    in_reality = window.conversation.room.room_id == PHYSICS_ROOM_ID
    if not in_reality and act.verb != "goto_earth":
        return False
    apply_physics_act(window, act)
    return True


def apply_physics_verb(
    window,
    verb: str,
    *,
    name: str = "",
    flag: str = "",
    on: bool | None = None,
    page: str = "",
) -> None:
    apply_physics_act(
        window,
        PhysicsAct(verb=verb, name=name, flag=flag, on=on, page=page),
    )


def apply_physics_act(window, act: PhysicsAct) -> None:
    from arelis.physics.runtime import get_system

    verb = act.verb
    if verb == "lab":
        apply_tile(window, "world", show=bool(act.on), page=act.page)
        return
    if verb == "overlay":
        apply_tile(window, "world", show=True, page="solar")
        system = get_system()
        if system is None:
            window.thinking.append("No solar system loaded", kind="status")
            return
        val = system.apply_overlay(act.flag, on=act.on)
        if val is None:
            window.thinking.append(f"unknown overlay {act.flag}", kind="status")
            return
        window.thinking.append(f"{act.flag}={val}", kind="status")
        touch_solar(window)
        return
    if verb == "travel":
        apply_tile(window, "world", show=True, page="solar")
        system = get_system()
        if system is None:
            window.thinking.append("No solar system loaded", kind="status")
            return
        name = (act.name or "").strip()
        if not name:
            name = ""
            if hasattr(window, "world_window"):
                name = str(window.world_window.solar._inspect or "")
            if not name:
                name = str(system.lock or "")
        if not name:
            window.thinking.append(
                "Name a body, or inspect one first.", kind="status"
            )
            return
        if system.nbody.find(name) is None:
            window.thinking.append(f"No body named {name!r}", kind="status")
            return
        system.lock = name
        system.pending_inspect = name
        system.pending_travel = name
        window.thinking.append(f"flying to {name}", kind="status")
        touch_solar(window)
        return
    if verb == "inspect_body":
        apply_tile(window, "world", show=True, page="solar")
        system = get_system()
        if system is None:
            window.thinking.append("No solar system loaded", kind="status")
            return
        name = (act.name or "").strip()
        if not name or system.nbody.find(name) is None:
            window.thinking.append(f"No body named {name!r}", kind="status")
            return
        system.lock = name
        system.pending_inspect = name
        window.thinking.append(f"inspecting {name}", kind="status")
        touch_solar(window)
        return
    if verb == "reset_view":
        apply_tile(window, "world", show=True, page="solar")
        system = get_system()
        if system is None:
            window.thinking.append("No solar system loaded", kind="status")
            return
        system.pending_reset = True
        window.thinking.append("reset view", kind="status")
        touch_solar(window)
        return
    if verb == "enter_earth":
        apply_tile(window, "world", show=True, page="solar")
        from arelis.earth.runtime import require_earth

        note = require_earth().enter()
        system = get_system()
        if system is not None and system.nbody.find("Earth") is not None:
            system.lock = "Earth"
            system.pending_inspect = "Earth"
            system.pending_travel = "Earth"
        window.thinking.append(note, kind="status")
        touch_solar(window)
        return
    if verb == "leave_earth":
        from arelis.earth.dump import dump_state
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is None or not zone.active:
            window.thinking.append("already solar", kind="status")
            return
        try:
            dump_state(zone, trigger="leave")
        except OSError:
            pass
        window.thinking.append(zone.leave(), kind="status")
        touch_solar(window)
        return
    if verb == "goto_earth":
        from arelis.earth.gazetteer import resolve_place
        from arelis.earth.runtime import require_earth

        query = (act.name or "").strip()
        zone = require_earth()
        hit = resolve_place(query, zone)
        if hit is None:
            if query.casefold() in {"home", "here"}:
                window.thinking.append(
                    "Set a home city in your profile first.", kind="status"
                )
                return
            window.thinking.append(
                f"I don't know a place named {query!r}.", kind="status"
            )
            return
        if not world_available():
            window.thinking.append(
                "Reality's plate is a source-checkout stage — not in the installer.",
                kind="status",
            )
            return
        toggle_world(window, True, page="solar", force=True)
        if not zone.active:
            zone.enter()
        zone.request_goto(hit)
        system = get_system()
        on_earth = False
        if hasattr(window, "world_window"):
            on_earth = getattr(window.world_window.solar, "_earth_cam", None) is not None
        if system is not None and system.nbody.find("Earth") is not None:
            system.lock = "Earth"
            system.pending_inspect = "Earth"
            if not on_earth:
                system.pending_travel = "Earth"
        window.thinking.append(f"flying to {hit.name}", kind="status")
        touch_solar(window)
        return
    if verb == "ride_iss":
        apply_tile(window, "world", show=True, page="solar")
        from arelis.earth.runtime import require_earth

        zone = require_earth()
        if not zone.active:
            zone.enter()
        hit = zone.ride("norad:25544")
        system = get_system()
        if system is not None:
            system.lock = "Earth"
            system.pending_inspect = "Earth"
            system.pending_travel = "Earth"
        window.thinking.append(
            f"riding {hit.label}" if hit else "ISS not in the store",
            kind="status",
        )
        touch_solar(window)
        return
    if is_time_verb(verb):
        system = get_system()
        if system is None:
            window.thinking.append("No solar system loaded", kind="status")
            return
        if verb == "pause":
            system.paused = True
        elif verb == "resume":
            system.paused = False
        elif verb == "step":
            system.step_once()
        elif verb == "faster":
            system.set_rate(min(1.0e7, system.rate * 10.0))
        elif verb == "slower":
            system.set_rate(system.rate / 10.0)
        elif verb == "realtime":
            system.go_realtime()
        elif verb == "hour":
            system.set_rate(3_600.0)
        elif verb == "day":
            system.set_rate(86_400.0)
        elif verb == "year":
            system.set_rate(365.25 * 86_400.0)
        elif verb == "fly":
            system.enter_inspect()
        elif verb == "inspect":
            system.enter_inspect()
        window.thinking.append(
            f"{verb}  rate={system.rate:g}  t={system.t:.3e}s",
            kind="status",
        )
        touch_solar(window)
        return
    system = get_system()
    if system is not None and is_toy_verb(verb):
        if verb == "freeze":
            system.paused = True
            window.thinking.append("pause  (freeze is the sandbox word)", kind="status")
            return
        if verb == "unfreeze":
            system.paused = False
            window.thinking.append("resume  (unfreeze is the sandbox word)", kind="status")
            return
        window.thinking.append(
            "No discs in Reality. Spawn a particle, belt tracer, or L4 from "
            "the ⋯ menu. WASD flies the inspect camera. heavier/lighter would "
            "change a mass — that is solar impulse/add_planet with Allow.",
            kind="status",
        )
        return
    result = window.world_scene.apply_verb(verb)
    if hasattr(window, "world_window"):
        window.world_window.panel.refresh()
    if result:
        mass = result.get("mass")
        frozen = result.get("frozen")
        bits = [str(result.get("verb") or verb)]
        if isinstance(mass, (int, float)):
            bits.append(f"{mass:.2f}×")
        if frozen:
            bits.append("frozen")
        window.thinking.append(" ".join(bits), kind="status")
    else:
        window.thinking.append("Nothing is held", kind="status")


def touch_solar(window) -> None:
    if hasattr(window, "world_window") and window.world_window.solar_active():
        window.world_window.solar.update()


def _dock_toggle(window, key: str):
    """View-menu dock: window_docks.toggle_* if present, else window._toggle_*."""
    docks = None
    try:
        from arelis.ui import window_docks as docks
    except ImportError:
        docks = None
    name = f"toggle_{key}"
    if docks is not None:
        fn = getattr(docks, name, None)
        if callable(fn):
            return lambda show, _fn=fn: _fn(window, show)
    return getattr(window, f"_{name}")


def apply_tile(window, name: str, *, show: bool, page: str = "") -> None:
    """Show or hide a View-menu tile from the tile tool."""
    from arelis.ui.theme import active_theme

    key = (name or "").strip().lower()
    mapping = {
        "thinking": window.act_thinking,
        "workspace": window.act_workspace,
        "history": window.act_history,
        "notifications": window.act_notifications,
        "camera": window.act_camera,
        "contacts": window.act_contacts,
        "calendar": window.act_calendar,
        "world": window.act_world,
    }
    if key == "chat":
        if active_theme() == "filament":
            window._filament_set_chat_open(show)
        return
    action = mapping.get(key)
    if action is None:
        return
    action.setChecked(show)
    if key == "world":
        toggle_world(window, show, page=page)
        return
    if key in _DOCK_TILES:
        _dock_toggle(window, key)(show)
        return


def on_world_window_closed(window) -> None:
    from arelis.ui.idle_host import sync_idle_mode

    window.act_world.setChecked(False)
    window._calendar_sync_timer.stop()
    window._calendar_sync_watchdog.stop()
    sync_idle_mode(window)


def bind_world(window) -> None:
    """Wire Reality chip and plate-closed onto this window."""
    window.conversation.world_requested.connect(lambda: open_world(window))
    window.world_window.closed.connect(lambda: on_world_window_closed(window))
