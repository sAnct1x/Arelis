"""Kill stray Arelis UI, launch real ArelisWindow, checklist all instrument docks.

Pass criteria (automated):
  - each dock: float → opaque void chrome → redock
  - WA_TranslucentBackground OFF while floating (opaque plate — no chat bleed)
  - fill_alpha sealed (~255) while floating
  - frameless + in-panel FloatingDockTitleBar while floating
  - shell margins zero while floating
  - no QGraphicsOpacityEffect on floating docks
  - sanitize force-redocks all floats (launch ghost path)

Also writes logs/verify_no_ghost_*.png for visual review.
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time

# Force a real Windows surface.
os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ.pop("ARELIS_ALLOW_OFFSCREEN", None)

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QDockWidget, QWidget

from arelis.config import PROJECT_ROOT, load_config
from arelis.core.bus import EventBus
from arelis.core.events import Event
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.llm import build_router
from arelis.memory import DEFAULT_EMBED_MODEL, MemoryIndexer, MemoryStore
from arelis.tools import build_tool_registry
from arelis.ui.app import (
    ArelisWindow,
    BusBridge,
    _apply_floating_dock_chrome,
    _glassify_floating_dock,
)
from arelis.ui.chrome import FloatingDockTitleBar
from arelis.ui.theme import app_font, load_fonts, stylesheet
from arelis.workspace import WorkspaceRoots, compose_stt_initial_prompt

CHAT_MARK = "GHOSTCHECK_CHAT_MARKER_QQQ"
THINK_MARK = "GHOSTCHECK_THINK_MARKER_WWW"
_OUT = PROJECT_ROOT / "logs"


def _kill_arelis_ui() -> None:
    """Force-kill other Arelis UI processes (never this verifier)."""
    if sys.platform != "win32":
        return
    import subprocess

    self_pid = os.getpid()
    # Only the real UI entrypoint (`python -m arelis`), not arelis.ui.* helpers.
    ps = rf"""
