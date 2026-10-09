"""Approved face, clean thoughts, and a plate that disappears into the theme."""

from __future__ import annotations

import time
from itertools import pairwise

import numpy as np
from PySide6.QtCore import QPoint
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from arelis.core.events import Event, EventType
from arelis.ui.event_host import dispatch_event
from arelis.ui.persona_face.motion import Frame

_INTERNAL = (
    "thinking\u2026 (fast: qwen3.5:9b)",
    "Role 'fast' -> model qwen3.5:9b",
    "round 1/8 weather",
    "phase=model role=fast",
    "timing  total=48.3s model=48.3s",
    "loading the model...",
    "waiting for the conversation model...",
    "Ready for the first reply.",
)
_REASON = "The moon pulls the water, so the tide rises."


def _plain(window) -> str:
    return window.chat.view.toPlainText()


def test_expanded_thought_keeps_reasoning_and_drops_internal_lines(arelis_window, qt_app, caplog):
    import logging

    caplog.set_level(logging.INFO)
    """A turn's thought is her reasoning. Status and model lines stay off that block."""
    window = arelis_window()
    window.show()
    qt_app.processEvents()
    window.persona_dock.show()
    window._set_busy(True)
    for line in _INTERNAL:
        dispatch_event(window, Event(EventType.THINKING, {"text": line}))
    dispatch_event(window, Event(EventType.THINKING, {"text": _REASON}))
    window.chat.expand_thinking()
    qt_app.processEvents()
    shown = _plain(window)
    assert _REASON in shown
    assert "round " not in shown
    assert "phase=" not in shown
    assert "timing total" not in shown
    assert "timing  total" not in shown
    assert "Role " not in shown
    assert "loading the model" not in shown
    assert "fast:" not in shown
    logged = caplog.text
    assert "phase=" in logged
    assert "Role " in logged
    # She is open, so the latest internal line is on her caption, not dropped.
    assert window.persona_panel.status_text()
    window.persona_dock.hide()
    window.close()


def test_a_turn_with_no_reasoning_has_no_thought_line(arelis_window, qt_app):
    """Only internal lines do not open a thought."""
    window = arelis_window()
    window.show()
    qt_app.processEvents()
    window._set_busy(True)
    dispatch_event(window, Event(EventType.THINKING, {"text": "round 2/8 search"}))
    dispatch_event(window, Event(EventType.THINKING, {"text": "phase=fanout n=1"}))
    window.chat.expand_thinking()
    qt_app.processEvents()
    shown = _plain(window)
    assert "round " not in shown
    assert "phase=" not in shown
    assert "Thinking for" not in shown
    window.persona_dock.hide()
    window.close()


# Cheek centre on the v2.4 closeup, the lower cheek just right of the nose.
_CHEEK = np.array([189.0, 179.0, 199.0])
_LAYERS: dict | None = None


def _layers() -> dict:
    global _LAYERS
    if _LAYERS is None:
        from arelis.ui.persona_face.engine import bake_layers

        _LAYERS = bake_layers(220)
    return _LAYERS


