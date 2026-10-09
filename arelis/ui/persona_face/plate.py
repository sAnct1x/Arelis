"""Bake the approved renderer once. A frame only moves the cached layers."""

from __future__ import annotations

import math
import threading

import numpy as np

from arelis.ui.persona_face import face_src as face2
from arelis.ui.persona_face.adult import V24Rig, apply_v23
from arelis.ui.persona_face.face_src import Canvas2
from arelis.ui.persona_face.nebula_src import Canvas, background, hexrgb
from arelis.ui.persona_face.scene_bits import orbit_ring, sparkle

# Head and shoulders. Hair ends around the shoulder, so the plate is not a tall empty drop.
VIEW = (-0.80, 0.80, -0.58, 0.72)
POSE = (0.0, 0.0, 0.0, 1.0)
BLINK_LEVELS = (0.0, 0.25, 0.5, 0.75, 1.0)
GAZE_LEVELS = ((0.0, 0.0), (0.012, -0.01), (-0.008, 0.004))
MOUTH_LEVELS = tuple(i / 7.0 for i in range(8))
# One smooth sweep of the renderer's own hair drift. The ends are different
# poses, so playback walks inside the list and never wraps.
PHASE_COUNT = 36
PHASE_T = np.linspace(0.35, 5.15, PHASE_COUNT)
FACE_T = float(PHASE_T[0])

_RIG: V24Rig | None = None
_LOCK = threading.RLock()


def raster_size(width: int) -> tuple[int, int]:
    x0, x1, y0, y1 = VIEW
    height = max(1, round(width * (y1 - y0) / (x1 - x0)))
    return int(width), height


def unstretch_y(y):
    return face2.VY + (y - face2.VY) / face2.VSTRETCH


def shared_rig() -> V24Rig:
    global _RIG
    with _LOCK:
        if _RIG is None:
            apply_v23()
            _RIG = V24Rig()
        return _RIG


def _bloom_scale(width: int) -> float:
    """Same halo fraction as the 640 px approved still. Sigma is in pixels."""
    # Hero frames were tuned at 1024 px across the same dock-width view.
    return max(0.15, width / 1024.0)


def _shaded(cv: Canvas2) -> tuple[np.ndarray, np.ndarray]:
    acc = np.zeros((cv.H, cv.W, 3))
    for sigma, layer in cv.layers.items():
        scale = 2 * math.pi * sigma * sigma if sigma > 0.5 else 1
        acc += Canvas.blur(layer, sigma) * scale
    shade = np.zeros((cv.H, cv.W))
    tint = np.array([1.0, 1.18, 0.78])
    for sigma, layer in cv.shades.items():
        if sigma > 0.5:
            blurred = Canvas.blur(np.repeat(layer[..., None], 3, -1), sigma)[..., 0]
            shade += blurred * (2 * math.pi * sigma * sigma)
        else:
            shade += layer
    dark = np.exp(-np.clip(shade, 0, None)[..., None] * tint)
    return acc * dark, dark


def _lit(cv: Canvas2, exposure: float) -> tuple[np.ndarray, np.ndarray]:
    colored, dark = _shaded(cv)
    scale = _bloom_scale(cv.W)
    lit = colored.copy()
    for sigma, amount in ((6.0 * scale, 0.35), (22.0 * scale, 0.28), (60.0 * scale, 0.22)):
        lit += amount * Canvas.blur(colored, sigma)
    lit *= exposure * dark**0.6
    return lit, dark


