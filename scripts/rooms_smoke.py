"""Drive Rooms through the real desktop stack and photograph every step.

Not a unit test. This boots the actual window, the actual event bus on its own
thread, the actual orchestrator, memory archive and room store, and then types
into the actual composer — the same path a person uses. Room commands never
reach the model, so the only thing stubbed is the router, which keeps the run
deterministic and independent of whether Ollama happens to be up.

Everything lands in logs/rooms-smoke/: a PNG of the window after each step, a
JSONL of the measured state at each step, and a report.md tying them together.
Runs against a scratch ARELIS_DATA_DIR, so the live archive is never touched.

    python scripts/rooms_smoke.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "logs" / "rooms-smoke"

# Both before any arelis import: paths.py and the Qt platform are read at import
# time, and offscreen keeps the run from stealing the desktop it is testing.
SCRATCH = Path(tempfile.mkdtemp(prefix="arelis-rooms-smoke-"))
os.environ["ARELIS_DATA_DIR"] = str(SCRATCH)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(REPO))

import asyncio
import threading

from PySide6.QtWidgets import QApplication

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.memory import MemoryStore
from arelis.rooms import RoomStore
from arelis.tools import build_tool_registry
from arelis.ui.app import ArelisWindow, BusBridge
from arelis.ui.theme import app_font, load_fonts, stylesheet
from arelis.workspace import WorkspaceRoots


class StubRouter:
    """Enough ModelRouter to boot. Room commands never reach a model."""

    def __init__(self) -> None:
        self.default_role = "fast"
        self.active_model = None
        self.active_role = None
        self.models = {"fast": "mock", "research": "mock", "code": "mock"}
        self.provider = None
        self.reserve_vram_for_heavy = False

    def model_for(self, role=None):
        return "mock"

    async def ensure_role(self, role, *, force: bool = False):
        del force
        self.active_role = role
        return "mock"

    def mark_sticky(self, role) -> None:
        return None

    def clear_sticky(self) -> None:
        return None

    def apply_sticky(self, wanted, reason: str):
        return wanted, reason

    async def stream(self, role, messages, **kwargs):
        yield ("token", "(model stubbed for this run)")

    async def close(self) -> None:
        return None


class Harness:
    def __init__(self) -> None:
        OUT.mkdir(parents=True, exist_ok=True)
        for stale in OUT.glob("*"):
            if stale.is_file():
                stale.unlink()

        self.projects = SCRATCH / "projects"
        (self.projects / "Lab Notes").mkdir(parents=True)
        (self.projects / "Arelis Source").mkdir(parents=True)
        (self.projects / "Lab Notes" / "readings.csv").write_text(
            "t,fringe\n0,1.0\n1,0.8\n", encoding="utf-8"
        )

        self.workspace = WorkspaceRoots.from_paths(
            [
                str(self.projects / "Lab Notes"),
                str(self.projects / "Arelis Source"),
            ],
            active="Lab Notes",
        )
        self.rooms = RoomStore()
        self.config = {
            "ui": {"default_width": 1360, "default_height": 880},
            "agent": {"max_rounds": 2},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
            "presence": {"close_to_tray": False},
            "tools": {},
            "memory": {"docs": {"enabled": False}},
            "_persona_path": str(REPO / "arelis" / "persona" / "arelis.md"),
            "_workspace": self.workspace,
            "_rooms": self.rooms,
        }

        self.app = QApplication.instance() or QApplication([])
        # Same order main() uses. Without the fonts the offscreen platform has
        # no family to fall back to and every screenshot is a wall of tofu
        # boxes — structurally correct and completely unreadable.
        self.app.setFont(app_font(load_fonts()))
        self.app.setStyleSheet(stylesheet())

        self.bus = EventBus()
        self.bridge = BusBridge()
        self.events: list[Event] = []
        self.done_count = 0

        async def mirror(event: Event) -> None:
            self.events.append(event)
            if event.type in {EventType.ASSISTANT_DONE, EventType.ERROR}:
                self.done_count += 1
            self.bridge.feed(event)

        self.bus.subscribe(None, mirror)

        self.store = MemoryStore()
        self.store.start_glass_session()
        self.router = StubRouter()
        self.tools = build_tool_registry(self.config, self.workspace)
        self.memory = SessionMemory(sink=self.store)
        self.orchestrator = Orchestrator(
            self.bus,
            self.router,  # type: ignore[arg-type]
            self.tools,
            self.config,
            self.memory,
            workspace=self.workspace,
        )

        self.loop = asyncio.new_event_loop()

        def loop_thread() -> None:
            asyncio.set_event_loop(self.loop)
            self.loop.bus_task = self.loop.create_task(self.bus.run())  # type: ignore[attr-defined]
            self.loop.run_forever()

        self.thread = threading.Thread(
            target=loop_thread, name="rooms-smoke-asyncio", daemon=True
        )
        self.thread.start()

        self.window = ArelisWindow(
            self.config,
            self.bridge,
            self.loop,
            self.bus,
            None,
            store=self.store,
            router=self.router,  # type: ignore[arg-type]
        )
        self.window.resize(1360, 880)
        self.window.show()
        self.pump(0.5)

        self.steps: list[dict] = []
        self.failures: list[str] = []
        self._last_wait = 0.0

    # -- plumbing --------------------------------------------------------

    def pump(self, seconds: float) -> None:
        """Turn the Qt loop while the asyncio thread works."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()

    def wait_for(self, done, *, timeout: float = 20.0) -> float:
        """Turn the Qt loop until the predicate holds. Returns seconds waited.

        A fixed sleep is not enough here and the first version of this harness
        proved it: the window's readiness probe occupies the bus for a second or
        two at startup, so a click that waits one second looks like a dead
        button. The measured wait is kept per step so a genuinely slow path is
        visible rather than flaky.
        """
        started = time.monotonic()
        end = started + timeout
        while time.monotonic() < end and not done():
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        return time.monotonic() - started

    def send(self, text: str, *, timeout: float = 20.0) -> None:
        """Type it into the real composer and press enter."""
        before = self.done_count
        self.window.conversation.input.setPlainText(text)
        self.window.conversation._submit()
        self._last_wait = self.wait_for(
            lambda: self.done_count > before, timeout=timeout
        )
        self.pump(0.35)

    def state(self) -> dict:
        room = self.rooms.active
        strip = self.window.conversation.room
        return {
            "active_room": self.rooms.active_id,
            "room_name": room.name if room else "",
            "room_purpose": room.purpose if room else "",
            "room_root": room.root if room else "",
            "room_kind": room.kind if room else "",
            "session_id": self.store.session_id,
            "session_room_id": (
                (self.store.get_session(self.store.session_id) or {}).get("room_id")
                if self.store.session_id
                else None
            ),
            "workspace_active": self.workspace.active,
            "router_role": self.router.default_role,
            "strip_visible": not strip.isHidden(),
            "strip_room_id": strip.room_id,
            "strip_name": strip.name.text(),
            "strip_detail": strip.detail.text(),
            "dock_project": self.window.workspace.project_combo.currentText(),
            "memory_first_message": (
                self.memory.as_ollama()[0]["content"][:80]
                if self.memory.as_ollama()
                else ""
            ),
            "memory_len": len(self.memory.messages),
            "rooms_on_disk": [r.id for r in RoomStore().all()],
            "asked_for": [
                str(e.payload.get("text") or "")[:40]
                for e in self.events
                if e.type == EventType.USER_MESSAGE
            ][-3:],
            "busy": self.window.conversation.input.isEnabled() is False,
            "leave_btn_enabled": self.window.conversation.room.leave_btn.isEnabled(),
            "waited_s": round(self._last_wait, 2),
        }

    def step(self, name: str, action, expect: dict | None = None) -> dict:
        index = len(self.steps) + 1
        started = datetime.now(UTC).isoformat(timespec="seconds")
        action()
        measured = self.state()
        shot = OUT / f"{index:02d}-{_slug(name)}.png"
        self.window.grab().save(str(shot))

        problems = []
        for key, want in (expect or {}).items():
            got = measured.get(key)
            if callable(want):
                if not want(got):
                    problems.append(f"{key}={got!r} failed its check")
            elif got != want:
                problems.append(f"{key} expected {want!r}, got {got!r}")
        for problem in problems:
            self.failures.append(f"step {index} ({name}): {problem}")

        record = {
            "step": index,
            "name": name,
            "at": started,
            "screenshot": shot.name,
            "state": measured,
            "problems": problems,
            "last_reply": _last_reply(self.events),
        }
        self.steps.append(record)
        mark = "ok  " if not problems else "FAIL"
        print(f"  {mark} {index:2d}. {name}")
        for problem in problems:
            print(f"        {problem}")
        return record

    def finish(self) -> int:
        (OUT / "steps.jsonl").write_text(
            "\n".join(json.dumps(s) for s in self.steps) + "\n", encoding="utf-8"
        )
        (OUT / "report.md").write_text(_report(self.steps, self.failures), encoding="utf-8")

        rooms_yaml = SCRATCH / "data" / "rooms.yaml"
        if rooms_yaml.is_file():
            shutil.copy(rooms_yaml, OUT / "rooms.yaml")

        self.window.dispose()
        self.window.hide()
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=3)
        self.store.close()
        return 1 if self.failures else 0


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")[:48]


