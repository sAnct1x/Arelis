"""The face itself. Layers are cached images. A frame only moves and fades them."""

from __future__ import annotations

import math
import threading

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QImage, QPainter, QTransform
from PySide6.QtWidgets import QWidget

from arelis.ui.persona_face.bake import composite_rest, flatten_on_black
from arelis.ui.persona_face.engine import (
    BLINK_LEVELS,
    MOUTH_LEVELS,
    PHASE_COUNT,
    VIEW,
    bake_layers,
    raster_size,
    smooth,
)
from arelis.ui.persona_face.motion import Frame
from arelis.ui.void_idle import paint_orbit

_LIGHT = ("wisps", "ring", "star")


def _qimage(array: np.ndarray) -> QImage:
    """Premultiplied image. The numpy buffer can be dropped after copy."""
    src = np.ascontiguousarray(array)
    height, width, _ = src.shape
    bgra = np.ascontiguousarray(src[..., [2, 1, 0, 3]])
    image = QImage(bgra.data, width, height, width * 4, QImage.Format.Format_ARGB32_Premultiplied)
    return image.copy()


def _rgba_image(array: np.ndarray) -> QImage:
    src = np.ascontiguousarray(array)
    height, width, _ = src.shape
    image = QImage(src.data, width, height, width * 4, QImage.Format.Format_RGBA8888)
    return image.copy()