def _world_patch(image: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
    from arelis.ui.persona_face.engine import VIEW

    x0, x1, y0, y1 = VIEW
    height, width, _ = image.shape
    left, right, top, bottom = box
    px0 = int((left - x0) / (x1 - x0) * (width - 1))
    px1 = int((right - x0) / (x1 - x0) * (width - 1))
    py0 = int((top - y0) / (y1 - y0) * (height - 1))
    py1 = int((bottom - y0) / (y1 - y0) * (height - 1))
    return image[py0:py1, px0:px1]


def test_baked_skin_is_lavender_like_the_approved_closeup():
    """Cheek centre stays within 4 levels of (189, 179, 199) on each channel.

    That is the lower cheek on the v2.4 closeup. Blue sits at least 12 above
    green. The drifted plate was grey, with blue only a couple above green,
    and about 60 levels darker than this.
    """
    from arelis.ui.persona_face.bake import composite_rest, flatten_on_black

    plate = flatten_on_black(composite_rest(_layers()))
    patch = _world_patch(plate, (-0.02, 0.08, 0.10, 0.16))[..., :3].astype(np.float64)
    mean = patch.mean(axis=(0, 1))
    # Branch cheek measured (188.5, 179.2, 199.0). Main at c4e166d measured
    # (188.7, 178.5, 192.1). Halfway on the blue miss is about 3.4 levels
    # under the old 12, so 4 fails main on this assert and still passes here.
    assert np.all(np.abs(mean - _CHEEK) <= 4.0), mean
    assert float(mean[2] - mean[1]) >= 12.0
    from arelis.ui.persona_face.engine import EYE_X, EYE_Y, VIEW

    height, width, _ = plate.shape
    x0, x1, y0, y1 = VIEW
    ex = int((EYE_X - x0) / (x1 - x0) * (width - 1))
    ey = int((EYE_Y - y0) / (y1 - y0) * (height - 1))
    eye = plate[ey - 8 : ey + 10, ex - 8 : ex + 8, :3].astype(np.float64)
    chroma = float((eye[..., 2] - eye[..., 1]).max())
    assert chroma > 60.0


def test_back_hair_is_strands_behind_her_neck():
    """Behind the neck, between the side locks, the back layer is strand hair.

    A flat fill of that same average has column deviation near 0 (under 1
    level even with rounding). This field measures well above 4, which is
    the cut a flat block fails and a strand texture still clears.
    """
    from arelis.ui.persona_face.bake import composite_rest

    plate = composite_rest(_layers())
    patch = _world_patch(plate, (-0.06, 0.06, 0.50, 0.80))
    alpha = patch[..., 3].astype(np.float64)
    assert float(alpha.mean()) > 40.0
    rgb = patch[..., :3].astype(np.float64)
    mean = rgb.mean(axis=(0, 1))
    assert float(mean[2] - mean[1]) >= 4.0
    # Deviation across the row. A flat block is ~0. Strands are not.
    deviation = float(rgb.mean(axis=-1).std(axis=1).mean())
    assert deviation > 4.0, deviation


def test_composited_hair_has_no_horizontal_stripes():
    """No hair row jumps more than 12 levels away from both neighbours.

    Slice warps overlapped by a fraction of a pixel and added, which drew a
    bright line on every band. A whole phase frame does not. Shoulder-length
    tips wobble about 8 levels on one row in this band, so 12 still catches
    a warp line and lets that wobble through.
    """
    from arelis.ui.persona_face.bake import composite_rest

    plate = composite_rest(_layers())
    # Back hair under the chin, between the side locks. A slice warp stripes
    # this whole column. Feature edges on the face are not in the box.
    # The long curtain used to fill y 0.56 to 0.88. Tips now fade out by the
    # shoulder, so the strand check sits higher, still under the chin.
    hair = _world_patch(plate, (-0.10, 0.10, 0.36, 0.46))
    rows = hair[..., :3].astype(np.float64).mean(axis=(1, 2))
    for index in range(1, len(rows) - 1):
        left = abs(float(rows[index] - rows[index - 1]))
        right = abs(float(rows[index] - rows[index + 1]))
        assert not (left > 12.0 and right > 12.0), (index, left, right)


def _panel_on(theme: str, qt_app):
    from arelis.ui.persona_face.panel import PersonaPanel
    from arelis.ui.theme import apply_theme, color

    apply_theme(theme)
    backdrop = color("bg0")
    panel = PersonaPanel()
    panel.resize(280, 360)
    panel.set_bake_delay(0)
    panel.show()
    qt_app.processEvents()
    deadline = time.monotonic() + 40.0
    while not panel.bake_ready and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.02)
    assert panel.bake_ready
    panel._timer.stop()
    panel._mode = "face"
    panel.avatar.reveal = 1.0
    panel.avatar.frame = Frame(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, False, 0, 0)
    panel.repaint()
    qt_app.processEvents()
    pix = QPixmap(panel.size())
    pix.fill(backdrop)
    painter = QPainter(pix)
    panel.render(painter, QPoint(0, 0))
    painter.end()
    return panel, pix.toImage(), backdrop


def _rgba_gap(image, backdrop) -> np.ndarray:
    from PySide6.QtGui import QImage

    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width = converted.width()
    height = converted.height()
    buf = np.frombuffer(converted.constBits(), dtype=np.uint8, count=height * width * 4)
    rgb = buf.reshape((height, width, 4))[..., :3].astype(np.int16)
    tone = np.array([backdrop.red(), backdrop.green(), backdrop.blue()], dtype=np.int16)
    return np.max(np.abs(rgb - tone), axis=-1)


def test_her_plate_matches_each_theme_just_outside_the_figure(qt_app):
    """Night, sodium and filament: no faint rectangle outside the figure.

    Solid pixels are the hair and the face. A veil more than 14 pixels away
    from that solid is the plate, and it has to sit within 2 levels of the dock.
    """
    from arelis.ui.theme import apply_theme

    for theme in ("night", "sodium", "filament"):
        panel, image, backdrop = _panel_on(theme, qt_app)
        gap = _rgba_gap(image, backdrop)
        solid = gap > 25
        near = solid.copy()
        for _ in range(14):
            grown = near.copy()
            grown[1:] |= near[:-1]
            grown[:-1] |= near[1:]
            grown[:, 1:] |= near[:, :-1]
            grown[:, :-1] |= near[:, 1:]
            near = grown
        haze = (gap >= 3) & (gap <= 14) & (~near)
        assert int(haze.sum()) < 40, (theme, int(haze.sum()))
        panel.close()
    apply_theme("sodium")


