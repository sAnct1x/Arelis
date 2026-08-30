"""One-off: why EarthGlobeHost fails with cesium. Do not use offscreen."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
except Exception as exc:
    print(f"webengine import failed: {exc}", flush=True)

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMainWindow

os.environ.setdefault("ARELIS_SOLAR_GL", "1")


class _ConsolePage:
    """Mixin-style page installed on the view."""


def main() -> int:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import (
        QWebEnginePage,
        QWebEngineProfile,
        QWebEngineSettings,
        QWebEngineUrlRequestInterceptor,
    )
    from PySide6.QtWebEngineWidgets import QWebEngineView

    from arelis.earth.globe_stack import choose_stack
    from arelis.ui.earth_globe_host import (
        GLOBE_DIR,
        GlobeBridge,
        webengine_available,
    )
    from arelis.ui.solar_gl import prepare_desktop_gl
    from arelis.ui.window_resize import configure_native_windows

    print(f"QT_QPA_PLATFORM={os.environ.get('QT_QPA_PLATFORM', '')!r}", flush=True)
    prepare_desktop_gl(os.environ)
    configure_native_windows()
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL, True)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication.instance() or QApplication([])

    events: list[str] = []

    def note(msg: str) -> None:
        events.append(msg)
        print(msg, flush=True)

    class Spy(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info) -> None:
            url = info.requestUrl().toString()
            note(f"req type={info.resourceType()} {url}")

    class ConsolePage(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, message, line, source):
            note(f"console level={level} {source}:{line} {message}")

    interceptor = Spy()
    profile = QWebEngineProfile.defaultProfile()
    profile.setUrlRequestInterceptor(interceptor)

    win = QMainWindow()
    win.resize(1280, 800)
    win.setWindowTitle("probe earth globe")
    view = QWebEngineView(win)
    page = ConsolePage(profile, view)
    view.setPage(page)
    view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    page.setBackgroundColor(QColor(0, 0, 0, 0))
    settings = view.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, True)

    bridge = GlobeBridge(view)
    failed_why: list[str] = []
    ready_kind: list[str] = []
    bridge.hostFailed.connect(lambda why: (failed_why.append(why), note(f"hostFailed why={why!r}")))
    bridge.hostReady.connect(lambda kind: (ready_kind.append(kind), note(f"hostReady kind={kind!r}")))
    bridge.hostTiles.connect(lambda kind: note(f"hostTiles kind={kind!r}"))

    channel = QWebChannel(page)
    channel.registerObject("bridge", bridge)
    page.setWebChannel(channel)

    view.loadFinished.connect(
        lambda ok: note(f"loadFinished ok={ok} url={page.url().toString()!r}")
    )
    page.renderProcessTerminated.connect(
        lambda status, code: note(f"renderProcessTerminated status={status} code={code}")
    )

    index = GLOBE_DIR / "index.html"
    view.setUrl(QUrl.fromLocalFile(str(index)))
    win.setCentralWidget(view)
    win.show()
    app.processEvents()

    deadline = time.perf_counter() + 60.0
    js_dump = {}
    dumped = False
    while time.perf_counter() < deadline:
        app.processEvents()
        if (ready_kind or failed_why) and not dumped:
            dumped = True
            page.runJavaScript(
                """
                (function () {
                  var gl = null, glErr = "";
                  try {
                    var c = document.createElement("canvas");
                    gl = c.getContext("webgl") || c.getContext("experimental-webgl");
                  } catch (e) { glErr = String(e); }
                  var scripts = Array.prototype.map.call(
                    document.getElementsByTagName("script"),
                    function (s) { return s.src || "(inline)"; }
                  );
                  return JSON.stringify({
                    cesium: typeof Cesium,
                    qt: typeof qt,
                    scripts: scripts,
                    webgl: !!gl,
                    glErr: glErr,
                    href: location.href
                  });
                })();
                """,
                lambda raw: js_dump.update({"raw": raw}),
            )
            t_extra = time.perf_counter() + 2.0
            while time.perf_counter() < t_extra:
                app.processEvents()
            break
        time.sleep(0.05)

    print(f"js_dump={js_dump.get('raw')}", flush=True)
    print(
        f"ready={bool(ready_kind)} failed={bool(failed_why)} "
        f"kind={ready_kind[-1] if ready_kind else (failed_why[-1] if failed_why else '')!r} "
        f"webengine_available={webengine_available()} "
        f"stack={choose_stack().kind} cesiumJs={choose_stack().to_payload()['cesiumJs']}",
        flush=True,
    )
    print("events:", flush=True)
    for row in events:
        print(f"  {row}", flush=True)
    QTimer.singleShot(0, app.quit)
    app.processEvents()
    return 0 if ready_kind and not failed_why else 1


if __name__ == "__main__":
    raise SystemExit(main())
