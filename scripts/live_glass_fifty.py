"""Open the Arelis glass and run the 50-prompt live fifty.

Everyday language, pictures, Reality, Earth. No email. No SMS. No voice.
Writes breadcrumbs to outputs/live_fifty/progress.json so a restart can skip
finished steps. Screen-grabs every Earth altitude line.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import threading
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")

os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.pop("ARELIS_ALLOW_OFFSCREEN", None)
os.environ["ARELIS_SOLAR_GL"] = "1"

from arelis.config import load_config
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.seat import build_seat
from arelis.eval.conversation import ToolCallRecord, _score_turn
from arelis.eval.live_fifty import FORBIDDEN_TOOLS, TIMEOUT_S, live_fifty_turns
from arelis.paths import outputs_dir
from arelis.presence.lock import PresenceLock, ui_lock_path
from arelis.spatial import PHYSICS_ROOM_ID
from arelis.ui.launch import force_windows_qt_platform
from arelis.ui.theme import apply_theme, load_fonts, stylesheet, theme_from_config
from arelis.ui.window_resize import configure_native_windows

LOD_LINES_M = (3_000_000, 800_000, 80_000, 20_000, 8_000, 2_000, 350)
ADDRESS_Q = "350 Fifth Avenue"
EARTH_CHIPS = (
    "live",
    "grid",
    "tiles",
    "buildings",
    "flights",
    "satellites",
    "iss",
    "weather",
    "cameras",
    "traffic",
)


def _snip(text: str, n: int = 220) -> str:
    one = " ".join((text or "").strip().split())
    one = _EMAIL.sub("[inbox]", one)
    one = one.encode("ascii", "replace").decode("ascii")
    return one if len(one) <= n else one[: n - 1] + "..."


def _pump(app: Any, ms: int = 50) -> None:
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < ms:
        app.processEvents()
        time.sleep(0.01)


_RECEIPT_TOOL = re.compile(
    r"(?i)tools used this turn:\s*([a-z0-9_]+)|"
    r"receipt action=([a-z0-9_]+)"
)


def _tools_from_receipt(final: str) -> list[str]:
    """Inject/same-call often writes a receipt without a TOOL_START the cap saw."""
    found: list[str] = []
    for match in _RECEIPT_TOOL.finditer(final or ""):
        name = (match.group(1) or match.group(2) or "").strip().lower()
        if name and name not in found:
            found.append(name)
    return found


def _cancel_hung(window: Any, app: Any) -> None:
    cancel = getattr(window, "_cancel_turn", None)
    if callable(cancel):
        try:
            cancel(schedule_next=False)
        except TypeError:
            cancel()
        except Exception:
            pass
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        _pump(app, 80)
        if not bool(getattr(window, "_turn_busy", False)):
            return


def _new_chat(window: Any, app: Any) -> None:
    from arelis.ui.history_host import on_history_new

    if bool(getattr(window, "_turn_busy", False)):
        _cancel_hung(window, app)
    try:
        on_history_new(window)
    except Exception:
        return
    # SESSION_LOAD can publish a leftover assistant line after busy drops.
    # Wait through that, then idle, so the next submit is not scored as done.
    deadline = time.monotonic() + 20
    saw_busy = False
    while time.monotonic() < deadline:
        _pump(app, 80)
        busy = bool(getattr(window, "_turn_busy", False))
        if busy:
            saw_busy = True
        elif saw_busy:
            break
    _pump(app, 1600)


def _fresh_token() -> str:
    return "F50-" + datetime.now().strftime("%H%M%S")


class _Cap:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.tools: list[str] = []
            self.records: list[ToolCallRecord] = []
            self.final = ""
            self.done = False
            self.error = ""

    def snapshot(self) -> tuple[list[str], list[ToolCallRecord], str, bool, str]:
        with self.lock:
            return list(self.tools), list(self.records), self.final, self.done, self.error


def _bind_cap(bus: EventBus, cap: _Cap) -> None:
    async def on_start(event: Event) -> None:
        name = str((event.payload or {}).get("tool") or "")
        args = dict((event.payload or {}).get("args") or {})
        if not name:
            return
        rec = ToolCallRecord(name=name, args=args)
        with cap.lock:
            cap.tools.append(name)
            cap.records.append(rec)

    async def on_result(event: Event) -> None:
        name = str((event.payload or {}).get("tool") or "")
        ok = (event.payload or {}).get("ok")
        ms = int((event.payload or {}).get("ms") or 0)
        out = str((event.payload or {}).get("output") or "")[:200]
        with cap.lock:
            for rec in reversed(cap.records):
                if rec.name == name and rec.ok is None:
                    rec.ok = bool(ok) if ok is not None else None
                    rec.ms = ms
                    rec.output_head = out
                    break

    async def on_done(event: Event) -> None:
        with cap.lock:
            cap.final = str((event.payload or {}).get("text") or "")
            cap.done = True

    async def on_err(event: Event) -> None:
        with cap.lock:
            cap.error = str((event.payload or {}).get("message") or "error")
            cap.done = True

    bus.subscribe(EventType.TOOL_START, on_start)
    bus.subscribe(EventType.TOOL_RESULT, on_result)
    bus.subscribe(EventType.ASSISTANT_DONE, on_done)
    bus.subscribe(EventType.ERROR, on_err)


def _click_allow(window: Any) -> bool:
    confirm = getattr(window.conversation, "confirm", None)
    if confirm is None or not window.conversation.confirm_open():
        return False
    btn = getattr(confirm, "allow_btn", None)
    if btn is None or not btn.isVisible():
        return False
    btn.click()
    return True


def _skip_parked(window: Any, app: Any) -> int:
    n = 0
    for _ in range(8):
        if not window.conversation.confirm_open():
            break
        skip = getattr(window.conversation.confirm, "skip_btn", None)
        if skip is None or not skip.isVisible():
            break
        skip.click()
        n += 1
        _pump(app, 200)
    return n


def _progress_path(out: Path) -> Path:
    return out / "progress.json"


def _load_progress(out: Path) -> dict[str, Any]:
    path = _progress_path(out)
    if not path.is_file():
        return {"done": [], "notes": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"done": [], "notes": []}


def _save_progress(out: Path, data: dict[str, Any]) -> None:
    data["updated"] = datetime.now(UTC).isoformat()
    _progress_path(out).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _note(out: Path, line: str) -> None:
    prog = _load_progress(out)
    notes = list(prog.get("notes") or [])
    notes.append(f"{datetime.now(UTC).strftime('%H:%M:%S')}  {line}")
    prog["notes"] = notes[-200:]
    _save_progress(out, prog)
    print(f"  .. {line}", flush=True)


def _screen_grab(top: Any, dest: Path) -> Path:
    from PySide6.QtGui import QGuiApplication

    dest.parent.mkdir(parents=True, exist_ok=True)
    if top is None:
        return dest
    top.show()
    top.raise_()
    top.activateWindow()
    screen = top.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        pix = top.grab()
        pix.save(str(dest))
        return dest
    geo = top.frameGeometry()
    full = screen.grabWindow(0)
    img = (
        full.copy(geo).toImage()
        if not full.isNull()
        else screen.grabWindow(int(top.winId())).toImage()
    )
    img.save(str(dest), "PNG")
    return dest


def _solar(window: Any) -> Any:
    ww = getattr(window, "world_window", None)
    return getattr(ww, "solar", None) if ww is not None else None


def _ensure_reality(window: Any, app: Any, out: Path) -> bool:
    from arelis.ui.world_host import toggle_world

    try:
        window._enter_room_from_menu(PHYSICS_ROOM_ID)
    except Exception as exc:
        _note(out, f"room enter failed: {type(exc).__name__}")
    _pump(app, 400)
    try:
        toggle_world(window, True, page="solar", force=True)
    except Exception as exc:
        _note(out, f"toggle Reality failed: {type(exc).__name__}")
        return False
    _pump(app, 800)
    panel = _solar(window)
    if panel is None:
        _note(out, "no SolarPanel")
        return False
    try:
        panel._ensure_ic()
    except Exception:
        pass
    _pump(app, 400)
    _note(out, "Reality plate open on solar")
    return True


def _drive_verb(window: Any, text: str, app: Any) -> bool:
    from arelis.ui.world_host import try_physics_verb, try_tile_speech

    try:
        hit = try_physics_verb(window, text) or try_tile_speech(window, text)
    except Exception:
        return False
    _pump(app, 600)
    return bool(hit)


def _place_earth(panel: Any, lat: float, lon: float, alt_m: float) -> None:
    from arelis.earth.frames import EarthCam, apply_earth_cam, earth_spin_jd, lla_to_ecef
    from arelis.earth.lod import view_from_eye
    from arelis.earth.runtime import get_earth
    from arelis.physics.runtime import get_system

    system = get_system()
    if system is None:
        return
    earth = system.nbody.find("Earth")
    if earth is None:
        return
    jd = earth_spin_jd(system.epoch_jd, system.t)
    eye = lla_to_ecef(lat, lon, alt_m)
    look = lla_to_ecef(lat, lon, 0.0)
    north = lla_to_ecef(min(89.0, lat + 0.25), lon, alt_m)
    up = (north[0] - eye[0], north[1] - eye[1], north[2] - eye[2])
    panel._earth_cam = EarthCam(eye=eye, look=look, up=up)
    panel._globe_hpr = (0.0, -90.0)
    apply_earth_cam(panel.cam, (earth.x, earth.y, earth.z), jd, panel._earth_cam)
    zone = get_earth()
    if zone is not None:
        zone.note_view(view_from_eye(eye, px_r=800.0, locked=True, look_ecef=look))
    if getattr(panel, "_globe_host", None) is not None:
        try:
            panel._sync_earth_globe(force=True)
        except Exception:
            pass
    panel.update()


def _earth_ready(panel: Any) -> bool:
    host = getattr(panel, "_globe_host", None)
    return bool(host is not None and (getattr(host, "ready", False) or getattr(host, "failed", False)))


def _wait_earth(panel: Any, app: Any, timeout_s: float = 90) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        if _earth_ready(panel):
            return bool(getattr(panel._globe_host, "ready", False))
        _pump(app, 250)
    return False


def _physical_reality(window: Any, app: Any, out: Path) -> list[dict[str, Any]]:
    from arelis.spatial.verbs import PhysicsAct
    from arelis.ui.world_host import apply_physics_act

    rows: list[dict[str, Any]] = []
    if not _ensure_reality(window, app, out):
        return [{"id": "R_open", "ok": False, "detail": "plate missing"}]
    panel = _solar(window)
    ww = window.world_window
    dest = out / "reality"
    dest.mkdir(parents=True, exist_ok=True)
    _screen_grab(ww, dest / "01_solar_open.png")
    rows.append({"id": "R_open", "ok": True, "detail": "solar plate"})

    for i, name in enumerate(("Mars", "Jupiter", "Saturn", "Earth"), 2):
        apply_physics_act(window, PhysicsAct(verb="travel", name=name))
        _pump(app, 2500)
        shot = dest / f"{i:02d}_{name.lower()}.png"
        _screen_grab(ww, shot)
        inspect = str(getattr(panel, "_inspect", "") or "")
        rows.append({"id": f"R_{name.lower()}", "ok": True, "detail": f"inspect={inspect}"})
        _note(out, f"traveled to {name} inspect={inspect}")

    try:
        from PySide6.QtCore import Qt

        panel._hotkey(int(Qt.Key.Key_Space))
        _pump(app, 300)
        rows.append({"id": "R_pause", "ok": True, "detail": "space"})
        panel._hotkey(int(Qt.Key.Key_Space))
        _pump(app, 200)
    except Exception as exc:
        rows.append({"id": "R_pause", "ok": False, "detail": type(exc).__name__})

    apply_physics_act(window, PhysicsAct(verb="overlay", flag="osculating", on=True))
    _pump(app, 400)
    _screen_grab(ww, dest / "06_orbits_on.png")
    apply_physics_act(window, PhysicsAct(verb="overlay", flag="osculating", on=False))
    _pump(app, 300)
    _screen_grab(ww, dest / "07_orbits_off.png")
    rows.append({"id": "R_orbits", "ok": True, "detail": "toggled"})
    return rows


def _physical_earth(window: Any, app: Any, out: Path) -> list[dict[str, Any]]:
    from arelis.earth.runtime import get_earth
    from arelis.spatial.verbs import PhysicsAct
    from arelis.ui.earth_find import apply_goto, open_find, type_find
    from arelis.ui.world_host import apply_physics_act

    rows: list[dict[str, Any]] = []
    dest = out / "earth"
    dest.mkdir(parents=True, exist_ok=True)
    if not _ensure_reality(window, app, out):
        return [{"id": "E_open", "ok": False, "detail": "no plate"}]
    apply_physics_act(window, PhysicsAct(verb="travel", name="Earth"))
    _pump(app, 3000)
    apply_physics_act(window, PhysicsAct(verb="enter_earth"))
    panel = _solar(window)
    ready = _wait_earth(panel, app, 120)
    host = getattr(panel, "_globe_host", None)
    _screen_grab(window.world_window, dest / "00_enter.png")
    rows.append(
        {
            "id": "E_enter",
            "ok": ready,
            "detail": f"ready={ready} host={host is not None}",
        }
    )
    _note(out, f"Earth enter ready={ready}")
    if not ready:
        return rows

    notes: list[str] = []
    from arelis.earth.gazetteer import resolve_place

    tokyo = resolve_place("Tokyo")
    if tokyo is None:
        return [*rows, {"id": "E_tokyo", "ok": False, "detail": "no Tokyo in gazetteer"}]
    for alt in LOD_LINES_M:
        _place_earth(panel, float(tokyo.lat), float(tokyo.lon), float(alt))
        _pump(app, 1400)
        name = f"lod_{alt}m.png"
        _screen_grab(window.world_window, dest / name)
        zone = get_earth()
        band = ""
        if zone is not None:
            try:
                band = str(getattr(zone, "band", "") or "")
            except Exception:
                band = ""
        line = f"{alt} m over Tokyo  band={band or '?'}"
        notes.append(line)
        rows.append({"id": f"E_lod_{alt}", "ok": True, "detail": line})
        _note(out, line)

    zone = get_earth()
    if zone is not None:
        zone.layers["flights"] = True
        zone.layers["satellites"] = True
        zone.layers["iss"] = True
        zone.live = True
        try:
            panel._sync_earth_globe(force=True)
        except Exception:
            pass
        _pump(app, 800)
        _screen_grab(window.world_window, dest / "layers_planes_sats_iss.png")
        rows.append({"id": "E_layers_live", "ok": True, "detail": "flights/sats/iss on"})

        try:
            zone.ride("norad:25544")
            _pump(app, 2000)
            _screen_grab(window.world_window, dest / "iss_ride.png")
            rows.append({"id": "E_iss", "ok": True, "detail": "ride ISS"})
            zone.stop_ride()
        except Exception as exc:
            rows.append({"id": "E_iss", "ok": False, "detail": type(exc).__name__})

    for chip in EARTH_CHIPS:
        try:
            panel._toggle_earth_chip(chip)
            _pump(app, 350)
            _screen_grab(window.world_window, dest / f"chip_{chip}_a.png")
            panel._toggle_earth_chip(chip)
            _pump(app, 250)
            _screen_grab(window.world_window, dest / f"chip_{chip}_b.png")
            rows.append({"id": f"E_chip_{chip}", "ok": True, "detail": "toggled"})
        except Exception as exc:
            rows.append({"id": f"E_chip_{chip}", "ok": False, "detail": type(exc).__name__})

    try:
        open_find(panel)
        _pump(app, 200)
        type_find(panel, ADDRESS_Q)
        _pump(app, 800)
        apply_goto(panel)
        _pump(app, 2500)
        _screen_grab(window.world_window, dest / "address_fifth_ave.png")
        rows.append({"id": "E_address", "ok": True, "detail": ADDRESS_Q})
        _note(out, f"Find → {ADDRESS_Q}")
    except Exception as exc:
        rows.append({"id": "E_address", "ok": False, "detail": type(exc).__name__})

    analysis = dest / "LOOK.md"
    analysis.write_text(
        "# Earth walk — what we saw\n\n"
        + "\n".join(f"- {n}" for n in notes)
        + "\n\nPublic address fly-in: 350 Fifth Avenue.\n"
        + "Layers toggled on then off: "
        + ", ".join(EARTH_CHIPS)
        + ".\n"
        + "ISS ride attempted. Planes/sats/ISS marks forced on once.\n",
        encoding="utf-8",
    )
    return rows


def _write_report(out: Path, rows: list[dict[str, Any]], extra: list[dict[str, Any]], token: str) -> None:
    passed = sum(1 for r in rows if r.get("ok"))
    failed = sum(1 for r in rows if r.get("ok") is False)
    lines = [
        f"# Live fifty  {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"Token: `{token}`",
        "",
        f"Chat turns: {passed} pass / {failed} fail / {len(rows)} total",
        "",
        "| # | id | result | ms | tools | why |",
        "|---|-----|--------|----|-------|-----|",
    ]
    for i, row in enumerate(rows, 1):
        mark = "PASS" if row.get("ok") else "FAIL"
        tools = ", ".join(row.get("tools") or []) or "—"
        why = _snip("; ".join(row.get("reasons") or []) or row.get("final") or row.get("detail") or "", 80)
        lines.append(
            f"| {i} | `{row.get('id')}` | {mark} | {row.get('ms', 0)} | {tools} | {why} |"
        )
    if extra:
        lines.extend(["", "## Physical Reality / Earth", ""])
        for row in extra:
            mark = "PASS" if row.get("ok") else "FAIL"
            lines.append(f"- {mark}  `{row.get('id')}`: {row.get('detail')}")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "report.json").write_text(
        json.dumps({"turns": rows, "physical": extra}, indent=2),
        encoding="utf-8",
    )


def _open_glass(config: dict[str, Any], cap: _Cap) -> tuple[Any, Any, Any, Any, Any]:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from arelis.llm import prefix_warmup_for, run_model_preflight, run_model_warmup
    from arelis.paths import app_icon_path
    from arelis.ui.app import ArelisWindow, BusBridge
    from arelis.ui.scale import configure_display_scale
    from arelis.ui.solar_gl import prepare_desktop_gl

    configure_native_windows()
    configure_display_scale(config)
    force_windows_qt_platform(os.environ)
    prepare_desktop_gl(os.environ)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Arelis")
    icon = app_icon_path()
    if icon.is_file():
        from PySide6.QtGui import QIcon

        app.setWindowIcon(QIcon(str(icon)))
    apply_theme(theme_from_config(config))
    app.setFont(__import__("arelis.ui.theme", fromlist=["app_font"]).app_font(load_fonts()))
    app.setStyleSheet(stylesheet())

    bus = EventBus()
    bridge = BusBridge()

    async def mirror(event: Event) -> None:
        bridge.feed(event)

    bus.subscribe(None, mirror)
    _bind_cap(bus, cap)
    seat = build_seat(config, profile="ui", bus=bus)
    loop = asyncio.new_event_loop()

    def loop_thread() -> None:
        asyncio.set_event_loop(loop)
        bus_task = loop.create_task(bus.run())
        loop.bus_task = bus_task  # type: ignore[attr-defined]
        loop.run_forever()

    thread = threading.Thread(target=loop_thread, name="arelis-asyncio", daemon=True)
    thread.start()
    seat.router.arm_warmup()

    async def _startup() -> None:
        try:
            await run_model_preflight(bus, seat.router.provider, config.get("models"))
            await run_model_warmup(
                bus, seat.router, prefix=prefix_warmup_for(config, seat.tools)
            )
        finally:
            seat.router.mark_warmup_done()

    asyncio.run_coroutine_threadsafe(_startup(), loop)
    window = ArelisWindow(
        config,
        bridge,
        loop,
        bus,
        None,
        store=seat.store,
        restore_session_id=None,
        router=seat.router,
    )
    window.show()
    window.raise_()
    window.activateWindow()
    window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
    return app, window, seat, loop, thread


def _wait_warmup(window: Any, app: Any, timeout_s: float = 180) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        pending = getattr(window.router, "warmup_pending", None)
        if callable(pending) and not pending():
            return
        if pending is None or pending is False:
            return
        _pump(app, 200)
    raise TimeoutError("model warmup did not finish")


def _run_turn(
    window: Any,
    app: Any,
    cap: _Cap,
    turn: Any,
    shot: Path,
    timeout_s: float,
) -> dict[str, Any]:
    if bool(getattr(window, "_turn_busy", False)):
        _cancel_hung(window, app)
    cap.reset()
    t0 = time.perf_counter()
    if "clipboard" in (turn.expect_tools or ()):
        try:
            from arelis.tools.clipboard import _write_windows_clipboard

            _write_windows_clipboard(f"board clipboard {turn.id}")
        except Exception:
            pass
    window.conversation.input.setText(turn.user)
    window._on_submit(turn.user, "fast")
    _pump(app, 80)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _click_allow(window):
            _pump(app, 80)
        _tools, _records, _final, done, _error = cap.snapshot()
        busy = bool(getattr(window, "_turn_busy", False))
        if done and not busy:
            break
        if turn.allow_no_tools and not busy and time.monotonic() - t0 > 2.5:
            # Closed verb — no assistant-done.
            break
        _pump(app, 120)
    tools, records, final, done, error = cap.snapshot()
    if not final:
        final = str(getattr(window.chat, "_last_assistant_body", "") or "")
    extra = _tools_from_receipt(final)
    for name in extra:
        if name not in tools:
            tools.append(name)
    if not done and not turn.allow_no_tools:
        _cancel_hung(window, app)
        tools, records, final2, done, error = cap.snapshot()
        if final2:
            final = final2
    forbidden = [t for t in tools if t in FORBIDDEN_TOOLS]
    ok, reasons = _score_turn(
        turn,
        tools_called=tools,
        tool_records=records,
        final_text=final,
    )
    if turn.allow_no_tools and not reasons:
        ok = True
    if forbidden:
        ok = False
        reasons = [*list(reasons), f"forbidden tools: {forbidden}"]
    if error and not final and not turn.allow_no_tools:
        ok = False
        reasons = [*list(reasons), error]
    if not done and not turn.allow_no_tools:
        ok = False
        reasons = [*list(reasons), f"turn did not finish in {timeout_s:.0f}s"]
    _screen_grab(window, shot)
    ms = int((time.perf_counter() - t0) * 1000)
    return {
        "id": turn.id,
        "ok": ok,
        "reasons": reasons,
        "tools": tools,
        "ms": ms,
        "final": _snip(final, 400),
        "user": turn.user,
        "screenshot": shot.name,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the 50-prompt live fifty")
    parser.add_argument("--only", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--skip-physical", action="store_true")
    args = parser.parse_args()
    token = str(args.token or "").strip() or _fresh_token()

    out = outputs_dir() / "live_fifty"
    out.mkdir(parents=True, exist_ok=True)
    prog = _load_progress(out)
    done_ids = set(prog.get("done") or [])
    if str(prog.get("token") or "") != token:
        done_ids = set()
        prog = {"done": [], "notes": [], "token": token}
    print(f"live fifty  {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}  token={token}", flush=True)

    config = load_config()
    ui_lock = PresenceLock(ui_lock_path(config))
    if not ui_lock.acquire():
        print("FAIL  Arelis glass is already open (ui lock held). Close it first.")
        return 2

    cap = _Cap()
    rows: list[dict[str, Any]] = list(prog.get("turns") or [])
    extra: list[dict[str, Any]] = list(prog.get("physical") or [])
    app = None
    window = None
    loop = None
    thread = None
    try:
        app, window, _seat, loop, thread = _open_glass(config, cap)
        _pump(app, 400)
        skipped = _skip_parked(window, app)
        if skipped:
            print(f"  skipped {skipped} parked confirm(s)", flush=True)
        print("  waiting for model warmup…", flush=True)
        _wait_warmup(window, app)
        try:
            from arelis.tools.comfy_lifecycle import ensure_comfy_running

            img = (config.get("tools") or {}).get("image") or {}
            fut = asyncio.run_coroutine_threadsafe(
                ensure_comfy_running(
                    str(img.get("comfy_url") or "http://127.0.0.1:8188"),
                    launch_command=str(img.get("launch_command") or ""),
                    launch_cwd=str(img.get("launch_cwd") or ""),
                    startup_timeout_s=float(img.get("startup_timeout_s") or 180),
                    auto_start=bool(img.get("auto_start")),
                ),
                loop,
            )
            comfy = fut.result(timeout=200)
            print(f"  comfy={comfy or 'off'}", flush=True)
        except Exception as exc:
            print(f"  comfy skip: {type(exc).__name__}", flush=True)

        print("  glass ready", flush=True)
        _note(out, f"glass ready token={token}")
        turns = live_fifty_turns(token=token)
        if args.only:
            want = {x.strip() for x in args.only.split(",") if x.strip()}
            turns = [t for t in turns if t.id in want]
        for i, turn in enumerate(turns, 1):
            if turn.id in done_ids:
                print(f"\n[{i}/{len(turns)}] {turn.id}  skip (breadcrumb)", flush=True)
                continue
            if getattr(turn, "new_chat", False):
                print("  new chat", flush=True)
                _new_chat(window, app)
            timeout = TIMEOUT_S.get(turn.id, 240)
            shot = out / f"{i:03d}_{turn.id}.png"
            print(f"\n[{i}/{len(turns)}] {turn.id}  ({timeout:.0f}s)", flush=True)
            print(f"  >> {_snip(turn.user, 120)}", flush=True)
            try:
                row = _run_turn(window, app, cap, turn, shot, timeout)
            except Exception as exc:
                row = {
                    "id": turn.id,
                    "ok": False,
                    "reasons": [f"{type(exc).__name__}: {exc}"],
                    "tools": [],
                    "ms": 0,
                    "final": "",
                    "user": turn.user,
                    "screenshot": shot.name,
                }
                traceback.print_exc()
            if turn.allow_no_tools:
                _drive_verb(window, turn.user, app)
            rows = [r for r in rows if r.get("id") != turn.id]
            rows.append(row)
            done_ids.add(turn.id)
            mark = "PASS" if row["ok"] else "FAIL"
            print(
                f"  {mark}  {row['ms']}ms  tools={row.get('tools') or '-'}  "
                f"{_snip('; '.join(row.get('reasons') or []) or row.get('final') or '', 160)}",
                flush=True,
            )
            _save_progress(
                out,
                {"done": sorted(done_ids), "token": token, "turns": rows, "physical": extra},
            )
            _write_report(out, rows, extra, token)
            if turn.id == "T28_lab" and not args.skip_physical:
                extra.extend(_physical_reality(window, app, out))
            if turn.id == "T37_enter" and not args.skip_physical:
                extra.extend(_physical_earth(window, app, out))
            _save_progress(
                out,
                {"done": sorted(done_ids), "token": token, "turns": rows, "physical": extra},
            )
            _write_report(out, rows, extra, token)
            _pump(app, 600)

        _write_report(out, rows, extra, token)
        passed = sum(1 for r in rows if r.get("ok"))
        print()
        print(f"summary  {passed}/{len(rows)} chat  wrote {out / 'report.md'}", flush=True)
        print("glass stays open. Close it when you have looked.", flush=True)
        if app is not None:
            app.setQuitOnLastWindowClosed(True)
            app.exec()
        return 0 if passed == len(rows) else 1
    finally:
        if window is not None:
            try:
                window._force_quit = True
                window.close()
            except Exception:
                pass
        if loop is not None:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        if thread is not None:
            thread.join(timeout=3)
        try:
            ui_lock.release()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