def test_hair_tips_move_and_roots_stay_and_busy_is_quieter(qt_app):
    """A few seconds of flow moves the tips. The roots and the face barely move.

    Busy cuts the same drive, so the tip shift is smaller than calm.
    """
    from arelis.ui.persona_face.motion import Motion
    from arelis.ui.persona_face.panel import PersonaPanel

    calm = Motion(seed=3)
    busy = Motion(seed=3)
    calm_tips = []
    busy_tips = []
    for step in range(80):
        t = step * 0.05
        calm_tips.append(
            abs(
                calm.step(
                    t, 0.05, state="rest", speaking=False, model_busy=False, loudness=0.0
                ).hair_tip
            )
        )
        busy_tips.append(
            abs(
                busy.step(
                    t, 0.05, state="rest", speaking=False, model_busy=True, loudness=0.0
                ).hair_tip
            )
        )
    assert max(calm_tips) > max(busy_tips) + 0.05

    panel = PersonaPanel()
    panel.resize(220, 300)
    panel.set_bake_delay(0)
    panel.show()
    deadline = time.monotonic() + 40.0
    while not panel.bake_ready and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.02)
    assert panel.bake_ready
    deadline = time.monotonic() + 90.0
    while panel.avatar.phases_ready() < 8 and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.02)
    assert panel.avatar.phases_ready() >= 8
    panel._timer.stop()
    panel._mode = "face"
    panel.avatar.reveal = 1.0

    def grab(frame: Frame) -> np.ndarray:
        panel.avatar.frame = frame
        panel.avatar.repaint()
        QApplication.processEvents()
        image = panel.grab().toImage()
        converted = image.convertToFormat(image.format())
        return _rgba(converted)

    still = Frame(0, 0, 0, 0.0, 0.0, 0.0, 0, 0, 0, 0, 1, 1, 0, False, 0, 0, 0.0)
    later = Frame(0, 0, 0, 0.04, 0.2, 0.85, 0, 0, 0, 0, 1, 1, 0, False, 0, 0, 4.0)
    first = grab(still)
    second = grab(later)
    height, width, _ = first.shape
    diff = np.abs(first.astype(np.int16) - second.astype(np.int16))[..., :3].mean(axis=-1)
    # Scalp side stays put. The lower side lock is the tips. The cheek is the face.
    roots = diff[int(height * 0.11) : int(height * 0.17), int(width * 0.28) : int(width * 0.40)]
    tips = diff[int(height * 0.43) : int(height * 0.52), int(width * 0.50) : int(width * 0.68)]
    face = diff[int(height * 0.27) : int(height * 0.35), int(width * 0.40) : int(width * 0.55)]
    assert float(tips.mean()) > float(roots.mean()) + 1.5
    assert float(tips.mean()) > float(face.mean()) + 1.5
    assert float(face.mean()) < 2.0
    panel.close()


def _paint_rgba(theme: str, qt_app):
    """Face at full reveal, pixels with their alpha, not flattened on the dock."""
    from PySide6.QtGui import QImage

    from arelis.ui.persona_face.motion import Frame
    from arelis.ui.persona_face.panel import PersonaPanel
    from arelis.ui.theme import apply_theme

    apply_theme(theme)
    panel = PersonaPanel()
    panel.resize(280, 360)
    panel.set_bake_delay(0)
    panel.show()
    qt_app.processEvents()
    deadline = time.monotonic() + 50.0
    while not panel.bake_ready and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.02)
    assert panel.bake_ready
    panel.avatar.shutdown()
    panel._timer.stop()
    panel._mode = "face"
    panel.avatar.reveal = 1.0
    panel.avatar.frame = Frame(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, False, 0, 0)
    panel.avatar.repaint()
    qt_app.processEvents()
    image = panel.avatar.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    rgba = _rgba(image)
    rest = _rgba(panel.rest_face_image().convertToFormat(QImage.Format.Format_RGBA8888))
    panel.close()
    return rgba, rest


def _over_straight(rgba: np.ndarray, bg: tuple[int, int, int]) -> np.ndarray:
    """Widget grabs are straight alpha. Composite the way a dock paints her."""
    rgb = rgba[..., :3].astype(np.float32)
    alpha = rgba[..., 3:4].astype(np.float32) / 255.0
    tone = np.array(bg, dtype=np.float32)
    return rgb * alpha + tone * (1.0 - alpha)


