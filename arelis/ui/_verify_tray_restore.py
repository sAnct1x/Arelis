"""Hide the glass to the tray, restore it, and measure what is on screen.

"Two Arelises stacked on top of each other" has three possible causes and the
fix for one does nothing for the others, so all three are measured:

  - how many visible top-level windows this process owns, at every phase. A
    floating dock is its own top-level window, and one that stays behind when
    the glass goes to the tray *is* a second Arelis on screen — no compositing
    involved. That is what this counts.
  - what the window comes back as. Restoring a maximized glass at its
    restored-down size leaves the full-screen frame Windows kept underneath the
    smaller one for as long as the resize takes.
  - whether the pixels settle, via screenshots either side of the restore.

Writes logs/verify_tray_restore_*.png so the frames can be looked at as well as
counted.

Scenarios: --maximized, --docks, --float, --quit (tray Quit instead of restore).
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading

os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ.pop("ARELIS_ALLOW_OFFSCREEN", None)

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from arelis.config import load_config
from arelis.core.bus import EventBus
from arelis.core.events import Event
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.llm import build_router
from arelis.memory import DEFAULT_EMBED_MODEL, MemoryIndexer, MemoryStore
from arelis.paths import logs_dir
from arelis.tools import build_tool_registry
from arelis.ui.app import ArelisWindow, BusBridge
from arelis.ui.theme import app_font, load_fonts, stylesheet
from arelis.workspace import WorkspaceRoots, compose_stt_initial_prompt

_OUT = logs_dir()


def _visible_top_levels() -> list[tuple[int, str, str]]:
    """(hwnd, class, title) for every visible top-level window of this process."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[tuple[int, str, str]] = []
    me = os.getpid()

    proc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
    )

    def _visit(hwnd: int, _param: int) -> bool:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) != me or not user32.IsWindowVisible(hwnd):
            return True
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        klass = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, klass, 256)
        found.append((int(hwnd), klass.value, title.value))
        return True

    user32.EnumWindows(proc(_visit), 0)
    return found


def _grab(tag: str) -> str:
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return ""
    _OUT.mkdir(parents=True, exist_ok=True)
    path = _OUT / f"verify_tray_restore_{tag}.png"
    screen.grabWindow(0).save(str(path))
    return str(path)


def main() -> int:
    config = load_config()
    workspace = WorkspaceRoots.from_config(config)
    config["_workspace"] = workspace
    stt = config.setdefault("voice", {}).setdefault("stt", {})
    stt["initial_prompt"] = compose_stt_initial_prompt(config, workspace)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Arelis")
    app.setQuitOnLastWindowClosed(False)
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
    Orchestrator(bus, router, tools, config, SessionMemory(sink=store), workspace=workspace)
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
        loop.bus_task = loop.create_task(bus.run())  # type: ignore[attr-defined]
        loop.run_forever()

    threading.Thread(target=loop_thread, name="arelis-restore-asyncio", daemon=True).start()

    window = ArelisWindow(
        config, bridge, loop, bus, voice, store=store, restore_session_id=None, indexer=indexer,
        router=router,
    )
    window.chat.add_user("TRAY RESTORE CHECK")
    window.chat.begin_assistant()
    window.chat.finish_assistant("Restore me without leaving a second copy behind.")
    window.resize(1280, 800)
    window.move(120, 90)
    # Without this the close-to-tray branch of closeEvent is unreachable and the
    # window takes the quit path instead, which is a different measurement.
    window.setup_tray(app)
    maximized = "--maximized" in sys.argv
    if "--docks" in sys.argv:
        for dock in (window.think_dock, window.work_dock, window.history_dock):
            dock.setFloating(False)
            dock.show()
    quit_scenario = "--quit" in sys.argv or "--quitbare" in sys.argv
    floated = "--float" in sys.argv
    if floated:
        from arelis.ui.app import _apply_floating_dock_chrome, _glassify_floating_dock

        window.think_dock.show()
        window.think_dock.setFloating(True)
        app.processEvents()
        _apply_floating_dock_chrome(window.think_dock, True)
        _glassify_floating_dock(window.think_dock)
        window.think_dock.move(1500, 300)
        window.think_dock.resize(420, 520)
        window.think_dock.show()
    if maximized:
        window.showMaximized()
    else:
        window.show()
    window.raise_()
    window.activateWindow()

    report: dict[str, object] = {"scenario": "maximized" if maximized else "normal"}

    def _float_state() -> tuple[bool, bool, bool, tuple[int, int, int, int]]:
        dock = window.think_dock
        return (
            dock.isVisible(),
            dock.isFloating(),
            dock.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground),
            dock.geometry().getRect(),
        )

    def step(name: str) -> None:
        print(f"step: {name}", flush=True)

    def emit() -> None:
        report["code"] = _report(report, quit_scenario=quit_scenario, floated=floated)

    def step_bare_quit() -> None:
        # What the self-updater does: QApplication.quit() with everything still
        # on screen. The installer is waiting for this process to release its
        # files, so an event loop that declines to unwind here is an update that
        # never happens.
        step("bare_quit")
        report["before"] = _visible_top_levels()
        report["before_float"] = _float_state()
        report["hidden"] = []
        report["hidden_float"] = (False, True, False, (0, 0, 0, 0))
        emit()
        QApplication.quit()

    def step_before() -> None:
        step("before")
        report["before"] = _visible_top_levels()
        report["before_maximized"] = window.isMaximized()
        report["before_geometry"] = window.geometry().getRect()
        report["before_float"] = _float_state()
        report["shot_before"] = _grab("1_before")
        window.close()
        QTimer.singleShot(700, step_hidden)

    def step_hidden() -> None:
        step("hidden")
        report["hidden"] = _visible_top_levels()
        report["hidden_float"] = _float_state()
        report["shot_hidden"] = _grab("2_hidden")
        if quit_scenario:
            emit()
            window.quit_from_tray()
            return
        window.show_from_tray()
        QTimer.singleShot(0, step_restored_immediate)

    def step_restored_immediate() -> None:
        step("restored_immediate")
        report["shot_restore_0ms"] = _grab("3_restore_0ms")
        QTimer.singleShot(60, step_restored_early)

    def step_restored_early() -> None:
        step("restored_early")
        report["restored"] = _visible_top_levels()
        report["restored_maximized"] = window.isMaximized()
        report["restored_geometry"] = window.geometry().getRect()
        report["shot_restore_60ms"] = _grab("4_restore_60ms")
        QTimer.singleShot(900, step_settled)

    def step_settled() -> None:
        step("settled")
        report["settled"] = _visible_top_levels()
        report["settled_maximized"] = window.isMaximized()
        report["settled_geometry"] = window.geometry().getRect()
        report["settled_float"] = _float_state()
        report["shot_settled"] = _grab("5_settled")
        # Reported from inside the event loop rather than after app.exec()
        # returns, because whether it returns is itself one of the things under
        # test and a measurement that cannot be printed is not a measurement.
        emit()
        app.quit()

    # A wedged compositor or a synchronous repaint that never returns would
    # otherwise leave a translucent harness window on the owner's desktop that
    # looks exactly like the defect being investigated. os._exit rather than
    # app.quit: the point is to survive an event loop that has stopped running.
    def watchdog() -> None:
        print("WEDGED: the Qt event loop did not finish on its own", flush=True)
        sys.stdout.flush()
        os._exit(3)

    alarm = threading.Timer(25.0, watchdog)
    alarm.daemon = True
    alarm.start()

    QTimer.singleShot(2500, step_bare_quit if "--quitbare" in sys.argv else step_before)
    app.exec()
    alarm.cancel()

    try:
        loop.call_soon_threadsafe(loop.stop)
    except Exception:
        pass
    print("exec: app.exec() returned", flush=True)
    return int(report.get("code", 1))  # type: ignore[arg-type]


