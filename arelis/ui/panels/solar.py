"""True-scale solar view.

IAU spheres, 1/r² sun, cited albedo if a map is on disk. Inspect-only fly
camera. Overlay flags live on SolarSystem.overlay. No rideable craft.
"""

from __future__ import annotations

import math
import os
import threading
import time
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFont,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from arelis.physics.attitude import (
    body_frame_ecliptic,
    earth_lonlat_grid,
    lonlat_from_frame,
    moon_lonlat_grid,
    saturn_ring_axes,
    spin_caption,
    spin_jd,
)
from arelis.physics.camera import (
    SOLAR_SPAN_M,
    SPEED_MAX,
    CameraWarp,
    FlyCamera,
    overview_distance,
    project_with_basis,
    speed_label,
)
from arelis.physics.clocks import (
    RATE_DAY,
    RATE_HOUR,
    RATE_REALTIME,
    RATE_YEAR,
    jd_iso,
    rate_label,
)
from arelis.physics.collision import stop_radius_m
from arelis.physics.constants import (
    AU_M,
    BODIES,
    BODY_BY_NAME,
    G_SI,
    PLANET_NAMES,
    SATURN_CASSINI_INNER_M,
    SATURN_CASSINI_OUTER_M,
    SATURN_RING_INNER_M,
    SATURN_RING_OUTER_M,
)
from arelis.physics.elements import (
    BEAD_LAP_S,
    ISO_G_FACTORS,
    bead_true_anomalies,
    hill_radius,
    osculating,
    position_at_true_anomaly,
    well_grid,
    well_inner_ring,
    well_theta_count,
)
from arelis.physics.evolution import GYR_MAX, GYR_MIN, sample, sun_rgb
from arelis.physics.maps import describe, forget_ready, load_rgb
from arelis.physics.runtime import get_system
from arelis.physics.scene import BodyView, SolarSystem
from arelis.ui.theme import FONT_PX, color

_Basis = tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]

_FILL = 0.03  # night fill so a pick reticle is visible. Not sunlight.
_GLOBE_MAX = 384  # software sphere; approach, not landing
_IDLE_PX = 0.35  # redraw once the fastest body has moved this far on screen
_CLOSE_GLOBE_PX = 48.0  # hide heliocentric orbits once a globe fills the view
SOLAR_OVERLAY: tuple[tuple[str, str, str], ...] = (
    ("gravity", "G  Gravity", "Newtonian wells + Hill. Sketch, not GR."),
    ("magnetic", "M  Magnetic", "Earth magnetopause. Shue 1998, ram from Parker."),
    ("wind", "P  Wind", "Parker 1958 spiral + quiet wind. Not MHD."),
    ("grid", ";  Grid", "Lat/lon on inspect. Body-fixed when IAU W exists."),
)
SOLAR_SPAWN: tuple[tuple[str, str, str], ...] = (
    ("probe", "Particle", "Massless circular around the inspected body."),
    ("tracer", "Belt", "One main-belt tracer. Not a named rock."),
    ("l4", "Earth L4", "Sun–Earth L4 sketch, not N-body rest."),
    ("impulse", "Kick", "Δv on the inspected body. Counterfactual."),
    ("planet", "Planet", "Add a circular planet. Counterfactual."),
    ("toy", "Toy", "Open the tabletop physics plate."),
)
HELP_HOTKEYS: tuple[str, ...] = (
    "WASD/QE fly  wheel dolly  click inspect  right/dblclick travel  "
    "Home/R reset  Enter travel",
    "Space pause  1–4 [ ] rate  \\ warp  O orbits  L Lagrange  T trails  "
    "` graphs",
    "G gravity  M magnetic  P wind  ; grid  H this plate  "
    "⋯ Gravity/Magnetic/Wind/Grid + spawn. Spoken flags match. No F.",
)
# Always-on strip. H expands KEY_LEGEND. Tokens here must match HELP_HOTKEYS.
KEY_STRIP: tuple[tuple[str, str], ...] = (
    ("WASD", "fly"),
    ("Space", "pause"),
    ("click", "inspect"),
    ("H", "keys"),
)
KEY_LEGEND: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Move",
        (
            ("WASD", "fly"),
            ("QE", "up / down"),
            ("wheel", "dolly along look"),
            ("Shift+wheel", "speed"),
            ("drag", "look"),
            ("Home / R", "reset view"),
        ),
    ),
    (
        "Time",
        (
            ("Space", "pause"),
            ("1 2 3 4", "live · h · d · y"),
            ("[ ]", "rate ×10"),
            ("\\", "warp"),
        ),
    ),
    (
        "Look",
        (
            ("click", "inspect"),
            ("Enter", "travel"),
            ("right / dbl", "travel"),
            ("O", "orbits"),
            ("L", "Lagrange"),
            ("T", "trails"),
            ("`", "graphs"),
        ),
    ),
    (
        "Sketches",
        (
            ("G", "gravity"),
            ("M", "magnetic"),
            ("P", "wind"),
            (";", "grid"),
            ("H", "this plate"),
            ("⋯", "overlays + spawn"),
        ),
    ),
)
_HUD_MAX_W = 720
_HUD_MIN_W = 280
_HUD_GAP = 12
_HUD_LANE = 304
_ROSTER_MAX_ROWS = 12
_ROSTER_ROW = 20
_ROSTER_GAP = 14
_KEYS_ROW = 22
_LEGEND_ROW = 17
_LEGEND_BLOCK = 32 + 7 * _LEGEND_ROW + 12


def _wash(name: str, alpha: int) -> QColor:
    """Theme color with a plate alpha. Solar chrome stays sodium, not ice-blue."""
    tint = QColor(color(name))
    tint.setAlpha(max(0, min(255, int(alpha))))
    return tint
_cache: dict[str, np.ndarray] = {}
_TINT: dict[str, tuple[int, int, int]] = {
    "Sun": (255, 250, 230),
    "Mercury": (170, 160, 150),
    "Venus": (230, 210, 160),
    "Earth": (70, 110, 180),
    "Moon": (180, 178, 172),
    "Mars": (180, 110, 70),
    "Jupiter": (210, 180, 140),
    "Saturn": (220, 200, 150),
    "Uranus": (160, 210, 220),
    "Neptune": (70, 110, 200),
    "Io": (200, 170, 90),
    "Europa": (190, 180, 160),
    "Ganymede": (160, 150, 130),
    "Callisto": (120, 110, 100),
    "Titan": (210, 170, 80),
    "Triton": (150, 160, 170),
    "Ceres": (118, 112, 106),
    "Vesta": (168, 140, 108),
    "Pallas": (132, 124, 112),
    "Hygiea": (120, 116, 110),
}


def _is_sketch(body: BodyView) -> bool:
    """Belt tracers, massless probes, L-point marks. Not catalog worlds."""
    return bool(body.tracer) or body.kind in {"probe", "lagrange"}


def _fmt_m(metres: float) -> str:
    m = abs(float(metres))
    if m >= 0.01 * AU_M:
        return f"{metres / AU_M:.4g} AU"
    if m >= 1000.0:
        return f"{metres / 1000.0:.4g} km"
    return f"{metres:.4g} m"


def _albedo(path: Path) -> np.ndarray | None:
    key = str(path)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    rgb = load_rgb(path)
    if rgb is None:
        return None
    w, h, buf = rgb
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3).copy()
    _cache[key] = arr
    return arr