class _BakeThread(QThread):
    ready = Signal(object)

    def __init__(self, size: int, generation: int) -> None:
        super().__init__()
        self._size = size
        self._generation = generation
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        # A failed bake has to reach the widget. Swallowing it leaves the orb up
        # with no explanation, so the error string is the payload.
        try:

            def publish(layers: dict, phases: int) -> None:
                if self._cancel.is_set():
                    return
                payload = {
                    "layers": layers,
                    "phases": phases,
                    "generation": self._generation,
                    "thread": threading.current_thread().name,
                    "error": "",
                }
                if phases == 1:
                    payload["rest"] = flatten_on_black(composite_rest(layers))
                    payload["shapes"] = {
                        name: layers[name].shape[:2] for name in ("face", "wisps", "star")
                    }
                self.ready.emit(payload)

            bake_layers(self._size, cancel=self._cancel, publish=publish)
        except Exception as exc:
            if self._cancel.is_set():
                return
            self.ready.emit(
                {
                    "layers": {},
                    "rest": None,
                    "shapes": {},
                    "phases": 0,
                    "generation": self._generation,
                    "thread": threading.current_thread().name,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )


class PersonaAvatar(QWidget):
    """Portrait. Starts as the orb and fades the baked face in over it."""

    pressed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("personaAvatar")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setMouseTracking(False)
        self.reveal = 0.0
        self.frame = Frame(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, False, 0, 0)
        self.speaking = False
        self.thinking = False
        self.glow = 0.0
        self._images: dict[str, QImage] = {}
        self._rest: QImage | None = None
        self._shapes: dict[str, tuple[int, int]] = {}
        self._bake_ready = False
        self._bake_error = ""
        self._thread_name = ""
        self._painted_orb = False
        self._phases_ready = 0
        self._closing = False
        self._generation = 0
        self._baker: _BakeThread | None = None
        self._baked_px = 0
        self._dpr = 1.0
        self._rebake = QTimer(self)
        self._rebake.setSingleShot(True)
        self._rebake.timeout.connect(self._start_bake)
        self._orbit_angle = 18.0
        self._canvas: QImage | None = None
        self._mask: QImage | None = None
        self._mask_key: tuple[int, int, float] | None = None
        self.mask_builds = 0

    def bake_ready(self) -> bool:
        return self._bake_ready

    def bake_thread_name(self) -> str:
        return self._thread_name

    def painted_orb_while_baking(self) -> bool:
        return self._painted_orb

    def layer_shapes(self) -> dict[str, tuple[int, int]]:
        return dict(self._shapes)

    def phases_ready(self) -> int:
        return self._phases_ready

    def rest_face_image(self) -> QImage:
        if self._rest is None:
            return QImage()
        return self._rest

    def request_bake(self, delay_ms: int) -> None:
        self._rebake.start(max(0, int(delay_ms)))

    def note_resize(self) -> None:
        if not self._bake_ready:
            return
        needed = self._pixel_size()
        dpr = self.devicePixelRatioF()
        if abs(dpr - self._dpr) > 0.05 or needed > self._baked_px * 1.25:
            self._rebake.start(250)

    def _pixel_size(self) -> int:
        dpr = max(1.0, float(self.devicePixelRatioF()))
        width = round(max(64.0, self.width() * dpr))
        _wide, height = raster_size(width)
        long_side = max(width, height)
        if long_side > 1024:
            width = max(64, int(width * 1024 / long_side))
        return min(1024, width)

    def _start_bake(self) -> None:
        if self._closing or not self.isVisible():
            return
        size = self._pixel_size()
        if self._baker is not None and self._baker.isRunning():
            return
        self._baked_px = size
        self._dpr = float(self.devicePixelRatioF())
        self._generation += 1
        self._baker = _BakeThread(size, self._generation)
        self._baker.ready.connect(self._on_baked)
        self._baker.start()

    def _on_baked(self, payload: object) -> None:
        if self._closing or not isinstance(payload, dict):
            return
        if int(payload.get("generation", -1)) != self._generation:
            return
        self._thread_name = str(payload.get("thread", ""))
        self._bake_error = str(payload.get("error", ""))
        layers = payload.get("layers") or {}
        for name, array in layers.items():
            self._images[name] = _qimage(array)
        rest = payload.get("rest")
        if rest is not None:
            self._rest = _rgba_image(rest)
        if payload.get("shapes"):
            self._shapes = dict(payload["shapes"])
        self._phases_ready = max(self._phases_ready, int(payload.get("phases") or 0))
        self._bake_ready = "face" in self._images and self._rest is not None
        self.update()

    def shutdown(self) -> None:
        """Stop the bake before this widget is destroyed.

        A thread that outlives the widget faults on Windows when Qt tears
        the receiver down. Cancel, drop the signal, then wait it out.
        """
        self._closing = True
        self._rebake.stop()
        baker = self._baker
        self._baker = None
        if baker is None:
            return
        try:
            baker.ready.disconnect(self._on_baked)
        except RuntimeError:
            pass
        baker.cancel()
        if baker.isRunning():
            baker.wait()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        dpr = max(1.0, float(self.devicePixelRatioF()))
        width = max(1, round(self.width() * dpr))
        height = max(1, round(self.height() * dpr))
        canvas = self._canvas
        if canvas is None or canvas.width() != width or canvas.height() != height:
            canvas = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
            self._canvas = canvas
        canvas.setDevicePixelRatio(dpr)
        canvas.fill(0)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # The plate is already at device pixels. A smooth scale on top blurs her.
        if not self._bake_ready:
            self._painted_orb = True
        self._paint_orb(painter)
        if self._bake_ready and self.reveal > 0.001:
            self._paint_face(painter)
        painter.resetTransform()
        painter.setOpacity(1.0)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, self._edge_mask(width, height, dpr))
        painter.end()
        screen = QPainter(self)
        screen.drawImage(0, 0, canvas)
        screen.end()

    def _edge_mask(self, width: int, height: int, dpr: float) -> QImage:
        """Soft alpha that reaches zero at the face frame, built once per size.

        Layers stop at the frame, and hair drifts a few pixels past it. Fading
        the finished plate here hides that line without any per frame work.
        """
        key = (width, height, round(dpr, 3))
        if self._mask is not None and self._mask_key == key:
            return self._mask
        rect = self._face_rect()
        left = rect.left() * dpr
        right = rect.right() * dpr
        top = rect.top() * dpr
        bottom = rect.bottom() * dpr
        band_x = max(8.0, 12.0 * dpr)
        band_top = max(6.0, 10.0 * dpr)
        band_bottom = max(8.0, 14.0 * dpr)
        # A few percent at the frame stays clear, so the dock color is the edge.
        dead_x = rect.width() * dpr * 0.045
        dead_top = rect.height() * dpr * 0.035
        dead_bottom = rect.height() * dpr * 0.05
        xs = np.arange(width, dtype=np.float32) + 0.5
        ys = np.arange(height, dtype=np.float32) + 0.5
        fade_x = smooth((np.minimum(xs - left, right - xs) - dead_x) / band_x)
        fade_y = np.minimum(
            smooth((ys - top - dead_top) / band_top),
            smooth((bottom - ys - dead_bottom) / band_bottom),
        )
        alpha = np.clip(fade_y[:, None] * fade_x[None, :], 0.0, 1.0)
        level = np.round(alpha * 255.0).astype(np.uint8)
        bgra = np.ascontiguousarray(np.repeat(level[:, :, None], 4, axis=2))
        image = QImage(
            bgra.data, width, height, width * 4, QImage.Format.Format_ARGB32_Premultiplied
        )
        self._mask = image.copy()
        self._mask.setDevicePixelRatio(1.0)
        self._mask_key = key
        self.mask_builds += 1
        return self._mask

    def _face_rect(self) -> QRectF:
        """Tall frame: head toward the top, hair filling the rest."""
        x0, x1, y0, y1 = VIEW
        aspect = (y1 - y0) / (x1 - x0)
        # Leave a soft margin so hair fades inside the plate instead of clipping.
        inset_x = self.width() * 0.04
        inset_y = self.height() * 0.04
        width = max(1.0, self.width() - inset_x * 2.0)
        height = width * aspect
        limit = max(1.0, self.height() - inset_y * 2.0)
        if height > limit:
            height = limit
            width = height / aspect
        x = (self.width() - width) / 2.0
        y = inset_y
        return QRectF(x, y, width, height)

    def _map(self, vx: float, vy: float, rect: QRectF) -> QPointF:
        x0, x1, y0, y1 = VIEW
        px = rect.x() + (vx - x0) / (x1 - x0) * rect.width()
        py = rect.y() + (vy - y0) / (y1 - y0) * rect.height()
        return QPointF(px, py)

    def _paint_orb(self, painter: QPainter) -> None:
        fade = 1.0 - self.reveal
        if self.reveal > 0.0 and not self._bake_ready:
            fade = 1.0
        if fade <= 0.02 and self._bake_ready:
            return
        rect = self._face_rect()
        center = rect.center()
        star = self._map(0.23, -0.38, rect)
        dx = star.x() - center.x()
        dy = star.y() - center.y()
        star_angle = math.degrees(math.atan2(dx, -dy))
        self._orbit_angle = (self._orbit_angle + 0.8) % 360.0
        angle = self._orbit_angle * (1.0 - self.reveal) + star_angle * self.reveal
        box = rect.width() * (0.42 + 0.5 * self.reveal)
        painter.save()
        painter.setOpacity(max(0.0, min(1.0, fade)))
        paint_orbit(
            painter,
            center.x(),
            center.y(),
            box=box,
            dim=0.55 + 0.35 * fade,
            angle=angle,
            beat=self.frame.breath * 0.5 + 0.5,
        )
        painter.restore()

    def _paint_face(self, painter: QPainter) -> None:
        rect = self._face_rect()
        pivot = self._map(0.0, 0.36, rect)
        breath = 1.0 + 0.004 * self.frame.breath
        sway = self.frame.sway_deg
        painter.save()
        painter.setOpacity(self.reveal)
        transform = QTransform()
        transform.translate(pivot.x(), pivot.y() + self.frame.bob * 4.0)
        transform.rotate(sway)
        transform.scale(breath, breath)
        transform.translate(-pivot.x(), -pivot.y())
        self._blit_phase(painter, "back", rect, transform)
        self._blit(painter, "wisps", rect, dx=self.frame.wisp_x * 8.0, dy=self.frame.wisp_y * 6.0)
        self._blit(painter, "face", rect, transform, light=False)
        self._blit_mouth(painter, rect, transform)
        self._blit_eyes(painter, rect, transform)
        self._blit_phase(painter, "front", rect, transform)
        painter.setOpacity(self.reveal * self.frame.ring)
        self._blit(painter, "ring", rect, transform, light=True)
        star = self.frame.star * (1.15 if self.thinking else 1.0) * (1.0 + 0.35 * self.glow)
        painter.setOpacity(max(0.0, min(1.0, self.reveal * star)))
        self._blit(painter, "star", rect, transform, light=True)
        painter.restore()

    def _blit(
        self,
        painter: QPainter,
        name: str,
        rect: QRectF,
        transform: QTransform | None = None,
        dx: float = 0.0,
        dy: float = 0.0,
        light: bool = True,
    ) -> None:
        image = self._images.get(name)
        if image is None or image.isNull():
            return
        painter.save()
        if light and name in _LIGHT:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        else:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if transform is not None:
            painter.setTransform(transform, True)
        painter.drawImage(rect.translated(dx, dy), image)
        painter.restore()

    def _phase_pair(self) -> tuple[int, int, float]:
        """Index along the baked sweep. Value noise in hair_tip, no wrap."""
        ready = self._phases_ready
        if ready <= 1:
            return 0, 0, 0.0
        span = min(ready, PHASE_COUNT) - 1
        tip = self.frame.hair_tip
        if tip < -1.0:
            tip = -1.0
        elif tip > 1.0:
            tip = 1.0
        pos = (tip + 1.0) * 0.5 * span
        index = int(pos)
        if index >= span:
            return span, span, 0.0
        return index, index + 1, pos - index

    def _blit_phase(
        self, painter: QPainter, kind: str, rect: QRectF, transform: QTransform
    ) -> None:
        first, second, mix = self._phase_pair()
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        painter.setTransform(transform, True)
        base = painter.opacity()
        image_a = self._images.get(f"{kind}_{first}")
        image_b = self._images.get(f"{kind}_{second}")
        if image_a is not None and mix < 0.999:
            painter.setOpacity(base * (1.0 - mix))
            painter.drawImage(rect, image_a)
        if image_b is not None and mix > 0.001 and second != first:
            painter.setOpacity(base * mix)
            painter.drawImage(rect, image_b)
        painter.restore()

    def _blit_pair(
        self,
        painter: QPainter,
        names: tuple[str, str],
        mix: float,
        rect: QRectF,
        transform: QTransform,
    ) -> None:
        mix = max(0.0, min(1.0, mix))
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setTransform(transform, True)
        first = self._images.get(names[0])
        second = self._images.get(names[1])
        base = painter.opacity()
        if first is not None and mix < 0.999:
            painter.setOpacity(base * (1.0 - mix))
            painter.drawImage(rect, first)
        if second is not None and mix > 0.001:
            painter.setOpacity(base * mix)
            painter.drawImage(rect, second)
        painter.restore()

    def _blit_mouth(self, painter: QPainter, rect: QRectF, transform: QTransform) -> None:
        level = max(0.0, min(0.999, self.frame.mouth)) * (len(MOUTH_LEVELS) - 1)
        index = int(level)
        self._blit_pair(
            painter, (f"mouth_{index}", f"mouth_{index + 1}"), level - index, rect, transform
        )

    def _blit_eyes(self, painter: QPainter, rect: QRectF, transform: QTransform) -> None:
        blink = max(0.0, min(0.999, self.frame.blink))
        if blink < 0.08:
            gaze = self.frame.gaze_x
            if self.thinking:
                self._blit_pair(painter, ("gaze_0", "gaze_1"), 0.65, rect, transform)
            elif gaze >= 0.0:
                self._blit_pair(
                    painter, ("gaze_0", "gaze_1"), min(1.0, gaze / 0.012), rect, transform
                )
            else:
                self._blit_pair(
                    painter, ("gaze_0", "gaze_2"), min(1.0, -gaze / 0.008), rect, transform
                )
            return
        level = blink * (len(BLINK_LEVELS) - 1)
        index = int(level)
        nxt = min(index + 1, len(BLINK_LEVELS) - 1)
        self._blit_pair(painter, (f"eye_{index}", f"eye_{nxt}"), level - index, rect, transform)
