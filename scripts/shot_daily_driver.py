"""Screenshot + video pass of the daily-driver surfaces Phase 5–7 touched.

Opens the real glass (not offscreen), walks idle /tools, Settings models,
Allow, history search, workspace, hung countdown, confirm cards, Drive.
Writes PNGs and a walk video under outputs/daily_driver_pass/.

Does not enter Earth. Isolated ARELIS_DATA_DIR so this does not write
into the live profile.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_DATA = Path(tempfile.mkdtemp(prefix="arelis-shot-")).resolve()
os.environ["ARELIS_DATA_DIR"] = str(_DATA)
os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.pop("ARELIS_ALLOW_OFFSCREEN", None)
os.environ["ARELIS_SOLAR_GL"] = "0"

OUT = ROOT / "outputs" / "daily_driver_pass"
FRAME_W = 1280
FRAME_H = 800
HOLD_S = 1.4


def _pump(app: Any, ms: int = 80) -> None:
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < ms:
        app.processEvents()
        time.sleep(0.01)


def _grab(top: Any, dest: Path) -> Path:
    from PySide6.QtGui import QGuiApplication

    dest.parent.mkdir(parents=True, exist_ok=True)
    top.show()
    top.raise_()
    top.activateWindow()
    app = QGuiApplication.instance()
    _pump(app or top, 160)
    # Widget grab, not grabWindow(0). The desktop grab paints whatever is
    # behind a translucent HWND — last pass was this Cursor chat, not her.
    pix = top.grab()
    if pix.isNull() or pix.width() < 40:
        screen = top.screen() or (app.primaryScreen() if app is not None else None)
        if screen is not None:
            pix = screen.grabWindow(int(top.winId()))
    pix.save(str(dest), "PNG")
    print(
        f"  shot {dest.name}  {pix.width()}x{pix.height()}  {dest.stat().st_size} bytes", flush=True
    )
    return dest


def _composite_popup(dialog: Any, combo: Any, dest: Path) -> Path:
    """Dialog grab plus the open combo list, because the popup is its own HWND."""
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtWidgets import QAbstractItemView, QApplication

    combo.showPopup()
    _pump(QApplication.instance() or dialog, 180)
    plate = dialog.grab()
    view = combo.view()
    if view is None:
        combo.hidePopup()
        plate.save(str(dest), "PNG")
        print(f"  shot {dest.name}  {plate.width()}x{plate.height()}  (no popup)", flush=True)
        return dest
    popup: Any = view.window() if isinstance(view, QAbstractItemView) else view
    extra = popup.grab() if popup is not None else view.grab()
    combo.hidePopup()
    _pump(QApplication.instance() or dialog, 80)
    if extra.isNull() or extra.width() < 8:
        plate.save(str(dest), "PNG")
        print(f"  shot {dest.name}  {plate.width()}x{plate.height()}  (empty popup)", flush=True)
        return dest
    # Drop the list just under the Chat combo.
    origin = combo.mapTo(dialog, combo.rect().bottomLeft())
    out_w = max(plate.width(), origin.x() + extra.width() + 12)
    out_h = max(plate.height(), origin.y() + extra.height() + 12)
    canvas = QPixmap(out_w, out_h)
    canvas.fill(plate.toImage().pixelColor(2, 2))
    painter = QPainter(canvas)
    painter.drawPixmap(0, 0, plate)
    painter.drawPixmap(origin.x(), origin.y(), extra)
    painter.end()
    canvas.save(str(dest), "PNG")
    print(
        f"  shot {dest.name}  {canvas.width()}x{canvas.height()}  "
        f"{dest.stat().st_size} bytes  (picker open)",
        flush=True,
    )
    return dest


def _letterbox(path: Path, width: int, height: int) -> Any:
    from PIL import Image

    src = Image.open(path).convert("RGB")
    canvas = Image.new("RGB", (width, height), (10, 4, 2))
    scale = min(width / src.width, height / src.height)
    nw = max(1, int(src.width * scale))
    nh = max(1, int(src.height * scale))
    fitted = src.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas.paste(fitted, ((width - nw) // 2, (height - nh) // 2))
    return canvas


def _find_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            return exe
    except Exception:
        return None
    return None


def _stitch_avi(frames: list[Path], dest: Path) -> Path:
    """MJPEG AVI so the walk is a real video even when ffmpeg is missing."""
    from io import BytesIO

    dest.parent.mkdir(parents=True, exist_ok=True)
    fps = 5
    hold = max(1, round(HOLD_S * fps))
    blobs: list[bytes] = []
    for frame in frames:
        buf = BytesIO()
        _letterbox(frame, FRAME_W, FRAME_H).save(buf, format="JPEG", quality=90)
        blobs.extend([buf.getvalue()] * hold)
    # Repeat the last still so the concat duration includes the final hold.
    if blobs:
        blobs.append(blobs[-1])

    n = len(blobs)
    # 56-byte avih + 4-byte list size later; build movi first so offsets are known.
    movi = bytearray(b"movi")
    offsets: list[int] = []
    sizes: list[int] = []
    for jpeg in blobs:
        pad = jpeg + (b"\x00" if len(jpeg) % 2 else b"")
        offsets.append(len(movi))
        sizes.append(len(jpeg))
        movi += b"00dc" + struct.pack("<I", len(jpeg)) + pad

    frames_per_sec = fps
    usec = int(1_000_000 / frames_per_sec)
    avih = struct.pack(
        "<14I",
        usec,
        FRAME_W * FRAME_H * 3 * frames_per_sec,
        0,
        0x10,  # AVIF_HASINDEX
        n,
        0,
        1,
        0,
        FRAME_W,
        FRAME_H,
        0,
        0,
        0,
        0,
    )
    strh = struct.pack(
        "<4s4sIHH8I4H",
        b"vids",
        b"MJPG",
        0,
        0,
        0,
        0,
        1,
        frames_per_sec,
        0,
        n,
        0,
        0xFFFFFFFF,
        0,
        0,
        0,
        FRAME_W,
        FRAME_H,
    )
    # BITMAPINFOHEADER
    strf = struct.pack(
        "<IiiHHIIiiII",
        40,
        FRAME_W,
        FRAME_H,
        1,
        24,
        0x47504A4D,  # MJPG
        FRAME_W * FRAME_H * 3,
        0,
        0,
        0,
        0,
    )
    strl = b"strl" + b"strh" + struct.pack("<I", len(strh)) + strh
    strl += b"strf" + struct.pack("<I", len(strf)) + strf
    hdrl = (
        b"hdrl"
        + b"avih"
        + struct.pack("<I", len(avih))
        + avih
        + b"LIST"
        + struct.pack("<I", len(strl))
        + strl
    )
    idx = bytearray(b"idx1")
    idx_body = bytearray()
    for off, size in zip(offsets, sizes, strict=True):
        idx_body += struct.pack("<4sIII", b"00dc", 0x10, off, size)
    idx += struct.pack("<I", len(idx_body)) + idx_body

    riff_body = (
        b"AVI "
        + b"LIST"
        + struct.pack("<I", len(hdrl))
        + hdrl
        + b"LIST"
        + struct.pack("<I", len(movi))
        + bytes(movi)
        + bytes(idx)
    )
    dest.write_bytes(b"RIFF" + struct.pack("<I", len(riff_body)) + riff_body)
    print(f"  video {dest}  {dest.stat().st_size} bytes  (mjpeg avi)", flush=True)
    return dest


def _stage_letterboxed(frames: list[Path], dest_dir: Path) -> list[Path]:
    staged_dir = dest_dir / "_staged"
    if staged_dir.exists():
        shutil.rmtree(staged_dir, ignore_errors=True)
    staged_dir.mkdir(parents=True, exist_ok=True)
    staged: list[Path] = []
    for i, frame in enumerate(frames):
        out = staged_dir / f"{i:02d}.png"
        _letterbox(frame, FRAME_W, FRAME_H).save(out)
        staged.append(out)
    return staged


def _stitch_ffmpeg(ffmpeg: str, frames: list[Path], dest: Path) -> Path | None:
    even = _stage_letterboxed(frames, dest.parent)
    list_file = dest.parent / "frames.txt"
    lines = []
    for frame in even:
        lines.append(f"file '{frame.resolve().as_posix()}'")
        lines.append(f"duration {HOLD_S}")
    lines.append(f"file '{even[-1].resolve().as_posix()}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-pix_fmt",
        "yuv420p",
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print((result.stderr or result.stdout)[-800:], flush=True)
        return None
    print(f"  video {dest}  {dest.stat().st_size} bytes", flush=True)
    return dest


def _stitch_video(frames: list[Path], dest: Path) -> Path | None:
    if not frames:
        return None
    ffmpeg = _find_ffmpeg()
    if ffmpeg is not None:
        made = _stitch_ffmpeg(ffmpeg, frames, dest)
        if made is not None:
            return made
        print("  ffmpeg failed — falling back to mjpeg avi", flush=True)
    return _stitch_avi(frames, dest.with_suffix(".avi"))


def _settings(config: dict[str, Any], tab: str, list_models: Any) -> Any:
    from arelis.ui.settings_dialog import SettingsDialog

    dlg = SettingsDialog(config, initial_tab=tab, list_models=list_models)
    dlg.show()
    return dlg


def main() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from arelis.core.bus import EventBus
    from arelis.core.compact_prompt import format_tool_catalog
    from arelis.ui.app import ArelisWindow, BusBridge
    from arelis.ui.idle_host import refresh_idle_face, sync_idle_mode
    from arelis.ui.launch import force_windows_qt_platform
    from arelis.ui.theme import app_font, apply_theme, load_fonts, stylesheet, theme_from_config
    from arelis.ui.turn_watchdog import arm_hung_turn, disarm_hung_turn, paint_hung_countdown
    from arelis.ui.window_docks import toggle_history, toggle_workspace
    from arelis.ui.window_resize import configure_native_windows

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    for old in OUT.glob("walk.*"):
        old.unlink()

    force_windows_qt_platform(os.environ)
    configure_native_windows()
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme("sodium")
    app.setFont(app_font(load_fonts()))
    app.setStyleSheet(stylesheet())

    config = {
        "ui": {"default_width": FRAME_W, "default_height": FRAME_H, "hung_turn_s": 90},
        "router": {"default_role": "fast"},
        "voice": {"enabled": False},
        "models": {
            "fast": "qwen3.5:9b",
            "research": "qwen3.5:9b",
            "vision": "qwen2.5vl:3b",
        },
        "workspace": {"named_roots": [{"name": "arelis", "path": str(ROOT), "read_only": False}]},
        "tools": {"sms": {"inbound": {"ingest": {}}}},
        "agent": {},
    }
    apply_theme(theme_from_config(config))

    window = ArelisWindow(config, BusBridge(), asyncio.new_event_loop(), EventBus())
    window.resize(FRAME_W, FRAME_H)
    window.show()
    window.raise_()
    window.activateWindow()
    window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
    _pump(app, 400)
    sync_idle_mode(window)
    refresh_idle_face(window)
    window.chat.empty._layout_idle()
    _pump(app, 200)

    frames: list[Path] = []

    def tags() -> list[str]:
        return ["qwen3.5:9b", "llama3:8b", "qwen2.5vl:3b"]

    def shot(name: str, widget: Any | None = None) -> Path:
        dest = OUT / f"{name}.png"
        _grab(widget or window, dest)
        frames.append(dest)
        return dest

    shot("01_idle_tools_chip")

    catalog = format_tool_catalog()
    window.chat.add_system(catalog)
    window.conversation.set_idle_mode(False)
    window.conversation.input.setText("/tools")
    _pump(app, 200)
    shot("02_tools_catalog")

    dlg = _settings(config, "window", tags)
    _pump(app, 250)
    picker = OUT / "03_settings_models.png"
    _composite_popup(dlg, dlg.fast_model, picker)
    frames.append(picker)
    dlg.close()

    dlg = _settings(config, "allow", tags)
    _pump(app, 250)
    shot("04_settings_allow", dlg)
    dlg.close()

    toggle_history(window, True)
    window.history.search.setText("thursday")
    _pump(app, 200)
    shot("05_history_search")

    toggle_workspace(window, True)
    _pump(app, 200)
    shot("06_workspace")

    window._turn_busy = True
    window.conversation.set_busy(True)
    window.chat.show_progress("working")
    arm_hung_turn(window)
    paint_hung_countdown(window)
    _pump(app, 200)
    shot("07_hung_countdown")
    window._turn_busy = False
    window.conversation.set_busy(False)
    disarm_hung_turn(window)
    window.chat.clear_progress()

    window.chat.clear()
    window.conversation.set_idle_mode(False)
    window.chat.add_user("write a research report on prefix caching")
    window.conversation.confirm.ask(
        "shot-report",
        "research_report",
        "write a research report",
        detail="Question: how does prefix caching work\nSaved under outputs/research/",
        persist_ok=True,
        persist_label="don't ask again about files",
        headline="write a research report",
    )
    _pump(app, 200)
    shot("08_confirm_research_report")
    window.conversation.confirm.dismiss()

    window.chat.clear()
    window.conversation.set_idle_mode(False)
    window.chat.add_user("use the webcam")
    window.conversation.confirm.ask(
        "shot-cam",
        "camera",
        "use the webcam",
        persist_ok=True,
        persist_label="don't ask again about seeing",
        headline="use the webcam",
    )
    _pump(app, 200)
    shot("09_confirm_camera")
    window.conversation.confirm.dismiss()

    window.chat.clear()
    window.conversation.set_idle_mode(False)
    window.chat.add_user("open the docs and read the page")
    window.conversation.set_drive(True, "reading the page")
    _pump(app, 200)
    shot("10_drive_strip")
    window.conversation.set_drive(False)

    window.chat.clear()
    window.conversation.set_idle_mode(False)
    window.chat.add_user("remind me in 20 minutes")
    window.chat.finish_assistant("I'll remind you in 20 minutes.")
    window.conversation.input.setText("")
    _pump(app, 250)
    shot("11_composer_and_export")

    video = _stitch_video(frames, OUT / "walk.mp4")
    report = [
        f"frames: {len(frames)}",
        f"dir: {OUT}",
        f"video: {video or 'none'}",
        "",
        *[p.name for p in frames],
    ]
    (OUT / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report), flush=True)
    window.hide()
    shutil.rmtree(_DATA, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
