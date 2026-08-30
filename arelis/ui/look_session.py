"""Live look-from / listen on the Reality plate. Same window, not a second app.

Owned RTSP/USB/HTTP plays as video. Official publisher stills refresh.
Radio Browser streams play audio. Stream URLs never appear in status text.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QImage

from arelis.earth.look import LookHandle, official_url_ok, open_source

log = logging.getLogger(__name__)

_STILL_PERIOD_S = 2.0
_UA = "ArelisEarth/0.2"


class LookSession(QObject):
    """One playable source at a time. Drop the URL when inspect closes."""

    frame = Signal(object)
    status = Signal(str)
    playing = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._handle: LookHandle | None = None
        self._thread: QThread | None = None
        self._worker: _GrabWorker | None = None
        self._player = None
        self._output = None
        self._boot_player()

    def active_id(self) -> str:
        return self._handle.entity_id if self._handle is not None else ""

    def start(self, handle: LookHandle) -> None:
        if (
            self._handle is not None
            and self._handle.entity_id == handle.entity_id
            and self._handle.kind == handle.kind
        ):
            return
        self.stop()
        self._handle = handle
        try:
            from arelis.physics.telemetry import emit

            emit(
                "look_start",
                id=handle.entity_id,
                kind=handle.kind,
                media=handle.media,
            )
        except Exception:
            pass
        if handle.media == "audio":
            self._start_audio(handle)
            return
        self._worker = _GrabWorker(handle)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.frame.connect(self.frame)
        self._worker.status.connect(self.status)
        self._thread.start()
        self.playing.emit(True)
        if handle.kind == "owned":
            self.status.emit("Looking from owned camera — live.")
        elif handle.media == "still":
            self.status.emit("Publisher still — refreshing.")
        else:
            self.status.emit("Publisher live.")

    def stop(self) -> None:
        handle = self._handle
        self._handle = None
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:
                pass
        worker = self._worker
        thread = self._thread
        self._worker = None
        self._thread = None
        if worker is not None:
            worker.stop()
        if thread is not None:
            thread.quit()
            if not thread.wait(1500):
                thread.terminate()
                thread.wait(400)
        if handle is not None:
            self.playing.emit(False)
            try:
                from arelis.physics.telemetry import emit

                emit("look_stop", id=handle.entity_id, kind=handle.kind)
            except Exception:
                pass

    def _boot_player(self) -> None:
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            return
        self._output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._output)
        self._player.errorOccurred.connect(self._on_player_error)

    def _start_audio(self, handle: LookHandle) -> None:
        if self._player is None:
            self.status.emit("No audio player on this build.")
            return
        try:
            self._player.setSource(QUrl(handle.source()))
            self._player.play()
        except Exception:
            self.status.emit("Published stream failed.")
            return
        self.playing.emit(True)
        self.status.emit("Listening — published stream.")

    def _on_player_error(self, *_args: object) -> None:
        self.status.emit("Published stream failed.")


class _GrabWorker(QObject):
    frame = Signal(object)
    status = Signal(str)

    def __init__(self, handle: LookHandle) -> None:
        super().__init__()
        self._handle = handle
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        handle = self._handle
        if handle.media == "still":
            self._poll_still(handle)
            return
        self._grab_video(handle)

    def _poll_still(self, handle: LookHandle) -> None:
        url = handle.source()
        if handle.kind == "official" and not official_url_ok(url):
            self.status.emit("Publisher still is not on an allowed host.")
            return
        while not self._stop.is_set():
            image = _fetch_still(url, official=handle.kind == "official")
            if image is not None:
                self.frame.emit(image)
            elif not self._stop.is_set():
                self.status.emit("Publisher still failed. Pin stays.")
            self._stop.wait(_STILL_PERIOD_S)

    def _grab_video(self, handle: LookHandle) -> None:
        try:
            import cv2
        except ImportError:
            if handle.media in {"still", "mjpeg"} or handle.kind == "official":
                self._poll_still(handle)
            else:
                self.status.emit("Live video needs OpenCV on this machine.")
            return
        source = open_source(handle)
        cap = None
        try:
            cap = cv2.VideoCapture(source)
            try:
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 4000)
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 4000)
            except Exception:
                pass
            misses = 0
            while not self._stop.is_set():
                ok, bgr = cap.read()
                if not ok or bgr is None:
                    misses += 1
                    if misses >= 8:
                        self.status.emit("Live stream failed. Pin stays.")
                        return
                    self._stop.wait(0.25)
                    continue
                misses = 0
                image = _bgr_to_qimage(bgr)
                if image is not None:
                    self.frame.emit(image)
        except Exception:
            self.status.emit("Live stream failed. Pin stays.")
        finally:
            if cap is not None:
                cap.release()


def _fetch_still(url: str, *, official: bool) -> QImage | None:
    try:
        import httpx
    except ImportError:
        return None
    try:
        with httpx.Client(timeout=8.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": _UA})
            resp.raise_for_status()
            if official and not official_url_ok(str(resp.url)):
                return None
            image = QImage.fromData(resp.content)
            if image.isNull():
                return None
            return image
    except Exception:
        return None


def _bgr_to_qimage(bgr: Any) -> QImage | None:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    try:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        rgb = np.ascontiguousarray(rgb)
        h, w = rgb.shape[:2]
        if w < 1 or h < 1:
            return None
        image = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
        return image.copy()
    except Exception:
        return None
