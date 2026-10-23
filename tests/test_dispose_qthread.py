"""Window teardown must not destroy a QThread that is still in run().

The macOS job aborted in the autouse window drain: DeferredDelete destroyed
a parent, that deleted a child QThread, and Qt called abort. These tests
keep a worker blocked across that drain.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread
from PySide6.QtWidgets import QApplication, QWidget

from arelis.ui.live_threads import quiesce_widget_threads


def test_fixture_dispose_survives_a_blocked_child_thread(qt_app) -> None:
    """The autouse drain runs after this returns, while the worker is blocked.

    A fix that only waits for a thread which is about to exit still aborts
    here: the worker stays in run() for longer than that wait.
    """
    started = threading.Event()

    class Worker(QThread):
        def run(self) -> None:
            started.set()
            threading.Event().wait(1.5)

    window = QWidget()
    worker = Worker(QObject(window))
    worker.setObjectName("dispose-probe")
    worker.start()
    assert started.wait(2)
    assert worker.isRunning()
    window.deleteLater()


def test_quiesce_unparents_a_blocked_thread_before_deferred_delete(qt_app) -> None:
    started = threading.Event()
    release = threading.Event()

    class Worker(QThread):
        def run(self) -> None:
            started.set()
            release.wait(timeout=5)

    window = QWidget()
    worker = Worker(QObject(window))
    worker.setObjectName("dispose-probe")
    worker.start()
    assert started.wait(2)
    window.deleteLater()
    try:
        quiesce_widget_threads(qt_app, wait_ms=0)
        assert worker.isRunning()
        assert worker.parent() is None
        qt_app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()
        assert shiboken6.isValid(worker)
        assert worker.isRunning()
    finally:
        release.set()
        worker.wait(2000)


def test_quit_joins_a_running_avatar_bake(qt_app, monkeypatch) -> None:
    """Quit must join handed-off workers, including a mid-download prepare.

    Setup-not-finished parks a real ``_PrepareWorker`` without calling
    cancel(), then ``run_ui`` must signal cancel and join it well under
    ``HANDED_OFF_WAIT_S`` (1s read timeout, then ``cancelled()``). The
    other exits park a parentless bake worker via aboutToQuit. A skipped
    cancel, a no-op wait, a skipped park, or a skipped drain leaves a
    worker running. Isolate QT_QPA_PLATFORM so Windows does not leak
    into the next test.
    """
    import arelis.ui.live_threads as live
    from arelis.setup.catalog import CATALOG
    from arelis.ui import launch as launch_mod
    from arelis.ui.live_threads import park_running_thread
    from arelis.ui.persona_face.avatar import PersonaAvatar
    from arelis.ui.setup_wizard import _PrepareWorker

    monkeypatch.setenv("ARELIS_ALLOW_OFFSCREEN", "1")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    started = threading.Event()

    def fake_bake(size: object, cancel: object = None, publish: object = None) -> dict:
        started.set()
        time.sleep(3.2)
        return {}

    def fake_download(
        model: object,
        *,
        dest_dir: object = None,
        progress: object = None,
        cancelled: object = None,
    ) -> object:
        del model, dest_dir, progress
        started.set()
        while True:
            if callable(cancelled) and cancelled():
                raise RuntimeError("The download was stopped.")
            time.sleep(1.0)

    monkeypatch.setattr("arelis.ui.persona_face.avatar.bake_layers", fake_bake)
    monkeypatch.setattr(
        "arelis.ui.persona_face.avatar.face_cache.load_layers", lambda *_a, **_k: None
    )
    monkeypatch.setattr("arelis.ui.setup_wizard.download_model", fake_download)

    class _Lock:
        def acquire(self) -> bool:
            return True

        def release(self) -> None:
            return None

    monkeypatch.setattr("arelis.presence.lock.PresenceLock", lambda path: _Lock())
    monkeypatch.setattr(
        "arelis.presence.ipc_token.claim_session_token", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "arelis.jobs.schedule.repoint_moved_tasks_on_launch", lambda: None
    )
    monkeypatch.setattr("arelis.ui.dialog.notice", lambda *_a, **_k: None)

    real_drain = live.drain_parked_threads
    drain_calls: list[str] = []

    def spy_drain(timeout_s: float = live.HANDED_OFF_WAIT_S) -> None:
        drain_calls.append(f"{timeout_s:g}")
        real_drain(timeout_s)

    monkeypatch.setattr(live, "drain_parked_threads", spy_drain)

    def start_baker() -> tuple[PersonaAvatar, QThread]:
        started.clear()
        avatar = PersonaAvatar()
        avatar.resize(220, 300)
        avatar.show()
        qt_app.processEvents()
        avatar._start_bake()
        assert started.wait(2)
        baker = avatar._baker
        assert baker is not None and baker.isRunning()
        return avatar, baker

    def quit_parks(avatar: PersonaAvatar) -> None:
        qt_app.aboutToQuit.emit()
        assert avatar._baker is None

    avatars: list[PersonaAvatar] = []
    prepare: _PrepareWorker | None = None
    try:
        monkeypatch.setattr(launch_mod, "prompt_for_workspace_root", lambda: None)
        monkeypatch.setattr(launch_mod, "try_quiet_complete_model_setup", lambda: None)
        monkeypatch.setattr(launch_mod, "needs_model_setup", lambda: True)
        monkeypatch.setattr(launch_mod, "first_run_blocks_main", lambda: True)
        monkeypatch.setattr(launch_mod, "prompt_for_model_setup", lambda parent=None: None)
        started.clear()
        prepare = _PrepareWorker(CATALOG[0].tag)
        prepare.start()
        assert started.wait(2)
        assert prepare.isRunning()
        # Park only. If drain skips cancel(), this loops past the 6s bound
        # the same way a mid-download close hung for 90s with no window.
        park_running_thread(prepare)
        before = len(drain_calls)
        t0 = time.monotonic()
        assert launch_mod.run_ui({}) == 1
        elapsed = time.monotonic() - t0
        assert len(drain_calls) > before
        assert float(drain_calls[-1]) > 5.0
        assert not prepare.isRunning()
        assert elapsed < live.HANDED_OFF_WAIT_S

        class BoomWindow:
            def __init__(self, *_a: object, **_k: object) -> None:
                raise RuntimeError("window failed")

        class _Router:
            provider = None

            def arm_warmup(self) -> None:
                return None

            def mark_warmup_done(self) -> None:
                return None

            async def close(self) -> None:
                return None

        async def _resume_last_room() -> None:
            return None

        fake_seat = SimpleNamespace(
            router=_Router(),
            store=None,
            tools={},
            orchestrator=SimpleNamespace(resume_last_room=_resume_last_room),
        )
        monkeypatch.setattr(launch_mod, "apply_first_run_glass", lambda *_a, **_k: {})
        monkeypatch.setattr("arelis.core.seat.build_seat", lambda *_a, **_k: fake_seat)
        monkeypatch.setattr(launch_mod, "VoiceService", lambda *_a, **_k: SimpleNamespace(stt=None))
        monkeypatch.setattr(
            launch_mod,
            "MemoryIndexer",
            lambda *_a, **_k: SimpleNamespace(join_writes=lambda timeout_s=0: None),
        )
        monkeypatch.setattr("arelis.ui.app.ArelisWindow", BoomWindow)

        avatar, baker = start_baker()
        avatars.append(avatar)
        quit_parks(avatar)
        before = len(drain_calls)
        with pytest.raises(RuntimeError, match="window failed"):
            launch_mod.run_ui({})
        assert len(drain_calls) > before
        assert float(drain_calls[-1]) > 5.0
        assert not baker.isRunning()

        class QuietWindow(QWidget):
            def __init__(self, *_a: object, **_k: object) -> None:
                super().__init__()
                self._force_quit = True
                self.orchestrator = fake_seat.orchestrator
                self.inbound_runtime = None
                self.ipc_client = None
                self.ipc_server = None
                self._pending_store = SimpleNamespace(list=lambda: [])
                self._orphan_ingest_stop = None
                self.sms_ingest = None
                self.sms_watcher = None
                self.sms_auto_reply = None
                self.config = {}

            def setup_tray(self, app: object) -> None:
                del app

            def queue_pending_confirms(self, parked: object) -> None:
                del parked

        monkeypatch.setattr("arelis.ui.app.ArelisWindow", QuietWindow)
        monkeypatch.setattr(QApplication, "exec", lambda self: 0)
        monkeypatch.setattr("arelis.i18n.apply_language", lambda *_a, **_k: None)
        monkeypatch.setattr(launch_mod, "_present_at_startup", lambda window: None)
        monkeypatch.setattr(
            "arelis.ui.update_prompt.schedule_update_check", lambda *_a, **_k: None
        )
        monkeypatch.setattr(
            launch_mod, "_start_activation_listener", lambda *_a, **_k: None
        )
        monkeypatch.setattr(
            "arelis.presence.glass_inbound.install_owned_inbound", lambda *_a, **_k: None
        )

        avatar, baker = start_baker()
        avatars.append(avatar)
        quit_parks(avatar)
        before = len(drain_calls)
        assert launch_mod.run_ui({}) == 0
        assert len(drain_calls) > before
        assert float(drain_calls[-1]) > 5.0
        assert not baker.isRunning()
    finally:
        if prepare is not None:
            prepare.cancel()
            prepare.wait(2000)
        for avatar in avatars:
            avatar.shutdown()
        real_drain(0.05)