def _report(report: dict[str, object], *, quit_scenario: bool, floated: bool) -> int:
    print(f"scenario: {report.get('scenario')}", flush=True)
    for phase in ("before", "hidden", "restored", "settled"):
        wins = report.get(phase)
        if wins is None:
            continue
        print(f"{phase}: {len(wins)} visible top-level window(s)", flush=True)  # type: ignore[arg-type]
        for hwnd, klass, title in wins:  # type: ignore[misc]
            print(f"    hwnd=0x{hwnd:X} class={klass} title={title!r}", flush=True)
    if quit_scenario:
        print(f"before_float : {report.get('before_float')}", flush=True)
        print(f"hidden_float : {report.get('hidden_float')}", flush=True)
        hidden = report.get("hidden") or []
        if hidden:
            print(
                f"FAIL: {len(hidden)} window(s) still on screen after close-to-tray",
                flush=True,
            )
            return 1
        print("PASS: tray Quit left nothing on screen", flush=True)
        return 0
    for phase in ("before", "restored", "settled"):
        print(
            f"{phase}: maximized={report.get(phase + '_maximized')} "
            f"geometry={report.get(phase + '_geometry')}",
            flush=True,
        )
    for key, value in report.items():
        if key.startswith("shot_"):
            print(f"{key}: {value}", flush=True)
    errors: list[str] = []
    before = len(report.get("before") or [])  # type: ignore[arg-type]
    settled = len(report.get("settled") or [])  # type: ignore[arg-type]
    if not before or settled != before:
        errors.append(f"{before} window(s) before hide, {settled} after restore")
    if report.get("before_maximized") != report.get("settled_maximized"):
        errors.append(
            f"maximized {report.get('before_maximized')} -> {report.get('settled_maximized')}"
        )
    if report.get("before_geometry") != report.get("settled_geometry"):
        errors.append(
            f"geometry {report.get('before_geometry')} -> {report.get('settled_geometry')}"
        )
    if floated:
        print(f"before_float : {report.get('before_float')}", flush=True)
        print(f"hidden_float : {report.get('hidden_float')}", flush=True)
        print(f"settled_float: {report.get('settled_float')}", flush=True)
        hidden_visible, *_ = report.get("hidden_float")  # type: ignore[misc]
        if hidden_visible:
            errors.append("floating dock still on screen with the glass in the tray")
        if report.get("before_float") != report.get("settled_float"):
            errors.append(
                f"floating dock {report.get('before_float')} -> {report.get('settled_float')}"
            )
    if not errors:
        print("PASS: restore came back as the same window in the same place", flush=True)
        return 0
    for err in errors:
        print(f"FAIL: {err}", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