def _lum(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def test_soft_edges_have_no_dark_halo_and_the_neck_is_lavender_gas(qt_app):
    """A light dock and a dark dock, sampled along the silhouette.

    A soft-edge pixel may not be darker than both the inside of the figure and
    the background by more than 40 levels. The old plate's fringe ran about
    59 levels too dark on a light ground. What is left is the strand's own
    shading, about 38 levels under a brighter neighbour, so 40 sits between
    that shading and the old shell.

    The upper neck has to stay at least 0.55 of the cheek luminance. The
    v2.4 closeup neck is about 0.72 of the cheek. This plate's neck was a
    solid column at about 0.27, so 0.55 is the line between that column and
    the closeup.
    """
    from arelis.ui.theme import apply_theme, color

    rgba, rest = _paint_rgba("night", qt_app)
    alpha = rgba[..., 3]
    inside = alpha > 210
    grad_y = np.abs(np.diff(alpha.astype(np.int16), axis=0, prepend=alpha[:1]))
    grad_x = np.abs(np.diff(alpha.astype(np.int16), axis=1, prepend=alpha[:, :1]))
    # Soft edge only. Opaque shading inside the hair is not a fringe.
    edge = ((grad_x + grad_y) > 25) & (alpha > 20) & (alpha < 230)
    grounds = {
        "light": (240, 236, 248),
        "dark": (
            color("bg0").red(),
            color("bg0").green(),
            color("bg0").blue(),
        ),
    }
    height, width = alpha.shape
    ys, xs = np.where(edge)
    step = max(1, len(ys) // 1500)
    for name, bg in grounds.items():
        comp = _over_straight(rgba, bg)
        lum = _lum(comp)
        bg_l = float(_lum(np.array(bg, dtype=np.float32)))
        worst = 0.0
        for y, x in zip(ys[::step], xs[::step], strict=False):
            y0, y1 = max(0, y - 5), min(height, y + 6)
            x0, x1 = max(0, x - 5), min(width, x + 6)
            core = inside[y0:y1, x0:x1]
            if int(core.sum()) < 2:
                continue
            inside_l = float(lum[y0:y1, x0:x1][core].mean())
            margin = min(inside_l, bg_l) - float(lum[y, x])
            if margin > worst:
                worst = margin
        assert worst <= 40.0, (name, worst)
    cheek = _lum(_world_patch(rest, (-0.02, 0.08, 0.10, 0.16))[..., :3])
    neck = _lum(_world_patch(rest, (-0.045, 0.045, 0.32, 0.46))[..., :3])
    cheek_l = float(cheek.mean())
    neck_l = float(neck.mean())
    assert cheek_l > 40.0
    assert neck_l >= cheek_l * 0.55, (neck_l, cheek_l)
    apply_theme("sodium")


def _rgba(image) -> np.ndarray:
    from PySide6.QtGui import QImage

    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width = converted.width()
    height = converted.height()
    bits = converted.constBits()
    buf = np.frombuffer(bits, dtype=np.uint8, count=height * width * 4)
    return buf.reshape((height, width, 4)).copy()


def test_status_line_elides_on_the_right(qt_app):
    """A long timing line keeps its first characters and ellipsizes the tail."""
    from arelis.ui.persona_face.panel import PersonaPanel

    panel = PersonaPanel()
    panel.set_bake_delay(60.0)
    panel.resize(220, 320)
    raw = "timing total=6.4s model=6.3s prefill=4.3s decode=1.8s first_token=0.4s"
    panel.show_status(raw)
    shown = panel.elided_status(160)
    assert shown.startswith("timing total")
    assert not shown.startswith("otal")
    assert len(shown) < len(raw)
    panel.show()
    panel.repaint()
    qt_app.processEvents()
    panel.close()


def test_the_wake_holds_the_middle_for_about_two_seconds(qt_app):
    """Fake clock: still between 0 and 1 at 1s, done by 3.5s, not before 1.5s.

    Motion off is the only instant skip. The system flag is a separate path.
    """
    from arelis.ui.persona_face.panel import PersonaPanel, client_animations

    panel = PersonaPanel()
    panel._force_motion = True
    panel.set_bake_delay(60.0)
    panel.resize(220, 320)
    panel.show()
    clock = {"t": 0.0}
    panel.set_clock(lambda: clock["t"])
    panel.set_state("thinking")
    clock["t"] = 1.0
    panel.tick()
    assert 0.0 < panel.avatar.reveal < 1.0
    clock["t"] = 1.5
    panel.tick()
    assert panel.avatar.reveal < 1.0
    clock["t"] = 3.5
    panel.tick()
    assert panel.form() == "face"
    assert panel.avatar.reveal == 1.0
    panel.close()

    off = PersonaPanel()
    off._force_motion = False
    off.set_bake_delay(60.0)
    off.resize(220, 320)
    off.show()
    off.set_state("thinking")
    assert off.form() == "face"
    assert off.avatar.reveal == 1.0
    off.close()

    if client_animations():
        live = PersonaPanel()
        live._force_motion = None
        live.set_bake_delay(60.0)
        live.resize(220, 320)
        live.show()
        clock = {"t": 0.0}
        live.set_clock(lambda: clock["t"])
        live.set_state("thinking")
        clock["t"] = 0.4
        live.tick()
        assert 0.0 < live.avatar.reveal < 1.0
        live.close()


def _block_fraction(image: np.ndarray, silhouette: np.ndarray) -> float:
    """Flat runs sitting on a hard step. Nearest upscale is full of these.

    A smooth blur of this plate measured 0. A nearest repeat of the same
    plate measured about 0.13, so 0.02 sits between them.
    """
    lum = image[..., :3].astype(np.float32).mean(axis=-1)
    diff = np.abs(np.diff(lum, axis=1))
    inside = silhouette[:, 1:] & silhouette[:, :-1]
    zero = (diff < 0.5) & inside
    jump = (diff >= 18.0) & inside
    beside = np.zeros_like(zero)
    beside[:, 1:] |= jump[:, :-1]
    beside[:, :-1] |= jump[:, 1:]
    bad = zero & beside
    return float(bad.sum()) / float(max(1, int(inside.sum())))


def test_a_mid_wake_frame_has_no_pixel_blocks():
    """The blur the early wake draws is area-down plus bilinear, not blocks."""
    from arelis.ui.persona_face.bake import blur_premul, composite_rest

    plate = composite_rest(_layers())
    # Reveal 0.45 is blur-heavy: frames 2 to 4 of the strip live here.
    reveal = 0.45
    span = (reveal - 0.18) / 0.82
    sharp = span * span * (3.0 - 2.0 * span)
    blurred = blur_premul(plate, 10).astype(np.float32)
    crisp = plate.astype(np.float32)
    frame = blurred * (reveal * (1.0 - sharp)) + crisp * (reveal * sharp)
    frame = np.clip(frame, 0, 255).astype(np.uint8)
    silhouette = plate[..., 3] > 80
    assert _block_fraction(frame, silhouette) < 0.02


def test_the_hair_clip_is_a_four_point_star():
    """Bright pixels are thin spikes, not a filled disc.

    On a 220 px plate the arms reach about 14 px and the diagonals about 10.
    A filled disc of that radius would light most of the circle (fraction near
    1) and the diagonal would match the arms. Under 0.45, with arms longer
    than the diagonals, is the star.
    """
    star = _layers()["star"]
    alpha = star[..., 3]
    peak = np.unravel_index(int(alpha.argmax()), alpha.shape)
    cy, cx = int(peak[0]), int(peak[1])
    height, width = alpha.shape
    yy, xx = np.mgrid[:height, :width]
    dy = yy - cy
    dx = xx - cx
    radius = np.hypot(dx, dy)
    angle = np.abs(np.arctan2(dy, dx))
    axis = np.minimum(angle, np.abs(angle - np.pi / 2.0))
    axis = np.minimum(axis, np.abs(angle - np.pi))
    diagonal = np.minimum(np.abs(angle - np.pi / 4.0), np.abs(angle - 3.0 * np.pi / 4.0))
    lit = alpha >= 40
    assert int(lit.sum()) > 8
    arm = lit & (axis < 0.28)
    slash = lit & (diagonal < 0.28)
    arm_r = float(radius[arm].max())
    slash_r = float(radius[slash].max()) if slash.any() else 0.0
    assert arm_r > slash_r * 1.15
    circle = radius <= arm_r
    fraction = float(lit[circle].mean())
    assert fraction < 0.45, (fraction, arm_r, slash_r)


def test_the_neck_fades_as_lavender_and_the_tips_leave_the_frame():
    """Neck blue sits above green, and the lower neck is dimmer than the upper.

    The tips' alpha is gone at the last rows. The fade starts near 88 percent
    of the height, so the rows just inside that band are still partly there.
    """
    from arelis.ui.persona_face.bake import composite_rest

    plate = composite_rest(_layers())
    neck = _world_patch(_layers()["face"], (-0.045, 0.045, 0.28, 0.62)).astype(np.float64)
    lit = neck[..., 3] > 80
    assert int(lit.sum()) > 10
    color = neck[..., :3][lit]
    assert float(color[:, 2].mean() - color[:, 1].mean()) >= 12.0
    alpha_rows = neck[..., 3]
    upper = float(alpha_rows[: max(1, len(alpha_rows) // 5)].mean())
    lower = float(alpha_rows[-max(1, len(alpha_rows) // 5) :].mean())
    assert upper > 150.0
    assert lower < upper * 0.45, (upper, lower)
    alpha = plate[..., 3].astype(np.float64)
    start = int(alpha.shape[0] * 0.88)
    head = float(alpha[start : start + 3].mean())
    tail = float(alpha[-3:].mean())
    assert tail < 8.0
    assert head > tail + 25.0


def test_the_side_lock_has_no_hard_pink_edge_at_the_ring():
    """No column of hard steps where the left lock crosses the ring.

    After the ring hide was softened this patch's worst column was about 0.30
    of its rows. A straight cut lines up near 1. 0.55 is between those.
    """
    from arelis.ui.persona_face.bake import composite_rest

    plate = composite_rest(_layers())
    side = _world_patch(plate, (-0.62, -0.28, 0.28, 0.72)).astype(np.float64)
    diff = np.abs(np.diff(side.mean(axis=-1), axis=1))
    jumps = diff > 22.0
    worst = float(jumps.mean(axis=0).max()) if jumps.size else 0.0
    assert worst < 0.55, worst


def test_the_outer_left_lock_fades_out_before_the_ring():
    """The outer left lock thins to nothing below the ring, so no ribbon hangs out.

    Its tips left the head together and read as one straight band under the
    ring (pink in r3, recoloured in r5). The front hair now fades over a wide
    ramp past x -0.40 and below y 0.26, and the back hair fills that side.
    Deep in that zone (x under -0.55, y over 0.42) the front layer must be
    nearly empty: mean alpha under 2 and max under 12 of 255. On the r5 plate
    the same box held the ribbon at alpha near 190.
    """
    front = _layers()["front_0"]
    alpha = _world_patch(front, (-0.80, -0.55, 0.42, 0.77))[..., 3].astype(np.float64)
    assert float(alpha.mean()) < 2.0, float(alpha.mean())
    assert float(alpha.max()) < 12.0, float(alpha.max())


def test_she_materializes_over_several_ticks_and_folds_faster(qt_app):
    """Bloom eases up. The star ends on the clip. Fold is shorter. Off skips."""
    from arelis.ui.persona_face.panel import BLOOM_S, FOLD_S, PersonaPanel

    panel = PersonaPanel()
    panel._force_motion = True
    panel.set_bake_delay(60.0)
    panel.resize(220, 320)
    panel.show()
    clock = {"t": 0.0}
    panel.set_clock(lambda: clock["t"])
    panel.set_state("thinking")
    reveals = []
    for step in range(1, 6):
        clock["t"] = BLOOM_S * step / 6.0
        panel.tick()
        reveals.append(panel.avatar.reveal)
    assert reveals[0] > 0.0
    assert all(later > earlier for earlier, later in pairwise(reveals))
    assert 0.0 < reveals[2] < 1.0
    clock["t"] = BLOOM_S + 0.05
    panel.tick()
    assert panel.form() == "face"
    assert panel.avatar.reveal == 1.0
    panel.repaint()
    qt_app.processEvents()
    home = panel.avatar._map(0.232, -0.372, panel.avatar._face_rect())
    assert abs(panel.avatar.star_anchor.x() - home.x()) < 2.0
    assert abs(panel.avatar.star_anchor.y() - home.y()) < 2.0
    assert FOLD_S < BLOOM_S
    panel.set_state("done")
    clock["t"] = BLOOM_S + 60.05
    panel.tick()
    assert panel.form() == "fold"
    clock["t"] = BLOOM_S + 60.05 + FOLD_S * 0.5
    panel.tick()
    assert 0.0 < panel.avatar.reveal < 1.0
    clock["t"] = BLOOM_S + 60.05 + FOLD_S + 0.05
    panel.tick()
    assert panel.form() == "orb"
    assert panel.avatar.reveal == 0.0

    panel._force_motion = False
    panel.set_state("thinking")
    assert panel.form() == "face"
    assert panel.avatar.reveal == 1.0
    panel.close()


def _fake_layers(size: int) -> dict:
    from arelis.ui.persona_face.engine import raster_size

    wide, high = raster_size(size)

    def layer(red: int, green: int, blue: int, alpha: int = 255) -> np.ndarray:
        image = np.zeros((high, wide, 4), dtype=np.uint8)
        image[..., 0] = red
        image[..., 1] = green
        image[..., 2] = blue
        image[..., 3] = alpha
        return image

    layers = {
        "face": layer(180, 170, 200),
        "wisps": layer(0, 0, 0, 0),
        "mouth_0": layer(0, 0, 0, 0),
        "eye_0": layer(0, 0, 0, 0),
        "ring": layer(40, 20, 60, 40),
        "star": layer(255, 250, 240, 200),
        "back_0": layer(90, 70, 130, 80),
        "front_0": layer(150, 120, 190, 90),
    }
    for index in range(1, 4):
        layers[f"back_{index}"] = layer(90, 70, 130, 70)
        layers[f"front_{index}"] = layer(150, 120, 190, 80)
    return layers


def test_a_second_bake_reuses_the_disk_cache(qt_app, tmp_path, monkeypatch):
    """Same key does not call the renderer. A new size, version, or torn file does."""
    import arelis.ui.persona_face.avatar as avatar_mod
    import arelis.ui.persona_face.cache as face_cache

    monkeypatch.setattr(face_cache, "cache_root", lambda: tmp_path)
    calls: list[int] = []

    def fake(size, cancel=None, publish=None):
        calls.append(int(size))
        layers = _fake_layers(int(size))
        if publish is not None:
            publish(dict(layers), 1)
            extra = {name: layers[name] for name in layers if name.endswith(("_1", "_2", "_3"))}
            publish(extra, 4)
        return layers

    monkeypatch.setattr(avatar_mod, "bake_layers", fake)

    def show(width: int):
        from arelis.ui.persona_face.panel import PersonaPanel

        panel = PersonaPanel()
        panel.set_bake_delay(0.0)
        panel.resize(width, int(width * 1.4))
        panel.show()
        deadline = time.monotonic() + 15.0
        while not panel.bake_ready and time.monotonic() < deadline:
            qt_app.processEvents()
            time.sleep(0.01)
        assert panel.bake_ready
        baker = panel.avatar._baker
        if baker is not None:
            baker.wait(5000)
        return panel

    first = show(180)
    assert calls == [first.avatar._baked_px]
    first_rest = _rgba(first.rest_face_image())
    first.close()

    second = show(180)
    assert calls == [first.avatar._baked_px]
    second_rest = _rgba(second.rest_face_image())
    assert first_rest.shape == second_rest.shape
    assert np.array_equal(first_rest, second_rest)
    second.close()

    third = show(260)
    assert len(calls) == 2
    assert calls[1] != calls[0]
    third.close()

    monkeypatch.setattr(face_cache, "renderer_version", lambda: "bbbbbbbbbbbbbbbb")
    fourth = show(180)
    assert len(calls) == 3
    names = [item.name for item in tmp_path.iterdir() if item.is_dir()]
    assert any("bbbbbbbbbbbbbbbb" in name for name in names)
    assert not any(name.startswith("f1-r") and "bbbbbbbbbbbbbbbb" not in name for name in names)
    fourth.close()

    monkeypatch.setattr(face_cache, "renderer_version", lambda: "cccccccccccccccc")
    torn = show(180)
    torn.close()
    assert len(calls) == 4
    folder = next(
        item for item in tmp_path.iterdir() if item.is_dir() and "cccccccccccccccc" in item.name
    )
    (folder / "base.npz").write_bytes(b"not a zip")
    again = show(180)
    assert len(calls) == 5
    again.close()

    from arelis.ui.persona_face.engine import raster_size

    _wide, high = raster_size(calls[0])
    assert face_cache.load_layers(calls[0], high, 2.0) is None


def test_a_startup_resize_still_hits_the_cache(qt_app, tmp_path, monkeypatch):
    """Layout grows the dock before the bake. The second run reuses that size."""
    import arelis.ui.persona_face.avatar as avatar_mod
    import arelis.ui.persona_face.cache as face_cache

    monkeypatch.setattr(face_cache, "cache_root", lambda: tmp_path)
    calls: list[int] = []

    def fake(size, cancel=None, publish=None):
        calls.append(int(size))
        layers = _fake_layers(int(size))
        if publish is not None:
            publish(dict(layers), 1)
            extra = {name: layers[name] for name in layers if name.endswith(("_1", "_2", "_3"))}
            publish(extra, 4)
        return layers

    monkeypatch.setattr(avatar_mod, "bake_layers", fake)

    def grow():
        from arelis.ui.persona_face.panel import PersonaPanel

        panel = PersonaPanel()
        panel.set_bake_delay(0.0)
        panel.resize(160, 240)
        panel.show()
        qt_app.processEvents()
        panel.resize(220, 320)
        qt_app.processEvents()
        panel.resize(340, 460)
        qt_app.processEvents()
        deadline = time.monotonic() + 8.0
        while not panel.bake_ready and time.monotonic() < deadline:
            qt_app.processEvents()
            time.sleep(0.02)
        assert panel.bake_ready
        baker = panel.avatar._baker
        if baker is not None:
            baker.wait(4000)
        return panel

    first = grow()
    assert calls == [first.avatar._baked_px]
    assert len(calls) == 1
    first.close()

    second = grow()
    assert calls == [first.avatar._baked_px]
    assert second.bake_ready
    second.close()


def _over_premul(image: np.ndarray, bg: tuple[int, int, int]) -> np.ndarray:
    """Source-over for a premultiplied plate onto a flat dock colour."""
    src = image.astype(np.float32) / 255.0
    tone = np.array(bg, dtype=np.float32) / 255.0
    return (src[..., :3] + tone * (1.0 - src[..., 3:4])) * 255.0


def _straight(patch: np.ndarray) -> np.ndarray:
    """Un-premultiply. rgb and alpha are both stored 0 to 255."""
    alpha = patch[..., 3:4].astype(np.float64)
    return patch[..., :3].astype(np.float64) * (255.0 / np.maximum(alpha, 1.0))


def test_crown_and_fringe_cover_the_forehead():
    """Between the temples, above the brow, the front hair is actually hair.

    The r4 plate kept that alpha and stored the colour near 0, so the forehead
    read as bare grey skin. Hair here is lavender: blue leads green, and the
    straight luminance stays well above a grey scalp.
    """
    front = _layers()["front_0"]
    patch = _world_patch(front, (-0.16, 0.20, -0.50, -0.26))
    alpha = patch[..., 3].astype(np.float64) / 255.0
    covered = alpha > 0.45
    assert float(covered.mean()) > 0.35, float(covered.mean())
    straight = _straight(patch)[covered]
    lum = _lum(straight.astype(np.float32))
    assert float(np.median(lum)) > 80.0, float(np.median(lum))
    gap = float(np.median(straight[:, 2] - straight[:, 1]))
    assert gap > 12.0, gap


def test_no_black_silhouette_on_a_light_or_night_ground():
    """A high-alpha pixel may not composite near black on either ground.

    The r4 front hair was a black mask: alpha above 0.3, colour about 0, so
    source-over punched a hole darker than the ground, at luminance 0.
    Strand tips on this plate bottom out around luminance 33, so under 25 is
    the black mask and not those tips. Eyes and the mouth sit inside the face
    oval and are not part of that silhouette.
    """
    from arelis.ui.persona_face.bake import composite_rest
    from arelis.ui.persona_face.engine import VIEW

    plate = composite_rest(_layers())
    alpha = plate[..., 3].astype(np.float64) / 255.0
    height, width = alpha.shape
    x0, x1, y0, y1 = VIEW
    ys = y0 + (np.arange(height) + 0.5) / height * (y1 - y0)
    xs = x0 + (np.arange(width) + 0.5) / width * (x1 - x0)
    # Face oval: lashes and irises are dark on purpose. The hole was the hair.
    skip = (np.abs(xs)[None, :] < 0.22) & (ys[:, None] > -0.22) & (ys[:, None] < 0.30)
    grounds = {"night": (12, 10, 22), "light": (240, 236, 248)}
    for name, bg in grounds.items():
        comp = _over_premul(plate, bg).astype(np.float32)
        lum = _lum(comp)
        ground = float(_lum(np.array(bg, dtype=np.float32)))
        bad = (alpha > 0.3) & (lum < 25.0) & (lum + 1.0 < ground) & ~skip
        assert int(bad.sum()) == 0, (
            name,
            int(bad.sum()),
            float(lum[bad].min()) if bad.any() else 0,
        )


def test_the_star_sits_in_the_hair():
    """The clip centre is inside hair, and that hair still has a hair colour.

    The centre is the sparkle's world point, not a spike tip. A black mask can
    keep alpha above 0.5 and still leave the star floating over a bare scalp.
    The hair under the star has to be lavender, not empty.
    """
    from arelis.ui.persona_face.engine import VIEW
    from arelis.ui.persona_face.plate import POSE, shared_rig

    layers = _layers()
    spot = shared_rig().to_world(np.array([[0.232, -0.372]]), POSE)[0]
    front = layers["front_0"]
    back = layers["back_0"]
    height, width, _ = front.shape
    x0, x1, y0, y1 = VIEW
    px = int((float(spot[0]) - x0) / (x1 - x0) * (width - 1))
    py = int((float(spot[1]) - y0) / (y1 - y0) * (height - 1))
    hair = max(int(front[py, px, 3]), int(back[py, px, 3])) / 255.0
    assert hair > 0.5, hair
    assert int(front[py, px, 3]) > 128
    straight = _straight(front[py : py + 1, px : px + 1])[0, 0]
    lum = float(_lum(straight.astype(np.float32)))
    assert lum > 40.0, (lum, straight.tolist())
    assert float(straight[2] - straight[1]) > 8.0, straight.tolist()


# Shoulder line in world y. Tips fade out at this line. Below it the plate is clear.
_SHOULDER_Y = 0.66


def _span(mask: np.ndarray, view_width: float) -> float:
    cols = np.flatnonzero(mask)
    if len(cols) < 2:
        return 0.0
    return float(cols[-1] - cols[0] + 1) / float(mask.shape[0]) * view_width


def _straight_lum(patch: np.ndarray) -> float:
    alpha = patch[..., 3].astype(np.float64)
    rgb = patch[..., :3].astype(np.float64) * (255.0 / np.maximum(alpha[..., None], 1.0))
    lit = alpha > 40.0
    assert int(lit.sum()) > 8
    return float(np.mean(_lum(rgb[lit].astype(np.float32))))


def test_the_face_fills_the_hair_at_the_cheeks():
    """Skin width over hair width at the cheekbone is at least 0.64.

    On the approved close-up, a cheek band (rows 560 to 650 of 1024) gives
    connected skin over the hair silhouette a median of about 0.46 and a
    widest row of about 0.50. Hair runs off both edges of that crop, so 0.50
    is the face share of a cut-off head, not of the whole mass. The in-app
    plate at the cheekbone (local y 0.03) measured about 0.58, and the face
    still sat inside a wide block. 0.64 is above that plate and in the
    direction of the close-up, where the face is most of the head.
    """
    from arelis.ui.persona_face.engine import VIEW
    from arelis.ui.persona_face.plate import unstretch_y

    hair = np.maximum(_layers()["back_0"][..., 3], _layers()["front_0"][..., 3])
    face = _layers()["face"][..., 3]
    height = face.shape[0]
    x0, x1, y0, y1 = VIEW
    world_y = y0 + (np.arange(height) + 0.5) / height * (y1 - y0)
    local = np.asarray(unstretch_y(world_y), dtype=np.float64)
    row = int(np.argmin(np.abs(local - 0.03)))
    span = x1 - x0
    skin = _span(face[row] > 128, span)
    silhouette = _span(np.maximum(hair[row], face[row]) > 24, span)
    ratio = skin / silhouette if silhouette else 0.0
    assert ratio >= 0.64, (ratio, skin, silhouette)


def test_the_neck_is_behind_the_jaw():
    """Just under the jaw the neck is darker than the chin and narrower.

    The pale bulge is the neck continuing the chin. Just under the jaw
    (world y 0.34 to 0.40) the face layer is only a few levels under the chin
    patch at y 0.20 to 0.26, so the jaw edge does not read in front. That
    neck has to be at least 12 levels darker, and narrower than the jaw at
    local y 0.20. It stays lavender, not a grey column.
    """
    from arelis.ui.persona_face.engine import VIEW
    from arelis.ui.persona_face.plate import unstretch_y

    face = _layers()["face"]
    height, width, _ = face.shape
    x0, x1, y0, y1 = VIEW
    world_y = y0 + (np.arange(height) + 0.5) / height * (y1 - y0)
    local = np.asarray(unstretch_y(world_y), dtype=np.float64)
    jaw_row = int(np.argmin(np.abs(local - 0.20)))
    neck_row = int(np.argmin(np.abs(world_y - 0.44)))
    span = x1 - x0
    jaw = _span(face[jaw_row, :, 3] > 200, span)
    # The neck is the face-layer column under the chin, not the side hair.
    neck = _span(
        (face[neck_row, :, 3] > 40) & (np.abs(x0 + (np.arange(width) + 0.5) / width * span) < 0.12),
        span,
    )
    assert jaw > 0.24, jaw
    assert neck > 0.04, neck
    assert neck < jaw * 0.72, (neck, jaw)
    chin_l = _straight_lum(_world_patch(face, (-0.04, 0.04, 0.20, 0.26)))
    neck_l = _straight_lum(_world_patch(face, (-0.04, 0.04, 0.34, 0.40)))
    assert neck_l <= chin_l - 12.0, (neck_l, chin_l)
    neck_px = _world_patch(face, (-0.04, 0.04, 0.34, 0.40))
    alpha = neck_px[..., 3].astype(np.float64)
    rgb = neck_px[..., :3].astype(np.float64) * (255.0 / np.maximum(alpha[..., None], 1.0))
    lit = rgb[alpha > 40.0]
    assert float(lit[:, 2].mean() - lit[:, 1].mean()) >= 12.0


def test_the_hair_stops_at_the_shoulder():
    """Below the shoulder line the hair alpha is gone.

    The line is world y 0.66, under the jaw and where the shoulders sit.
    Tips may fade on the way down. On the tall plate the hair still ran past
    y 1.0, with mean alpha about 77 below y 0.75.
    """
    from arelis.ui.persona_face.bake import composite_rest
    from arelis.ui.persona_face.engine import VIEW

    plate = composite_rest(_layers())
    alpha = plate[..., 3].astype(np.float64)
    height = alpha.shape[0]
    x0, x1, y0, y1 = VIEW
    del x0, x1
    world_y = y0 + (np.arange(height) + 0.5) / height * (y1 - y0)
    below = world_y > _SHOULDER_Y
    assert int(below.sum()) > 4
    low = alpha[below]
    assert float(low.mean()) < 8.0, float(low.mean())
    assert float(low.max()) < 28.0, float(low.max())