def _fade_bottom(alpha: np.ndarray, premul: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Hair tips die out over the last 12 percent. The raster edge is clear."""
    rows = alpha.shape[0]
    start = int(rows * 0.88)
    if start >= rows - 1:
        return alpha, premul
    ramp = np.ones(rows, dtype=np.float32)
    ramp[start:] = np.linspace(1.0, 0.0, rows - start, dtype=np.float32)
    alpha = alpha * ramp[:, None]
    premul = premul * ramp[:, None, None]
    return alpha, premul


def _neck_lavender(
    cv: Canvas2, alpha: np.ndarray, premul: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Upper neck is lavender gas under the jaw. It thins downward.

    The centre just under the chin is darker than the jaw. The rim stays
    light so a light dock does not pick up a dark shell. Blue stays above green.
    """
    # Below the chin only. A wide band from y 0.22 painted the neck onto the jaw.
    below = np.clip((cv.Y - 0.330) / 0.10, 0.0, 1.0)
    fall = np.clip((0.56 - cv.Y) / 0.16, 0.0, 1.0)
    side = np.clip((0.052 - np.abs(cv.X)) / 0.028, 0.0, 1.0)
    band = below * side * fall
    use = band * (alpha > 0.02)
    # Centre of the neck, just under the jaw, is darker. The rim stays light
    # lavender so the edge is not a dark shell on a light dock.
    jaw = np.clip((0.43 - cv.Y) / 0.08, 0.0, 1.0)
    core = np.clip((side - 0.25) / 0.55, 0.0, 1.0) * jaw
    light = np.array([188.0, 152.0, 216.0], dtype=np.float32) / 255.0
    dark = np.array([176.0, 146.0, 204.0], dtype=np.float32) / 255.0
    tint = light * (1.0 - core[..., None]) + dark * core[..., None]
    new_a = alpha * (0.25 + 0.75 * fall) * (0.50 + 0.50 * below)
    premul = premul * (1.0 - use[..., None]) + (tint * new_a[..., None]) * use[..., None]
    alpha = alpha * (1.0 - use) + new_a * use
    # The glow stays opaque until it is almost gone, so fade the column itself.
    column = np.clip((0.07 - np.abs(cv.X)) / 0.035, 0.0, 1.0)
    drop = np.clip((cv.Y - 0.46) / 0.10, 0.0, 1.0) * column
    alpha = alpha * (1.0 - drop)
    premul = premul * (1.0 - drop[..., None])
    return alpha, premul


def to_premul(
    cv: Canvas2,
    exposure: float = 1.0,
    *,
    face: bool = False,
    floor: float = 0.095,
    ink: str = "glow",
) -> np.ndarray:
    """Filmed light on a clear plate. Faint veil drops out so no rectangle remains.

    The face centre uses the same tone map as render_frame, including the
    nebula glow behind the skin, so the cheek stays the approved lavender.
    The edge stays the glow alone, or a light theme would pick up a dark box.
    """
    if ink == "star":
        # Tight glow only. The wide face bloom turns the four spikes into a disc,
        # and a steep alpha ramp then fills that disc solid white.
        colored, _dark = _shaded(cv)
        scale = _bloom_scale(cv.W)
        lit = colored + 0.5 * Canvas.blur(colored, max(1.1, 2.2 * scale))
        lit *= exposure
        glow = 1.0 - np.exp(-np.clip(lit, 0, None))
        peak = glow.max(axis=-1)
        # Alpha stays with the hue so the fringe is star-colored. The floor
        # drops the wide grey disc; what remains is the core and the spikes.
        hue = glow / np.maximum(peak[..., None], 1e-3)
        alpha = np.clip((peak - 0.16) / 0.28, 0.0, 1.0) ** 1.6
        premul = np.clip(hue, 0.0, 1.0) * alpha[..., None]
        alpha, premul = _fade_bottom(alpha, premul)
        out = np.empty((cv.H, cv.W, 4), dtype=np.uint8)
        out[..., 0] = np.clip(premul[..., 0] * 255.0 + 0.5, 0, 255).astype(np.uint8)
        out[..., 1] = np.clip(premul[..., 1] * 255.0 + 0.5, 0, 255).astype(np.uint8)
        out[..., 2] = np.clip(premul[..., 2] * 255.0 + 0.5, 0, 255).astype(np.uint8)
        out[..., 3] = np.clip(alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)
        return out
    lit, dark = _lit(cv, exposure)
    glow = 1.0 - np.exp(-np.clip(lit, 0, None))
    peak = glow.max(axis=-1)
    # Below this the glow is a rectangle on a light theme, not part of her.
    # Hair sits softer than skin, so its floor is lower. The corners still fall out.
    shown = glow
    if face or ink == "filmed":
        bg = background(cv.W, cv.H, face2.PAL, stars=int(900 * cv.W * cv.H / 1024**2))
        filmed = 1.0 - (1.0 - bg * dark**0.3) * np.exp(-np.clip(lit, 0, None))
        if ink == "filmed":
            shown = filmed
        else:
            core = np.clip((peak - 0.28) / 0.22, 0.0, 1.0) ** 2
            shown = glow * (1.0 - core[..., None]) + filmed * core[..., None]
    # Interior keeps the filmed plate (the approved cheek). The rim's
    # associated color is the glow hue, premultiplied once below, so a
    # light dock does not pick up a black outline.
    hue = glow / np.maximum(peak[..., None], 1e-3)
    # Opaque as soon as the light clears the floor, so hair stays a solid
    # strand field. The color blend below is what kills the gray shell.
    alpha = np.clip((peak - floor) / 0.05, 0.0, 1.0)
    alpha = np.where(peak < floor, 0.0, alpha)
    premul = np.clip(shown, 0.0, 1.0) * alpha[..., None]
    # Filmed color goes gray before it goes clear. Blend the outer band to the
    # glow hue with a wide blur so the shell fades instead of drawing a line.
    empty = (alpha < 0.15).astype(np.float32)
    spread = Canvas.blur(np.repeat(empty[..., None], 3, axis=-1), max(2.0, cv.W * 0.04))[..., 0]
    top = float(spread.max())
    weight = np.clip(spread / top, 0.0, 1.0) if top > 1e-6 else np.zeros_like(spread)
    weight = np.where(alpha < 0.05, 0.0, weight)
    hue_premul = np.clip(hue, 0.0, 1.0) * alpha[..., None]
    premul = hue_premul * weight[..., None] + premul * (1.0 - weight[..., None])
    if face:
        alpha, premul = _neck_lavender(cv, alpha, premul)
    alpha, premul = _fade_bottom(alpha, premul)
    out = np.empty((cv.H, cv.W, 4), dtype=np.uint8)
    out[..., 0] = np.clip(premul[..., 0] * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 1] = np.clip(premul[..., 1] * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 2] = np.clip(premul[..., 2] * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out


def _canvas(width: int, height: int) -> Canvas2:
    return Canvas2(width, height, view=VIEW)


def _clone(cv: Canvas2) -> Canvas2:
    other = _canvas(cv.W, cv.H)
    other.layers = {key: value.copy() for key, value in cv.layers.items()}
    other.shades = {key: value.copy() for key, value in cv.shades.items()}
    return other


def _world_box(
    image: np.ndarray, box: tuple[float, float, float, float], feather: int = 8
) -> np.ndarray:
    """Keep one region of a full frame and fade its edge."""
    x0, x1, y0, y1 = VIEW
    height, width, _ = image.shape
    left, right, top, bottom = box
    px0 = int((left - x0) / (x1 - x0) * width)
    px1 = int((right - x0) / (x1 - x0) * width)
    py0 = int((top - y0) / (y1 - y0) * height)
    py1 = int((bottom - y0) / (y1 - y0) * height)
    px0 = max(0, px0)
    py0 = max(0, py0)
    px1 = min(width, max(px0 + 1, px1))
    py1 = min(height, max(py0 + 1, py1))
    out = np.zeros_like(image)
    patch = image[py0:py1, px0:px1].astype(np.float32)
    yy = np.arange(py1 - py0, dtype=np.float32)
    xx = np.arange(px1 - px0, dtype=np.float32)
    fade_y = np.clip(np.minimum(yy, (py1 - py0 - 1) - yy) / max(feather, 1), 0, 1)
    fade_x = np.clip(np.minimum(xx, (px1 - px0 - 1) - xx) / max(feather, 1), 0, 1)
    fade = fade_y[:, None] * fade_x[None, :]
    patch[..., 3] *= fade
    patch[..., :3] *= fade[..., None]
    out[py0:py1, px0:px1] = np.clip(patch + 0.5, 0, 255).astype(np.uint8)
    return out


def _paint_back(rig: V24Rig, width: int, height: int, t: float) -> np.ndarray:
    cv = _canvas(width, height)
    rig.draw_back(cv, t, POSE)
    return to_premul(cv, 3.2, floor=0.06)


def _fade_outer_left_lock(plate: np.ndarray) -> np.ndarray:
    """Fade the outer left lock out before it crosses the ring.

    Its tips left the head together and read as one flat ribbon below the ring.
    The back hair still fills that side, so the front lock simply thins to
    nothing there over a wide ramp. Premultiplied, so all four channels scale.
    """
    cv = _canvas(plate.shape[1], plate.shape[0])
    side = np.clip((-0.32 - cv.X) / 0.16, 0.0, 1.0)
    below = np.clip((cv.Y - 0.30) / 0.16, 0.0, 1.0)
    keep = 1.0 - face2.smooth(side) * face2.smooth(below)
    out = plate.astype(np.float32) * keep[..., None]
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def _paint_front(rig: V24Rig, width: int, height: int, t: float) -> np.ndarray:
    cv = _canvas(width, height)
    rig.splat_front_hair(cv, t, POSE)
    return _fade_outer_left_lock(to_premul(cv, 1.0))


def _paint_wisps(rig: V24Rig, width: int, height: int) -> np.ndarray:
    cv = _canvas(width, height)
    moved = rig.wisp + 0.035 * rig.d_wisp(rig.wisp, FACE_T)
    # Keep the cloud on the figure. A full-frame veil reads as a rectangle.
    near = np.hypot(moved[:, 0], moved[:, 1] - 0.05) < 0.72
    cv.splat(moved[near], rig.wisp_w[near] * 0.55, rig.wisp_c[near], 9.0)
    return to_premul(cv, 0.7)


def _paint_ring(rig: V24Rig, width: int, height: int) -> np.ndarray:
    cv = _canvas(width, height)
    rng = np.random.default_rng(5)
    orbit_ring(cv, face2.PAL, rig.noise, rng, 0.85, c=(0.0, 0.30), rx=0.70, ry=0.165, tilt=-0.15)
    return to_premul(cv, 1.0)


def _paint_star(rig: V24Rig, width: int, height: int) -> np.ndarray:
    cv = _canvas(width, height)
    spot = rig.to_world(np.array([[0.232, -0.372]]), POSE)[0]
    sparkle(cv, spot, 0.078, hexrgb(face2.PAL["star"]), 0.85 + 0.12 * math.sin(FACE_T * 1.7))
    return to_premul(cv, 1.05, ink="star")


def _body(rig: V24Rig, cv: Canvas2, mouth: float) -> None:
    """Gas, glow dust and neck. The same pass the approved draw uses before the skin."""
    pal = face2.PAL
    gas = rig.gas + 0.004 * rig.d_gas(rig.gas, FACE_T)
    gas = gas.copy()
    gas[:, 1] += mouth * 0.016 * face2.ss(face2.MOUTH_Y - 0.03, face2.CHIN, gas[:, 1])
    cv.splat(rig.to_world(gas, POSE), rig.gas_w, face2.lerpc(pal["face"], pal["hair0"], 0.3), 2.0)
    if face2.GLOW:
        dust = rig.gas[rig._dust]
        tw = 0.5 + 0.5 * np.sin(FACE_T * 1.9 + np.arange(len(dust)) * 2.3)
        cv.splat(
            rig.to_world(dust + 0.003 * rig.d_gas(dust, FACE_T), POSE),
            0.05 * tw,
            hexrgb("#ffffff"),
            0.8,
        )
    if face2.NECK:
        neck = rig.neck_gas + 0.012 * rig.d_wisp(rig.neck_gas, FACE_T) * rig.neck_amp[:, None]
        cv.splat(
            rig.to_world(neck, POSE),
            rig.neck_w,
            face2.lerpc(pal["face"], pal["hair0"], 0.35 + 0.25 * rig.neck_c),
            2.0,
        )


def _fields(rig: V24Rig, cv: Canvas2, mouth: float, blink: float, gaze) -> None:
    rig._pose = POSE
    local_x, local_y = rig.to_local(cv.X, cv.Y, POSE)
    rig.face_fields(cv, local_x, local_y, FACE_T, mouth, blink, gaze, 0.0)


def _skin_canvas(rig: V24Rig, width: int, height: int, cover: np.ndarray) -> Canvas2:
    cv = _canvas(width, height)
    _body(rig, cv, 0.0)
    rig._cover = cover
    rig.skip_eyes = True
    rig.skip_mouth = True
    try:
        _fields(rig, cv, 0.0, 0.0, (0.0, 0.0))
    finally:
        rig.skip_eyes = False
        rig.skip_mouth = False
    return cv


def _draw_eyes(rig: V24Rig, cv: Canvas2, blink: float, gaze: tuple[float, float]) -> None:
    rig._pose = POSE
    local_x, local_y = rig.to_local(cv.X, cv.Y, POSE)
    stretched = face2.EYE_Y + (local_y - face2.EYE_Y) * face2.VSTRETCH
    edge = cv.px * 1.2
    for sign in (-1, 1):
        rig.eye(cv, local_x, stretched, sign, blink, gaze, edge)


def _draw_mouth(rig: V24Rig, cv: Canvas2, mouth: float) -> None:
    rig._pose = POSE
    local_x, local_y = rig.to_local(cv.X, cv.Y, POSE)
    stretched = face2.MOUTH_Y + (local_y - face2.MOUTH_Y) * face2.VSTRETCH
    rig.mouth(cv, local_x, stretched, mouth, cv.px * 1.2)


def _feature_patch(
    rig: V24Rig,
    skin: Canvas2,
    cover: np.ndarray,
    *,
    mouth: float,
    blink: float,
    gaze: tuple[float, float],
    box: tuple[float, float, float, float],
    eyes: bool,
    lips: bool,
) -> np.ndarray:
    cv = _clone(skin)
    rig._cover = cover
    if eyes:
        rig.skip_eyes = False
        _draw_eyes(rig, cv, blink, gaze)
    if lips:
        rig.skip_mouth = False
        _draw_mouth(rig, cv, mouth)
    return _world_box(to_premul(cv, 1.02, face=True), box)


def _stopped(cancel: threading.Event | None) -> bool:
    return cancel is not None and cancel.is_set()


def bake_layers(
    size: int,
    cancel: threading.Event | None = None,
    publish=None,
) -> dict[str, np.ndarray]:
    """Face first, then hair phases. Size is the width in pixels.

    publish(layers_copy, phases_ready, rest_or_none) may run after phase 0
    and again as later phases land. The caller blends only the phases it has.
    The shared rig is not safe to draw from two threads, so the whole bake
    holds the rig lock.
    """
    with _LOCK:
        return _bake_layers(size, cancel, publish)


def _bake_layers(
    size: int,
    cancel: threading.Event | None,
    publish,
) -> dict[str, np.ndarray]:
    width, height = raster_size(int(size))
    rig = shared_rig()
    cover_cv = _canvas(width, height)
    rig.splat_front_hair(cover_cv, FACE_T, POSE, cover_only=True)
    cover = rig._cover
    skin = _skin_canvas(rig, width, height, cover)
    layers: dict[str, np.ndarray] = {
        "wisps": _paint_wisps(rig, width, height),
        "face": to_premul(skin, 1.02, face=True),
        "back_0": _paint_back(rig, width, height, float(PHASE_T[0])),
        "front_0": _paint_front(rig, width, height, float(PHASE_T[0])),
    }
    eye_box = (-0.28, 0.28, -0.10, 0.10)
    mouth_box = (-0.16, 0.16, 0.12, 0.30)
    for index, blink in enumerate(BLINK_LEVELS):
        layers[f"eye_{index}"] = _feature_patch(
            rig,
            skin,
            cover,
            mouth=0.0,
            blink=blink,
            gaze=(0.0, 0.0),
            box=eye_box,
            eyes=True,
            lips=False,
        )
    layers["gaze_0"] = layers["eye_0"]
    for index, gaze in enumerate(GAZE_LEVELS[1:], start=1):
        layers[f"gaze_{index}"] = _feature_patch(
            rig, skin, cover, mouth=0.0, blink=0.0, gaze=gaze, box=eye_box, eyes=True, lips=False
        )
    for index, openness in enumerate(MOUTH_LEVELS):
        layers[f"mouth_{index}"] = _feature_patch(
            rig,
            skin,
            cover,
            mouth=openness,
            blink=0.0,
            gaze=(0.0, 0.0),
            box=mouth_box,
            eyes=False,
            lips=True,
        )
    layers["ring"] = _paint_ring(rig, width, height)
    layers["star"] = _paint_star(rig, width, height)
    if publish is not None and not _stopped(cancel):
        publish(dict(layers), 1)
    for index in range(1, PHASE_COUNT):
        if _stopped(cancel):
            break
        t = float(PHASE_T[index])
        layers[f"back_{index}"] = _paint_back(rig, width, height, t)
        layers[f"front_{index}"] = _paint_front(rig, width, height, t)
        if publish is not None and not _stopped(cancel):
            publish(
                {
                    f"back_{index}": layers[f"back_{index}"],
                    f"front_{index}": layers[f"front_{index}"],
                },
                index + 1,
            )
    return layers


def paint_face(rig, width: int) -> np.ndarray:
    """Skin plate. Alpha is the adult outline so the jaw width can be measured."""
    del rig
    with _LOCK:
        return _paint_face_locked(width)


def _paint_face_locked(width: int) -> np.ndarray:
    real = shared_rig()
    wide, high = raster_size(width)
    real.splat_front_hair(_canvas(wide, high), FACE_T, POSE, cover_only=True)
    cover = real._cover
    skin = _skin_canvas(real, wide, high, cover)
    image = to_premul(skin, 1.02, face=True)
    xs = face2.Canvas2(wide, high, view=VIEW)
    local_y = unstretch_y(xs.Y)
    local_x = xs.X
    # Hard outline at the adult jaw, in the unstretched head the tests measure.
    hw = face2.face_w(local_y)
    inside = (np.abs(local_x) < hw) & (hw > 0)
    image = image.copy()
    image[..., 3] = np.where(inside, 255, image[..., 3]).astype(np.uint8)
    return image


def paint_eyes(rig, width: int, blink: float, gaze: tuple[float, float]) -> np.ndarray:
    del rig
    with _LOCK:
        return _paint_eyes_locked(width, blink, gaze)


def _paint_eyes_locked(width: int, blink: float, gaze: tuple[float, float]) -> np.ndarray:
    real = shared_rig()
    wide, high = raster_size(width)
    real.splat_front_hair(_canvas(wide, high), FACE_T, POSE, cover_only=True)
    cover = real._cover
    skin = _skin_canvas(real, wide, high, cover)
    image = _feature_patch(
        real,
        skin,
        cover,
        mouth=0.0,
        blink=blink,
        gaze=gaze,
        box=(-0.40, 0.40, -0.16, 0.14),
        eyes=True,
        lips=False,
    )
    image = image.copy()
    image[..., 3] = _eye_opening(wide, high, blink)
    return image


def _eye_opening(width: int, height: int, blink: float) -> np.ndarray:
    """Lid opening in the adult eye, opaque, so the span can be measured."""
    from arelis.ui.persona_face.adult import EYE_SCALE

    x0, x1, y0, y1 = VIEW
    xs = x0 + (np.arange(width) + 0.5) * (x1 - x0) / width
    ys = y0 + (np.arange(height) + 0.5) * (y1 - y0) / height
    local_x = xs[None, :]
    local_y = face2.VY + (ys[:, None] - face2.VY) / face2.VSTRETCH
    seen_y = face2.EYE_Y + (local_y - face2.EYE_Y) * face2.VSTRETCH
    mask = np.zeros((height, width), dtype=np.uint8)
    edge = (x1 - x0) / width * 1.2
    blink = float(blink)
    for sign in (-1.0, 1.0):
        cx = sign * face2.EYE_X
        cy = face2.EYE_Y
        xs_eye = cx + (local_x - cx) / EYE_SCALE
        ys_eye = cy + (seen_y - cy) / EYE_SCALE
        u = (xs_eye - cx) * sign / face2.EYE_HW
        ey = ys_eye - cy
        uc = np.clip(u, -1.0, 1.0)
        q = np.clip(1.0 - uc**2, 0.0, 1.0)
        tilt = 0.007
        upper = -0.0300 * q**0.75 * (1.0 - 0.12 * uc) - tilt * uc
        lower = 0.0115 * q**1.25 - tilt * uc * 0.55
        closed = 0.008 * q - tilt * uc * 0.75
        up = upper * (1.0 - blink) + closed * blink
        lo = lower * (1.0 - blink) + closed * blink
        inside = face2.smooth((1.0 - np.abs(u)) / 0.05)
        opening = face2.smooth((ey - up) / edge) * face2.smooth((lo - ey) / edge) * inside
        mask = np.where(opening > 0.28, np.uint8(255), mask)
    return mask


def paint_mouth(rig, width: int, openness: float) -> np.ndarray:
    del rig
    with _LOCK:
        return _paint_mouth_locked(width, openness)


def _paint_mouth_locked(width: int, openness: float) -> np.ndarray:
    real = shared_rig()
    wide, high = raster_size(width)
    real.splat_front_hair(_canvas(wide, high), FACE_T, POSE, cover_only=True)
    cover = real._cover
    skin = _skin_canvas(real, wide, high, cover)
    return _feature_patch(
        real,
        skin,
        cover,
        mouth=openness,
        blink=0.0,
        gaze=(0.0, 0.0),
        box=(-0.20, 0.20, 0.10, 0.32),
        eyes=False,
        lips=True,
    )


class Rig:
    """Tests construct one of these. The art lives on the shared adult rig."""

    def __init__(self, size: int) -> None:
        self.size = int(size)
        apply_v23()
        shared_rig()
