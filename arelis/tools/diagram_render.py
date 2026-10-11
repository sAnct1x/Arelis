"""Turn diagram text into an SVG and a PNG.

Each function returns None when it wrote both files, or a short sentence when
it did not. Parser failures keep the renderer's own line so the next try can
fix the text. A missing network, including a slide that needs a package the
computer has not saved yet, is rewritten into plain words. No shell.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from arelis.tools.diagram_bins import OFFLINE, HelperError, ensure_binary

_TIMEOUT_S = 10
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/][^\s]+|/(?:[\w.+@-]+/)+[\w.+@-]*)")
_URL_RE = re.compile(r"https?://\S+")
_OFFLINE_MARKERS = (
    "failed to download",
    "connection refused",
    "connection failed",
    "connect error",
    "network is unreachable",
    "name or service not known",
    "temporary failure in name resolution",
    "timed out",
    "timeout",
    "offline",
    "no route to host",
)
_EMPTY = "That diagram came out empty. Check the text and try again."
_TOO_LONG = "That diagram took too long, so I stopped."
_CHECK = "That diagram could not be drawn. Check the text and try again."
_DRAWING = "That drawing could not be read. Check the markup and try again."


def render_mermaid(source: str, svg_path: Path, png_path: Path) -> str | None:
    try:
        binary = ensure_binary()
    except HelperError as exc:
        return str(exc)
    with tempfile.TemporaryDirectory(prefix="arelis-diagram-") as raw:
        folder = Path(raw)
        src = folder / "diagram.mmd"
        src.write_text(source, encoding="utf-8")
        svg_tmp = folder / "diagram.svg"
        png_tmp = folder / "diagram.png"
        error = _mmdr(binary, src, svg_tmp, "svg")
        if error:
            return error
        error = _mmdr(binary, src, png_tmp, "png")
        if error:
            return error
        if _too_small(svg_tmp) or _too_small(png_tmp):
            return _EMPTY
        _place(svg_tmp, svg_path)
        _place(png_tmp, png_path)
    return None


def render_vegalite(source: str, svg_path: Path, png_path: Path) -> str | None:
    try:
        spec = json.loads(source)
    except json.JSONDecodeError as exc:
        return f"That chart text is not valid. {exc.msg}."
    if not isinstance(spec, dict):
        return "That chart text needs to be one object."
    try:
        import vl_convert as vlc
    except ImportError:
        return "I could not draw that chart on this computer."
    try:
        svg = vlc.vegalite_to_svg(spec)
        png = vlc.vegalite_to_png(spec, scale=2)
    except Exception as exc:
        return _public_error(exc)
    svg_bytes = svg.encode("utf-8") if isinstance(svg, str) else bytes(svg)
    png_bytes = bytes(png)
    if len(svg_bytes) < 32 or len(png_bytes) < 32:
        return _EMPTY
    _write_bytes(svg_path, svg_bytes)
    _write_bytes(png_path, png_bytes)
    return None


def render_typst(source: str, svg_path: Path, png_path: Path) -> str | None:
    try:
        import typst
    except ImportError:
        return "I could not draw that slide on this computer."
    with tempfile.TemporaryDirectory(prefix="arelis-diagram-") as raw:
        src = Path(raw) / "slide.typ"
        src.write_text(source, encoding="utf-8")
        try:
            svg = typst.compile(str(src), format="svg")
            png = typst.compile(str(src), format="png", ppi=144)
        except Exception as exc:
            return _public_error(exc)
    svg_bytes = _first_bytes(svg)
    png_bytes = _first_bytes(png)
    if len(svg_bytes) < 32 or len(png_bytes) < 32:
        return _EMPTY
    _write_bytes(svg_path, svg_bytes)
    _write_bytes(png_path, png_bytes)
    return None


def render_svg(source: str, svg_path: Path, png_path: Path) -> str | None:
    raw = source.encode("utf-8")
    if not raw.strip():
        return "Tell me what to draw."
    error = _rasterize(raw, png_path)
    if error:
        png_path.unlink(missing_ok=True)
        return error
    if _too_small(png_path):
        png_path.unlink(missing_ok=True)
        return _EMPTY
    _write_bytes(svg_path, raw)
    return None


def _mmdr(binary: Path, src: Path, dest: Path, fmt: str) -> str | None:
    command = [str(binary), "-i", str(src), "-o", str(dest), "-e", fmt]
    kwargs: dict[str, object] = {
        "capture_output": True,
        "timeout": _TIMEOUT_S,
        "check": False,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        completed = subprocess.run(command, **kwargs)
    except subprocess.TimeoutExpired:
        dest.unlink(missing_ok=True)
        return _TOO_LONG
    except OSError:
        return "I could not draw that diagram. Try again."
    if completed.returncode != 0 or not dest.is_file():
        dest.unlink(missing_ok=True)
        text = (completed.stderr or b"").decode("utf-8", "replace")
        if not text.strip():
            text = (completed.stdout or b"").decode("utf-8", "replace")
        return _public_error(text)
    return None


def _rasterize(svg: bytes, png_path: Path) -> str | None:
    qt_error: Exception | None = None
    try:
        _run_on_qt(lambda: _raster_qt(svg, png_path))
        if png_path.is_file() and png_path.stat().st_size > 0:
            return None
    except Exception as exc:
        qt_error = exc
        png_path.unlink(missing_ok=True)
    fallback = _raster_resvg(svg, png_path)
    if fallback is None and png_path.is_file() and png_path.stat().st_size > 0:
        return None
    if qt_error is not None:
        return _public_error(qt_error)
    if fallback and fallback != "missing":
        return fallback
    return _DRAWING


def _run_on_qt(fn):
    """Paint on the window thread when one is already running.

    Tools run on the background loop. Starting a second window there aborts,
    so a live window does the paint and this call waits for it. Tests and the
    proof script have no window, and paint on the caller.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None or QThread.currentThread() == app.thread():
        return fn()
    return _invoke_on(app, fn)


