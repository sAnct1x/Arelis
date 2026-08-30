"""Solar plate constants and software-globe helpers. Re-exported from solar."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PySide6.QtGui import (
    QColor,
    QImage,
)

from arelis.physics.constants import (
    AU_M,
)
from arelis.physics.maps import load_rgb
from arelis.physics.scene import BodyView
from arelis.ui.theme import color

_Basis = tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]

_FILL = 0.0  # night is vacuum. Pick uses the disc alpha, not a fake fill.
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
    "⋯ Gravity/Magnetic/Wind/Grid + spawn. Spoken flags match. "
    "Travel to Earth enters the Earth zone. No F.",
)
# Collapsed plate: dim hints plus one real Keys control. H expands KEY_LEGEND.
# Tokens here must match HELP_HOTKEYS.
KEY_STRIP: tuple[tuple[str, str], ...] = (
    ("WASD", "fly"),
    ("Space", "pause"),
    ("click", "inspect"),
    ("H", "keys"),
)
KEY_HINT = "WASD fly · Space pause · click inspect"
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
    "Sun": (255, 236, 210),
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
    vis: np.ndarray | None = None,
    shine_light: tuple[float, float, float] | None = None,
    shine: float = 0.0,
    umbra_glow: bool = False,
) -> QImage:
    """Sphere sample. Finite-disk sun, umbra/penumbra, optional earthshine."""

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
        one = 1.0 - mu
        ld = 1.0 - 0.52 * one - 0.18 * one * one
        limb = np.array((198.0, 86.0, 12.0), dtype=np.float32)
        mid = np.array((255.0, 210.0, 108.0), dtype=np.float32)
        core = np.array((255.0, 248.0, 210.0), dtype=np.float32)
        w = np.power(mu, 0.42)
        samp = limb + (mid - limb) * w[..., None]
        samp = samp + (core - samp) * np.power(mu, 0.65)[..., None]
        samp = samp * ld[..., None]
        samp = samp * 1.08
        samp = samp + np.array((255.0, 245.0, 210.0)) * (0.28 * np.power(mu, 6.0))[
            ..., None
        ]
        if granulate and size >= 32:
            scale = 28.0
            gx = np.floor(nx * scale)
            gy = np.floor(ny * scale)
            fx = nx * scale - gx
            fy = ny * scale - gy
            d1 = np.full_like(nx, 8.0)
            d2 = np.full_like(nx, 8.0)
            for oy in (-1.0, 0.0, 1.0):
                for ox in (-1.0, 0.0, 1.0):
                    cx = gx + ox
                    cy = gy + oy
                    hx = np.mod(np.sin(cx * 127.1 + cy * 311.7) * 43758.5453, 1.0)
                    hy = np.mod(np.sin(cx * 269.5 + cy * 183.3) * 24634.6345, 1.0)
                    rx = ox + hx - fx
                    ry = oy + hy - fy
                    dist = rx * rx + ry * ry
                    closer = dist < d1
                    d2 = np.where(closer, d1, np.minimum(d2, dist))
                    d1 = np.where(closer, dist, d1)
            edge = np.clip((d2 - d1) * 2.6, 0.0, 1.0)
            amp = 0.10 + 0.12 * np.power(one, 0.45)
            cells = np.clip(edge, 0.0, 1.0)
            gran = 0.90 + 0.16 * cells
            samp = samp * gran[..., None]
            samp = samp * (1.0 + 0.05 * amp[..., None] * (edge * 2.0 - 1.0)[..., None])
            samp = samp + np.array((210.0, 90.0, 18.0)) * (0.36 * np.power(one, 3.2))[
                ..., None
            ]
        lit = np.clip(samp, 0, 255).astype(np.uint8)
        rgb[..., :3] = lit
        rgb[..., 3] = np.where(mask, 255, 0).astype(np.uint8)
        return QImage(rgb.data, size, size, size * 4, QImage.Format.Format_RGBA8888).copy()
    lx, ly, lz = light
    ln = math.sqrt(lx * lx + ly * ly + lz * lz) or 1.0
    lambert = np.clip((nx * lx + ny * ly + nz * lz) / ln, 0.0, 1.0)
    sun = lambert if vis is None else lambert * vis
    shade = fill + (1.0 - fill) * sun
    if shine > 1.0e-4 and shine_light is not None:
        slx, sly, slz = shine_light
        sln = math.sqrt(slx * slx + sly * sly + slz * slz) or 1.0
        bounce = np.clip((nx * slx + ny * sly + nz * slz) / sln, 0.0, 1.0)
        shade = shade + shine * bounce
    if albedo is not None:
        if lon is None or lat is None:
            lon = np.arctan2(nx, nz)
            lat = np.arcsin(np.clip(ny, -1.0, 1.0))
        samp = _sample_albedo(albedo, lon, lat)
    else:
        samp = np.array(tint, dtype=np.float32)
    lit = samp * shade[..., None]
    if umbra_glow and vis is not None:
        copper = np.array((158.0, 42.0, 14.0), dtype=np.float32)
        glow = (1.0 - vis) * np.clip(lambert, 0.12, 1.0)
        lit = lit + copper * (0.22 * glow)[..., None]
    rgb[..., :3] = np.clip(lit, 0, 255).astype(np.uint8)
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