def _sample_albedo(albedo: np.ndarray, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Bilinear sample of an equirectangular map. Longitude wraps; poles clamp."""
    h, w = albedo.shape[0], albedo.shape[1]
    u = ((lon / (2.0 * math.pi)) + 0.5) * w
    v = (0.5 - lat / math.pi) * max(h - 1, 1)
    u = np.mod(u, max(w, 1))
    v = np.clip(v, 0.0, max(h - 1, 0))
    u0 = np.floor(u).astype(np.int32) % max(w, 1)
    v0 = np.clip(np.floor(v).astype(np.int32), 0, max(h - 1, 0))
    u1 = (u0 + 1) % max(w, 1)
    v1 = np.clip(v0 + 1, 0, max(h - 1, 0))
    fu = (u - np.floor(u))[..., None]
    fv = (v - np.floor(v))[..., None]
    tex = albedo.astype(np.float32)
    s00 = tex[v0, u0]
    s10 = tex[v0, u1]
    s01 = tex[v1, u0]
    s11 = tex[v1, u1]
    return (s00 * (1.0 - fu) + s10 * fu) * (1.0 - fv) + (
        s01 * (1.0 - fu) + s11 * fu
    ) * fv


def _on_frame(
    host: tuple[float, float, float],
    radius: float,
    lat: float,
    clon: float,
    slon: float,
    xx: tuple[float, float, float],
    yx: tuple[float, float, float],
    zx: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Point at body-fixed lat, with clon/slon = cos/sin of longitude."""
    clat, slat = math.cos(lat), math.sin(lat)
    return (
        host[0] + radius * (clat * clon * xx[0] + clat * slon * yx[0] + slat * zx[0]),
        host[1] + radius * (clat * clon * xx[1] + clat * slon * yx[1] + slat * zx[1]),
        host[2] + radius * (clat * clon * xx[2] + clat * slon * yx[2] + slat * zx[2]),
    )


def _globe(
    size: int,
    light: tuple[float, float, float],
    *,
    albedo: np.ndarray | None = None,
    tint: tuple[int, int, int] = (200, 180, 160),
    lon: np.ndarray | None = None,
    lat: np.ndarray | None = None,
    fill: float = _FILL,
    emissive: bool = False,
    granulate: bool = False,
) -> QImage:
    """Sphere sample. Terminator from camera-space sun. No extra craters."""
    from arelis.physics.corona import LIMB_U

    size = max(16, min(int(size), _GLOBE_MAX))
    yy, xx = np.mgrid[0:size, 0:size]
    nx = (xx + 0.5) / size * 2.0 - 1.0
    ny = 1.0 - (yy + 0.5) / size * 2.0
    r2 = nx * nx + ny * ny
    mask = r2 <= 1.0
    nz = np.zeros_like(nx)
    nz[mask] = np.sqrt(np.maximum(0.0, 1.0 - r2[mask]))
    rgb = np.zeros((size, size, 4), dtype=np.uint8)
    if emissive:
        mu = np.clip(nz, 0.0, 1.0)
        ld = 1.0 - LIMB_U * (1.0 - mu)
        core = np.array(tint, dtype=np.float32) * np.array([1.05, 0.94, 0.62])
        limbc = np.array(tint, dtype=np.float32) * np.array([1.0, 0.38, 0.08])
        w = np.power(mu, 0.52)
        samp = limbc + (core - limbc) * w[..., None]
        if size >= 96 and granulate:
            g = np.sin(nx * 18.0 + ny * 12.0 + time.perf_counter() * 0.16)
            g += 0.5 * np.sin(nx * 34.0 - ny * 22.0 - time.perf_counter() * 0.09)
            samp = samp * (1.0 + 0.12 * g[..., None])
        lit = np.clip(samp * ld[..., None], 0, 255).astype(np.uint8)
        rgb[..., :3] = lit
        rgb[..., 3] = np.where(mask, 255, 0).astype(np.uint8)
        return QImage(rgb.data, size, size, size * 4, QImage.Format.Format_RGBA8888).copy()
    lx, ly, lz = light
    ln = math.sqrt(lx * lx + ly * ly + lz * lz) or 1.0
    lambert = np.clip((nx * lx + ny * ly + nz * lz) / ln, 0.0, 1.0)
    shade = fill + (1.0 - fill) * lambert
    if albedo is not None:
        if lon is None or lat is None:
            lon = np.arctan2(nx, nz)
            lat = np.arcsin(np.clip(ny, -1.0, 1.0))
        samp = _sample_albedo(albedo, lon, lat)
    else:
        samp = np.array(tint, dtype=np.float32)
    lit = np.clip(samp * shade[..., None], 0, 255).astype(np.uint8)
    rgb[..., :3] = lit
    rgb[..., 3] = np.where(mask, 255, 0).astype(np.uint8)
    return QImage(rgb.data, size, size, size * 4, QImage.Format.Format_RGBA8888).copy()


def _world_normals(
    nx: np.ndarray,
    ny: np.ndarray,
    nz: np.ndarray,
    basis: _Basis,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    fx, fy, fz = basis
    nwx = nx * fx[0] + ny * fy[0] + nz * (-fz[0])
    nwy = nx * fx[1] + ny * fy[1] + nz * (-fz[1])
    nwz = nx * fx[2] + ny * fy[2] + nz * (-fz[2])
    return nwx, nwy, nwz


def _sphere_axes(size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    size = max(16, min(int(size), _GLOBE_MAX))
    yy, xx = np.mgrid[0:size, 0:size]
    nx = (xx + 0.5) / size * 2.0 - 1.0
    ny = 1.0 - (yy + 0.5) / size * 2.0
    r2 = nx * nx + ny * ny
    nz = np.zeros_like(nx)
    nz[r2 <= 1.0] = np.sqrt(np.maximum(0.0, 1.0 - r2[r2 <= 1.0]))
    return nx, ny, nz


class SolarPanel(QWidget):
    """True-scale solar laboratory. OpenGL space when the context lives."""

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
        self._inspect_more = False
        self._roster_scroll = 0
        self._hud_bottom = 120
        self._hud_box = QRect()
        self._keys_hit = QRect()
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
                epoch_tdb=(
                    "Kepler catalog bootstrap, not Horizons. "
                    "IAS15 from here. A successful Horizons fetch replaces this."
                ),
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
            if self._warp is not None:
                self._step_warp(system, dt)
            else:
                self._fly_camera(dt)
            if not system.paused:
                system.tick(dt)
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
        if self._maps_note != self._painted_note:
            return True
        if system is None:
            return False
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
            if self._keys_hit.contains(int(px), int(py)):
                self._help = not self._help
                self.update()
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
                self.setCursor(
                    Qt.CursorShape.PointingHandCursor
                    if hit
                    else Qt.CursorShape.ArrowCursor
                )
            return
        ox, oy = self._drag
        dyaw, dpitch = (ox - x) * 0.0036, (oy - y) * 0.0036
        self.cam.look(dyaw, dpitch)
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
            name = self._body_at(px, py)
            if name:
                self._travel_to(name)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
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
            system.set_rate(RATE_REALTIME)
        elif key == Qt.Key.Key_2:
            system.set_rate(RATE_HOUR)
        elif key == Qt.Key.Key_3:
            system.set_rate(RATE_DAY)
        elif key == Qt.Key.Key_4:
            system.set_rate(RATE_YEAR)
        elif key == Qt.Key.Key_BracketRight or key == Qt.Key.Key_Equal:
            system.set_rate(system.rate * 10.0)
        elif key == Qt.Key.Key_BracketLeft or key == Qt.Key.Key_Minus:
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
        elif delta != 0:
            if self._warp is None:
                self._camera_fly(1.0 if delta > 0 else -1.0, 0.0, 0.0, 0.20)
        event.accept()
        self.update()

    def _inspect_at(self, px: float, py: float) -> None:
        name = self._body_at(px, py)
        if name:
            self._set_inspect(name)
        elif not self._inspect_rect().contains(int(px), int(py)):
            self._set_inspect(None)
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
            self._warp = None

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
        self._warp = None

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
            if spec is not None and spec.kind == "moon":
                painter.drawText(
                    row.adjusted(14, 0, -8, 0),
                    Qt.AlignmentFlag.AlignVCenter,
                    f"· {name}",
                )
            else:
                painter.drawText(
                    row.adjusted(8, 0, -8, 0),
                    Qt.AlignmentFlag.AlignVCenter,
                    name,
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
        return radius / max(depth, 1.0) * (self.height() / 1.4)

    def _screen_radius(self, body: BodyView, depth: float) -> float:
        """IAU angular size with a screen-space floor. Not a physics radius."""
        true = self._true_px(body.radius, depth)
        if body.tracer:
            return max(1.0, true)
        floor = {"star": 6.0, "planet": 5.0, "asteroid": 4.0}.get(body.kind, 3.0)
        return max(true, floor)

    def reset_view(self, *, keep_inspect: bool = False) -> None:
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
        self._painted_wall = time.perf_counter()
        self._painted_note = self._maps_note
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

    def _paint_overlay(self, painter: QPainter, *, software: bool) -> None:
        system = get_system()
        if system is None:
            self._fitted_lock = None
            painter.setPen(color("text_dim"))
            painter.drawText(
                self.rect().adjusted(24, 48, -24, -120),
                Qt.AlignmentFlag.AlignCenter,
                self._empty_caption(),
            )
            plate_w = self._hud_plate_width()
            used = self._paint_keys_chrome(
                painter, QRect(10, 8, plate_w, 280)
            )
            self._hud_box = QRect(10, 8, plate_w, used)
            self._hud_bottom = self._hud_box.bottom()
            self._paint_tools(painter)
            self._paint_confirm(painter)
            return
        if id(system) != self._view_id:
            self._view_id = id(system)
            if system.ic_date:
                self._ic_date = system.ic_date
            if software:
                self.reset_view()
            elif not self._reset_pending:
                self._reset_pending = True
                QTimer.singleShot(0, self._reset_after_paint)
        self._begin_view(system)
        sun = system.nbody.find("Sun")
        dist_sun = 0.0
        if sun is not None:
            dist_sun = math.hypot(
                self._eye[0] - sun.x, self._eye[1] - sun.y, self._eye[2] - sun.z
            )
        shots: list[tuple[float, BodyView, tuple[float, float, float] | None]] = []
        for body in system.views():
            if not software and body.tracer:
                continue
            proj = self._proj((body.x, body.y, body.z))
            shots.append((-(proj[2] if proj else 0.0), body, proj))
        shots.sort(key=lambda row: row[0])
        self._drawn_labels = []
        self._cover = None
        if self._inspect:
            for _depth, body, proj in shots:
                if body.name == self._inspect and proj is not None:
                    self._cover = (
                        proj[0],
                        proj[1],
                        self._true_px(body.radius, proj[2]),
                    )
                    break
        if software:
            if sun is not None and dist_sun > 0.25 * AU_M:
                self._paint_ecliptic(painter, sun)
            if system.show_trails:
                self._paint_trails(painter, system)
            if system.show_lagrange:
                self._paint_lagrange(painter, system)
            if system.show_osculating:
                self._paint_heliocentric_orbits(painter, system)
        for _depth, body, proj in shots:
            if body.tracer:
                if software:
                    self._paint_body(painter, system, body, sun, self._basis, proj)
                continue
            if _is_sketch(body):
                continue
            if software:
                self._paint_body(painter, system, body, sun, self._basis, proj)
            elif proj is not None:
                sx, sy, depth = proj
                px_r = self._screen_radius(body, depth)
                self._label_body(painter, body, sx, sy, px_r)
        if system.overlay.show_gravity:
            self._paint_wells(painter, system, strokes=software)
            self._paint_g(painter, system)
        if system.overlay.show_magnetic:
            self._paint_magnetopause(painter, system, strokes=software)
        if system.overlay.show_wind:
            self._paint_wind(painter, system)
        if system.overlay.show_grid:
            self._paint_grid(painter, system)
        self._paint_free_markers(painter, system)
        self._paint_hud(painter, system)
        self._paint_roster(painter, system)
        self._paint_inspect(painter, system)
        self._paint_speed(painter)
        self._paint_epoch(painter, system)
        self._paint_tools(painter)
        self._paint_confirm(painter)

    def _light_cam(
        self,
        body: BodyView,
        sun,
        basis: _Basis,
    ) -> tuple[float, float, float]:
        fx, fy, fz = basis
        if sun is None or body.name == "Sun":
            return (0.2, 0.3, 1.0)
        lx, ly, lz = sun.x - body.x, sun.y - body.y, sun.z - body.z
        return (
            lx * fx[0] + ly * fx[1] + lz * fx[2],
            lx * fy[0] + ly * fy[1] + lz * fy[2],
            -(lx * fz[0] + ly * fz[1] + lz * fz[2]),
        )

    def _paint_body(
        self,
        painter: QPainter,
        system: SolarSystem,
        body: BodyView,
        sun,
        basis: _Basis,
        proj: tuple[float, float, float] | None = None,
    ) -> None:
        if proj is None:
            proj = self._proj((body.x, body.y, body.z))
        if proj is None:
            return
        sx, sy, depth = proj
        px_r = self._screen_radius(body, depth)
        if body.tracer:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(180, 180, 190, 80))
            painter.drawEllipse(QPoint(int(sx), int(sy)), 1, 1)
            return
        light = self._light_cam(body, sun, basis)
        info = describe(body.name)
        alb = _albedo(info.path) if info.path is not None else None
        lon = lat = None
        size = max(16, min(int(px_r * 2), _GLOBE_MAX))
        tint = _TINT.get(body.name, (200, 180, 160))
        if body.name == "Sun" and abs(system.future_gyr) > 1e-6:
            tint = sun_rgb(sample(system.future_gyr))
        if alb is not None and px_r >= 6:
            nx, ny, nz = _sphere_axes(size)
            nwx, nwy, nwz = _world_normals(nx, ny, nz, basis)
            jd = spin_jd(system.epoch_jd, system.t)
            if body.name == "Earth" and system.epoch_jd > 0.0:
                lon, lat = earth_lonlat_grid(nwx, nwy, nwz, jd)
            elif body.name == "Moon":
                earth = system.nbody.find("Earth")
                if earth is not None:
                    lon, lat = moon_lonlat_grid(
                        nwx,
                        nwy,
                        nwz,
                        (body.x, body.y, body.z),
                        (earth.x, earth.y, earth.z),
                    )
            else:
                earth = system.nbody.find("Earth")
                moon = system.nbody.find("Moon")
                frame = body_frame_ecliptic(
                    body.name,
                    jd,
                    moon=(moon.x, moon.y, moon.z) if moon is not None else None,
                    earth=(earth.x, earth.y, earth.z) if earth is not None else None,
                )
                if frame is not None:
                    lon, lat = lonlat_from_frame(nwx, nwy, nwz, frame)
        if px_r >= 4:
            globe = _globe(
                size,
                light,
                albedo=alb if alb is not None and px_r >= 6 else None,
                tint=tint,
                lon=lon,
                lat=lat,
                fill=0.28 if body.kind == "asteroid" else _FILL,
                emissive=body.name == "Sun",
                granulate=body.name == "Sun" and px_r >= 80.0,
            )
            painter.drawImage(
                QRect(
                    int(sx - px_r),
                    int(sy - px_r),
                    int(px_r * 2),
                    int(px_r * 2),
                ),
                globe,
            )
            if body.name == "Earth" and px_r >= 12:
                self._earth_limb(painter, sx, sy, px_r)
            if body.name == "Sun" and px_r >= 8:
                self._sun_limb(painter, sx, sy, px_r)
                self._paint_sun_loops(painter, system, body)
            if body.name == "Saturn" and px_r >= 8:
                self._paint_saturn_rings(painter, body)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(*tint))
            painter.drawEllipse(QPoint(int(sx), int(sy)), max(1, int(px_r)), max(1, int(px_r)))
        self._label_body(painter, body, sx, sy, px_r)

    def _chrome_rects(self) -> list[QRect]:
        """Panel boxes a label must dodge, rebuilt only when the chrome changes.

        Six candidate positions per body times every visible body used to
        re-sort the roster and re-derive the inspect tile for each probe.
        """
        system = get_system()
        key = (
            self.width(),
            self.height(),
            self._hud_bottom,
            self._inspect or "",
            self._roster_scroll,
            self._help,
            self._tools_open,
            str(self._confirm.get("kind") or "") if self._confirm else "",
            id(system),
            0 if system is None else len(system.nbody.particles),
            bool(system is not None and system.show_graphs),
        )
        if key == self._chrome_key and self._chrome_cache is not None:
            return self._chrome_cache
        boxes = [
            self._hud_plate_rect(),
            self._roster_rect(),
            self._speed_rect(),
            self._epoch_rect(),
        ]
        if not self._keys_hit.isEmpty():
            boxes.append(self._keys_hit)
        if self._tools_open:
            boxes.append(self._tools_rect())
        for box in (self._inspect_rect(), self._confirm_rect()):
            if not box.isEmpty():
                boxes.append(box)
        self._chrome_key = key
        self._chrome_cache = boxes
        return boxes

    def _chrome_covers(self, x: int, y: int) -> bool:
        return any(box.contains(x, y) for box in self._chrome_rects())

    def _label_body(
        self,
        painter: QPainter,
        body: BodyView,
        sx: float,
        sy: float,
        px_r: float,
    ) -> None:
        inspect = body.name == self._inspect
        if inspect:
            return
        if self._on_globe(sx, sy):
            return
        want = px_r >= 6 or body.kind in {"star", "planet", "asteroid"}
        if not want:
            return
        width = self._label_w.get(body.name)
        if width is None:
            width = max(28, painter.fontMetrics().horizontalAdvance(body.name) + 4)
            self._label_w[body.name] = width
        candidates = (
            (int(sx + max(px_r, 2) + 6), int(sy + 4)),
            (int(sx - width - 4), int(sy + 4)),
            (int(sx + 4), int(sy - max(px_r, 2) - 12)),
            (int(sx + 4), int(sy + max(px_r, 2) + 14)),
            (int(sx + max(px_r, 2) + 6), int(sy - 12)),
            (int(sx - width - 4), int(sy - 12)),
        )
        chosen: tuple[int, int] | None = None
        for x, y in candidates:
            if self._chrome_covers(x, y):
                continue
            if any(
                abs(ox - x) < 48 and abs(oy - y) < 13
                for _name, ox, oy, _w in self._drawn_labels
            ):
                continue
            chosen = (x, y)
            break
        if chosen is None:
            return
        x, y = chosen
        self._drawn_labels.append((body.name, x, y, width))
        painter.setPen(color("text_dim"))
        painter.drawText(x, y, body.name)

    def _on_globe(self, x: float, y: float) -> bool:
        if self._cover is None:
            return False
        cx, cy, cr = self._cover
        return math.hypot(x - cx, y - cy) < cr + 6.0

    def _close_globe(self) -> bool:
        return self._cover is not None and self._cover[2] >= _CLOSE_GLOBE_PX

    def _look_field_m(self, system: SolarSystem) -> float:
        look = self.cam.distance
        if self._inspect:
            body = system.nbody.find(self._inspect)
            if body is not None:
                look = math.hypot(
                    self.cam.x - body.x,
                    self.cam.y - body.y,
                    self.cam.z - body.z,
                )
        return look * math.tan(0.35)

    def _earth_limb(self, painter: QPainter, sx: float, sy: float, px_r: float) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        halo = QPen(QColor(110, 170, 255, 48))
        halo.setWidth(max(1, int(px_r * 0.028)))
        painter.setPen(halo)
        painter.drawEllipse(
            QPoint(int(sx), int(sy)),
            int(px_r + 2),
            int(px_r + 2),
        )

    def _sun_limb(self, painter: QPainter, sx: float, sy: float, px_r: float) -> None:
        """Optically-thin gold falloff. Not the old six-fold ray spikes."""
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for mul, alpha, width in (
            (1.12, 200, 0.08),
            (1.45, 110, 0.14),
            (2.05, 55, 0.22),
            (3.20, 22, 0.32),
            (4.80, 10, 0.40),
        ):
            halo = QPen(QColor(255, 140, 32, alpha))
            halo.setWidth(max(2, int(px_r * width)))
            painter.setPen(halo)
            painter.drawEllipse(
                QPoint(int(sx), int(sy)),
                int(px_r * mul),
                int(px_r * mul),
            )

    def _paint_sun_loops(
        self, painter: QPainter, system: SolarSystem, body: BodyView
    ) -> None:
        from arelis.physics.corona import loops

        disc = self._proj((body.x, body.y, body.z))
        if disc is None or disc[2] < 1.0:
            return
        from arelis.physics.corona import LOOP_MIN_PX

        if self._true_px(body.radius, disc[2]) < LOOP_MIN_PX:
            return
        jd = spin_jd(system.epoch_jd, system.t)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for loop in loops(body.radius, jd, time.perf_counter()):
            pts: list[QPoint] = []
            for x, y, z in loop.points:
                hit = self._proj((body.x + x, body.y + y, body.z + z))
                if hit is None:
                    if len(pts) >= 2:
                        self._stroke_loop(painter, pts, loop.flare)
                    pts = []
                    continue
                pts.append(QPoint(int(hit[0]), int(hit[1])))
            if len(pts) >= 2:
                self._stroke_loop(painter, pts, loop.flare)

    def _stroke_loop(self, painter: QPainter, pts: list[QPoint], flare: float) -> None:
        if flare > 0.22:
            painter.setPen(QPen(QColor(255, 220, 90, 210), 2))
        else:
            painter.setPen(QPen(QColor(255, 130, 28, 120), 1))
        for a, b in pairwise(pts):
            painter.drawLine(a, b)

    def _paint_saturn_rings(self, painter: QPainter, body: BodyView) -> None:
        """IAU pole + C–A radii. Sketch, not ring particles."""
        xx, yx, zx = saturn_ring_axes()
        del zx
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(220, 200, 160, 110), 1))
        disc = self._proj((body.x, body.y, body.z))
        hide_r = (
            self._true_px(body.radius, disc[2]) if disc is not None else 0.0
        )
        for radius in (
            SATURN_RING_INNER_M,
            SATURN_CASSINI_INNER_M,
            SATURN_CASSINI_OUTER_M,
            SATURN_RING_OUTER_M,
        ):
            pts = []
            for i in range(64):
                ang = 2.0 * math.pi * i / 64.0
                c, s = math.cos(ang), math.sin(ang)
                proj = self._proj(
                    (
                        body.x + (xx[0] * c + yx[0] * s) * radius,
                        body.y + (xx[1] * c + yx[1] * s) * radius,
                        body.z + (xx[2] * c + yx[2] * s) * radius,
                    )
                )
                if proj is None:
                    continue
                if disc is not None and math.hypot(
                    proj[0] - disc[0], proj[1] - disc[1]
                ) < hide_r:
                    continue
                pts.append(QPoint(int(proj[0]), int(proj[1])))
            if len(pts) > 2:
                for a, b in zip(pts, pts[1:], strict=False):
                    painter.drawLine(a, b)

    def _paint_heliocentric_orbits(self, painter: QPainter, system: SolarSystem) -> None:
        """Osculating ellipses. Not trails, not a radius cheat."""
        inspect = self._inspect
        close = self._close_globe()
        for body in system.views():
            if body.tracer or body.name == "Sun":
                continue
            if body.kind == "moon" and body.name != inspect and body.parent != inspect:
                continue
            if body.kind not in {"planet", "asteroid", "moon"}:
                continue
            if close and body.parent != inspect:
                continue
            r, v, mu, _about, origin = system.about(body)
            el = osculating(r, v, mu)
            if el is None or el.e >= 0.95:
                continue
            alpha = 90 if body.name == inspect else 42 if body.kind == "planet" else 28
            dash = QPen(QColor(255, 255, 255, alpha))
            dash.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(dash)
            pts = []
            steps = 72 if body.kind == "asteroid" else 96
            for i in range(steps):
                nu = 2.0 * math.pi * i / steps
                px, py, pz = position_at_true_anomaly(el, nu)
                proj = self._proj((origin[0] + px, origin[1] + py, origin[2] + pz))
                if proj is None or self._on_globe(proj[0], proj[1]):
                    pts.append(None)
                    continue
                pts.append(QPoint(int(proj[0]), int(proj[1])))
            if len([p for p in pts if p is not None]) > 2:
                for a, b in zip(pts, pts[1:] + pts[:1], strict=False):
                    if a is None or b is None:
                        continue
                    painter.drawLine(a, b)
            phase = (time.perf_counter() / BEAD_LAP_S) * 2.0 * math.pi
            for k, nu_b in enumerate(
                bead_true_anomalies(el.true_anomaly, phase=phase)
            ):
                bx, by, bz = position_at_true_anomaly(el, nu_b)
                hit = self._proj((origin[0] + bx, origin[1] + by, origin[2] + bz))
                if hit is None:
                    continue
                lead = 1.0 if k == 0 else 0.42
                glow = 3 + int(3 * lead)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(200, 230, 255, int(120 + 110 * lead)))
                painter.drawEllipse(QPoint(int(hit[0]), int(hit[1])), glow, glow)
            painter.setBrush(Qt.BrushStyle.NoBrush)

    def _paint_trails(self, painter: QPainter, system: SolarSystem) -> None:
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
        for name, trail in system.trails.items():
            del name
            pts = []
            for x, y, z in trail:
                proj = self._proj((x, y, z))
                if proj:
                    pts.append(QPoint(int(proj[0]), int(proj[1])))
            for a, b in pairwise(pts):
                painter.drawLine(a, b)

    def _paint_lagrange(self, painter: QPainter, system: SolarSystem) -> None:
        painter.setPen(QPen(QColor(180, 220, 255, 160), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for pts in (system.lagrange_sun_earth(), system.lagrange_sun_jupiter()):
            for label, xyz in pts.items():
                proj = self._proj(xyz)
                if proj is None:
                    continue
                x, y, _d = proj
                painter.drawLine(int(x - 4), int(y), int(x + 4), int(y))
                painter.drawLine(int(x), int(y - 4), int(x), int(y + 4))
                painter.drawText(int(x + 6), int(y - 2), label)

    def _paint_ecliptic(self, painter: QPainter, sun) -> None:
        dash = QPen(QColor(255, 255, 255, 28))
        dash.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(dash)
        pts = []
        for i in range(96):
            ang = 2.0 * math.pi * i / 96.0
            x = sun.x + AU_M * math.cos(ang)
            y = sun.y + AU_M * math.sin(ang)
            proj = self._proj((x, y, sun.z))
            if proj:
                pts.append(QPoint(int(proj[0]), int(proj[1])))
        for a, b in zip(pts, pts[1:] + pts[:1], strict=False):
            painter.drawLine(a, b)

    def _facing(self, cx: float, cy: float, cz: float, x: float, y: float, z: float) -> bool:
        return (x - cx) * (self._eye[0] - x) + (y - cy) * (self._eye[1] - y) + (
            z - cz
        ) * (self._eye[2] - z) > 0.0

    def _stroke_world(
        self,
        painter: QPainter,
        pts: list[tuple[float, float, float]],
        *,
        closed: bool = False,
        host: tuple[float, float, float] | None = None,
    ) -> None:
        last = None
        seq = pts + ([pts[0]] if closed and pts else [])
        for p in seq:
            if host is not None and not self._facing(host[0], host[1], host[2], *p):
                last = None
                continue
            proj = self._proj(p)
            if proj is None:
                last = None
                continue
            cur = QPoint(int(proj[0]), int(proj[1]))
            if last is not None:
                painter.drawLine(last, cur)
            last = cur

    def _ring_xy(
        self,
        painter: QPainter,
        body: BodyView,
        radius: float,
        n: int = 72,
    ) -> None:
        pts = [
            (
                body.x + radius * math.cos(2.0 * math.pi * i / n),
                body.y + radius * math.sin(2.0 * math.pi * i / n),
                body.z,
            )
            for i in range(n)
        ]
        self._stroke_world(painter, pts, closed=True)

    def _paint_sphere_cage(
        self,
        painter: QPainter,
        body: BodyView,
        radius: float,
        *,
        meridians: int = 4,
    ) -> None:
        """Projected meridians + equator of a sphere. Software stand-in for a shell."""
        self._ring_xy(painter, body, radius)
        n = 36
        for k in range(max(int(meridians), 2)):
            lon = k * math.pi / max(int(meridians), 2)
            cl, sl = math.cos(lon), math.sin(lon)
            pts = [
                (
                    body.x + radius * math.sin(math.pi * i / n) * cl,
                    body.y + radius * math.sin(math.pi * i / n) * sl,
                    body.z + radius * math.cos(math.pi * i / n),
                )
                for i in range(n + 1)
            ]
            self._stroke_world(painter, pts)

    def _paint_magnetopause(
        self, painter: QPainter, system: SolarSystem, *, strokes: bool = True
    ) -> None:
        from arelis.physics.magnetosphere import (
            dipole_L_polylines,
            earth_standoff_m,
            shue_meridians,
            sunward_basis,
        )
        from arelis.physics.parker import dynamic_pressure_npa

        earth = system.nbody.find("Earth")
        sun = system.nbody.find("Sun")
        if earth is None:
            return
        if self._inspect and self._inspect != "Earth":
            return
        if sun is not None:
            sl = math.hypot(sun.x - earth.x, sun.y - earth.y, sun.z - earth.z) or AU_M
            p_npa = dynamic_pressure_npa(sl)
            ux, uy, uz = sunward_basis(
                (earth.x, earth.y, earth.z), (sun.x, sun.y, sun.z)
            )
        else:
            p_npa = dynamic_pressure_npa(AU_M)
            ux, uy, uz = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
        r0_m, r0_re, alpha = earth_standoff_m(p_npa, earth.radius)
        host = (earth.x, earth.y, earth.z)
        if strokes:
            painter.setPen(QPen(QColor(120, 180, 255, 130), 1))
            for line in shue_meridians(r0_m, alpha, ux, uy, uz):
                world = [(host[0] + p[0], host[1] + p[1], host[2] + p[2]) for p in line]
                self._stroke_world(painter, world)
            painter.setPen(QPen(QColor(150, 200, 255, 80), 1))
            for loop in dipole_L_polylines(earth.radius, ux, uy, uz, n_lon=8):
                world = [
                    (host[0] + p[0], host[1] + p[1], host[2] + p[2]) for p in loop
                ]
                self._stroke_world(painter, world)
        nose = (host[0] + r0_m * ux[0], host[1] + r0_m * ux[1], host[2] + r0_m * ux[2])
        proj = self._proj(nose)
        if proj is not None and self._inspect != "Earth":
            painter.setPen(QColor(160, 200, 255, 190))
            painter.drawText(
                int(proj[0]) + 8,
                int(proj[1]) - 4,
                f"Shue r0={r0_re:.1f} Re  P={p_npa:.2f} nPa + dipole — not IGRF",
            )

    def _paint_wind(self, painter: QPainter, system: SolarSystem) -> None:
        from arelis.physics.attitude import spin_jd
        from arelis.physics.parker import (
            CITE,
            HELIOPAUSE_AU,
            R_SOURCE_RSUN,
            heliopause_ring,
            spiral_points,
        )

        sun = system.nbody.find("Sun")
        if sun is None:
            return
        jd = spin_jd(system.epoch_jd, system.t)
        r_sun = BODY_BY_NAME["Sun"].radius
        r0 = R_SOURCE_RSUN * r_sun
        r1 = 5.0 * AU_M
        painter.setPen(QPen(QColor(255, 170, 70, 70), 1))
        for k in range(8):
            phi0 = k * math.pi / 4.0
            pts = spiral_points(phi0, r0, r1, jd)
            world = [(sun.x + p[0], sun.y + p[1], sun.z + p[2]) for p in pts]
            self._stroke_world(painter, world)
        hp = heliopause_ring(HELIOPAUSE_AU * AU_M, jd)
        painter.setPen(QPen(QColor(180, 140, 90, 50), 1, Qt.PenStyle.DashLine))
        world_hp = [(sun.x + p[0], sun.y + p[1], sun.z + p[2]) for p in hp]
        self._stroke_world(painter, world_hp, closed=True)
        hit = self._proj((sun.x + hp[0, 0], sun.y + hp[0, 1], sun.z + hp[0, 2]))
        if hit is not None:
            painter.setPen(QColor(200, 160, 90, 160))
            painter.drawText(int(hit[0]) + 6, int(hit[1]) - 2, "heliopause ~120 AU (Voyager)")
        disc = self._proj((sun.x, sun.y, sun.z))
        if disc is not None and self._inspect != "Sun" and self._true_px(r_sun, disc[2]) >= 8.0:
            painter.setPen(QColor(255, 180, 80, 170))
            painter.drawText(int(disc[0]) + 10, int(disc[1]) + 14, CITE.split(". ")[0] + ".")

    def _paint_g(self, painter: QPainter, system: SolarSystem) -> None:
        name = self._inspect or system.lock
        origin = system.nbody.find(name)
        if origin is None:
            return
        gx, gy, gz, g = system.gravity_at(origin.x, origin.y, origin.z)
        if g < 1e-20:
            return
        scale = max(8.0e6, origin.radius * 3.0)
        tip = (
            origin.x + gx / g * scale,
            origin.y + gy / g * scale,
            origin.z + gz / g * scale,
        )
        a = self._proj((origin.x, origin.y, origin.z))
        b = self._proj(tip)
        if a is None or b is None:
            return
        painter.setPen(QPen(QColor(255, 200, 80, 200), 2))
        painter.drawLine(int(a[0]), int(a[1]), int(b[0]), int(b[1]))
        painter.setPen(color("text"))
        painter.drawText(int(b[0]) + 6, int(b[1]), f"|g|={g:.3e} m/s² at centre")

    def _paint_wells(
        self, painter: QPainter, system: SolarSystem, *, strokes: bool = True
    ) -> None:
        inspect = system.nbody.find(self._inspect) if self._inspect else None
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if strokes:
            for body in system.views():
                if _is_sketch(body):
                    continue
                wanted = body.kind in {"star", "planet"} or (
                    inspect is not None and body.name == inspect.name
                )
                if not wanted:
                    continue
                disc = self._proj((body.x, body.y, body.z))
                depth = disc[2] if disc is not None else 1.0e30
                for k, alpha in zip(ISO_G_FACTORS, (90, 55, 32), strict=True):
                    if self._true_px(k * body.radius, depth) > 80.0:
                        continue
                    painter.setPen(QPen(QColor(255, 196, 90, alpha), 1))
                    self._paint_sphere_cage(painter, body, k * body.radius)
                r, v, mu, _about, _origin = system.about(body)
                el = osculating(r, v, mu)
                if el is not None and body.mass > 0.0 and mu > 0.0:
                    hill = hill_radius(float(el.a), body.mass, mu / G_SI)
                    if hill > 8.0 * body.radius and self._true_px(hill, depth) <= 72.0:
                        painter.setPen(QPen(QColor(255, 160, 70, 70), 1, Qt.PenStyle.DotLine))
                        self._paint_sphere_cage(painter, body, hill, meridians=6)
                        if inspect is not None and body.name == inspect.name:
                            tip = self._proj((body.x + hill, body.y, body.z))
                            if tip is not None:
                                painter.setPen(QColor(255, 180, 90, 180))
                                painter.drawText(int(tip[0]) + 6, int(tip[1]), "Hill")
                if inspect is not None and body.name == inspect.name:
                    self._paint_well_slice(painter, body, mu)

    def _paint_well_slice(self, painter: QPainter, body: BodyView, mu: float) -> None:
        n = 16
        n_th = well_theta_count(n)
        inner = well_inner_ring(n)
        pts = well_grid(mu, body.radius, n=n)
        painter.setPen(QPen(QColor(255, 180, 80, 70), 1))
        for ir in range(inner, n + 1):
            ring = [
                (
                    body.x + pts[ir * n_th + it][0],
                    body.y + pts[ir * n_th + it][1],
                    body.z + pts[ir * n_th + it][2],
                )
                for it in range(n_th)
            ]
            self._stroke_world(painter, ring, closed=True)
        for it in range(0, n_th, 2):
            spoke = [
                (
                    body.x + pts[ir * n_th + it][0],
                    body.y + pts[ir * n_th + it][1],
                    body.z + pts[ir * n_th + it][2],
                )
                for ir in range(inner, n + 1)
            ]
            self._stroke_world(painter, spoke)

    def _paint_grid(self, painter: QPainter, system: SolarSystem) -> None:
        if not self._inspect:
            return
        body = system.nbody.find(self._inspect)
        if body is None:
            return
        disc = self._proj((body.x, body.y, body.z))
        if disc is None:
            return
        if self._true_px(body.radius, disc[2]) < 18.0:
            return
        r = body.radius * 1.004
        host = (body.x, body.y, body.z)
        earth = system.nbody.find("Earth")
        moon = system.nbody.find("Moon")
        frame = body_frame_ecliptic(
            body.name,
            spin_jd(system.epoch_jd, system.t),
            moon=(moon.x, moon.y, moon.z) if moon is not None else None,
            earth=(earth.x, earth.y, earth.z) if earth is not None else None,
        )
        if frame is None:
            xx, yx, zx = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
        else:
            xx, yx, zx = frame
        painter.setPen(QPen(QColor(210, 220, 230, 90), 1))
        for k in range(6):
            lon = k * math.pi / 3.0
            cl, sl = math.cos(lon), math.sin(lon)
            meridian = [
                _on_frame(host, r, lat, cl, sl, xx, yx, zx)
                for lat in (math.radians(-80.0 + 160.0 * i / 24.0) for i in range(25))
            ]
            self._stroke_world(painter, meridian, host=host)
        for lat_deg in (-60.0, -30.0, 0.0, 30.0, 60.0):
            lat = math.radians(lat_deg)
            parallel = [
                _on_frame(
                    host,
                    r,
                    lat,
                    math.cos(lon),
                    math.sin(lon),
                    xx,
                    yx,
                    zx,
                )
                for lon in (2.0 * math.pi * i / 36.0 for i in range(36))
            ]
            self._stroke_world(painter, parallel, closed=True, host=host)

    def _maps_alert(self) -> str:
        note = (self._maps_note or "").strip()
        if not note:
            return ""
        low = note.lower()
        if "kepler" in low or "horizons ic" in low or "cached" in low:
            return ""
        if "counterfactual" in low:
            return ""
        if "horizons" in low or "vector" in low:
            return ""
        if "fetching nasa albedo" in low:
            return note
        if "map" in low or "albedo" in low:
            return note
        return ""

    def _inspect_column_width(self) -> int:
        if not self._inspect:
            return 0
        want = min(520, max(460, self.width() // 3))
        room = self.width() - 28 - _HUD_LANE
        if room < 240:
            return max(200, self.width() - _HUD_LANE - 28)
        return min(want, max(240, room))

    def _hud_plate_width(self) -> int:
        right = self.width() - 10
        if self._inspect:
            col = self._inspect_column_width()
            right = min(right, self.width() - col - 16 - _HUD_GAP)
        return max(_HUD_MIN_W, min(_HUD_MAX_W, right - 10))

    def _hud_plate_rect(self) -> QRect:
        if not self._hud_box.isEmpty():
            return QRect(self._hud_box)
        return QRect(10, 8, self._hud_plate_width(), max(8, self._hud_bottom - 8))

    def _legend_columns(self, inner_w: int) -> int:
        return 4 if inner_w >= 560 else 2

    def _hud_status_lines(self, system: SolarSystem) -> list[str]:
        hud = system.hud_for_lock()
        look = self._look_field_m(system)
        clock = "paused" if system.paused else "run"
        bits = [
            clock,
            rate_label(float(hud.get("rate") or system.rate)),
            f"field {_fmt_m(look)}",
        ]
        flags = []
        if system.overlay.show_gravity:
            flags.append("g")
        if system.overlay.show_magnetic:
            flags.append("B")
        if system.overlay.show_wind:
            flags.append("wind")
        if system.overlay.show_grid:
            flags.append("grid")
        if flags:
            bits.append(" ".join(flags))
        lines = ["   ".join(bits)]
        ic = system.ic_caption()
        if ic:
            lines.append(ic)
        alert = self._maps_alert()
        if alert:
            lines.append(alert)
        if not self._space_live() and self._gl is not None:
            lines.append("OpenGL failed — software globes")
        return lines

    def _wrapped_h(self, fm: QFontMetrics, text: str, width: int) -> int:
        wrap = int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap)
        return fm.boundingRect(QRect(0, 0, max(width, 40), 8000), wrap, text).height()

    def _key_strip_chips(
        self, fm: QFontMetrics, left: int, top: int, width: int
    ) -> tuple[list[tuple[QRect, str, bool]], int]:
        chips: list[tuple[QRect, str, bool]] = []
        x = left + 10
        y = top + 4
        right = left + width - 10
        for key, hint in KEY_STRIP:
            label = f"{key}  {hint}"
            w = fm.horizontalAdvance(label) + 16
            if x + w > right and x > left + 10:
                x = left + 10
                y += _KEYS_ROW + 4
            chips.append((QRect(x, y, w, _KEYS_ROW), label, key == "H" and self._help))
            x += w + 6
        return chips, y + _KEYS_ROW + 4

    def _legend_items(
        self, box_left: int, legend_top: int, inner_w: int
    ) -> tuple[list[tuple[int, int, str, tuple[tuple[str, str], ...], int]], int]:
        cols = self._legend_columns(inner_w)
        col_w = max(130, inner_w // max(cols, 1))
        items: list[tuple[int, int, str, tuple[tuple[str, str], ...], int]] = []
        bottom = legend_top
        for gi, (title, rows) in enumerate(KEY_LEGEND):
            cx = box_left + 10 + (gi % cols) * col_w
            cy = legend_top + (gi // cols) * _LEGEND_BLOCK
            items.append((cx, cy, title, rows, col_w))
            bottom = max(bottom, cy + 32 + len(rows) * _LEGEND_ROW)
        return items, bottom

    def _keys_chrome_height(self, fm: QFontMetrics, width: int) -> int:
        _chips, y = self._key_strip_chips(fm, 0, 0, width)
        if not self._help:
            return y
        inner_w = width - 20
        _items, bottom = self._legend_items(0, y, inner_w)
        y = bottom + 8
        return y + self._wrapped_h(fm, self._keys_footer(), inner_w) + 8

    def _keys_footer(self) -> str:
        return "Spoken flags match H and ⋯. No F. Travel flies the eye, not a burn."

    def _paint_plate(self, painter: QPainter, box: QRect, *, radius: int = 8) -> None:
        painter.setPen(QPen(color("edge"), 1))
        painter.setBrush(_wash("glass_fill", 255))
        painter.drawRoundedRect(box, radius, radius)

    def _paint_chip(
        self,
        painter: QPainter,
        box: QRect,
        label: str,
        *,
        on: bool = False,
    ) -> None:
        painter.setPen(QPen(color("edge_hot") if on else color("edge"), 1))
        painter.setBrush(_wash("accent", 130 if on else 42))
        painter.drawRoundedRect(box, 4, 4)
        painter.setPen(color("text"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)

    def _paint_keys_chrome(self, painter: QPainter, box: QRect) -> int:
        """Always-on key strip. Click toggles the grouped legend. Returns used height."""
        fm = painter.fontMetrics()
        chips, y = self._key_strip_chips(fm, box.left(), box.top(), box.width())
        for rect, label, on in chips:
            self._paint_chip(painter, rect, label, on=on)
        self._keys_hit = QRect(box.left(), box.top(), box.width(), y - box.top())
        if not self._help:
            return y - box.top()
        inner_w = box.width() - 20
        items, bottom = self._legend_items(box.left(), y, inner_w)
        for cx, cy, title, rows, col_w in items:
            painter.setPen(color("accent"))
            painter.drawText(cx, cy + 14, title)
            yy = cy + 32
            tight = col_w < 170
            for key, hint in rows:
                if tight:
                    painter.setPen(color("text"))
                    painter.drawText(cx, yy, f"{key}  {hint}")
                else:
                    painter.setPen(color("text"))
                    painter.drawText(cx, yy, key)
                    painter.setPen(color("text_dim"))
                    painter.drawText(cx + 78, yy, hint)
                yy += _LEGEND_ROW
        y = bottom + 8
        wrap = int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap)
        footer = self._keys_footer()
        foot_h = max(24, self._wrapped_h(fm, footer, inner_w) + 4)
        foot = QRect(box.left() + 10, y, inner_w, foot_h)
        painter.setPen(color("text_dim"))
        painter.drawText(foot, wrap, footer)
        y = y + foot_h + 8
        self._keys_hit = QRect(box.left(), box.top(), box.width(), y - box.top())
        return y - box.top()

    def _paint_hud(self, painter: QPainter, system: SolarSystem) -> None:
        wrap = int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap)
        plate_w = self._hud_plate_width()
        inner = plate_w - 24
        fm = painter.fontMetrics()
        lines = self._hud_status_lines(system)
        y = 12
        status_rows: list[tuple[int, int, str]] = []
        for i, line in enumerate(lines):
            h = self._wrapped_h(fm, line, inner)
            status_rows.append((y, h, line))
            y += h + 4
        keys_top = y
        keys_h = self._keys_chrome_height(fm, plate_w)
        plate = QRect(10, 8, plate_w, keys_top + keys_h)
        self._paint_plate(painter, plate, radius=6)
        for i, (y0, h, line) in enumerate(status_rows):
            painter.setPen(color("text") if i == 0 else color("text_dim"))
            painter.drawText(QRect(20, y0, inner, h + 4), wrap, line)
        used = self._paint_keys_chrome(
            painter, QRect(10, keys_top, plate_w, keys_h + 8)
        )
        bottom = max(plate.bottom(), keys_top + used + 8)
        self._hud_box = QRect(plate.left(), plate.top(), plate.width(), bottom - plate.top())
        self._hud_bottom = self._hud_box.bottom()
        if system.show_graphs and system.energy_hist:
            self._spark(painter, system)

    def _spark(self, painter: QPainter, system: SolarSystem) -> None:
        box = QRect(self.width() - 220, 18, 200, 56)
        self._paint_plate(painter, box, radius=4)
        vals = [
            abs(e - system.energy0) / max(abs(system.energy0), 1e-30)
            for _t, e in system.energy_hist
        ]
        if not vals:
            return
        lo, hi = min(vals), max(vals)
        span = max(hi - lo, 1e-16)
        painter.setPen(QPen(color("accent"), 1))
        prev = None
        n = len(vals)
        for i, v in enumerate(vals):
            x = box.left() + int(i / max(n - 1, 1) * (box.width() - 2))
            y = box.bottom() - int((v - lo) / span * (box.height() - 4))
            pt = QPoint(x, y)
            if prev:
                painter.drawLine(prev, pt)
            prev = pt
        painter.setPen(color("text_dim"))
        painter.drawText(box.adjusted(4, 2, 0, 0), "|ΔE/E0|")

    def _paint_free_markers(self, painter: QPainter, system: SolarSystem) -> None:
        for body in system.views():
            if body.kind not in {"probe", "lagrange"}:
                continue
            proj = self._proj((body.x, body.y, body.z))
            if proj is None:
                continue
            sx, sy, _d = proj
            ink = (
                QColor(180, 255, 200, 220)
                if body.kind == "probe"
                else QColor(180, 220, 255, 220)
            )
            painter.setPen(QPen(ink, 2))
            painter.setBrush(ink)
            painter.drawEllipse(QPoint(int(sx), int(sy)), 3, 3)
            painter.setPen(color("text_dim"))
            note = (
                "massless"
                if body.kind == "probe"
                else "CR3BP L-point, not N-body eq."
            )
            painter.drawText(int(sx) + 8, int(sy) - 4, f"{body.name} ({note})")

    def _dots_rect(self) -> QRect:
        return QRect(self.width() - 36, self.height() - 36, 24, 16)

    def _empty_caption(self) -> str:
        if self._load_pending:
            return self._load_progress or "Fetching JPL Horizons VECTORS…"
        note = (self._maps_note or "").strip()
        if note:
            return "No solar system loaded.\n" + _short_horizons_note(note)
        return (
            "No solar system loaded.\n"
            "Fetching JPL Horizons VECTORS once.\n"
            "WASD fly · click a world · H keys · ⋯ overlays"
        )

    def _speed_rect(self) -> QRect:
        return QRect(22, self.height() - 88, min(420, max(120, self.width() - 80)), 16)

    def _u_from_x(self, box: QRect, px: float) -> float:
        return min(1.0, max(0.0, (float(px) - box.left()) / max(box.width(), 1)))

    def _paint_speed(self, painter: QPainter) -> None:
        box = self._speed_rect()
        self._paint_plate(painter, box, radius=3)
        fill_w = int(self.cam.speed_u() * box.width())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_wash("accent", 160))
        painter.drawRect(box.left() + 1, box.top() + 1, max(2, fill_w - 2), box.height() - 2)
        painter.setPen(color("text_dim"))
        painter.drawText(
            box.x(),
            box.y() - 4,
            f"Camera  {speed_label(self.cam.speed)}   Shift+wheel",
        )

    def _inspect_rect(self) -> QRect:
        if not self._inspect:
            return QRect()
        system = get_system()
        lines = self._inspect_lines(system) if system is not None else []
        w = self._inspect_column_width()
        inner = w - 28
        body_h = self._inspect_body_height(lines, inner)
        top = 18
        if system is not None and system.show_graphs:
            top = 154
        h = min(max(body_h + 64, 220), max(220, self.height() - top - 72))
        return QRect(self.width() - w - 16, top, w, h)

    def _inspect_font(self, *, title: bool = False) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(FONT_PX + 6 if title else FONT_PX + 1)
        font.setBold(title)
        return font

    def _inspect_body_height(self, lines: list[str], width: int) -> int:
        title_fm = QFontMetrics(self._inspect_font(title=True))
        body_fm = QFontMetrics(self._inspect_font())
        h = title_fm.height() + 10
        wrap = int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap)
        box = QRect(0, 0, max(width, 40), 8000)
        for i, line in enumerate(lines):
            if i == 0:
                continue
            h += body_fm.boundingRect(box, wrap, line).height() + 8
        return h

    def _inspect_close_rect(self) -> QRect:
        box = self._inspect_rect()
        if box.isEmpty():
            return QRect()
        return QRect(box.right() - 24, box.top() + 6, 18, 18)

    def _inspect_travel_rect(self) -> QRect:
        box = self._inspect_rect()
        if box.isEmpty():
            return QRect()
        return QRect(box.left() + 12, box.bottom() - 38, box.width() - 24, 26)

    def _inspect_lines(self, system: SolarSystem | None) -> list[str]:
        """Memoised per simulated second. Every rect query used to rebuild a HUD."""
        if system is None or not self._inspect:
            return []
        key = (
            id(system),
            self._inspect,
            len(system.nbody.particles),
            int(system.t),
            system.ic_caption(),
            system.overlay.show_magnetic,
            system.overlay.show_wind,
            system.overlay.show_grid,
        )
        if key == self._inspect_key and self._inspect_cache is not None:
            return self._inspect_cache
        lines = self._build_inspect_lines(system)
        self._inspect_key = key
        self._inspect_cache = lines
        return lines

    def _build_inspect_lines(self, system: SolarSystem) -> list[str]:
        hud = system.hud_for_name(self._inspect)
        kind = str(hud.get("kind") or "")
        name = str(hud.get("name") or self._inspect)
        lines = [name]
        parent = hud.get("parent")
        who = kind if kind else "body"
        if parent:
            lines.append(f"{who} of {parent}")
        else:
            lines.append(who)
        radius = float(hud.get("radius_m") or 0)
        gm = float(hud.get("gm") or 0)
        bits = [f"R {_fmt_m(radius)}"]
        if gm > 0.0:
            mass = gm / G_SI
            bits.append(f"M {mass:.3g} kg")
            bits.append(f"GM {gm:.4g} m³/s²")
            if radius > 0.0:
                bits.append(f"g {gm / (radius * radius):.3g} m/s²")
        lines.append(" · ".join(bits) + "  ·  IAU sphere")
        if hud.get("a_au") is not None:
            lines.append(
                f"a {float(hud['a_au']):.4g} AU   e {float(hud.get('e') or 0):.4f}   "
                f"i {float(hud.get('i_deg') or 0):.2f}°   "
                f"P {float(hud.get('period_day') or 0):.3g} d"
            )
            lines.append(
                f"Hill {_fmt_m(float(hud.get('hill_m') or 0))}   "
                f"SOI {_fmt_m(float(hud.get('soi_m') or 0))}   "
                "numbers, not capture walls"
            )
        ic = system.ic_caption()
        if (
            hud.get("e") is not None
            and float(hud.get("e") or 0) < 1e-4
            and "not Horizons" in ic
        ):
            lines.append(
                "e≈0 is the circular Kepler bootstrap, not a Horizons eccentricity."
            )
        hid = hud.get("horizons_id")
        if hid:
            lines.append(f"Horizons COMMAND={hid}")
        info = describe(name)
        if name == "Sun":
            from arelis.physics.corona import CITE

            lines.append(CITE)
        elif kind == "asteroid":
            if info.path is None:
                lines.append(
                    "IAU mean sphere, not a potato. No crater DEM. "
                    f"{info.source}"
                )
            else:
                gsd = f"{info.km_per_px:g} km/px" if info.km_per_px else "?"
                lines.append(
                    f"IAU mean sphere, not a potato. Albedo {info.source} "
                    f"(~{gsd}), large-scale only."
                )
        elif info.path is None:
            lines.append(f"albedo: none — {info.source}. Limb-lit sphere, no fake detail.")
            lines.append(spin_caption(name))
        else:
            gsd = f"{info.km_per_px:g} km/px" if info.km_per_px else "?"
            extra = " " + spin_caption(name)
            src = info.source.lower()
            if any(word in src for word in ("mosaic", "voyager", "cassini")):
                extra += " Coverage gaps stay tint — not invented fill."
            lines.append(f"albedo: {info.source}  (~{gsd}).{extra}")
        if system.overlay.show_magnetic and name != "Earth":
            lines.append(
                "Magnetic overlay is Earth Shue 1998 only. Inspect Earth to see it."
            )
        if system.overlay.show_wind:
            from arelis.physics.parker import CITE as WIND_CITE

            lines.append(WIND_CITE)
        if name == "Saturn":
            lines.append(
                "Rings: IAU WGCCRE 2015 pole, C–A + Cassini (NASA/JPL km). "
                "Sketch, not particles."
            )
        r_stop, cite = stop_radius_m(name)
        lines.append(f"approach stop {_fmt_m(r_stop)}. {cite}")
        integ = str(hud.get("integrator") or "")
        if integ:
            lines.append(integ)
        lines.append(
            "Travel to flies the eye: accel, cruise, slow. Camera warp, not a burn. No landing."
        )
        return [line for line in lines if line]

    def _paint_inspect(self, painter: QPainter, system: SolarSystem) -> None:
        if not self._inspect:
            return
        lines = self._inspect_lines(system)
        box = self._inspect_rect()
        old_font = painter.font()
        self._paint_plate(painter, box, radius=8)
        close = self._inspect_close_rect()
        painter.setPen(color("text_dim"))
        painter.drawText(close, Qt.AlignmentFlag.AlignCenter, "x")
        y = box.top() + 16
        wrap = int(
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap
        )
        if lines:
            painter.setFont(self._inspect_font(title=True))
            painter.setPen(color("text"))
            title_box = QRect(box.left() + 16, y, box.width() - 44, 48)
            painter.drawText(title_box, wrap, lines[0])
            y = (
                painter.fontMetrics()
                .boundingRect(title_box, wrap, lines[0])
                .bottom()
                + 10
            )
        painter.setFont(self._inspect_font())
        limit = box.bottom() - 52
        inner_w = box.width() - 32
        for i, line in enumerate(lines):
            if i == 0:
                continue
            if y > limit:
                break
            painter.setPen(color("text") if i == 1 else color("text_dim"))
            text_box = QRect(box.left() + 16, y, inner_w, max(16, limit - y))
            painter.drawText(text_box, wrap, line)
            y = (
                painter.fontMetrics()
                .boundingRect(text_box, wrap, line)
                .bottom()
                + 8
            )
        travel = self._inspect_travel_rect()
        self._paint_chip(painter, travel, "Travel to  ·  Enter", on=True)
        painter.setFont(old_font)

    def _epoch_rect(self) -> QRect:
        return QRect(22, self.height() - 48, min(420, max(120, self.width() - 80)), 16)

    def _set_epoch_from_x(self, system: SolarSystem, px: float) -> None:
        box = self._epoch_rect()
        u = max(0.0, min(1.0, (float(px) - box.left()) / max(box.width(), 1)))
        system.set_future_gyr(GYR_MIN + u * (GYR_MAX - GYR_MIN))

    def _paint_epoch(self, painter: QPainter, system: SolarSystem) -> None:
        box = self._epoch_rect()
        self._paint_plate(painter, box, radius=3)
        span = GYR_MAX - GYR_MIN
        u = (system.future_gyr - GYR_MIN) / span if span else 0.0
        fill_w = int(max(0.0, min(1.0, u)) * box.width())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_wash("accent", 160))
        painter.drawRect(box.left() + 1, box.top() + 1, max(2, fill_w - 2), box.height() - 2)
        painter.setPen(color("text_dim"))
        sign = "+" if system.future_gyr > 0 else ""
        painter.drawText(
            box.x(),
            box.y() - 4,
            f"Sun {sign}{system.future_gyr:.2f} Gyr   cited track, not IAS15",
        )

    def _tools_rect(self) -> QRect:
        dots = self._dots_rect()
        n = len(SOLAR_OVERLAY) + len(SOLAR_SPAWN)
        width, row_h, head = 328, 36, 8
        height = head + n * row_h + 10
        y = dots.top() - height - 6
        if y < 8:
            height = max(120, dots.top() - 14)
            y = 8
        return QRect(dots.right() - width, y, width, height)

    def _chip_rects(self) -> list[tuple[str, QRect]]:
        panel = self._tools_rect().adjusted(8, 8, -8, -8)
        items = list(SOLAR_OVERLAY) + list(SOLAR_SPAWN)
        n = max(len(items), 1)
        h = max(28, panel.height() // n)
        rows: list[tuple[str, QRect]] = []
        for i, (kind, _label, _hint) in enumerate(items):
            rows.append(
                (kind, QRect(panel.left(), panel.top() + i * h, panel.width(), h - 3))
            )
        return rows

    def _spawn_hit(self, px: float, py: float) -> str | None:
        for kind, rect in self._chip_rects():
            if rect.contains(int(px), int(py)):
                return kind
        return None

    def _overlay_on(self, kind: str) -> bool:
        system = get_system()
        if system is None:
            return False
        if kind == "gravity":
            return system.overlay.show_gravity
        if kind == "magnetic":
            return system.overlay.show_magnetic
        if kind == "wind":
            return system.overlay.show_wind
        if kind == "grid":
            return system.overlay.show_grid
        return False

    def _toggle_overlay(self, kind: str) -> bool:
        """Flip a sketch overlay. True keeps the ⋯ tray open."""
        overlay = {item[0] for item in SOLAR_OVERLAY}
        if kind not in overlay:
            return False
        system = get_system()
        if system is None:
            return True
        if kind == "gravity":
            system.overlay.show_gravity = not system.overlay.show_gravity
        elif kind == "magnetic":
            system.overlay.show_magnetic = not system.overlay.show_magnetic
        elif kind == "wind":
            system.overlay.show_wind = not system.overlay.show_wind
        elif kind == "grid":
            system.overlay.show_grid = not system.overlay.show_grid
        return True

    def _spawn(self, kind: str) -> None:
        if kind == "toy":
            self.toy_requested.emit()
            return
        system = get_system()
        if system is None:
            return
        host = self._inspect
        if kind == "probe" and host and host != "Sun":
            hit = system.nbody.find(host)
            if hit is not None and hit.massive:
                system.lock = host
        try:
            if kind == "probe":
                system.spawn_probe()
            elif kind == "tracer":
                system.spawn_tracer()
            elif kind == "l4":
                system.spawn_lagrange("L4")
            elif kind == "impulse":
                self._open_impulse_confirm(self._inspect or "")
            elif kind == "planet":
                self._open_planet_confirm()
        except RuntimeError:
            return

    def _open_impulse_confirm(self, name: str) -> None:
        system = get_system()
        body = system.nbody.find(name) if system is not None and name else None
        if body is None or not body.massive:
            self._confirm = {"kind": "need_inspect"}
            return
        self._confirm = {"kind": "impulse", "name": body.name, "dv_mps": 100.0}

    def _open_planet_confirm(self) -> None:
        system = get_system()
        if system is None or system.nbody.find("Sun") is None:
            self._confirm = {"kind": "need_inspect"}
            return
        self._confirm = {"kind": "planet", "a_au": 2.5}

    def _confirm_rect(self) -> QRect:
        if not self._confirm:
            return QRect()
        kind = str(self._confirm.get("kind") or "")
        h = 140 if kind == "need_inspect" else 220
        w = 440
        return QRect((self.width() - w) // 2, (self.height() - h) // 2 - 16, w, h)

    def _confirm_chip_rects(self) -> dict[str, QRect]:
        box = self._confirm_rect()
        if box.isEmpty():
            return {}
        y = box.bottom() - 34
        kind = str(self._confirm.get("kind") or "") if self._confirm else ""
        chips: dict[str, QRect] = {}
        if kind == "impulse":
            x = box.left() + 16
            for label in ("dv10", "dv100", "dv1000"):
                chips[label] = QRect(x, box.top() + 118, 88, 24)
                x += 96
        if kind == "planet":
            chips["a_prev"] = QRect(box.left() + 16, box.top() + 118, 28, 24)
            chips["a_next"] = QRect(box.left() + 52, box.top() + 118, 28, 24)
        if kind != "need_inspect":
            chips["apply"] = QRect(box.left() + 16, y, 120, 24)
            chips["cancel"] = QRect(box.left() + 144, y, 120, 24)
        else:
            chips["cancel"] = QRect(box.left() + 16, y, 120, 24)
        return chips

    def _confirm_hit(self, px: float, py: float) -> str | None:
        box = self._confirm_rect()
        if box.isEmpty() or not box.contains(int(px), int(py)):
            return None
        for name, rect in self._confirm_chip_rects().items():
            if rect.contains(int(px), int(py)):
                return name
        return "bg"

    def _confirm_click(self, hit: str) -> None:
        if self._confirm is None or hit == "bg":
            return
        if hit == "cancel":
            self._confirm = None
            self.update()
            return
        if hit == "dv10":
            self._confirm["dv_mps"] = 10.0
        elif hit == "dv100":
            self._confirm["dv_mps"] = 100.0
        elif hit == "dv1000":
            self._confirm["dv_mps"] = 1000.0
        elif hit == "a_prev":
            a = float(self._confirm.get("a_au") or 2.5)
            self._confirm["a_au"] = max(0.5, round(a - 0.5, 4))
        elif hit == "a_next":
            a = float(self._confirm.get("a_au") or 2.5)
            self._confirm["a_au"] = min(40.0, round(a + 0.5, 4))
        elif hit == "apply":
            self._confirm_apply()
            return
        self.update()

    def _confirm_apply(self) -> None:
        system = get_system()
        ask = self._confirm
        self._confirm = None
        if system is None or ask is None:
            self.update()
            return
        kind = str(ask.get("kind") or "")
        try:
            if kind == "impulse":
                name = str(ask.get("name") or "")
                mag = float(ask.get("dv_mps") or 0.0)
                if not system.prograde_impulse(name, mag):
                    self._maps_note = f"Could not impulse {name}."
            elif kind == "planet":
                a_au = float(ask.get("a_au") or 2.5)
                label = system.add_planet(a_au * AU_M, "extra")
                self._inspect = label
        except RuntimeError as exc:
            self._maps_note = str(exc)
        self.update()

    def _paint_confirm(self, painter: QPainter) -> None:
        ask = self._confirm
        if ask is None:
            return
        box = self._confirm_rect()
        self._paint_plate(painter, box, radius=8)
        kind = str(ask.get("kind") or "")
        painter.setPen(color("text"))
        y = box.top() + 28
        lines: list[str] = []
        if kind == "need_inspect":
            lines = [
                "Inspect a massive body first.",
                "Click a name in the list, then impulse.",
            ]
        elif kind == "impulse":
            name = str(ask.get("name") or "")
            mag = float(ask.get("dv_mps") or 0.0)
            lines = [
                f"Impulse {name}  +{mag:g} m/s prograde",
                "Along inertial v. Massive bodies only.",
                "COUNTERFACTUAL. Energy and L books reset.",
                "This is a new universe, not Horizons.",
            ]
        elif kind == "planet":
            a_au = float(ask.get("a_au") or 2.5)
            lines = [
                f"Add Earth-mass circular planet at {a_au:g} AU",
                "Coplanar with the ecliptic sketch. Not a real body.",
                "COUNTERFACTUAL. Energy and L books reset.",
            ]
        for line in lines:
            painter.drawText(box.left() + 16, y, line)
            y += 18
        chips = self._confirm_chip_rects()
        labels = {
            "dv10": "10 m/s",
            "dv100": "100 m/s",
            "dv1000": "1 km/s",
            "a_prev": "<",
            "a_next": ">",
            "apply": "Apply",
            "cancel": "Cancel",
        }
        selected = float(ask.get("dv_mps") or 0.0) if kind == "impulse" else None
        for name, rect in chips.items():
            on = (name == "dv10" and selected == 10.0) or (
                name == "dv100" and selected == 100.0
            ) or (name == "dv1000" and selected == 1000.0)
            painter.setPen(QPen(color("edge_hot") if on else color("edge"), 1))
            painter.setBrush(_wash("accent", 110 if on else 40))
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(color("text"))
            painter.drawText(
                rect, Qt.AlignmentFlag.AlignCenter, labels.get(name, name)
            )

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
        dots = self._dots_rect()
        ink = color("text_dim")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ink)
        cy = dots.center().y()
        gap = 6
        x0 = dots.center().x() - gap
        for i in range(3):
            painter.drawEllipse(QPoint(x0 + i * gap, cy), 2, 2)
        if not self._tools_open:
            return
        panel = self._tools_rect()
        painter.setBrush(_wash("glass_fill", 236))
        painter.setPen(QPen(color("edge"), 1))
        painter.drawRoundedRect(panel, 6, 6)
        captions = {
            kind: (label, hint)
            for kind, label, hint in (*SOLAR_OVERLAY, *SOLAR_SPAWN)
        }
        overlay = {kind for kind, _label, _hint in SOLAR_OVERLAY}
        for kind, rect in self._chip_rects():
            on = kind in overlay and self._overlay_on(kind)
            painter.setPen(QPen(color("edge_hot") if on else color("edge"), 1))
            painter.setBrush(_wash("accent", 110 if on else 36))
            painter.drawRoundedRect(rect, 4, 4)
            label, hint = captions.get(kind, (kind, ""))
            if on:
                label = f"{label}  on"
            painter.setPen(color("text"))
            painter.drawText(
                rect.adjusted(10, 2, -8, -16),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            painter.setPen(color("text_dim"))
            painter.drawText(
                rect.adjusted(10, 18, -8, -2),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                hint,
            )


def _short_horizons_note(note: str) -> str:
    text = (note or "").strip()
    if any(code in text for code in ("503", "429", "502", "504")) or "busy" in text.lower():
        return "JPL Horizons is busy."
    if "HTTP 400" in text:
        return "Horizons refused a VECTOR request."
    if len(text) > 180:
        return text[:177] + "…"
    return text
