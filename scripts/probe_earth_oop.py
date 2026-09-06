"""Prove Cesium can start after solar GL without killing this process.

Mimics the daily driver: desktop GL offscreen context, park(), then
EarthGlobeHost(process='out'). Does not import QWebEngineView in this
process. Success is: parent still alive and the child reports an HWND.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["ARELIS_SOLAR_GL"] = "1"
os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ["ARELIS_ALLOW_OFFSCREEN"] = "1"
os.environ.pop("QTWEBENGINE_CHROMIUM_FLAGS", None)


def _park_like_solar() -> None:
    from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
    from shiboken6 import delete, isValid

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
    fmt.setDepthBufferSize(24)
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    surf = QOffscreenSurface()
    surf.setFormat(fmt)
    surf.create()
    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    if not ctx.create():
        print("offscreen ctx create failed", flush=True)
        return
    ctx.makeCurrent(surf)
    ctx.doneCurrent()
    if isValid(ctx):
        delete(ctx)
    surf.destroy()


def main() -> int:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QOpenGLContext
    from PySide6.QtWidgets import QApplication, QWidget

    from arelis.ui.earth_globe_host import EarthGlobeHost, share_group_live
    from arelis.ui.solar_gl import prepare_desktop_gl
    from arelis.ui.window_resize import configure_native_windows

    prepare_desktop_gl(os.environ)
    configure_native_windows()
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL, True)
    # Old launch also set this. Leave it on so the probe matches the abort.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication.instance() or QApplication([])
    print(f"share after app={share_group_live()}", flush=True)
    _park_like_solar()
    shared = QOpenGLContext.globalShareContext()
    print(
        f"share after park={shared is not None}  "
        f"webengine_in_modules={'PySide6.QtWebEngineWidgets' in sys.modules}",
        flush=True,
    )

    plate = QWidget()
    plate.resize(960, 720)
    plate.setWindowTitle("probe earth oop")
    plate.show()
    host = EarthGlobeHost(plate, process="out")
    host.setGeometry(plate.rect())
    host.show()
    print(
        f"host own_process={host._own_process} failed={host.failed} pid="
        f"{getattr(host._proc, 'pid', None)}",
        flush=True,
    )
    if host.failed:
        print("FAIL host failed immediately", flush=True)
        return 2

    deadline = time.perf_counter() + 25.0
    result = {"code": 3, "hwnd_at": 0.0}

    def finish(code: int, why: str) -> None:
        print(
            f"{why} hwnd={host._hwnd} ready={host.ready} kind={host.kind!r} "
            f"failed={host.failed} "
            f"webengine_in_parent={'PySide6.QtWebEngineWidgets' in sys.modules}",
            flush=True,
        )
        result["code"] = code
        host.shutdown()
        plate.close()
        app.quit()

    def tick() -> None:
        app.processEvents()
        if host.failed and not host._hwnd:
            finish(2, "FAIL host.failed before hwnd")
            return
        if host._hwnd and not result["hwnd_at"]:
            result["hwnd_at"] = time.perf_counter()
            print(f"hwnd={host._hwnd} (parent still alive)", flush=True)
        if host.ready:
            finish(0, "PASS cesium ready")
            return
        if time.perf_counter() > deadline:
            if host._hwnd:
                finish(0, "PASS hwnd (ready still pending)")
            else:
                finish(3, "FAIL hwnd timeout")
            return
        QTimer.singleShot(100, tick)

    QTimer.singleShot(100, tick)
    app.exec()
    return int(result["code"])


if __name__ == "__main__":
    sys.exit(main())
