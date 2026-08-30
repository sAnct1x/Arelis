"""Glass process launch. ArelisWindow stays in app.py; this is the seat around it."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
from collections.abc import MutableMapping
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from arelis.config import load_config
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.llm import prefix_warmup_for, run_auto_lessons, run_model_preflight, run_model_warmup
from arelis.mail import load_account
from arelis.memory import DEFAULT_EMBED_MODEL, MemoryIndexer
from arelis.paths import app_icon_path, logs_dir
from arelis.presence.confirm_persist import ConfirmPersister
from arelis.presence.inbound_runtime import InboundRuntime, attach_inbound
from arelis.presence.ipc_client import IpcClient
from arelis.presence.ipc_server import IpcServer
from arelis.presence.lock import external_core_available
from arelis.ui.first_run import prompt_for_workspace_root
from arelis.ui.setup_wizard import prompt_for_model_setup
from arelis.ui.theme import app_font, load_fonts, qt_font_directory, stylesheet
from arelis.ui.window_resize import configure_native_windows
from arelis.voice import VoiceService
from arelis.workspace import WorkspaceRoots

log = logging.getLogger(__name__)

def force_windows_qt_platform(env: MutableMapping[str, str]) -> None:
    """Insist on the real Windows Qt backend, whatever the environment says.

    A stray QT_QPA_PLATFORM is a process that starts, runs, logs normally and
    never shows a window — the worst shape a failure can take, because there is
    nothing to look at while you work out why. offscreen is the value that
    actually gets set by accident, exported by a test run and inherited by the
    next launch from the same shell, but minimal and vnc go wrong identically.

    This used to be run_ui.ps1's job, and it no longer has one: the desktop
    shortcut points straight at pythonw.exe so that no console is ever created
    for a shell to hide, which means there is no shell left to clear the variable
    before Python starts.

    ARELIS_ALLOW_OFFSCREEN is the way out, for headless checks that mean it.
    """
    if sys.platform != "win32":
        return
    if env.get("ARELIS_ALLOW_OFFSCREEN"):
        return
    if env.get("QT_QPA_PLATFORM", "windows").lower() != "windows":
        env["QT_QPA_PLATFORM"] = "windows"


async def _drain_event_loop(
    loop: asyncio.AbstractEventLoop, *, budget_s: float
) -> None:
    """Stop what is still running before the loop is taken out from under it.

    Stopping the loop with work in flight is not free, whatever the exit code
    says. The visible symptom was tidy enough to ignore — "Task was destroyed but
    it is pending" for EventBus.run and MemoryIndexer.run_batch, then an
    "Indexed 3 workspace file(s)" line arriving two and a half seconds after quit
    had finished — but the second half of that is the part that matters. The
    indexer does its writing in ``asyncio.to_thread``, so cancelling the task
    only abandons the *await*: the worker thread carries on into memory.db while
    the interpreter is shutting down around it. A process exiting during a SQLite
    write is how an archive of every conversation someone has had becomes a file
    that no longer opens.

    So the order here is deliberate. Cancel first, so nothing new is started;
    wait for the cancellations to land, so tasks unwind through their own finally
    blocks; then wait on the default executor, which is the only way to know that
    the last statement has been written rather than merely that nobody is waiting
    for it. Async generators go last because closing them can await.

    Every wait is bounded. A shutdown that hangs is worse than one that leaves a
    warning in the log, and the caller passes a tighter ceiling for tray Quit
    than for an ordinary close.
    """
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks(loop) if t is not current and not t.done()]
    for task in pending:
        task.cancel()
    if pending:
        _done, still = await asyncio.wait(pending, timeout=budget_s)
        if still:
            log.info(
                "loop drain: %d task(s) did not stop within %.2fs", len(still), budget_s
            )
    # asyncio.wait rather than wait_for throughout, and that is the whole reason
    # the ceilings above are real. wait_for cancels what it is waiting on and then
    # waits for *that* to finish, so a task which swallows CancelledError — a bare
    # `except Exception` around an await is enough — turns the bound into a hang.
    # asyncio.wait just stops waiting.
    executor_stopped = asyncio.ensure_future(loop.shutdown_default_executor())
    _done, still = await asyncio.wait([executor_stopped], timeout=budget_s)
    if still:
        # Giving up here means the process may still exit with a write in flight,
        # which is the thing this function exists to prevent. It is the lesser
        # evil: a quit that never returns is a program the user has to kill, and
        # they will then be exiting mid-write anyway with no record of why.
        log.warning(
            "loop drain: background writes still running after %.2fs — exiting anyway",
            budget_s,
        )
    try:
        await loop.shutdown_asyncgens()
    except Exception:
        log.debug("loop drain: asyncgen shutdown failed", exc_info=True)


_HANDOFF_WAIT_S = 8.0
_HANDOFF_SLICE_S = 0.35
_HANDOFF_MAX_TRIES = 24


def _raise_running_instance(config: dict[str, Any]) -> int:
    """Second launch: put the Arelis that is already running back on screen.

    The UI lock is held, so this copy must not open a window — two glasses over
    one memory.db is not a thing anyone wants. But refusing quietly is worse than
    it sounds: the running instance is usually hidden in the tray, so the visible
    result of double-clicking Arelis was nothing at all, and the honest response
    to that is to click it again. Every launch/close/relaunch complaint about this
    program has started there.

    A held lock always means a living process. Windows releases both the named
    mutex and the byte lock when a process ends, however it ends, so there is no
    such thing here as a stale lock left by a crash — if the lock is held, someone
    is home. The wait-and-retry lives in ``_second_launch``; this function is the
    last-resort notice after that wait has already asked and the other copy still
    did not answer.
    """
    from arelis.presence.activate import activate_existing_ui
    from arelis.ui.dialog import notice

    if activate_existing_ui(config):
        log.info("second launch: asked the running Arelis to show itself")
        return 0
    # Held lock, no answer. Nothing here may kill the other process — it is the
    # one holding the conversation, the memory and possibly an unsent draft — so
    # say so and name where to look, which is the one outcome that is neither a
    # second window nor silence.
    log.warning("second launch: UI lock held but no Arelis answered on IPC")
    try:
        configure_native_windows()
        app = QApplication.instance() or QApplication([])
        app.setApplicationName("Arelis")
        icon_path = app_icon_path()
        if icon_path.is_file():
            app.setWindowIcon(QIcon(str(icon_path)))
        app.setFont(app_font(load_fonts()))
        app.setStyleSheet(stylesheet())
        notice(
            None,
            "Arelis is already running",
            "Arelis is already open, but it did not answer the request to come "
            "to the front.",
            detail=(
                "Look for the Arelis icon in the notification area — Windows "
                "often keeps it in the overflow behind the chevron — and choose "
                f"Open Arelis. If it is not responding at all, {logs_dir()}"
                "\\arelis.log has the last thing it did."
            ),
            warning=True,
        )
    except Exception:
        log.exception("second launch: could not show the already-running notice")
    return 1


def _second_launch(config: dict[str, Any], ui_lock: Any) -> int | None:
    """Ask the living glass to show, or wait for it to finish quitting.

    Returns an exit code if this process should stop, or None if it now holds
    the UI lock and should open a window. The gap this covers is Quit: IPC is
    already down, the lock is still held, and a shortcut click in that window
    used to either show the already-running dialog or (if the lock then dropped
    mid-click) open a second glass on top of the dying one.
    """
    from arelis.presence.activate import activate_existing_ui
    from arelis.presence.lock import lock_file_pid, pid_is_alive

    if activate_existing_ui(config):
        log.info("second launch: asked the running Arelis to show itself")
        return 0
    deadline = time.monotonic() + _HANDOFF_WAIT_S
    tries = 0
    while tries < _HANDOFF_MAX_TRIES and time.monotonic() < deadline:
        time.sleep(_HANDOFF_SLICE_S)
        tries += 1
        if activate_existing_ui(config):
            log.info("second launch: running Arelis answered on the retry")
            return 0
        if ui_lock.acquire():
            log.info("second launch: previous Arelis exited; this copy will open")
            return None
        path = getattr(ui_lock, "path", None)
        if path is not None:
            pid = lock_file_pid(path)
            if pid is not None and not pid_is_alive(pid) and ui_lock.acquire():
                log.info("second launch: lock holder is gone; this copy will open")
                return None
    return _raise_running_instance(config)


def run_ui(config: dict[str, Any] | None = None) -> int:
    # Before any QApplication — a native child HWND is the offset ghost, and
    # this attribute is what stops one winId() from promoting every sibling.
    configure_native_windows()
    # Remembered because first run may need to reload from disk, and a config
    # handed in by a caller (tests, harnesses) must not be silently replaced.
    config_was_given = config is not None
    config = config or load_config()
    # Single glass: a second launch raises the first rather than opening again.
    from arelis.presence.lock import PresenceLock, ui_lock_path

    ui_lock = PresenceLock(ui_lock_path(config))
    if not ui_lock.acquire():
        handed = _second_launch(config, ui_lock)
        if handed is not None:
            return handed

    _ui_lock_gate = threading.Lock()
    _ui_lock_out = False

    def _release_ui_lock() -> None:
        nonlocal _ui_lock_out
        with _ui_lock_gate:
            if _ui_lock_out:
                return
            _ui_lock_out = True
            ui_lock.release()

    def _bind_workspace(cfg: dict[str, Any]) -> WorkspaceRoots:
        from arelis.core.seat import bind_workspace

        return bind_workspace(cfg)

    workspace = _bind_workspace(config)
    force_windows_qt_platform(os.environ)
    from arelis.ui.solar_gl import prepare_desktop_gl

    prepare_desktop_gl(os.environ)
    os.environ.setdefault("QT_QPA_FONTDIR", str(qt_font_directory()))

    # A scheduled task holds the absolute path it was created with, so installing a
    # packaged build after running from a checkout leaves every job pointing at an
    # interpreter that has moved. Costs a small file read when nothing has changed.
    from arelis.jobs.schedule import repoint_moved_tasks_on_launch

    repoint_moved_tasks_on_launch()

    # Group taskbar buttons (python.exe vs pythonw.exe otherwise diverge).
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
                "Arelis.Desktop"
            )
        except Exception:
            pass

    configure_native_windows()
    from arelis.ui.solar_gl import gl_wanted

    if gl_wanted():
        QApplication.setAttribute(
            Qt.ApplicationAttribute.AA_UseDesktopOpenGL, True
        )
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Arelis")
    icon_path = app_icon_path()
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    families = load_fonts()
    app.setFont(app_font(families))
    app.setStyleSheet(stylesheet())

    # First run: ask which folder Arelis may work in. It happens here rather than
    # beside the other config work above because it needs a QApplication, and the
    # QApplication cannot be created until the font and platform environment is
    # set. Nothing between the two reads the workspace.
    # Returns None when the question has already been answered, which is every
    # launch after the first.
    if not config_was_given and prompt_for_workspace_root() is not None:
        config = load_config()
        workspace = _bind_workspace(config)
    if not config_was_given and prompt_for_model_setup() is not None:
        config = load_config()
        workspace = _bind_workspace(config)
    # Required so hiding the last window to the tray does not kill the process.
    presence_cfg_early = (config or {}).get("presence") or {}
    if bool(presence_cfg_early.get("close_to_tray", True)):
        app.setQuitOnLastWindowClosed(False)

    from arelis.ui.app import ArelisWindow, BusBridge

    bus = EventBus()
    bridge = BusBridge()

    async def mirror(event: Event) -> None:
        bridge.feed(event)

    bus.subscribe(None, mirror)
    from arelis.core.seat import build_seat

    # Cold glass launch is a new conversation. Jobs use profile="job"
    # (no sink). CLI restores the last thread.
    seat = build_seat(config, profile="ui", bus=bus)
    router = seat.router
    store = seat.store
    tools = seat.tools
    orchestrator = seat.orchestrator
    voice = VoiceService(bus, config)
    embed_model = str(
        (config.get("memory") or {}).get("embed_model") or DEFAULT_EMBED_MODEL
    )
    docs_cfg = (config.get("memory") or {}).get("docs") or {}
    mail_cfg = (config.get("memory") or {}).get("mail") or {}
    email_cfg = (config.get("tools") or {}).get("email") or {}
    mail_account = load_account() if mail_cfg.get("enabled", False) else None
    indexer = MemoryIndexer(
        store,
        router.provider,
        model=embed_model,
        workspace=workspace,
        index_docs=bool(docs_cfg.get("enabled", True)),
        max_file_bytes=int(docs_cfg.get("max_file_bytes", 524288)),
        chunk_chars=int(docs_cfg.get("chunk_chars", 1200)),
        chunk_overlap=int(docs_cfg.get("chunk_overlap", 200)),
        index_mail=bool(mail_cfg.get("enabled", False)),
        mail_account=mail_account,
        mail_host=str(email_cfg.get("imap_host", "imap.gmail.com")),
        mail_port=int(email_cfg.get("imap_port", 993)),
        mail_timeout_s=float(email_cfg.get("timeout_s", 30)),
        mail_max_messages=int(mail_cfg.get("max_messages", 40)),
        mail_retention_days=int(mail_cfg.get("retention_days", 30)),
        mail_max_body_chars=int(mail_cfg.get("max_body_chars", 4000)),
        mail_min_interval_s=float(mail_cfg.get("min_interval_s", 900)),
    )

    # Qt owns the main thread, so the whole async side (bus, orchestrator,
    # Ollama streaming, tools) runs on its own loop in a background thread.
    # Everything crossing back into Qt goes through BusBridge's signal, and
    # everything crossing out goes through run_coroutine_threadsafe. Touching
    # widgets directly from the async side would be a data race.
    loop = asyncio.new_event_loop()

    def loop_thread() -> None:
        asyncio.set_event_loop(loop)
        # Held in a local for the lifetime of the loop. A bare create_task is
        # only weakly referenced and can be collected while still running.
        bus_task = loop.create_task(bus.run())
        loop.bus_task = bus_task  # type: ignore[attr-defined]
        loop.run_forever()

    thread = threading.Thread(target=loop_thread, name="arelis-asyncio", daemon=True)
    thread.start()

    # Non-blocking for the window: a slow or absent Ollama must not delay
    # Qt. The first chat turn does wait — otherwise it races this warmup
    # and pays the prefix prefill twice.
    router.arm_warmup()

    async def _startup_models() -> None:
        try:
            await run_model_preflight(bus, router.provider, config.get("models"))
            await run_model_warmup(
                bus, router, prefix=prefix_warmup_for(config, tools)
            )
            agent_cfg = config.get("agent") or {}
            await run_auto_lessons(
                bus, enabled=bool(agent_cfg.get("auto_lessons", True))
            )
        finally:
            router.mark_warmup_done()

    asyncio.run_coroutine_threadsafe(_startup_models(), loop)

    try:
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
    except Exception:
        logging.getLogger(__name__).exception("Arelis window failed to start")
        _release_ui_lock()
        raise
    asyncio.run_coroutine_threadsafe(orchestrator.resume_last_room(), loop)
    # Inbound: by default the UI owns ingest. Close-to-tray keeps it alive when
    # the window hides; `arelis --core` can own ingest instead.
    presence_cfg = config.get("presence") or {}
    use_external = bool(presence_cfg.get("use_external_core", False))
    spawn_attach = os.environ.get("ARELIS_ATTACH_CORE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    # Attach when config asks, a core is already up, or core spawned us.
    core_up = external_core_available(config)
    attach_core = use_external or core_up or spawn_attach
    close_to_tray = bool(presence_cfg.get("close_to_tray", True))
    persister = ConfirmPersister(bus, window._pending_store)
    persister.start()
    if attach_core and (core_up or spawn_attach):
        # Never bind :8765 when attaching (or when core is about to own it).
        window.inbound_runtime = InboundRuntime(owned=False)
        ipc_enabled = bool(presence_cfg.get("ipc_enabled", True))
        if ipc_enabled:
            try:
                window.ipc_client = IpcClient(
                    bus,
                    host=str(presence_cfg.get("ipc_host") or "127.0.0.1"),
                    port=int(presence_cfg.get("ipc_port") or 8766),
                    on_open_ui=lambda _msg: QTimer.singleShot(
                        0, window._on_activation_request
                    ),
                    # Our own core may have fallen forward past the configured
                    # port because another account on this PC holds it. The
                    # handshake names the account, so scanning cannot attach us
                    # to the wrong one.
                    search_ports=True,
                )

                async def _start_ipc() -> None:
                    assert window.ipc_client is not None
                    window.ipc_client.start()

                asyncio.run_coroutine_threadsafe(_start_ipc(), loop)
            except ValueError as exc:
                asyncio.run_coroutine_threadsafe(
                    bus.publish(
                        Event(
                            EventType.STATUS,
                            {"message": f"Core IPC client not started: {exc}"},
                        )
                    ),
                    loop,
                )
        asyncio.run_coroutine_threadsafe(
            bus.publish(
                Event(
                    EventType.STATUS,
                    {
                        "message": (
                            "Detached Arelis core owns inbound notify. "
                            "Pending send confirms restore from disk; live SMS/"
                            "confirm events use the Core↔UI IPC bridge when attached."
                        )
                    },
                )
            ),
            loop,
        )
    else:
        hint = (
            "close to tray keeps listening; Quit from the tray to stop"
            if close_to_tray
            else "Arelis must stay open"
        )
        runtime = attach_inbound(
            bus,
            loop,
            config,
            owned=True,
            stay_open_hint=hint,
        )
        window.inbound_runtime = runtime
        window.sms_ingest = runtime.ingest
        window.sms_watcher = runtime.watcher
        window.sms_auto_reply = runtime.auto_reply
        window._bind_mobile_hub()
        for message in runtime.status_messages:
            asyncio.run_coroutine_threadsafe(
                bus.publish(Event(EventType.STATUS, {"message": message})),
                loop,
            )
        # With no core there is nothing on the bridge port, and a second launch
        # asking to be shown was talking to nobody — which is the whole of why
        # clicking the shortcut while tray-hidden did nothing. The UI answers for
        # itself in that case, over the same protocol and the same fall-forward
        # ports, so activate_existing_ui does not care which of the two replied.
        if bool(presence_cfg.get("ipc_enabled", True)):
            try:
                window.ipc_server = IpcServer(
                    bus,
                    host=str(presence_cfg.get("ipc_host") or "127.0.0.1"),
                    port=int(presence_cfg.get("ipc_port") or 8766),
                    on_open_ui=lambda _reason: QTimer.singleShot(
                        0, window._on_activation_request
                    ),
                )
            except ValueError as exc:
                log.warning("UI activation listener not started: %s", exc)
            else:

                async def _serve_activation() -> None:
                    assert window.ipc_server is not None
                    try:
                        await window.ipc_server.start()
                    except OSError as exc:
                        # Not fatal and not worth a dialog: everything else about
                        # this launch works, and the cost is that the next
                        # double-click has to fall back to the tray icon.
                        log.warning("UI activation listener could not bind: %s", exc)
                        window.ipc_server = None

                asyncio.run_coroutine_threadsafe(_serve_activation(), loop)

    window.setup_tray(app)
    parked = window._pending_store.list()
    if parked:
        window.queue_pending_confirms(parked)
        asyncio.run_coroutine_threadsafe(
            bus.publish(
                Event(
                    EventType.STATUS,
                    {
                        "message": (
                            f"{len(parked)} pending send confirm(s) waiting — "
                            "allow or skip in the card (nothing was sent while away)."
                        )
                    },
                )
            ),
            loop,
        )

    window.show()
    window.raise_()
    window.activateWindow()
    window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)

    def _deferred_memory_backup() -> None:
        try:
            from arelis.memory.backup import backup_memory_db

            backup_memory_db(store.path)
        except Exception:
            log.debug("deferred memory backup failed", exc_info=True)

    threading.Thread(
        target=_deferred_memory_backup,
        name="arelis-memory-backup",
        daemon=True,
    ).start()

    # After the window, not before: this reaches the network, and the first seconds of a
    # launch belong to the person who double-clicked something. Declines to do anything at
    # all unless this copy came from the installer, so a checkout is never offered a
    # release that would overwrite the code being edited.
    from arelis.ui.update_prompt import schedule_update_check

    schedule_update_check(window)
    try:
        code = app.exec()

        # Tray Quit is meant to feel instant, so every wait below is a ceiling
        # rather than a duration, and the force-quit ceilings are the tighter of
        # the two — the same distinction closeEvent already draws.
        force = bool(window._force_quit)
        drain_budget_s = 0.75 if force else 3.0

        async def shutdown() -> None:
            if window.ipc_client is not None:
                await window.ipc_client.stop()
                window.ipc_client = None
            if window.ipc_server is not None:
                try:
                    await asyncio.wait_for(window.ipc_server.stop(), timeout=1.0)
                except Exception:
                    pass
                window.ipc_server = None
            if window.inbound_runtime is not None:
                # closeEvent may already have stopped owned inbound; tolerate double-stop.
                try:
                    await asyncio.wait_for(window.inbound_runtime.stop(), timeout=2.0)
                except Exception:
                    pass
                if window.inbound_runtime.owned:
                    window.sms_ingest = None
                    window.sms_watcher = None
                    window.sms_auto_reply = None
            # IPC and ingest are down. Drop the single-instance lock before
            # model unload / browser close so a shortcut click during Quit
            # can take over instead of stacking a second glass or waiting on
            # a lock the dying copy still holds.
            _release_ui_lock()
            bus.stop()
            # Do not await model unload forever — just drop the HTTP client.
            try:
                await asyncio.wait_for(router.close(), timeout=2.0)
            except Exception:
                pass
            try:
                browser = tools.get("browser")
                session = getattr(browser, "session", None) if browser else None
                if session is not None:
                    await asyncio.wait_for(session.close(), timeout=2.0)
            except Exception:
                pass
            await _drain_event_loop(loop, budget_s=drain_budget_s)

        fut = asyncio.run_coroutine_threadsafe(shutdown(), loop)
        try:
            fut.result(timeout=2.0 if force else 8.0)
        except Exception:
            log.warning("shutdown did not finish in time", exc_info=True)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        return code
    finally:
        _release_ui_lock()
