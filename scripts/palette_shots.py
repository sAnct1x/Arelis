"""Photograph every painted surface so a palette change can be looked at.

A colour decision cannot be reviewed by reading a diff of hex triples. This
boots the same window ``rooms_smoke.py`` boots -- real docks, real settings
plate, real first-run dialog -- puts each surface into the state worth judging,
and saves a PNG of it. Run it once before a theme edit and once after, then put
the two folders side by side.

    python scripts/palette_shots.py before
    python scripts/palette_shots.py after

Everything lands in logs/palette/<tag>/. Runs against a scratch
ARELIS_DATA_DIR, so the live archive is never touched.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Both before any arelis import: paths.py and the Qt platform are read at import
# time, and offscreen keeps the run from stealing the desktop it is testing.
SCRATCH = Path(tempfile.mkdtemp(prefix="arelis-palette-"))
os.environ["ARELIS_DATA_DIR"] = str(SCRATCH)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(REPO))

import asyncio
import threading

from PySide6.QtWidgets import QApplication

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.memory import MemoryStore
from arelis.rooms import RoomStore
from arelis.ui.app import ArelisWindow, BusBridge
from arelis.ui.dialog import ConfirmDialog
from arelis.ui.first_run import FirstRunDialog
from arelis.ui.settings_dialog import SettingsDialog
from arelis.ui.theme import app_font, load_fonts, stylesheet
from arelis.workspace import WorkspaceRoots


class Shooter:
    def __init__(self, tag: str) -> None:
        self.out = REPO / "logs" / "palette" / tag
        self.out.mkdir(parents=True, exist_ok=True)
        for stale in self.out.glob("*.png"):
            stale.unlink()

        self.projects = SCRATCH / "projects"
        (self.projects / "Lab Notes").mkdir(parents=True)
        (self.projects / "Lab Notes" / "readings.csv").write_text(
            "t,fringe\n0,1.0\n1,0.8\n2,0.61\n", encoding="utf-8"
        )
        (self.projects / "Lab Notes" / "notes.md").write_text(
            "# Fringe run 3\n\nVisibility fell off after the second hour.\n",
            encoding="utf-8",
        )

        self.workspace = WorkspaceRoots.from_paths(
            [str(self.projects / "Lab Notes")], active="Lab Notes"
        )
        self.config = {
            "ui": {"default_width": 1360, "default_height": 880},
            "agent": {"max_rounds": 2},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
            "presence": {"close_to_tray": False},
            "tools": {},
            "memory": {"docs": {"enabled": False}},
            "workspace": {"roots": [str(self.projects / "Lab Notes")]},
            "_persona_path": str(REPO / "arelis" / "persona" / "arelis.md"),
            "_workspace": self.workspace,
            "_rooms": RoomStore(),
        }

        self.app = QApplication.instance() or QApplication([])
        self.app.setFont(app_font(load_fonts()))
        self.app.setStyleSheet(stylesheet())

        self.bus = EventBus()
        self.bridge = BusBridge()
        self.store = MemoryStore()
        self.store.start_glass_session()

        self.loop = asyncio.new_event_loop()

        def loop_thread() -> None:
            asyncio.set_event_loop(self.loop)
            self.loop.create_task(self.bus.run())
            self.loop.run_forever()

        self.thread = threading.Thread(
            target=loop_thread, name="palette-asyncio", daemon=True
        )
        self.thread.start()

        self.window = ArelisWindow(
            self.config,
            self.bridge,
            self.loop,
            self.bus,
            None,
            store=self.store,
        )
        self.window.resize(1360, 880)
        self.window.show()
        self.pump(0.6)
        self.shots: list[str] = []

    def pump(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()

    def shot(self, name: str, widget=None) -> None:
        target = widget if widget is not None else self.window
        self.pump(0.25)
        path = self.out / f"{name}.png"
        target.grab().save(str(path))
        self.shots.append(path.name)
        print(f"  {path.relative_to(REPO)}")

    def finish(self) -> None:
        self.window.dispose()
        self.window.hide()
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=3)
        self.store.close()


def main() -> int:
    tag = (sys.argv[1] if len(sys.argv) > 1 else "before").strip() or "before"
    s = Shooter(tag)
    print(f"palette shots [{tag}]:")

    w = s.window
    s.shot("01-idle-orbit")

    # A thread on screen: chat bubbles, the parked orbit, the composer row, and
    # the readiness strip all painting at once.
    w.chat.add_user("summarise the fringe run and tell me what to try next")
    w.chat.begin_assistant()
    for chunk in (
        "Visibility fell from **1.0 to 0.61** over three hours. ",
        "That is a slow drift rather than a step, so the mount is the first "
        "suspect and not the source.\n\n",
        "1. Re-level the mount and re-run the first hour.\n"
        "2. Log ambient temperature alongside `fringe`.\n",
    ):
        w.chat.append_delta(chunk)
    w.chat.finish_assistant(
        "Visibility fell from **1.0 to 0.61** over three hours. That is a slow "
        "drift rather than a step, so the mount is the first suspect and not "
        "the source.\n\n"
        "1. Re-level the mount and re-run the first hour.\n"
        "2. Log ambient temperature alongside `fringe`.\n"
    )
    w.chat.add_system("weather · 14°C, clear until 21:00")
    w.conversation.set_idle_mode(False)
    s.shot("02-conversation")

    # An Allow card, which is the app's own confirm language and the thing the
    # new dialogs have to agree with.
    w.conversation.ask_confirm(
        "c1",
        "workspace",
        "write notes.md in Lab Notes",
        detail="# Fringe run 3\n\nVisibility fell off after the second hour.",
        note="This overwrites a file that already exists.",
    )
    s.shot("03-confirm-card")
    w.conversation.dismiss_confirm()

    # Docks. History and workspace are the two with the most painted furniture.
    w.history.set_sessions(
        [
            {"id": "s1", "title": "fringe run 3", "started_at": "2026-08-16T21:04:00"},
            {"id": "s2", "title": "youtube thumbnail", "started_at": "2026-08-15T11:20:00"},
            {"id": "s3", "title": "what's on my calendar", "started_at": "2026-08-14T08:02:00"},
        ]
    )
    w.history.set_pending_facts(
        [
            {"id": 1, "text": "Climbs on Tuesdays"},
            {"id": 2, "text": "Prefers metric units in reports"},
        ]
    )
    w.history_dock.show()
    w.work_dock.show()
    s.shot("04-docks-history-workspace")

    w.think_dock.show()
    w._on_event(
        Event(
            EventType.THINKING,
            {"text": "checking the readings against the second run before answering"},
        )
    )
    s.shot("05-dock-thinking")

    for dock in (w.history_dock, w.work_dock, w.think_dock):
        dock.hide()

    # Floating plates get their own HWND, so grab the widget rather than window.
    w.contacts_inbox.show()
    s.shot("06-contacts-plate", w.contacts_inbox)
    w.contacts_inbox.hide()

    w.notify_inbox.show()
    s.shot("07-notifications-plate", w.notify_inbox)
    w.notify_inbox.hide()

    settings = SettingsDialog(s.config, active_facts=[{"id": 1, "text": "Climbs on Tuesdays"}])
    settings.resize(520, 560)
    settings.show()
    s.shot("08-settings-audio", settings)
    for index in range(settings.tabs.count()):
        if settings.tabs.tabText(index) == "Roots":
            settings.tabs.setCurrentIndex(index)
    s.shot("09-settings-roots", settings)
    for index in range(settings.tabs.count()):
        if settings.tabs.tabText(index) == "Memory":
            settings.tabs.setCurrentIndex(index)
    s.shot("10-settings-memory", settings)
    settings.hide()
    settings.deleteLater()

    first_run = FirstRunDialog(Path.home() / "Documents" / "Arelis")
    first_run.resize(560, 420)
    first_run.show()
    s.shot("11-first-run", first_run)
    first_run.hide()
    first_run.deleteLater()

    # The delete prompts, which used to be native message boxes and are the
    # surface most likely to look like a different program if this drifts.
    ask = ConfirmDialog(
        "Delete conversation",
        "Delete “fringe run 3”?",
        detail="This cannot be undone.",
        confirm_text="Delete",
        destructive=True,
    )
    ask.show()
    s.shot("12-confirm-delete", ask)
    ask.hide()
    ask.deleteLater()

    s.finish()
    print()
    print(f"{len(s.shots)} shots in {s.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