def _last_reply(events: list[Event]) -> str:
    for event in reversed(events):
        if event.type == EventType.ASSISTANT_DONE:
            return str(event.payload.get("text") or "")[:400]
    return ""


def _report(steps: list[dict], failures: list[str]) -> str:
    lines = [
        "# Rooms smoke run",
        "",
        f"{len(steps)} steps, {len(failures)} problems.",
        "",
    ]
    if failures:
        lines += ["## Problems", ""] + [f"- {f}" for f in failures] + [""]
    for step in steps:
        s = step["state"]
        lines += [
            f"## {step['step']}. {step['name']}",
            "",
            f"![step {step['step']}]({step['screenshot']})",
            "",
            f"- room: `{s['active_room'] or 'general'}`"
            f" · thread `{(s['session_id'] or '')[:8]}` (room_id `{s['session_room_id']}`)",
            f"- workspace: `{s['workspace_active']}` · dock shows `{s['dock_project']}`"
            f" · role `{s['router_role']}`",
            f"- strip: visible={s['strip_visible']} `{s['strip_name']}`"
            f" — {s['strip_detail']}",
            f"- memory: {s['memory_len']} message(s), first is"
            f" {s['memory_first_message']!r} · waited {s['waited_s']}s",
            "",
            "> " + (step["last_reply"].replace("\n", "\n> ") or "(no reply)"),
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    print(f"scratch data root: {SCRATCH}")
    h = Harness()
    print("running:")

    general_thread = {"id": ""}

    def remember_general() -> None:
        general_thread["id"] = h.store.session_id

    h.step(
        "cold launch is the general orbit",
        lambda: (h.send("this is the general conversation"), remember_general()),
        expect={
            "active_room": "",
            "strip_visible": False,
            "session_room_id": "",
        },
    )

    h.step(
        "rooms list explains itself when empty",
        lambda: h.send("/rooms"),
        expect={"active_room": ""},
    )

    h.step(
        "make a room by typing",
        lambda: h.send("/room new physics"),
        expect={
            "active_room": "physics",
            "strip_visible": True,
            "strip_room_id": "physics",
            "session_room_id": "physics",
            "rooms_on_disk": ["physics"],
            "session_id": lambda sid: sid != general_thread["id"],
        },
    )

    h.step(
        "give it a purpose",
        lambda: h.send("/room set purpose analysing the survey data, show your numbers"),
        expect={
            "room_purpose": "analysing the survey data, show your numbers",
            "strip_detail": lambda d: "analysing the survey data" in d,
        },
    )

    h.step(
        "point it at a folder",
        lambda: h.send("/room set root Arelis Source"),
        expect={
            "room_root": "Arelis Source",
            "workspace_active": "Arelis Source",
        },
    )

    h.step(
        "give it a lean",
        lambda: h.send("/room set kind analysis"),
        expect={"room_kind": "analysis"},
    )

    h.step(
        "talk inside the room",
        lambda: h.send("three weeks of analysis so far"),
        expect={
            "active_room": "physics",
            "memory_first_message": lambda m: m.startswith("three weeks"),
        },
    )

    h.step(
        "a bad folder name is refused with the list",
        lambda: h.send("/room set root nowhere"),
        expect={"room_root": "Arelis Source"},
    )

    h.step(
        "leave by saying so",
        lambda: h.send("leave the room"),
        expect={
            "active_room": "",
            "strip_visible": False,
            "session_id": lambda sid: sid == general_thread["id"],
            "memory_first_message": lambda m: m.startswith("this is the general"),
        },
    )

    h.step(
        "an ordinary sentence does not move anything",
        lambda: h.send("let's work on the budget"),
        expect={
            "active_room": "",
            "strip_visible": False,
            "session_id": lambda sid: sid == general_thread["id"],
        },
    )

    h.step(
        "walk back in by saying so",
        lambda: h.send("let's work on physics"),
        expect={
            "active_room": "physics",
            "strip_visible": True,
            "workspace_active": "Arelis Source",
            "router_role": "fast",
            "memory_first_message": lambda m: m.startswith("three weeks"),
        },
    )

    def click_leave() -> None:
        before = h.done_count
        h.window.conversation.room.leave_btn.click()
        h._last_wait = h.wait_for(lambda: h.done_count > before)
        h.pump(0.35)

    h.step(
        "the leave button on the strip",
        click_leave,
        expect={"active_room": "", "strip_visible": False},
    )

    h.step(
        "a second room keeps its own everything",
        lambda: (
            h.send("/room new writing"),
            h.send("/room set root Lab Notes"),
            h.send("drafting the introduction"),
        ),
        expect={
            "active_room": "writing",
            "workspace_active": "Lab Notes",
            "memory_first_message": lambda m: m.startswith("drafting"),
            "rooms_on_disk": ["physics", "writing"],
        },
    )

    h.step(
        "stepping between rooms does not mix them",
        lambda: h.send("/room physics"),
        expect={
            "active_room": "physics",
            "workspace_active": "Arelis Source",
            "memory_first_message": lambda m: m.startswith("three weeks"),
            "memory_len": 2,
        },
    )

    h.step(
        "the list marks the open one",
        lambda: h.send("/rooms"),
        expect={"active_room": "physics"},
    )

    h.step(
        "forgetting a room keeps its conversation",
        lambda: h.send("/room forget writing"),
        expect={
            "rooms_on_disk": ["physics"],
            "active_room": "physics",
        },
    )

    h.step(
        "help mentions the way in",
        lambda: h.send("/help"),
        expect={},
    )

    code = h.finish()
    print()
    print(f"artifacts: {OUT}")
    print(f"screenshots: {len(list(OUT.glob('*.png')))}")
    if code:
        print(f"PROBLEMS: {len(h.failures)}")
        for failure in h.failures:
            print(f"  - {failure}")
    else:
        print("all steps clean")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
