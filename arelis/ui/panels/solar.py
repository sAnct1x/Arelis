"""True-scale solar view.

IAU spheres, 1/r² sun, cited albedo if a map is on disk. Inspect-only fly
camera. Overlay flags live on SolarSystem.overlay. No rideable craft.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import UTC, datetime

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFont,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import QApplication, QWidget

from arelis.physics.camera import (
    SOLAR_SPAN_M,
    SPEED_MAX,
    CameraWarp,
    FlyCamera,
    overview_distance,
    project_with_basis,
)
from arelis.physics.clocks import (
    RATE_DAY,
    RATE_HOUR,
    RATE_YEAR,
)
from arelis.physics.constants import (
    AU_M,
    BODIES,
    BODY_BY_NAME,
    PLANET_NAMES,
)
from arelis.physics.evolution import sample, sun_rgb
from arelis.physics.maps import forget_ready
from arelis.physics.runtime import get_system
from arelis.physics.scene import BodyView, SolarSystem
from arelis.ui.earth_overlay import (
    hit_entity,
    hit_geo,
    look_from_pose,
    ride_pose,
)
from arelis.ui.panels.solar_const import (  # noqa: F401
    _CLOSE_GLOBE_PX,
    _FILL,
    _GLOBE_MAX,
    _HUD_GAP,
    _HUD_LANE,
    _HUD_MAX_W,
    _HUD_MIN_W,
    _IDLE_PX,
    _KEYS_ROW,
    _LEGEND_BLOCK,
    _LEGEND_ROW,
    _ROSTER_GAP,
    _ROSTER_MAX_ROWS,
    _ROSTER_ROW,
    _TINT,
    HELP_HOTKEYS,
    KEY_HINT,
    KEY_HINT_EARTH,
    KEY_LEGEND,
    KEY_STRIP,
    SOLAR_OVERLAY,
    SOLAR_SPAWN,
    _albedo,
    _Basis,
    _cache,
    _fmt_m,
    _globe,
    _is_sketch,
    _on_frame,
    _sample_albedo,
    _sphere_axes,
    _wash,
    _world_normals,
)
from arelis.ui.panels.solar_paint import (
    build_inspect_lines,
    chip_rects,
    chrome_covers,
    chrome_rects,
    close_globe,
    confirm_apply,
    confirm_chip_rects,
    confirm_click,
    confirm_hit,
    confirm_rect,
    dots_rect,
    earth_chip_at,
    earth_chip_layout,
    earth_limb,
    empty_caption,
    epoch_rect,
    facing,
    hud_plate_rect,
    hud_plate_width,
    hud_status_lines,
    inspect_body_height,
    inspect_close_rect,
    inspect_column_width,
    inspect_font,
    inspect_lines,
    inspect_rect,
    inspect_travel_rect,
    key_strip_chips,
    keys_chrome_height,
    keys_footer,
    label_body,
    legend_columns,
    legend_items,
    light_cam,
    look_field_m,
    maps_alert,
    on_globe,
    open_impulse_confirm,
    open_planet_confirm,
    overlay_on,
    paint_body,
    paint_chip,
    paint_confirm,
    paint_earth_card,
    paint_earth_toggles,
    paint_ecliptic,
    paint_epoch,
    paint_free_markers,
    paint_g,
    paint_grid,
    paint_heliocentric_orbits,
    paint_hud,
    paint_inspect,
    paint_keys_chrome,
    paint_lagrange,
    paint_magnetopause,
    paint_overlay,
    paint_plate,
    paint_saturn_rings,
    paint_speed,
    paint_sphere_cage,
    paint_sun_loops,
    paint_tools,
    paint_trails,
    paint_well_slice,
    paint_wells,
    paint_wind,
    ring_xy,
    set_epoch_from_x,
    spark,
    spawn,
    spawn_hit,
    speed_rect,
    start_earth_live,
    stroke_loop,
    stroke_world,
    sun_limb,
    toggle_earth_chip,
    toggle_overlay,
    tools_rect,
    u_from_x,
    wrapped_h,
)
from arelis.ui.theme import color


def _emit_earth_lock(on: bool) -> None:
    try:
        from arelis.physics.telemetry import emit

        emit("earth_lock", on=on)
    except Exception:
        pass


class SolarPanel(QWidget):
    """True-scale solar system in Reality. OpenGL space when the context lives."""

    toy_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SolarPanel")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(False)
        self.cam = FlyCamera()
        self._drag: tuple[float, float] | None = None
        self._epoch_drag = False
        self._maps_note = ""
        self._maps_pending: tuple[list[str], list[str]] | bool | None = None
        self._maps_tried = False
        self._load_pending = False
        self._load_result = None
        self._load_progress = ""
        self._load_refresh = False
        self._ic_date = datetime.now(UTC).date().isoformat()
        self._confirm: dict[str, str | float] | None = None
        self._hand_span: float | None = None
        self._hand_z: float | None = None
        self._fitted_lock: str | None = None
        self._view_id = 0
        self._inspect: str | None = None
        self._earth_id: str | None = None
        self._earth_cam = None
        self._earth_fly = None
        self._place: dict | None = None
        self._earth_card_box = QRect()
        self._look_session = None
        self._look_frame = None
        self._look_status = ""
        self._inspect_more = False
        self._roster_scroll = 0
        self._hud_bottom = 120
        self._hud_box = QRect()
        self._keys_hit = QRect()
        self._keys_toggle = QRect()
        self._earth_chip_hits: list[tuple[str, QRect]] = []
        self._earth_chip_box = QRect()
        self._earth_live_busy = False
        self._earth_live_done = False
        self._earth_find_on = False
        self._earth_find_q = ""
        self._earth_find_ix = 0
        self._earth_find_hits = []
        self._earth_find_box = QRect()
        self._earth_find_field = QRect()
        self._earth_find_hit_rects = []
        self._earth_coach_box = QRect()
        self._earth_key_hits = []
        self._earth_key_box = QRect()
        self._earth_paste_field = ""
        self._earth_paste_buf = ""
        self._drawn_labels: list[tuple[str, int, int, int]] = []
        self._cover: tuple[float, float, float] | None = None
        self._press: tuple[float, float] | None = None
        self._look_drag = False
        self._speed_drag = False
        self.menu_up = False
        self._keys: set[int] = set()
        self._help = False
        self._tools_open = False
        self._eye = (0.0, 0.0, 0.0)
        self._look = (1.0, 0.0, 0.0)
        self._basis: _Basis = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        self._clock = QTimer(self)
        self._clock.setInterval(16)
        self._clock.timeout.connect(self._tick)
        self._watch = QTimer(self)
        self._watch.setInterval(100)
        self._watch.timeout.connect(self._ingest_background)
        self._space = None
        self._gl = None
        self._reset_pending = False
        self._tick_t = time.perf_counter()
        self._fly_v = [0.0, 0.0, 0.0]
        self._warp: CameraWarp | None = None
        self._roster_key: object = None
        self._roster_cache: list[str] | None = None
        self._chrome_key: object = None
        self._chrome_cache: list[QRect] | None = None
        self._inspect_key: object = None
        self._inspect_cache: list[str] | None = None
        self._label_w: dict[str, int] = {}
        self._painted_t = 0.0
        self._painted_wall = 0.0
        self._painted_note = ""
        self._tile_gen = 0
        self._globe_host = None
        self._globe_mounting = False
        self._stars_hold: QImage | None = None
        self._earth_hud = None
        self._globe_cam_push = 0.0
        self._globe_data_push = 0.0
        self._globe_hpr: tuple[float, float] | None = None

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._tick_t = time.perf_counter()
        self._clock.start()
        self._watch.start()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self._ensure_ic()
        self._ensure_space()

    def camera_state(self) -> dict[str, float | list[float]]:
        """Eye in ECLIPJ2000 metres. For the leave receipt. Not a particle."""
        cam = self.cam
        return {
            "x": cam.x,
            "y": cam.y,
            "z": cam.z,
            "yaw": cam.yaw,
            "pitch": cam.pitch,
            "up": [cam.up[0], cam.up[1], cam.up[2]],
        }

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_earth_globe()

    def _ensure_space(self) -> None:
        from arelis.ui.solar_gl import SolarSpaceView, arm_fault_log, gl_wanted, trace

        if self._gl is not None:
            return
        if not gl_wanted():
            trace("skip GPU: ARELIS_SOLAR_GL is not 1 (software globes)")
            return
        trace("ensure_space: GPU requested (offscreen, not a Qt window)")
        arm_fault_log()
        self._gl = SolarSpaceView(self)
        self._gl.realize()
        if self._gl.gl_ok:
            trace("ensure_space: realize ok")
        else:
            trace("ensure_space: realize failed, software globes")

    def _space_live(self) -> bool:
        return self._gl is not None and bool(self._gl.gl_ok)

    def _tint_for(self, name: str, system: SolarSystem) -> tuple[int, int, int]:
        tint = _TINT.get(name, (200, 180, 160))
        if name == "Sun" and abs(system.future_gyr) > 1e-6:
            return sun_rgb(sample(system.future_gyr))
        return tint

    def hideEvent(self, event) -> None:
        self._clock.stop()
        self._watch.stop()
        self._close_earth_look()
        super().hideEvent(event)

    def _ensure_ic(self) -> None:
        if get_system() is None:
            if not self._try_nearest_cache():
                self._load_kepler_bootstrap()
        if self._load_pending:
            self._ensure_maps()
            return
        if self._needs_horizons():
            self.start_horizons_load()
        self._ensure_maps()

    def _ensure_maps(self) -> None:
        """One background NASA fetch if a catalogued map is missing. No retry loop."""
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        if self._maps_tried or self._maps_pending is not None:
            return
        from arelis.physics.maps import missing_maps

        if not missing_maps():
            return
        self._start_maps()

    def _needs_horizons(self) -> bool:
        system = get_system()
        if system is None:
            return True
        if system.counterfactual:
            return False
        return "not Horizons" in (system.epoch_tdb or "")

    def _ingest_background(self) -> bool:
        dirty = False
        loaded = self._load_result
        if loaded is not None:
            dirty = True
            self._load_result = None
            self._load_pending = False
            if loaded.ok:
                system = get_system()
                ox, oy, oz = self._anchor()
                r = math.hypot(self.cam.x - ox, self.cam.y - oy, self.cam.z - oz)
                cap = overview_distance(self._system_span(system))
                if r >= cap * 0.5:
                    self.reset_view(keep_inspect=True)
                if system is not None and system.ic_date:
                    self._ic_date = system.ic_date
                self._maps_note = (
                    system.ic_caption() if system is not None else loaded.output
                )
            else:
                self._on_horizons_fail()
            self._load_progress = ""
        pending = self._maps_pending
        if isinstance(pending, tuple):
            dirty = True
            saved, errors = pending
            self._maps_pending = None
            _cache.clear()
            forget_ready()
            if self._gl is not None:
                self._gl.invalidate_maps()
            if saved:
                self._maps_note = (
                    "albedo: " + ", ".join(saved) + " (NASA public domain, approach only)"
                )
            elif errors:
                self._maps_note = "maps failed: " + "; ".join(errors[:3])
            else:
                self._maps_note = (
                    "albedo already on disk (NASA public domain, approach only)"
                )
        if self._earth_live_done:
            dirty = True
            self._earth_live_done = False
            self._earth_live_busy = False
        return dirty

    def _on_horizons_fail(self) -> None:
        if get_system() is None:
            self._try_nearest_cache()
        if get_system() is None:
            self._load_kepler_bootstrap()
        if get_system() is None:
            self._maps_note = "No solar system loaded."

    def _try_nearest_cache(self) -> bool:
        from arelis.physics.engine import rebound_available
        from arelis.physics.ic_store import nearest_cached
        from arelis.physics.runtime import set_system
        from arelis.physics.scene import SolarSystem

        if not rebound_available():
            return False
        found = nearest_cached(self._ic_date)
        if found is None:
            return False
        day, states = found
        if "Sun" not in states:
            return False
        try:
            system = SolarSystem.from_states(
                states,
                tracers=0,
                epoch_tdb=f"JPL Horizons VECTORS, {day} (cached fetch)",
                ic_date=day,
            )
        except Exception:
            return False
        set_system(system)
        system.sync_to_now()
        self.reset_view()
        self._ic_date = day
        self._maps_note = system.ic_caption()
        return True

    def _load_kepler_bootstrap(self) -> None:
        from arelis.physics.demo import circular_system
        from arelis.physics.engine import rebound_available
        from arelis.physics.runtime import set_system
        from arelis.physics.scene import SolarSystem

        if not rebound_available():
            self._maps_note = "REBOUND is not installed."
            return
        try:
            system = SolarSystem.from_states(
                circular_system(),
                tracers=0,
                epoch_tdb="Placeholder orbits, not Horizons. Waiting on JPL.",
            )
        except Exception as exc:
            self._maps_note = str(exc)
            return
        set_system(system)
        self.reset_view()
        self._maps_note = system.ic_caption()

    def _tick(self) -> None:
        dt = self._frame_dt()
        ingested = self._ingest_background()
        system = get_system()
        if system is not None and not self.menu_up:
            if system.pending_inspect:
                self._set_inspect(system.pending_inspect)
                system.pending_inspect = None
            if system.pending_reset:
                system.pending_reset = False
                self.reset_view(keep_inspect=True)
            if system.pending_travel:
                name = system.pending_travel
                system.pending_travel = None
                self._travel_to(name)
            self._apply_pending_earth_goto()
            if self._warp is not None:
                self._step_warp(system, dt)
            else:
                self._step_earth_fly(dt)
                self._hold_earth_eye(system)
                self._follow_earth_ride(system)
                self._sync_earth_look()
                self._fly_camera(dt)
                self._remember_earth_eye(system)
                self._sync_earth_globe()
            if not system.paused:
                system.tick(dt)
            self._hold_earth_eye(system)
        if ingested or self._view_dirty(system):
            self.update()

    def _view_dirty(self, system: SolarSystem | None) -> bool:
        held = bool(self._keys)
        v = self._fly_v
        speed2 = v[0] * v[0] + v[1] * v[1] + v[2] * v[2]
        if not held and speed2 < 1e-6:
            v[0] = v[1] = v[2] = 0.0
            speed2 = 0.0
        if held or speed2 > 0.0:
            return True
        if self._warp is not None:
            return True
        if self._earth_fly is not None:
            return True
        if self._maps_note != self._painted_note:
            return True
        if system is None:
            return False
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is not None and zone.active:
            try:
                from arelis.earth.tiles import tile_generation

                gen = tile_generation()
            except Exception:
                gen = 0
            if gen != getattr(self, "_tile_gen", 0):
                self._tile_gen = gen
                return True
            if (
                zone.live
                and not system.paused
                and time.perf_counter() - self._painted_wall >= 2.0
            ):
                return True
        # Dipole flares and granulation run on wall time, even while IAS15 is paused.
        if system.paused:
            wait = 0.16 if system.show_osculating else 0.32
            return time.perf_counter() - self._painted_wall >= wait
        if self._motion_px(system) >= _IDLE_PX:
            return True
        if system.show_osculating:
            return time.perf_counter() - self._painted_wall >= 0.16
        # The key legend is static; sparklines still move on a paused clock.
        if self._help or system.show_graphs:
            return time.perf_counter() - self._painted_wall >= 0.25
        return False

    def _motion_px(self, system: SolarSystem) -> float:
        """Largest on-screen shift since the last paint, in pixels.

        Running at an hour per second from the overview moves every planet by a
        fraction of a pixel per frame. Repainting that was the run-idle burn.
        """
        dt = system.t - self._painted_t
        if dt <= 0.0:
            return 0.0
        scale = self.height() / 1.4
        ex, ey, ez = self.cam.x, self.cam.y, self.cam.z
        worst = 0.0
        for p in system.nbody.particles:
            if p.tracer:
                continue
            dx, dy, dz = p.x - ex, p.y - ey, p.z - ez
            depth = math.sqrt(dx * dx + dy * dy + dz * dz)
            speed = math.sqrt(p.vx * p.vx + p.vy * p.vy + p.vz * p.vz)
            rate = speed / max(depth, 1.0)
            if rate > worst:
                worst = rate
        return worst * scale * dt

    def _frame_dt(self) -> float:
        now = time.perf_counter()
        dt = min(0.05, max(1e-4, now - self._tick_t))
        self._tick_t = now
        return dt

    def _held(self, key: int) -> bool:
        return int(key) in self._keys

    def _fly_camera(self, dt: float) -> None:
        fwd = (1.0 if self._held(Qt.Key.Key_W) else 0.0) - (
            1.0 if self._held(Qt.Key.Key_S) else 0.0
        )
        right = (1.0 if self._held(Qt.Key.Key_D) else 0.0) - (
            1.0 if self._held(Qt.Key.Key_A) else 0.0
        )
        up = (1.0 if self._held(Qt.Key.Key_E) else 0.0) - (
            1.0 if self._held(Qt.Key.Key_Q) else 0.0
        )
        mag = math.sqrt(fwd * fwd + right * right + up * up)
        if mag > 1.0:
            fwd, right, up = fwd / mag, right / mag, up / mag
        blend = 1.0 - math.exp(-dt / 0.12)
        v = self._fly_v
        v[0] += (fwd - v[0]) * blend
        v[1] += (right - v[1]) * blend
        v[2] += (up - v[2]) * blend
        self._camera_fly(v[0], v[1], v[2], dt)
        turn = 1.35 * dt
        if self._held(Qt.Key.Key_Left):
            self.cam.look(turn, 0.0)
        if self._held(Qt.Key.Key_Right):
            self.cam.look(-turn, 0.0)
        if self._held(Qt.Key.Key_Up):
            self.cam.look(0.0, turn)
        if self._held(Qt.Key.Key_Down):
            self.cam.look(0.0, -turn)

    def apply_hand(
        self,
        ndc_x: float,
        ndc_y: float,
        *,
        pinched: bool,
        span: float,
        palm_z: float | None,
    ) -> None:
        """Palm z is camera dolly, not a physics coordinate."""
        if self._warp is not None:
            return
        if not pinched:
            self._hand_span = None
            self._hand_z = None
            self._drag = None
            return
        if self._drag is None:
            self._drag = (ndc_x, ndc_y)
            self._hand_span = span
            self._hand_z = palm_z
            return
        ox, oy = self._drag
        dyaw, dpitch = (ox - ndc_x) * 2.4, (oy - ndc_y) * 2.4
        self.cam.look(dyaw, dpitch)
        if self._hand_span and span > 1e-4:
            self.cam.nudge_speed(span / max(self._hand_span, 1e-4))
            self._hand_span = span
        if palm_z is not None:
            if self._hand_z is None:
                self._hand_z = palm_z
            else:
                self.cam.nudge_speed(1.0 + (palm_z - self._hand_z) * 1.4)
                self._hand_z = palm_z
        self._drag = (ndc_x, ndc_y)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        px, py = event.position().x(), event.position().y()
        if event.button() == Qt.MouseButton.LeftButton:
            if self._confirm is not None:
                hit = self._confirm_hit(px, py)
                if hit:
                    self._confirm_click(hit)
                return
            if self._dots_rect().contains(int(px), int(py)):
                self._tools_open = not self._tools_open
                self.update()
                return
            if self._keys_toggle.contains(int(px), int(py)):
                self._help = not self._help
                self.update()
                return
            from arelis.ui.earth_chrome import begin_paste, key_chip_at
            from arelis.ui.earth_find import apply_goto, hit_find, open_find

            key_field = key_chip_at(self, px, py)
            if key_field:
                begin_paste(self, key_field)
                return
            find_hit = hit_find(self, px, py)
            if find_hit == "field":
                open_find(self)
                return
            if isinstance(find_hit, int):
                apply_goto(self, find_hit)
                return
            earth_kind = self._earth_chip_at(px, py)
            if earth_kind:
                self._toggle_earth_chip(earth_kind)
                return
            if self._tools_open:
                kind = self._spawn_hit(px, py)
                if kind:
                    stay = self._toggle_overlay(kind)
                    if not stay:
                        self._spawn(kind)
                        self._tools_open = False
                    self.update()
                    return
            if self._inspect and self._inspect_close_rect().contains(int(px), int(py)):
                self._set_inspect(None)
                self.update()
                return
            if self._inspect and self._inspect_travel_rect().contains(int(px), int(py)):
                from arelis.earth.runtime import get_earth

                zone = get_earth()
                if (
                    self._inspect == "Earth"
                    and zone is not None
                    and zone.active
                ):
                    self._leave_earth_zone()
                else:
                    self._travel_to(self._inspect)
                return
            roster_hit = self._roster_hit(px, py)
            if roster_hit is not None:
                self._set_inspect(roster_hit)
                self.update()
                return
            if self._inspect and self._inspect_rect().contains(int(px), int(py)):
                return
            system = get_system()
            if system is not None and self._speed_rect().contains(int(px), int(py)):
                self._speed_drag = True
                self.cam.set_speed_u(self._u_from_x(self._speed_rect(), px))
                self.update()
                return
            if system is not None and self._epoch_rect().contains(int(px), int(py)):
                self._epoch_drag = True
                self._set_epoch_from_x(system, px)
                self.update()
                return
            self._press = (px, py)
            self._look_drag = False
            self._drag = None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        x, y = event.position().x(), event.position().y()
        if self._speed_drag:
            self.cam.set_speed_u(self._u_from_x(self._speed_rect(), x))
            self.update()
            return
        if self._epoch_drag:
            system = get_system()
            if system is not None:
                self._set_epoch_from_x(system, x)
            self.update()
            return
        if self._press is not None and not self._look_drag:
            ox, oy = self._press
            if math.hypot(x - ox, y - oy) > 6.0:
                self._look_drag = True
                self._drag = self._press
        if self._drag is None:
            if self._press is None and not self._speed_drag and not self._epoch_drag:
                over_chrome = self._chrome_covers(int(x), int(y))
                hit = None if over_chrome else self._body_at(x, y)
                over_keys = self._keys_toggle.contains(int(x), int(y))
                over_earth = self._earth_chip_at(x, y) is not None
                self.setCursor(
                    Qt.CursorShape.PointingHandCursor
                    if hit or over_keys or over_earth
                    else Qt.CursorShape.ArrowCursor
                )
            return
        ox, oy = self._drag
        dyaw, dpitch = (ox - x) * 0.0036, (oy - y) * 0.0036
        self.cam.look(dyaw, dpitch)
        self._remember_earth_eye()
        self._drag = (x, y)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if (
                self._press is not None
                and not self._look_drag
                and not self._epoch_drag
                and not self._speed_drag
            ):
                self._inspect_at(*self._press)
            self._drag = None
            self._press = None
            self._look_drag = False
            self._epoch_drag = False
            self._speed_drag = False

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        name = self._body_at(event.pos().x(), event.pos().y())
        if name:
            self._travel_to(name)
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            px, py = event.position().x(), event.position().y()
            if self._chrome_covers(int(px), int(py)):
                event.accept()
                return
            system = get_system()
            if system is not None:
                hit = hit_entity(self, system, px, py)
                if hit is not None:
                    self._select_earth_entity(hit, ride=True)
                    event.accept()
                    return
            name = self._body_at(px, py)
            if name:
                self._travel_to(name)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            from arelis.ui.earth_chrome import cancel_paste
            from arelis.ui.earth_find import close_find

            if str(getattr(self, "_earth_paste_field", "") or ""):
                cancel_paste(self)
                event.accept()
                return
            if getattr(self, "_earth_find_on", False):
                close_find(self)
                event.accept()
                return
            if self._confirm is not None:
                self._confirm = None
                self.update()
                event.accept()
                return
            win = self.window()
            escape = getattr(win, "_escape", None)
            if callable(escape):
                escape()
            event.accept()
            return
        if self._earth_key_event(event):
            event.accept()
            return
        mods = event.modifiers()
        if mods & (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        ):
            super().keyPressEvent(event)
            return
        if event.isAutoRepeat() or self.menu_up:
            return
        self._keys.add(int(event.key()))
        self._hotkey(event.key())
        # Pause, O, H and the rate keys all change a still frame.
        self.update()
        event.accept()

    def _earth_key_event(self, event: QKeyEvent) -> bool:
        """Find, key paste, and slash. True when the plate consumed the key."""
        from arelis.ui.earth_chrome import (
            backspace_paste,
            commit_paste,
            type_paste,
        )
        from arelis.ui.earth_find import (
            apply_goto,
            backspace_find,
            move_find,
            open_find,
            type_find,
        )

        paste_on = bool(str(getattr(self, "_earth_paste_field", "") or ""))
        find_on = bool(getattr(self, "_earth_find_on", False))
        if event.matches(QKeySequence.StandardKey.Paste):
            clip = QApplication.clipboard().text() if QApplication.clipboard() else ""
            if paste_on:
                type_paste(self, clip)
                return True
            if find_on:
                type_find(self, clip)
                return True
        if paste_on:
            if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                commit_paste(self)
                return True
            if event.key() == Qt.Key.Key_Backspace:
                backspace_paste(self)
                return True
            text = event.text()
            if text and text.isprintable():
                type_paste(self, text)
                return True
            return True
        if find_on:
            if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                apply_goto(self)
                return True
            if event.key() == Qt.Key.Key_Backspace:
                backspace_find(self)
                return True
            if event.key() == Qt.Key.Key_Up:
                move_find(self, -1)
                return True
            if event.key() == Qt.Key.Key_Down:
                move_find(self, 1)
                return True
            text = event.text()
            if text and text.isprintable():
                type_find(self, text)
                return True
            return False
        if event.key() == Qt.Key.Key_Slash and self._earth_zone_on():
            open_find(self)
            return True
        return False

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.isAutoRepeat():
            return
        self._keys.discard(int(event.key()))
        event.accept()

    def _hotkey(self, key: int) -> None:
        system = get_system()
        if system is None:
            return
        if key == Qt.Key.Key_Space:
            system.paused = not system.paused
        elif key == Qt.Key.Key_1:
            system.go_realtime()
        elif key == Qt.Key.Key_2:
            if not self._earth_zone_on():
                system.set_rate(RATE_HOUR)
        elif key == Qt.Key.Key_3:
            if not self._earth_zone_on():
                system.set_rate(RATE_DAY)
        elif key == Qt.Key.Key_4:
            if not self._earth_zone_on():
                system.set_rate(RATE_YEAR)
        elif key == Qt.Key.Key_BracketRight or key == Qt.Key.Key_Equal:
            if not self._earth_zone_on():
                system.set_rate(system.rate * 10.0)
        elif key == Qt.Key.Key_BracketLeft or key == Qt.Key.Key_Minus:
            if not self._earth_zone_on():
                system.set_rate(system.rate / 10.0)
        elif key == Qt.Key.Key_G:
            system.overlay.show_gravity = not system.overlay.show_gravity
        elif key == Qt.Key.Key_M:
            system.overlay.show_magnetic = not system.overlay.show_magnetic
        elif key == Qt.Key.Key_P:
            system.overlay.show_wind = not system.overlay.show_wind
        elif key == Qt.Key.Key_Semicolon:
            system.overlay.show_grid = not system.overlay.show_grid
        elif key == Qt.Key.Key_H:
            self._help = not self._help
        elif key == Qt.Key.Key_O:
            system.show_osculating = not system.show_osculating
        elif key == Qt.Key.Key_L:
            system.show_lagrange = not system.show_lagrange
        elif key == Qt.Key.Key_Backslash:
            from arelis.earth.runtime import get_earth

            zone = get_earth()
            if zone is None or not zone.active:
                system.toggle_warp()
        elif key == Qt.Key.Key_T:
            system.show_trails = not system.show_trails
        elif key == Qt.Key.Key_QuoteLeft:
            system.show_graphs = not system.show_graphs
        elif key == Qt.Key.Key_Comma:
            self._cycle_inspect(-1)
        elif key == Qt.Key.Key_Period:
            self._cycle_inspect(1)
        elif key in (Qt.Key.Key_Home, Qt.Key.Key_R):
            self.reset_view(keep_inspect=True)
            self.update()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._confirm is not None:
                self._confirm_click("apply")
            elif self._inspect:
                self._travel_to(self._inspect)

    def _begin_view(self, system: SolarSystem) -> None:
        fx, fy, fz = self.cam.forward()
        self._eye = (self.cam.x, self.cam.y, self.cam.z)
        self._look = (self.cam.x + fx, self.cam.y + fy, self.cam.z + fz)
        self._basis = self.cam.basis()

    def _proj(
        self, point: tuple[float, float, float]
    ) -> tuple[float, float, float] | None:
        return project_with_basis(
            point,
            self._eye,
            self._basis,
            self.width(),
            self.height(),
            fov_y=self._fov_y(),
        )

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.pixelDelta().y()
        pos = event.position()
        if self._roster_rect().contains(int(pos.x()), int(pos.y())):
            step = -1 if delta > 0 else 1
            self._roster_scroll = max(0, self._roster_scroll + step)
            event.accept()
            self.update()
            return
        over_speed = self._speed_rect().contains(int(pos.x()), int(pos.y()))
        if over_speed or event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.cam.nudge_speed(0.85 if delta < 0 else 1.18)
        elif self._earth_globe_live() and not self._chrome_covers(
            int(pos.x()), int(pos.y())
        ):
            event.ignore()
            return
        elif delta != 0:
            if self._warp is None:
                self._camera_fly(1.0 if delta > 0 else -1.0, 0.0, 0.0, 0.20)
        event.accept()
        self.update()

    def _inspect_at(self, px: float, py: float) -> None:
        system = get_system()
        if system is not None:
            hit = hit_entity(self, system, px, py)
            if hit is not None:
                self._place = None
                self._select_earth_entity(hit, ride=hit.layer == "cameras")
                return
            from arelis.earth.runtime import get_earth

            zone = get_earth()
            if zone is not None and zone.active:
                geo = hit_geo(self, system, px, py)
                if geo is not None:
                    self._select_earth_place(geo)
                    return
        name = self._body_at(px, py)
        if name:
            self._earth_id = None
            self._place = None
            self._close_earth_look()
            self._set_inspect(name)
        elif not self._inspect_rect().contains(int(px), int(py)):
            from arelis.earth.runtime import get_earth

            zone = get_earth()
            if zone is not None:
                zone.stop_ride()
                zone.track_id = ""
            self._earth_id = None
            self._place = None
            self._close_earth_look()
            self._set_inspect(None)
            self.update()

    def _select_earth_entity(self, hit, *, ride: bool) -> None:
        from arelis.earth.runtime import get_earth

        self._earth_id = hit.id
        zone = get_earth()
        if zone is not None:
            if ride:
                zone.ride(hit.id)
            else:
                zone.stop_ride()
                zone.track(hit.id)
        self._open_earth_look(hit)
        self.update()

    def _select_earth_place(self, geo: dict) -> None:
        from arelis.earth.frames import EarthCam, nadir_cam
        from arelis.earth.runtime import get_earth

        self._earth_id = None
        self._close_earth_look()
        self._place = geo
        zone = get_earth()
        if zone is not None:
            zone.stop_ride()
            zone.track_id = ""
        if self._earth_cam is None:
            self._remember_earth_eye()
        kind = str(geo.get("kind") or "earth")
        alt = {
            "city": 80_000.0,
            "home": 80_000.0,
            "contact": 80_000.0,
            "state": 350_000.0,
            "province": 350_000.0,
            "country": 1_100_000.0,
            "continent": 5_000_000.0,
        }.get(kind, 2_400_000.0)
        dest = nadir_cam(float(geo["lat"]), float(geo["lon"]), alt)
        start = self._earth_cam if isinstance(self._earth_cam, EarthCam) else dest
        self._earth_fly = {"start": start, "end": dest, "t": 0.0, "dur": 1.05}
        self._earth_cam = start
        self.update()

    def _step_earth_fly(self, dt: float) -> None:
        flight = self._earth_fly
        if not isinstance(flight, dict):
            return
        start = flight.get("start")
        end = flight.get("end")
        if start is None or end is None:
            self._earth_fly = None
            return
        dur = max(0.2, float(flight.get("dur") or 1.0))
        t = min(1.0, float(flight.get("t") or 0.0) + dt / dur)
        flight["t"] = t
        u = t * t * (3.0 - 2.0 * t)

        def mix(
            a: tuple[float, float, float], b: tuple[float, float, float]
        ) -> tuple[float, float, float]:
            return (
                a[0] + (b[0] - a[0]) * u,
                a[1] + (b[1] - a[1]) * u,
                a[2] + (b[2] - a[2]) * u,
            )

        from arelis.earth.frames import EarthCam

        self._earth_cam = EarthCam(
            eye=mix(start.eye, end.eye),
            look=mix(start.look, end.look),
            up=mix(start.up, end.up),
        )
        if t >= 1.0:
            self._earth_cam = end
            self._earth_fly = None
        if self._earth_globe_live():
            self._push_globe_camera()

    def _leave_earth_zone(self) -> None:
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is not None:
            zone.stop_ride()
            zone.leave()
        self._earth_cam = None
        self._earth_fly = None
        self._earth_id = None
        self._place = None
        self._close_earth_look()
        self._leave_earth_globe()
        self._globe_hpr = None
        self.update()

    def _earth_zone_on(self) -> bool:
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        return zone is not None and zone.active

    def _earth_globe_live(self) -> bool:
        host = self._globe_host
        return host is not None and not host.failed and host.isVisible()

    def _enter_earth_globe(self) -> None:
        system = get_system()
        if system is not None:
            try:
                system.go_realtime()
            except Exception:
                pass
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        self._park_space_for_earth()
        if self._globe_host is None:
            if getattr(self, "_globe_mounting", False):
                return
            self._globe_mounting = True
            QTimer.singleShot(0, self._mount_earth_globe)
            return
        self._show_earth_globe()

    def _mount_earth_globe(self) -> None:
        self._globe_mounting = False
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        from arelis.ui.earth_globe_host import (
            EarthGlobeHost,
            EarthHudGlass,
            webengine_available,
        )

        gl = getattr(self, "_gl", None)
        if gl is not None:
            if hasattr(gl, "park"):
                gl.park()
            else:
                gl.release_current()
        if self._globe_host is None and webengine_available():
            host = EarthGlobeHost(self)
            host.bridge.hostPicked.connect(self._on_globe_pick)
            host.bridge.hostCamera.connect(self._on_globe_camera)
            host.bridge.hostReady.connect(lambda _k: self._on_globe_ready())
            host.bridge.hostTiles.connect(lambda _k: self._on_globe_ready())
            host.bridge.hostFailed.connect(lambda _w: self._on_globe_failed())
            self._globe_host = host
        if self._earth_hud is None and self._globe_host is not None:
            self._earth_hud = EarthHudGlass(self)
        self._show_earth_globe()

    def _show_earth_globe(self) -> None:
        from arelis.ui.earth_globe_host import entity_rows, place_rows

        host = self._globe_host
        if host is not None and not host.failed:
            host.show()
            host.lower()
        if self._earth_hud is not None:
            self._earth_hud.show()
            self._earth_hud.raise_()
        self._layout_earth_globe()
        if host is not None and not host.failed:
            view = getattr(self, "_earth_cam", None)
            zone = None
            try:
                from arelis.earth.frames import ecef_to_geodetic
                from arelis.earth.runtime import get_earth

                zone = get_earth()
                if view is not None:
                    lat, lon, alt = ecef_to_geodetic(*view.eye)
                    host.push_camera(lat, lon, max(alt, 80_000.0))
            except Exception:
                pass
            host.push_entities(entity_rows())
            if zone is not None and zone.last_view is not None:
                host.push_places(
                    place_rows(zone.last_view.band, zone.last_view.lat, zone.last_view.lon)
                )
                host.push_streets(bool(zone.tiles))
                host.push_buildings()
        self.update()

    def _park_space_for_earth(self) -> None:
        """Last starfield, then stay off the shared GL context.

        Chromium aborts if the offscreen solar context is current — or
        becomes current again — while QWebEngineView is alive.
        """
        gl = getattr(self, "_gl", None)
        if gl is None:
            return
        if not getattr(gl, "_parked", False):
            try:
                frame = gl.render(
                    max(self.width(), 1), max(self.height(), 1), stars_only=True
                )
                if frame is not None and not frame.isNull():
                    self._stars_hold = QImage(frame)
            except Exception:
                pass
        if hasattr(gl, "park"):
            gl.park()
        else:
            gl.release_current()

    def _leave_earth_globe(self) -> None:
        self._globe_mounting = False
        self._stars_hold = None
        gl = getattr(self, "_gl", None)
        if gl is not None and hasattr(gl, "unpark"):
            gl.unpark()
        if self._globe_host is not None:
            self._globe_host.hide()
        if self._earth_hud is not None:
            self._earth_hud.hide()
        self._globe_hpr = None

    def _layout_earth_globe(self) -> None:
        if self._globe_host is not None:
            self._globe_host.setGeometry(self.rect())
        if self._earth_hud is not None:
            self._earth_hud.setGeometry(self.rect())
            host = self._globe_host
            if host is not None and not host.failed and host.isVisible():
                self._earth_hud.show()
                self._earth_hud.raise_()
            else:
                self._earth_hud.hide()

    def _on_globe_ready(self) -> None:
        self._layout_earth_globe()
        self._sync_earth_globe(force=True)
        self.update()

    def _on_globe_failed(self) -> None:
        self._leave_earth_globe()
        self.update()

    def _on_globe_pick(self, entity_id: str) -> None:
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is None:
            return
        hit = zone.get(entity_id)
        if hit is None:
            return
        self._earth_id = hit.id
        zone.track(hit.id)
        self._open_earth_look(hit)
        self.update()

    def _on_globe_camera(self, raw: str) -> None:
        if self._keys or self._earth_fly is not None:
            return
        try:
            payload = json.loads(raw)
            lat = float(payload["lat"])
            lon = float(payload["lon"])
            alt = float(payload["alt_m"])
            heading = float(payload.get("heading") or 0.0)
            pitch = float(payload.get("pitch") or -90.0)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return
        from arelis.earth.frames import nadir_cam

        self._globe_hpr = (heading, pitch)
        self._earth_cam = nadir_cam(lat, lon, alt)
        self._remember_earth_eye()
        try:
            from arelis.physics.runtime import get_system
            from arelis.ui.earth_overlay import sync_earth_view

            system = get_system()
            if system is not None:
                sync_earth_view(self, system)
        except Exception:
            pass
        self.update()

    def _push_globe_camera(self) -> None:
        host = self._globe_host
        pose = self._earth_cam
        if host is None or host.failed or not host.isVisible() or pose is None:
            return
        from arelis.earth.frames import ecef_to_geodetic

        lat, lon, alt = ecef_to_geodetic(*pose.eye)
        heading, pitch = self._globe_hpr if self._globe_hpr is not None else (None, None)
        host.push_camera(lat, lon, max(alt, 200.0), heading, pitch)
        self._globe_cam_push = time.perf_counter()

    def _sync_earth_globe(self, *, force: bool = False, camera: bool = False) -> None:
        host = self._globe_host
        if host is None or host.failed or not host.isVisible():
            return
        now = time.perf_counter()
        if camera or force:
            self._push_globe_camera()
        if not force and now - self._globe_data_push < 1.0:
            return
        self._globe_data_push = now
        from arelis.earth.runtime import get_earth
        from arelis.ui.earth_globe_host import entity_rows, place_rows

        host.push_entities(entity_rows())
        zone = get_earth()
        if zone is not None and zone.last_view is not None:
            host.push_places(
                place_rows(zone.last_view.band, zone.last_view.lat, zone.last_view.lon)
            )
            host.push_streets(bool(zone.tiles))
            host.push_buildings()

    def _open_earth_look(self, hit) -> None:
        from arelis.earth.look import resolve

        handle = resolve(hit.id)
        if handle is None:
            self._close_earth_look()
            return
        if self._look_session is None:
            from arelis.ui.look_session import LookSession

            session = LookSession(self)
            session.frame.connect(self._on_look_frame)
            session.status.connect(self._on_look_status)
            self._look_session = session
        self._look_session.start(handle)

    def _close_earth_look(self) -> None:
        session = self._look_session
        if session is not None:
            session.stop()
        self._look_frame = None
        self._look_status = ""

    def _on_look_frame(self, image) -> None:
        self._look_frame = image
        self.update()

    def _on_look_status(self, text: str) -> None:
        self._look_status = str(text or "")
        self.update()

    def _fov_y(self) -> float:
        punch = 0.0 if self._warp is None else 0.18 * self._warp.speed01
        return 0.70 + punch

    def _travel_to(self, name: str) -> None:
        """Fly the inspect eye to ~8× IAU radius. Accel, cruise, slow. Not a burn."""
        system = get_system()
        if system is None:
            return
        body = system.nbody.find(name)
        if body is None:
            return
        sun = system.nbody.find("Sun")
        sun_p = (sun.x, sun.y, sun.z) if sun is not None else None
        self._warp = CameraWarp.start(
            self.cam,
            name,
            body.x,
            body.y,
            body.z,
            body.radius,
            sun_p,
        )
        try:
            from arelis.physics.telemetry import emit

            emit("travel", body=name, radius=body.radius)
        except Exception:
            pass
        self._fly_v = [0.0, 0.0, 0.0]
        self._set_inspect(name)
        self.update()

    def _step_warp(self, system: SolarSystem, dt: float) -> None:
        flight = self._warp
        if flight is None:
            return
        body = system.nbody.find(flight.name)
        if body is None:
            self._warp = None
            return
        sun = system.nbody.find("Sun")
        sun_p = (sun.x, sun.y, sun.z) if sun is not None else None
        flying = flight.step(
            self.cam, body.x, body.y, body.z, body.radius, sun_p, dt
        )
        if not flying:
            name = flight.name
            self._warp = None
            self._after_travel(name)

    def _finish_travel(self) -> None:
        """Snap to the standoff. Tests, not a shortcut in the plate."""
        flight = self._warp
        system = get_system()
        if flight is None or system is None:
            return
        body = system.nbody.find(flight.name)
        if body is None:
            self._warp = None
            return
        sun = system.nbody.find("Sun")
        sun_p = (sun.x, sun.y, sun.z) if sun is not None else None
        flight.snap(self.cam, body.x, body.y, body.z, body.radius, sun_p)
        name = flight.name
        self._warp = None
        self._after_travel(name)

    def _after_travel(self, name: str) -> None:
        from arelis.earth.runtime import get_earth, require_earth

        if name == "Earth":
            require_earth().enter()
            self._remember_earth_eye()
            self._enter_earth_globe()
            self._apply_pending_earth_goto()
            return
        zone = get_earth()
        if zone is not None and zone.active:
            zone.stop_ride()
            zone.leave()
        self._earth_cam = None
        self._earth_id = None
        self._close_earth_look()
        self._leave_earth_globe()

    def _apply_pending_earth_goto(self) -> None:
        """Fly to a spoken or tool destination once Earth is the inspect body."""
        if self._warp is not None:
            return
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is None or not zone.active:
            return
        dest = zone.take_goto()
        if dest is None:
            return
        self._select_earth_place(dest)

    def _earth_lock_ready(self, system: SolarSystem) -> bool:
        from arelis.earth.frames import earth_eye_locked
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is None or not zone.active:
            return False
        earth = system.nbody.find("Earth")
        if earth is None:
            return False
        return earth_eye_locked(
            (earth.x, earth.y, earth.z),
            earth.radius,
            (self.cam.x, self.cam.y, self.cam.z),
        )

    def _hold_earth_eye(self, system: SolarSystem) -> None:
        """Keep the inspect eye on ECEF so the globe does not slide under you."""
        from arelis.earth.frames import apply_earth_cam, earth_spin_jd
        from arelis.earth.runtime import get_earth

        if self._earth_cam is None:
            return
        zone = get_earth()
        if zone is None or not zone.active or zone.ride_id:
            return
        earth = system.nbody.find("Earth")
        if earth is None:
            return
        apply_earth_cam(
            self.cam,
            (earth.x, earth.y, earth.z),
            earth_spin_jd(system.epoch_jd, system.t),
            self._earth_cam,
        )

    def _remember_earth_eye(self, system: SolarSystem | None = None) -> None:
        from arelis.earth.frames import capture_earth_cam, earth_spin_jd
        from arelis.earth.runtime import get_earth
        from arelis.physics.runtime import get_system as _live

        live = system if system is not None else _live()
        zone = get_earth()
        had = self._earth_cam is not None
        if live is None or zone is None or not zone.active:
            self._earth_cam = None
            if had:
                _emit_earth_lock(False)
            return
        if not self._earth_lock_ready(live):
            self._earth_cam = None
            if had:
                _emit_earth_lock(False)
            return
        earth = live.nbody.find("Earth")
        if earth is None:
            return
        self._earth_cam = capture_earth_cam(
            self.cam,
            (earth.x, earth.y, earth.z),
            earth_spin_jd(live.epoch_jd, live.t),
        )
        if not had:
            _emit_earth_lock(True)

    def _follow_earth_ride(self, system: SolarSystem) -> None:
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is None or not zone.ride_id:
            return
        ent = zone.get(zone.ride_id)
        if ent is None:
            return
        pose = None
        if ent.layer == "cameras":
            pose = look_from_pose(system, ent)
        if pose is None:
            pose = ride_pose(system, ent)
        if pose is None:
            return
        eye, look, up = pose
        self.cam.x, self.cam.y, self.cam.z = eye
        self.cam.aim(look[0], look[1], look[2], up=up)

    def _sync_earth_look(self) -> None:
        """Tool/voice ride or track should open the same live look as a click."""
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is None or not zone.active or not zone.ride_id:
            return
        eid = zone.ride_id
        session = self._look_session
        if session is not None and session.active_id() == eid:
            return
        hit = zone.get(eid)
        if hit is None:
            return
        self._earth_id = hit.id
        self._open_earth_look(hit)

    def _body_at(self, px: float, py: float) -> str | None:
        system = get_system()
        if system is None:
            return None
        self._begin_view(system)
        ix, iy = int(px), int(py)
        best: str | None = None
        best_score = 1.0e9
        for body in system.nbody.particles:
            if _is_sketch(body):
                continue
            proj = self._proj((body.x, body.y, body.z))
            if proj is None:
                continue
            depth = proj[2]
            true_px = self._true_px(body.radius, depth)
            if body.kind == "moon" and true_px < 2.0:
                continue
            d = math.hypot(proj[0] - px, proj[1] - py)
            px_r = self._screen_radius(body, depth)
            hit = max(20.0, px_r + 8.0)
            if d >= hit:
                continue
            score = d - 0.02 * math.log10(max(body.radius, 1.0))
            if score < best_score:
                best_score = score
                best = body.name
        if best is not None:
            return best
        for name, lx, ly, lw in reversed(self._drawn_labels):
            if QRect(lx, ly - 12, lw, 16).contains(ix, iy):
                return name
        return None

    def _roster_names(self, system: SolarSystem) -> list[str]:
        """Memoised: label placement asks for the roster box dozens of times a frame."""
        key = (
            id(system),
            len(system.nbody.particles),
            self._help,
        )
        if key == self._roster_key and self._roster_cache is not None:
            return self._roster_cache
        names = self._sorted_roster(system)
        self._roster_key = key
        self._roster_cache = names
        return names

    def _sorted_roster(self, system: SolarSystem) -> list[str]:
        bodies = [
            b
            for b in system.views()
            if not _is_sketch(b)
        ]
        planet_i = {name: i for i, name in enumerate(PLANET_NAMES)}
        catalog_i = {spec.name: i for i, spec in enumerate(BODIES)}

        def sort_key(body: BodyView) -> tuple[int, int, int]:
            if body.kind == "star":
                return (0, 0, 0)
            if body.kind == "planet":
                return (1, planet_i.get(body.name, 99), 0)
            if body.kind == "moon":
                return (
                    1,
                    planet_i.get(body.parent or "", 99),
                    catalog_i.get(body.name, 99),
                )
            if body.kind == "asteroid":
                return (2, catalog_i.get(body.name, 99), 0)
            return (9, catalog_i.get(body.name, 99), 0)

        return [body.name for body in sorted(bodies, key=sort_key)]

    def _roster_row_open(self, system: SolarSystem, name: str) -> bool:
        """Moons stay folded until that moon or its parent is inspect."""
        spec = BODY_BY_NAME.get(name)
        kind = spec.kind if spec is not None else ""
        parent = spec.parent if spec is not None else None
        if spec is None:
            body = system.nbody.find(name)
            if body is None:
                return True
            kind = body.kind
            parent = body.parent
        if kind != "moon":
            return True
        inspect = self._inspect
        return inspect == name or inspect == parent

    def _roster_shown(self, system: SolarSystem) -> list[str]:
        return [
            name
            for name in self._roster_names(system)
            if self._roster_row_open(system, name)
        ]

    def _roster_rect(self) -> QRect:
        top = self._hud_plate_rect().bottom() + _ROSTER_GAP
        floor = self._speed_rect().y() - 22
        room = floor - top
        if room < 40:
            return QRect()
        system = get_system()
        n = len(self._roster_shown(system)) if system is not None else 1
        rows = min(n, max(1, (room - 24) // _ROSTER_ROW), _ROSTER_MAX_ROWS)
        height = min(room, 22 + rows * _ROSTER_ROW + 6)
        return QRect(10, top, 168, max(44, height))

    def _roster_rows(self) -> int:
        box = self._roster_rect()
        if box.isEmpty():
            return 0
        return max(1, (box.height() - 18) // _ROSTER_ROW)

    def _roster_visible(self, system: SolarSystem) -> list[str]:
        names = self._roster_shown(system)
        rows = self._roster_rows()
        if rows <= 0:
            return []
        max_scroll = max(0, len(names) - rows)
        self._roster_scroll = min(max(0, self._roster_scroll), max_scroll)
        return names[self._roster_scroll : self._roster_scroll + rows]

    def _roster_row_rect(self, i: int) -> QRect:
        box = self._roster_rect()
        return QRect(box.left(), box.top() + 18 + i * _ROSTER_ROW, box.width(), _ROSTER_ROW)

    def _roster_hit(self, px: float, py: float) -> str | None:
        system = get_system()
        if system is None or not self._roster_rect().contains(int(px), int(py)):
            return None
        visible = self._roster_visible(system)
        for i, name in enumerate(visible):
            if self._roster_row_rect(i).contains(int(px), int(py)):
                return name
        return None

    def _cycle_inspect(self, step: int) -> None:
        system = get_system()
        if system is None:
            return
        names = self._roster_shown(system)
        if not names:
            return
        current = self._inspect or names[0]
        try:
            i = names.index(current)
        except ValueError:
            i = 0
        self._set_inspect(names[(i + step) % len(names)])
        self.update()

    def _set_inspect(self, name: str | None) -> None:
        self._inspect = name
        self._inspect_more = False
        system = get_system()
        if system is not None and name:
            self._reveal_roster(system, name)

    def _reveal_roster(self, system: SolarSystem, name: str) -> None:
        names = self._roster_shown(system)
        if name not in names:
            return
        i = names.index(name)
        rows = self._roster_rows()
        if i < self._roster_scroll:
            self._roster_scroll = i
        elif i >= self._roster_scroll + rows:
            self._roster_scroll = i - rows + 1

    def _paint_roster(self, painter: QPainter, system: SolarSystem) -> None:
        box = self._roster_rect()
        if box.isEmpty():
            return
        names = self._roster_visible(system)
        painter.setPen(QPen(color("edge"), 1))
        painter.setBrush(_wash("glass_fill", 255))
        painter.drawRoundedRect(box, 6, 6)
        painter.setPen(color("text_dim"))
        painter.drawText(box.adjusted(8, 2, -8, 0), "Bodies")
        for i, name in enumerate(names):
            row = self._roster_row_rect(i)
            if name == self._inspect:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(_wash("accent", 70))
                painter.drawRect(row.adjusted(2, 1, -2, -1))
            painter.setPen(color("text") if name == self._inspect else color("text_dim"))
            spec = BODY_BY_NAME.get(name)
            body = system.nbody.find(name)
            kind = getattr(body, "kind", None) if body is not None else None
            if kind is None and spec is not None:
                kind = spec.kind
            if kind in {"star", "planet", "moon", "asteroid", "probe", "lagrange"}:
                from arelis.ui.earth_marks import ink_for_kind, paint_mark

                paint_mark(
                    painter,
                    row.left() + 12,
                    row.center().y(),
                    kind,
                    band="city",
                    size=12,
                    ink=ink_for_kind(kind),
                )
            indent = 22 if kind == "moon" else 20
            label = f"· {name}" if spec is not None and spec.kind == "moon" else name
            painter.setPen(color("text") if name == self._inspect else color("text_dim"))
            painter.drawText(
                row.adjusted(indent, 0, -8, 0),
                Qt.AlignmentFlag.AlignVCenter,
                label,
            )

    def _anchor(self) -> tuple[float, float, float]:
        system = get_system()
        if system is not None:
            sun = system.nbody.find("Sun")
            if sun is not None:
                return (sun.x, sun.y, sun.z)
        return (0.0, 0.0, 0.0)

    def _system_span(self, system: SolarSystem | None) -> float:
        span = SOLAR_SPAN_M
        if system is None:
            return span
        ox = oy = oz = 0.0
        sun = system.nbody.find("Sun")
        if sun is not None:
            ox, oy, oz = sun.x, sun.y, sun.z
        for body in system.nbody.particles:
            if _is_sketch(body):
                continue
            d = math.hypot(body.x - ox, body.y - oy, body.z - oz)
            if d > span:
                span = d
        return span

    def _fly_speed(self) -> float:
        """Cruise with distance from the Sun; honor the slider near a body."""
        ox, oy, oz = self._anchor()
        dist_anchor = math.hypot(self.cam.x - ox, self.cam.y - oy, self.cam.z - oz)
        cruise = min(SPEED_MAX, max(self.cam.speed, dist_anchor * 0.08))
        system = get_system()
        if system is None:
            return cruise
        near = dist_anchor
        for body in system.nbody.particles:
            if _is_sketch(body):
                continue
            d = math.hypot(self.cam.x - body.x, self.cam.y - body.y, self.cam.z - body.z)
            if d < near:
                near = d
        if near < 0.03 * AU_M:
            return self.cam.speed
        return cruise

    def _camera_fly(self, fwd: float, right: float, up: float, dt: float) -> None:
        saved = self.cam.speed
        self.cam.speed = self._fly_speed()
        self.cam.fly(fwd, right, up, dt)
        self.cam.speed = saved
        self._clamp_pullback()
        self._remember_earth_eye()
        if self._earth_globe_live() and (abs(fwd) + abs(right) + abs(up)) > 1e-6:
            self._push_globe_camera()

    def _clamp_pullback(self) -> None:
        ox, oy, oz = self._anchor()
        cap = overview_distance(self._system_span(get_system())) * 1.15
        dx, dy, dz = self.cam.x - ox, self.cam.y - oy, self.cam.z - oz
        r = math.sqrt(dx * dx + dy * dy + dz * dz)
        if r <= cap:
            return
        s = cap / max(r, 1.0)
        self.cam.x = ox + dx * s
        self.cam.y = oy + dy * s
        self.cam.z = oz + dz * s
        self.cam.distance = cap

    def _true_px(self, radius: float, depth: float) -> float:
        from arelis.physics.star_look import angular_px

        return angular_px(radius, depth, self.height(), self._fov_y())

    def _screen_radius(self, body: BodyView, depth: float) -> float:
        """IAU angular size with a screen-space floor. Not a physics radius."""
        true = self._true_px(body.radius, depth)
        if body.tracer:
            return max(1.0, true)
        floor = {"star": 6.0, "planet": 5.0, "asteroid": 4.0}.get(body.kind, 3.0)
        return max(true, floor)

    def reset_view(self, *, keep_inspect: bool = False) -> None:
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is not None and zone.active:
            zone.stop_ride()
            zone.leave()
        self._earth_cam = None
        self._earth_fly = None
        self._earth_id = None
        self._place = None
        self._close_earth_look()
        self._leave_earth_globe()
        system = get_system()
        self._warp = None
        self.cam.frame_system(self._system_span(system))
        tx, ty, tz = self._anchor()
        self.cam.place_looking_at(tx, ty, tz, self.cam.distance)
        self._fitted_lock = None
        self._fly_v = [0.0, 0.0, 0.0]
        if not keep_inspect:
            self._inspect = None
            self._inspect_more = False
            self._roster_scroll = 0

    def _reset_after_paint(self) -> None:
        self._reset_pending = False
        self.reset_view()

    def paintEvent(self, _event) -> None:
        system = get_system()
        if system is not None:
            self._painted_t = system.t
        self._painted_note = self._maps_note
        try:
            if self._earth_globe_live() or self._globe_mounting:
                self._layout_earth_globe()
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                hold = self._stars_hold
                if hold is not None and not hold.isNull():
                    painter.drawImage(self.rect(), hold)
                else:
                    painter.fillRect(self.rect(), QColor(4, 5, 8))
                if self._earth_hud is not None:
                    self._earth_hud.update()
                return
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if self._space_live():
                assert self._gl is not None
                frame = self._gl.render(self.width(), self.height())
                if frame is not None and not frame.isNull():
                    painter.drawImage(self.rect(), frame)
                else:
                    painter.fillRect(self.rect(), QColor(4, 5, 8))
                self._paint_overlay(painter, software=False)
                return
            painter.fillRect(self.rect(), QColor(4, 5, 8))
            self._paint_overlay(painter, software=True)
        finally:
            # End, not start: a 150 ms Earth paint must not look already stale.
            self._painted_wall = time.perf_counter()

    def _paint_overlay(self, painter: QPainter, *, software: bool) -> None:
        return paint_overlay(self, painter, software=software)

    def _light_cam(self, body: BodyView, sun, basis: _Basis) -> tuple[float, float, float]:
        return light_cam(self, body, sun, basis)

    def _paint_body(
        self,
        painter: QPainter,
        system: SolarSystem,
        body: BodyView,
        sun,
        basis: _Basis,
        proj: tuple[float, float, float] | None = None,
    ) -> None:
        return paint_body(self, painter, system, body, sun, basis, proj)

    def _chrome_rects(self) -> list[QRect]:
        return chrome_rects(self)

    def _chrome_covers(self, x: int, y: int) -> bool:
        return chrome_covers(self, x, y)

    def _label_body(
        self, painter: QPainter, body: BodyView, sx: float, sy: float, px_r: float
    ) -> None:
        return label_body(self, painter, body, sx, sy, px_r)

    def _on_globe(self, x: float, y: float) -> bool:
        return on_globe(self, x, y)

    def _close_globe(self) -> bool:
        return close_globe(self)

    def _look_field_m(self, system: SolarSystem) -> float:
        return look_field_m(self, system)

    def _earth_limb(self, painter: QPainter, sx: float, sy: float, px_r: float) -> None:
        return earth_limb(self, painter, sx, sy, px_r)

    def _sun_limb(self, painter: QPainter, sx: float, sy: float, px_r: float) -> None:
        return sun_limb(self, painter, sx, sy, px_r)

    def _paint_sun_loops(self, painter: QPainter, system: SolarSystem, body: BodyView) -> None:
        return paint_sun_loops(self, painter, system, body)

    def _stroke_loop(self, painter: QPainter, pts: list[QPoint], flare: float) -> None:
        return stroke_loop(self, painter, pts, flare)

    def _paint_saturn_rings(self, painter: QPainter, body: BodyView) -> None:
        return paint_saturn_rings(self, painter, body)

    def _paint_heliocentric_orbits(self, painter: QPainter, system: SolarSystem) -> None:
        return paint_heliocentric_orbits(self, painter, system)

    def _paint_trails(self, painter: QPainter, system: SolarSystem) -> None:
        return paint_trails(self, painter, system)

    def _paint_lagrange(self, painter: QPainter, system: SolarSystem) -> None:
        return paint_lagrange(self, painter, system)

    def _paint_ecliptic(self, painter: QPainter, sun) -> None:
        return paint_ecliptic(self, painter, sun)

    def _facing(self, cx: float, cy: float, cz: float, x: float, y: float, z: float) -> bool:
        return facing(self, cx, cy, cz, x, y, z)

    def _stroke_world(
        self,
        painter: QPainter,
        pts: list[tuple[float, float, float]],
        *,
        closed: bool = False,
        host: tuple[float, float, float] | None = None,
    ) -> None:
        return stroke_world(self, painter, pts, closed=closed, host=host)

    def _ring_xy(self, painter: QPainter, body: BodyView, radius: float, n: int=72) -> None:
        return ring_xy(self, painter, body, radius, n)

    def _paint_sphere_cage(
        self, painter: QPainter, body: BodyView, radius: float, *, meridians: int = 4
    ) -> None:
        return paint_sphere_cage(self, painter, body, radius, meridians=meridians)

    def _paint_magnetopause(
        self, painter: QPainter, system: SolarSystem, *, strokes: bool = True
    ) -> None:
        return paint_magnetopause(self, painter, system, strokes=strokes)

    def _paint_wind(self, painter: QPainter, system: SolarSystem) -> None:
        return paint_wind(self, painter, system)

    def _paint_g(self, painter: QPainter, system: SolarSystem) -> None:
        return paint_g(self, painter, system)

    def _paint_wells(self, painter: QPainter, system: SolarSystem, *, strokes: bool=True) -> None:
        return paint_wells(self, painter, system, strokes=strokes)

    def _paint_well_slice(self, painter: QPainter, body: BodyView, mu: float) -> None:
        return paint_well_slice(self, painter, body, mu)

    def _paint_grid(self, painter: QPainter, system: SolarSystem) -> None:
        return paint_grid(self, painter, system)

    def _maps_alert(self) -> str:
        return maps_alert(self)

    def _inspect_column_width(self) -> int:
        return inspect_column_width(self)

    def _hud_plate_width(self) -> int:
        return hud_plate_width(self)

    def _hud_plate_rect(self) -> QRect:
        return hud_plate_rect(self)

    def _legend_columns(self, inner_w: int) -> int:
        return legend_columns(self, inner_w)

    def _hud_status_lines(self, system: SolarSystem) -> list[str]:
        return hud_status_lines(self, system)

    def _wrapped_h(self, fm: QFontMetrics, text: str, width: int) -> int:
        return wrapped_h(self, fm, text, width)

    def _key_strip_chips(
        self, fm: QFontMetrics, left: int, top: int, width: int
    ) -> tuple[list[tuple[QRect, str, bool]], int]:
        return key_strip_chips(self, fm, left, top, width)

    def _legend_items(
        self, box_left: int, legend_top: int, inner_w: int
    ) -> tuple[list[tuple[int, int, str, tuple[tuple[str, str], ...], int]], int]:
        return legend_items(self, box_left, legend_top, inner_w)

    def _keys_chrome_height(self, fm: QFontMetrics, width: int) -> int:
        return keys_chrome_height(self, fm, width)

    def _keys_footer(self) -> str:
        return keys_footer(self)

    def _paint_plate(self, painter: QPainter, box: QRect, *, radius: int=8) -> None:
        return paint_plate(self, painter, box, radius=radius)

    def _paint_chip(self, painter: QPainter, box: QRect, label: str, *, on: bool=False) -> None:
        return paint_chip(self, painter, box, label, on=on)

    def _paint_keys_chrome(self, painter: QPainter, box: QRect) -> int:
        return paint_keys_chrome(self, painter, box)

    def _paint_hud(self, painter: QPainter, system: SolarSystem) -> None:
        return paint_hud(self, painter, system)

    def _earth_chip_layout(self) -> tuple[list[tuple[str, QRect]], QRect]:
        return earth_chip_layout(self)

    def _earth_chip_at(self, px: float, py: float) -> str | None:
        return earth_chip_at(self, px, py)

    def _toggle_earth_chip(self, kind: str) -> None:
        toggle_earth_chip(self, kind)
        if not self._earth_globe_live():
            return
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is None:
            return
        if kind == "tiles":
            self._globe_host.push_streets(bool(zone.tiles))
        elif kind == "buildings":
            self._globe_host.push_buildings()

    def _start_earth_live(self) -> None:
        return start_earth_live(self)

    def _paint_earth_toggles(self, painter: QPainter) -> None:
        return paint_earth_toggles(self, painter)

    def _paint_earth_card(self, painter: QPainter) -> None:
        return paint_earth_card(self, painter)

    def _spark(self, painter: QPainter, system: SolarSystem) -> None:
        return spark(self, painter, system)

    def _paint_free_markers(self, painter: QPainter, system: SolarSystem) -> None:
        return paint_free_markers(self, painter, system)

    def _dots_rect(self) -> QRect:
        return dots_rect(self)

    def _empty_caption(self) -> str:
        return empty_caption(self)

    def _speed_rect(self) -> QRect:
        return speed_rect(self)

    def _u_from_x(self, box: QRect, px: float) -> float:
        return u_from_x(self, box, px)

    def _paint_speed(self, painter: QPainter) -> None:
        return paint_speed(self, painter)

    def _inspect_rect(self) -> QRect:
        return inspect_rect(self)

    def _inspect_font(self, *, title: bool=False) -> QFont:
        return inspect_font(self, title=title)

    def _inspect_body_height(self, lines: list[str], width: int) -> int:
        return inspect_body_height(self, lines, width)

    def _inspect_close_rect(self) -> QRect:
        return inspect_close_rect(self)

    def _inspect_travel_rect(self) -> QRect:
        return inspect_travel_rect(self)

    def _inspect_lines(self, system: SolarSystem | None) -> list[str]:
        return inspect_lines(self, system)

    def _build_inspect_lines(self, system: SolarSystem) -> list[str]:
        return build_inspect_lines(self, system)

    def _paint_inspect(self, painter: QPainter, system: SolarSystem) -> None:
        return paint_inspect(self, painter, system)

    def _epoch_rect(self) -> QRect:
        return epoch_rect(self)

    def _set_epoch_from_x(self, system: SolarSystem, px: float) -> None:
        return set_epoch_from_x(self, system, px)

    def _paint_epoch(self, painter: QPainter, system: SolarSystem) -> None:
        return paint_epoch(self, painter, system)

    def _tools_rect(self) -> QRect:
        return tools_rect(self)

    def _chip_rects(self) -> list[tuple[str, QRect]]:
        return chip_rects(self)

    def _spawn_hit(self, px: float, py: float) -> str | None:
        return spawn_hit(self, px, py)

    def _overlay_on(self, kind: str) -> bool:
        return overlay_on(self, kind)

    def _toggle_overlay(self, kind: str) -> bool:
        return toggle_overlay(self, kind)

    def _spawn(self, kind: str) -> None:
        return spawn(self, kind)

    def _open_impulse_confirm(self, name: str) -> None:
        return open_impulse_confirm(self, name)

    def _open_planet_confirm(self) -> None:
        return open_planet_confirm(self)

    def _confirm_rect(self) -> QRect:
        return confirm_rect(self)

    def _confirm_chip_rects(self) -> dict[str, QRect]:
        return confirm_chip_rects(self)

    def _confirm_hit(self, px: float, py: float) -> str | None:
        return confirm_hit(self, px, py)

    def _confirm_click(self, hit: str) -> None:
        return confirm_click(self, hit)

    def _confirm_apply(self) -> None:
        return confirm_apply(self)

    def _paint_confirm(self, painter: QPainter) -> None:
        return paint_confirm(self, painter)

    def start_horizons_load(self, *, refresh: bool = False) -> None:
        if self._load_pending:
            return
        live = get_system()
        if (
            live is not None
            and not refresh
            and "not Horizons" not in (live.epoch_tdb or "")
        ):
            return
        if not refresh and self._try_nearest_cache():
            return
        self._load_refresh = refresh
        self._load_pending = True
        self._load_progress = "Fetching JPL Horizons VECTORS…"
        if get_system() is None:
            self._maps_note = self._load_progress
        threading.Thread(target=self._horizons_work, daemon=True).start()

    def _horizons_work(self) -> None:
        import asyncio

        from arelis.tools.base import ToolResult
        from arelis.tools.solar_tool import SolarTool

        def progress(msg: str) -> None:
            self._load_progress = msg
            self._maps_note = msg

        kwargs: dict[str, object] = {
            "action": "load",
            "date": self._ic_date,
            "refresh": self._load_refresh,
        }
        system = get_system()
        if system is not None:
            kwargs["tracers"] = sum(1 for p in system.nbody.particles if p.tracer)
        try:
            result = asyncio.run(SolarTool(on_progress=progress).run(**kwargs))
        except Exception as exc:
            result = ToolResult(
                ok=False,
                output=str(exc),
                data={"fail_class": "fail:horizons"},
            )
        self._load_result = result

    def _start_maps(self, *, retry: bool = False) -> None:
        if self._maps_pending is True:
            return
        if self._maps_tried and not retry:
            return
        self._maps_tried = True
        self._maps_note = "fetching NASA albedo…"
        self._maps_pending = True

        def work() -> None:
            from arelis.physics.maps import download_maps

            self._maps_pending = download_maps()

        threading.Thread(target=work, daemon=True).start()

    def _paint_tools(self, painter: QPainter) -> None:
        return paint_tools(self, painter)
