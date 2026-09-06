"""Cesium in its own process. No solar GL, no Qt share group.

The daily driver used to park the offscreen context and then construct
QWebEngineView in the same process. On AMD that aborts — AA_ShareOpenGLContexts
leaves QOpenGLContext.globalShareContext() alive after park(). This process
is Chromium only. Sodium HUD and the solar lab stay in the parent.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

log = logging.getLogger("arelis.earth_globe_proc")


def _install_logging() -> None:
    try:
        from arelis.paths import logs_dir

        directory = logs_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "earth_globe.log"
        logging.basicConfig(
            filename=str(path),
            filemode="a",
            level=logging.INFO,
            format="%(asctime)s earth globe %(message)s",
        )
    except Exception:
        logging.basicConfig(level=logging.INFO)


def _note(msg: str) -> None:
    log.info("%s", msg)
    try:
        from arelis.paths import logs_dir

        path = logs_dir() / "earth_globe.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(msg + "\n")
            handle.flush()
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    os.environ["ARELIS_EARTH_GLOBE_CHILD"] = "1"
    os.environ["ARELIS_SOLAR_GL"] = "0"
    os.environ.pop("QTWEBENGINE_CHROMIUM_FLAGS", None)
    os.environ.pop("QT_OPENGL", None)
    if sys.platform == "win32":
        os.environ["QT_QPA_PLATFORM"] = "windows"

    parser = argparse.ArgumentParser(prog="earth_globe_proc")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)

    _install_logging()
    _note(f"child start port={args.port}")

    # WebEngine before QApplication. No share group — this process has no solar GL.
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QTcpSocket
    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    from PySide6.QtWidgets import QApplication

    from arelis.ui.earth_globe_host import (
        EarthGlobeHost,
        GlobeKeyHose,
        globe_key_payload,
        seal_globe_plate,
    )

    app = QApplication.instance() or QApplication([])
    host = EarthGlobeHost(process="in")
    host.setWindowFlags(
        Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
    )
    host.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
    seal_globe_plate(host)
    host.resize(960, 720)
    host.show()
    app.processEvents()
    hwnd = int(host.winId())
    _note(f"child hwnd={hwnd}")

    sock = QTcpSocket()
    buf = {"raw": b""}

    def send(payload: dict[str, Any]) -> None:
        line = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        sock.write(QByteArray(line))
        sock.flush()

    def on_ready(kind: str) -> None:
        send({"event": "ready", "kind": kind})

    def on_failed(why: str) -> None:
        send({"event": "failed", "why": why})

    def on_picked(entity_id: str) -> None:
        send({"event": "picked", "id": entity_id})

    def on_camera(raw: str) -> None:
        send({"event": "camera", "raw": raw})

    def on_ground(raw: str) -> None:
        send({"event": "ground", "raw": raw})

    def on_tiles(kind: str) -> None:
        send({"event": "tiles", "kind": kind})

    def on_js_key(raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        if isinstance(payload, dict):
            send({"event": "key", **payload})

    host.bridge.hostReady.connect(on_ready)
    host.bridge.hostFailed.connect(on_failed)
    host.bridge.hostPicked.connect(on_picked)
    host.bridge.hostCamera.connect(on_camera)
    host.bridge.hostGround.connect(on_ground)
    host.bridge.hostTiles.connect(on_tiles)
    host.bridge.hostKey.connect(on_js_key)

    def on_key(event) -> None:
        send(globe_key_payload(event))

    hose = GlobeKeyHose(on_key)
    app.installEventFilter(hose)

    def apply_op(msg: dict[str, Any]) -> None:
        op = str(msg.get("op") or "")
        if op == "quit":
            _note("child quit")
            host.hide()
            app.quit()
            return
        if op == "nudge":
            host.push_nudge(
                float(msg.get("fwd") or 0.0),
                float(msg.get("right") or 0.0),
                float(msg.get("up") or 0.0),
            )
            return
        if op == "look":
            host.push_look(
                float(msg.get("yaw") or 0.0),
                float(msg.get("pitch") or 0.0),
            )
            return
        if op == "aim":
            host.push_aim(
                float(msg["lat"]),
                float(msg["lon"]),
                float(msg.get("alt_m") or 0.0),
            )
            return
        if op == "camera":
            host.push_camera(
                float(msg["lat"]),
                float(msg["lon"]),
                float(msg["alt_m"]),
                msg.get("heading"),
                msg.get("pitch"),
                soft=bool(msg.get("soft")),
            )
            return
        if op == "fly":
            host.fly_to(float(msg["lat"]), float(msg["lon"]), float(msg["alt_m"]))
            return
        if op == "entities":
            host.push_entities(list(msg.get("rows") or []))
            return
        if op == "places":
            host.push_places(list(msg.get("rows") or []))
            return
        if op == "stack":
            host.push_stack()
            return
        if op == "find":
            host.bridge.findOpen.emit(bool(msg.get("on")))
            return
        if op == "streets":
            host.push_streets(bool(msg.get("on")))
            return
        if op == "buildings":
            rings = msg.get("rings")
            host.push_buildings(rings if isinstance(rings, list) else None)
            return
        if op == "roads":
            rows = msg.get("rows")
            host.push_roads(rows if isinstance(rows, list) else None)
            return
        if op == "marks":
            host.push_marks()
            return
        if op == "resize":
            host.resize(max(int(msg.get("w") or 1), 1), max(int(msg.get("h") or 1), 1))
            return

    def on_ready_read() -> None:
        buf["raw"] += bytes(sock.readAll().data())
        while b"\n" in buf["raw"]:
            line, buf["raw"] = buf["raw"].split(b"\n", 1)
            text = line.decode("utf-8").strip()
            if not text:
                continue
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict):
                apply_op(msg)

    def on_connected() -> None:
        _note("child connected")
        send({"event": "hwnd", "hwnd": hwnd})
        if host.ready:
            send({"event": "ready", "kind": host.kind})

    def on_error() -> None:
        _note(f"child socket error {sock.error()}")
        app.quit()

    sock.readyRead.connect(on_ready_read)
    sock.connected.connect(on_connected)
    sock.errorOccurred.connect(lambda *_: on_error())
    sock.disconnected.connect(app.quit)
    sock.connectToHost(QHostAddress.SpecialAddress.LocalHost, int(args.port))
    if sock.state() == QAbstractSocket.SocketState.UnconnectedState:
        _note("child connect failed immediately")
        return 2
    return int(app.exec())


if __name__ == "__main__":
    sys.exit(main())