def _invoke_on(app, fn):
    from PySide6.QtCore import QMetaObject, QObject, Qt, Slot

    box: dict[str, object] = {}

    class _Host(QObject):
        def __init__(self) -> None:
            super().__init__()

        @Slot()
        def fire(self) -> None:
            try:
                box["result"] = fn()
            except Exception as exc:
                box["error"] = exc

    host = _Host()
    host.moveToThread(app.thread())
    QMetaObject.invokeMethod(host, "fire", Qt.ConnectionType.BlockingQueuedConnection)
    error = box.get("error")
    if isinstance(error, Exception):
        raise error
    return box.get("result")


def _raster_qt(svg: bytes, png_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication

    global _qt_hold
    if QApplication.instance() is None:
        _qt_hold = QApplication(["arelis"])
    renderer = QSvgRenderer(QByteArray(svg))
    if not renderer.isValid():
        raise ValueError(_DRAWING)
    size = renderer.defaultSize()
    width = max(int(size.width()), 1)
    height = max(int(size.height()), 1)
    scale = 2 if max(width, height) < 800 else 1
    image = QImage(width * scale, height * scale, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    try:
        if scale != 1:
            painter.scale(float(scale), float(scale))
        renderer.render(painter)
    finally:
        painter.end()
    if image.isNull():
        raise ValueError(_EMPTY)
    tmp = png_path.with_name(png_path.name + ".part")
    if not image.save(str(tmp), "PNG"):
        tmp.unlink(missing_ok=True)
        raise ValueError(_DRAWING)
    os.replace(tmp, png_path)


_qt_hold = None


def _raster_resvg(svg: bytes, png_path: Path) -> str | None:
    text = svg.decode("utf-8", "replace")
    try:
        import resvg_py
    except ImportError:
        resvg_py = None
    if resvg_py is not None:
        fn = getattr(resvg_py, "svg_to_png", None) or getattr(resvg_py, "svg_to_bytes", None)
        if fn is not None:
            try:
                png = fn(text)
            except Exception as exc:
                return _public_error(exc)
            if not png:
                return _EMPTY
            _write_bytes(png_path, bytes(png))
            return None
    try:
        from resvg import render
    except ImportError:
        return "missing"
    try:
        png = render(text)
    except Exception as exc:
        return _public_error(exc)
    if not png:
        return _EMPTY
    _write_bytes(png_path, bytes(png))
    return None


def _public_error(problem: BaseException | str) -> str:
    text = str(problem or "").strip()
    if _is_offline(text):
        return OFFLINE
    kept: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("at ") or "Traceback" in line:
            continue
        if _URL_RE.search(line):
            continue
        line = _PATH_RE.sub("the diagram", line)
        line = line.replace(chr(0x2014), ",").replace(chr(0x2013), "-")
        if line:
            kept.append(line)
        if len(kept) >= 4:
            break
    message = "\n".join(kept).strip()
    return message or _CHECK


def _is_offline(text: str) -> bool:
    low = text.lower()
    if "failed to download" in low:
        return True
    return any(marker in low for marker in _OFFLINE_MARKERS)


def _first_bytes(value: object) -> bytes:
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return b""


def _too_small(path: Path) -> bool:
    try:
        return path.stat().st_size < 32
    except OSError:
        return True


def _place(src: Path, dest: Path) -> None:
    _write_bytes(dest, src.read_bytes())


def _write_bytes(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, dest)