$self = {self_pid}
Get-CimInstance Win32_Process | Where-Object {{
  $_.ProcessId -ne $self -and
  $_.Name -match '^(python|pythonw)\.exe$' -and
  $_.CommandLine -and
  (
    $_.CommandLine -match '-m arelis(\s|$)' -or
    $_.CommandLine -match 'arelis\\main\.py' -or
    $_.CommandLine -match 'scripts\\run_ui\.ps1'
  ) -and
  $_.CommandLine -notmatch '_verify_no_ghost' -and
  $_.CommandLine -notmatch '_smoke_floating_dock'
}} | ForEach-Object {{
  try {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; "killed $($_.ProcessId)" }}
  catch {{ "skip $($_.ProcessId)" }}
}}
"""
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        check=False,
        capture_output=True,
        text=True,
    )
    out = (completed.stdout or "").strip()
    if out:
        print(out, flush=True)


def _glass_host(dock: QDockWidget) -> QWidget | None:
    shell = dock.widget()
    if shell is None:
        return None
    for child in shell.findChildren(QWidget):
        if child.objectName() == "GlassDockContent":
            return child
    return None


def _check_floating(dock: QDockWidget, errors: list[str], *, tag: str) -> None:
    name = dock.objectName() or tag
    if not dock.isFloating():
        errors.append(f"{name}: not floating")
    if not dock.isVisible():
        errors.append(f"{name}: not visible while floating")
    if dock.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
        errors.append(f"{name}: WA_TranslucentBackground still on (ghost path)")
    if dock.graphicsEffect() is not None:
        errors.append(f"{name}: graphics opacity effect while floating")
    if not (dock.windowFlags() & Qt.WindowType.FramelessWindowHint):
        errors.append(f"{name}: missing FramelessWindowHint")
    tw = dock.titleBarWidget()
    if tw is None or tw.maximumHeight() != 0:
        errors.append(f"{name}: expected zero-height title stub while floating")
    shell = dock.widget()
    if shell is not None and shell.layout() is not None:
        m = shell.layout().contentsMargins()
        if m.left() or m.top() or m.right() or m.bottom():
            errors.append(
                f"{name}: floating shell gutters not zero: "
                f"{m.left()},{m.top()},{m.right()},{m.bottom()}"
            )
    host = _glass_host(dock)
    if host is None:
        errors.append(f"{name}: GlassDockContent missing")
    else:
        fill = int(getattr(host, "_fill_alpha", 0))
        if fill < 240:
            errors.append(f"{name}: fill_alpha={fill} too low (chat can bleed)")
        chrome = [c for c in host.findChildren(FloatingDockTitleBar) if c.isVisible()]
        if not chrome:
            errors.append(f"{name}: FloatingDockTitleBar not visible")
        docked_title = getattr(host, "title_label", None)
        if docked_title is not None and docked_title.isVisible():
            errors.append(f"{name}: docked title still visible while floating")
    print(
        f"INFO[{name}]: floating={dock.isFloating()} visible={dock.isVisible()} "
        f"translucent={dock.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)} "
        f"frameless={bool(dock.windowFlags() & Qt.WindowType.FramelessWindowHint)} "
        f"mode=opaque fill_alpha={getattr(host, '_fill_alpha', '?') if host else '?'}",
        flush=True,
    )


def _float_over_chat(window: ArelisWindow, dock: QDockWidget, app: QApplication) -> None:
    dock.show()
    dock.setFloating(True)
    app.processEvents()
    _apply_floating_dock_chrome(dock, True)
    _glassify_floating_dock(dock)
    chat_geo = window.conversation.frameGeometry()
    top_left = window.mapToGlobal(chat_geo.topLeft())
    dock.move(top_left.x() + 40, top_left.y() + 40)
    dock.resize(420, 520)
    dock.show()
    dock.raise_()
    app.processEvents()


def main() -> int:
    print("verify: killing leftover Arelis UI…", flush=True)
    _kill_arelis_ui()
    time.sleep(0.6)
    print("verify: building window…", flush=True)

    config = load_config()
    workspace = WorkspaceRoots.from_config(config)
    config["_workspace"] = workspace
    stt_cfg = config.setdefault("voice", {}).setdefault("stt", {})
    stt_cfg["initial_prompt"] = compose_stt_initial_prompt(config, workspace)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Arelis")
    app.setQuitOnLastWindowClosed(True)
    families = load_fonts()
    app.setFont(app_font(families))
    app.setStyleSheet(stylesheet())

    bus = EventBus()
    bridge = BusBridge()

    async def mirror(event: Event) -> None:
        bridge.feed(event)

    bus.subscribe(None, mirror)

    router = build_router(config)
    store = MemoryStore()
    store.start_session()
    tools = build_tool_registry(
        config, workspace, memory_store=store, provider=router.provider, router=router
    )
    memory = SessionMemory(sink=store)
    Orchestrator(bus, router, tools, config, memory, workspace=workspace)

    from arelis.voice import VoiceService

    voice = VoiceService(bus, config)
    indexer = MemoryIndexer(
        store,
        router.provider,
        model=str((config.get("memory") or {}).get("embed_model") or DEFAULT_EMBED_MODEL),
        workspace=workspace,
        index_docs=False,
        index_mail=False,
    )

    loop = asyncio.new_event_loop()

    def loop_thread() -> None:
        asyncio.set_event_loop(loop)
        bus_task = loop.create_task(bus.run())
        loop.bus_task = bus_task  # type: ignore[attr-defined]
        loop.run_forever()

    threading.Thread(target=loop_thread, name="arelis-verify-asyncio", daemon=True).start()

    window = ArelisWindow(
        config,
        bridge,
        loop,
        bus,
        voice,
        store=store,
        restore_session_id=None,
        indexer=indexer,
        router=router,
    )
    # Deterministic layout: chat + instruments visible, no saved float ghosts.
    for dock in (
        window.think_dock,
        window.work_dock,
        window.history_dock,
        window.camera_dock,
    ):
        dock.setFloating(False)
        dock.show()

    # Stamp unique markers into chat vs thinking.
    window.chat.add_user(CHAT_MARK)
    window.chat.begin_assistant()
    window.chat.finish_assistant(
        f"DALL-E Stable Diffusion puppy image instructions. {CHAT_MARK}"
    )
    window.thinking.clear()
    window.thinking.append(THINK_MARK, kind="status")
    window.thinking.append("Speech model ready.", kind="status")

    window.resize(1280, 800)
    window.show()
    window.raise_()
    app.processEvents()

    result: dict = {"ok": False, "errors": []}

    docks: list[tuple[str, QDockWidget]] = [
        ("thinking", window.think_dock),
        ("workspace", window.work_dock),
        ("history", window.history_dock),
        ("camera", window.camera_dock),
    ]

    def _run_checklist() -> None:
        errors: list[str] = []
        _OUT.mkdir(parents=True, exist_ok=True)

        # 1) Undock / seal / redock each instrument over chat.
        for tag, dock in docks:
            _float_over_chat(window, dock, app)
            app.processEvents()
            _check_floating(dock, errors, tag=tag)

            if tag == "thinking":
                main_pix = window.grab()
                dock_pix = dock.grab()
                main_path = _OUT / "verify_no_ghost_main.png"
                dock_path = _OUT / "verify_no_ghost_float.png"
                both_path = _OUT / "verify_no_ghost_screen.png"
                main_pix.save(str(main_path))
                dock_pix.save(str(dock_path))
                screen = QGuiApplication.primaryScreen()
                if screen is not None:
                    fg = dock.frameGeometry()
                    frame = screen.grabWindow(0, fg.x(), fg.y(), fg.width(), fg.height())
                    frame.save(str(both_path))
                    print(f"SHOT_FRAME: {both_path} {frame.width()}x{frame.height()}")
                print(f"SHOT_MAIN: {main_path} {main_pix.width()}x{main_pix.height()}")
                print(f"SHOT_FLOAT: {dock_path} {dock_pix.width()}x{dock_pix.height()}")

            dock.setFloating(False)
            app.processEvents()
            _apply_floating_dock_chrome(dock, False)
            if dock.isFloating():
                errors.append(f"{dock.objectName() or tag}: failed to redock")
            print(
                f"INFO[{dock.objectName() or tag}]: redocked floating={dock.isFloating()} "
                f"visible={dock.isVisible()}",
                flush=True,
            )

        # 2) Float all four, then sanitize (launch ghost path).
        for _, dock in docks:
            _float_over_chat(window, dock, app)
        still_floating = [d.objectName() for _, d in docks if d.isFloating()]
        if len(still_floating) != 4:
            errors.append(f"expected 4 floats before sanitize, got {still_floating}")
        window._sanitize_floating_docks()
        app.processEvents()
        for tag, dock in docks:
            if dock.isFloating():
                errors.append(f"{dock.objectName() or tag}: still floating after sanitize")
            else:
                print(f"INFO[{dock.objectName() or tag}]: sanitize redocked ok", flush=True)

        result["errors"] = errors
        result["ok"] = not errors
        app.quit()

    QTimer.singleShot(400, _run_checklist)
    app.exec()

    # Tear down asyncio loop.
    try:
        loop.call_soon_threadsafe(loop.stop)
    except Exception:
        pass

    if result["ok"]:
        print("PASS: void float verify (all docks)", flush=True)
        return 0
    for err in result["errors"]:
        print(f"FAIL: {err}", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
