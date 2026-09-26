"""Open the Arelis glass and run the 20-prompt live board.

Types each prompt, clicks Allow, scores tools + answer, writes
outputs/live_board/. Does not print phones, addresses, or names.
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

# Real desktop glass. Do not inherit an offscreen pytest leftover.
os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.pop("ARELIS_ALLOW_OFFSCREEN", None)
os.environ["ARELIS_SOLAR_GL"] = "0"

from arelis.config import load_config
from arelis.contacts import resolve_contact
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.seat import build_seat
from arelis.eval.conversation import ToolCallRecord, _score_turn
from arelis.eval.live_board import (
    FORBIDDEN_TOOLS,
    KEEP_MARK,
    SCRATCH_MARK,
    TIMEOUT_S,
    live_board_turns,
)
from arelis.mail import load_account, owner_inbox
from arelis.paths import outputs_dir
from arelis.presence.lock import PresenceLock, ui_lock_path
from arelis.sms_android import load_sms_account
from arelis.ui.launch import force_windows_qt_platform
from arelis.ui.theme import apply_theme, load_fonts, stylesheet, theme_from_config
from arelis.ui.window_resize import configure_native_windows


def _snip(text: str, n: int = 220) -> str:
    one = " ".join((text or "").split())
    one = _EMAIL.sub("[inbox]", one)
    one = one.encode("ascii", "replace").decode("ascii")
    return one if len(one) <= n else one[: n - 1] + "..."


def _pump(app: Any, ms: int = 50) -> None:
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < ms:
        app.processEvents()
        time.sleep(0.01)


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
            self.pending: dict[str, ToolCallRecord] = {}

    def snapshot(self) -> tuple[list[str], list[ToolCallRecord], str, bool, str]:
        with self.lock:
            return (
                list(self.tools),
                list(self.records),
                self.final,
                self.done,
                self.error,
            )


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
            cap.pending[name] = rec

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
    if confirm is None:
        return False
    if not window.conversation.confirm_open():
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


def _grab(window: Any, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    pix = window.grab()
    pix.save(str(dest))


def _verify_artifacts(token: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    out = outputs_dir()
    note = out / "live_board" / f"{token.lower()}-log.md"
    rows.append(
        {
            "check": "workspace_note",
            "ok": note.is_file() and token in note.read_text(encoding="utf-8", errors="replace"),
            "detail": str(note) if note.is_file() else "missing",
        }
    )
    csv_hits = []
    for folder in (out / "live_board", out / "documents"):
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.csv"):
            if token.lower() in path.name.lower():
                csv_hits.append(path)
    csv_ok = any(
        token in p.read_text(encoding="utf-8", errors="replace") for p in csv_hits
    )
    rows.append(
        {
            "check": "workspace_csv",
            "ok": csv_ok,
            "detail": csv_hits[-1].name if csv_hits else "missing",
        }
    )
    docs = out / "documents"
    md_hits = []
    pdf_hits = []
    if docs.is_dir():
        for path in docs.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            if token.lower() in name or "board log" in name or "live board" in name:
                if path.suffix.lower() == ".md":
                    md_hits.append(path)
                if path.suffix.lower() == ".pdf":
                    pdf_hits.append(path)
    rows.append(
        {
            "check": "document_md",
            "ok": bool(md_hits),
            "detail": md_hits[-1].name if md_hits else "missing",
        }
    )
    rows.append(
        {
            "check": "document_pdf",
            "ok": bool(pdf_hits),
            "detail": pdf_hits[-1].name if pdf_hits else "missing",
        }
    )
    research = out / "research"
    report_hits = []
    if research.is_dir():
        report_hits = sorted(research.glob("*.md"), key=lambda p: p.stat().st_mtime)
    rows.append(
        {
            "check": "research_report_file",
            "ok": bool(report_hits),
            "detail": report_hits[-1].name if report_hits else "missing",
        }
    )
    return rows


async def _verify_calendar(tools: Any, token: str) -> dict[str, Any]:
    agenda = tools.get("agenda")
    if agenda is None:
        return {"check": "calendar_keep", "ok": False, "detail": "no agenda tool"}
    try:
        result = await agenda.run(action="list")
    except Exception as exc:
        return {"check": "calendar_keep", "ok": False, "detail": type(exc).__name__}
    blob = str(result.output or "")
    data = getattr(result, "data", None) or {}
    events = data.get("events") or []
    keep = any(
        token.lower() in str(ev.get("summary") or "").lower()
        and KEEP_MARK in str(ev.get("summary") or "").lower()
        for ev in events
        if isinstance(ev, dict)
    )
    scratch = any(
        SCRATCH_MARK in str(ev.get("summary") or "").lower()
        and token.lower() in str(ev.get("summary") or "").lower()
        for ev in events
        if isinstance(ev, dict)
    )
    if not keep:
        keep = KEEP_MARK in blob.lower() and token.lower() in blob.lower()
        scratch = scratch or (
            SCRATCH_MARK in blob.lower() and token.lower() in blob.lower()
        )
    return {
        "check": "calendar_keep",
        "ok": bool(result.ok and keep and not scratch),
        "detail": (
            "stay present, toss gone"
            if keep and not scratch
            else f"stay={keep} toss={scratch}"
        ),
    }


def _env_line() -> dict[str, bool]:
    mail = load_account()
    sms = load_sms_account()
    me = resolve_contact("me")
    wife = resolve_contact("wife") or resolve_contact("my wife")
    return {
        "sms": bool(sms),
        "mail": bool(mail),
        "owner_inbox": bool(owner_inbox(mail)),
        "me": bool(me and me.digits),
        "wife": bool(wife),
    }


def _write_report(
    out: Path,
    rows: list[dict[str, Any]],
    extra: list[dict[str, Any]],
    token: str,
) -> None:
    passed = sum(1 for r in rows if r.get("ok"))
    failed = sum(1 for r in rows if r.get("ok") is False)
    lines = [
        f"# Live glass board  {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"Token: `{token}` — search Gmail, Messages, and Calendar for this.",
        "",
        f"Turns: {passed} pass / {failed} fail / {len(rows)} total",
        "",
        "| # | id | result | ms | tools | why |",
        "|---|-----|--------|----|-------|-----|",
    ]
    for i, row in enumerate(rows, 1):
        mark = "PASS" if row.get("ok") else "FAIL"
        tools = ", ".join(row.get("tools") or []) or "—"
        why = _snip("; ".join(row.get("reasons") or []) or row.get("final") or "", 80)
        lines.append(
            f"| {i} | `{row.get('id')}` | {mark} | {row.get('ms', 0)} | {tools} | {why} |"
        )
    if extra:
        lines.extend(["", "## Side-effect checks", ""])
        for row in extra:
            mark = "PASS" if row.get("ok") else "FAIL"
            lines.append(f"- {mark}  {row.get('check')}: {row.get('detail')}")
    lines.extend(
        [
            "",
            "## What you should see",
            "",
            f"- Gmail: subject `Arelis board {token}`",
            f"- File: `outputs/live_board/{token.lower()}-rows.csv`",
            f"- Calendar (phone): `Arelis stay {token}` tomorrow 3:00 PM",
            f"- Calendar: `Arelis toss {token}` should be gone",
            "",
        ]
    )
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "report.json").write_text(
        json.dumps({"turns": rows, "side_effects": extra}, indent=2),
        encoding="utf-8",
    )


def _open_glass(config: dict[str, Any], cap: _Cap) -> tuple[Any, Any, Any, Any, Any]:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from arelis.llm import prefix_warmup_for, run_model_preflight, run_model_warmup
    from arelis.paths import app_icon_path
    from arelis.ui.app import ArelisWindow, BusBridge
    from arelis.ui.scale import configure_display_scale

    configure_native_windows()
    configure_display_scale(config)
    force_windows_qt_platform(os.environ)
    from arelis.ui.solar_gl import prepare_desktop_gl

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
    cap.reset()
    t0 = time.perf_counter()
    window.conversation.input.setText(turn.user)
    window._on_submit(turn.user, "fast")
    _pump(app, 80)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _click_allow(window):
            _pump(app, 80)
        tools, records, final, done, error = cap.snapshot()
        busy = bool(getattr(window, "_turn_busy", False))
        if done and not busy:
            break
        _pump(app, 120)
    tools, records, final, done, error = cap.snapshot()
    if not final:
        final = str(getattr(window.chat, "_last_assistant_body", "") or "")
    forbidden = [t for t in tools if t in FORBIDDEN_TOOLS]
    ok, reasons = _score_turn(
        turn,
        tools_called=tools,
        tool_records=records,
        final_text=final,
    )
    if forbidden:
        ok = False
        reasons = [*list(reasons), f"forbidden tools: {forbidden}"]
    if error and not final:
        ok = False
        reasons = [*list(reasons), error]
    if not done:
        ok = False
        reasons = [*list(reasons), f"turn did not finish in {timeout_s:.0f}s"]
    _grab(window, shot)
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


def _fresh_token() -> str:
    return "BRD-" + datetime.now().strftime("%H%M%S")


def _run_turns(
    *,
    window: Any,
    app: Any,
    cap: _Cap,
    seat: Any,
    loop: Any,
    out: Path,
    token: str,
    only: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    extra: list[dict[str, Any]] = []
    turns = live_board_turns(token=token)
    if only:
        want = {x.strip() for x in only.split(",") if x.strip()}
        turns = [t for t in turns if t.id in want]
    for i, turn in enumerate(turns, 1):
        timeout = TIMEOUT_S.get(turn.id, 240)
        shot = out / f"{i:02d}_{turn.id}.png"
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
        rows.append(row)
        mark = "PASS" if row["ok"] else "FAIL"
        print(
            f"  {mark}  {row['ms']}ms  tools={row['tools'] or '-'}  "
            f"{_snip('; '.join(row['reasons']) or row['final'], 160)}",
            flush=True,
        )
        _write_report(out, rows, extra, token)
        _pump(app, 800)

    extra.extend(_verify_artifacts(token))
    if seat is not None:
        fut = asyncio.run_coroutine_threadsafe(_verify_calendar(seat.tools, token), loop)
        try:
            extra.append(fut.result(timeout=60))
        except Exception as exc:
            extra.append(
                {
                    "check": "calendar_keep",
                    "ok": False,
                    "detail": type(exc).__name__,
                }
            )
    extra.append({"check": "env", "ok": True, "detail": {k: v for k, v in _env_line().items()}})
    _write_report(out, rows, extra, token)
    return rows, extra


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the 20-prompt live glass board")
    parser.add_argument("--only", default="", help="Comma-separated turn ids")
    parser.add_argument("--token", default="", help="Search token for side effects")
    parser.add_argument(
        "--until-pass",
        action="store_true",
        help="Rerun the board with a fresh token until 20/20",
    )
    parser.add_argument("--max-attempts", type=int, default=8)
    args = parser.parse_args()
    token = str(args.token or "").strip() or _fresh_token()

    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    out = outputs_dir() / "live_board"
    out.mkdir(parents=True, exist_ok=True)
    env = _env_line()
    print(f"live glass board  {stamp}  token={token}", flush=True)
    print(
        f"  sms={env['sms']} mail={env['mail']} inbox={env['owner_inbox']} "
        f"me={env['me']} wife={env['wife']}",
        flush=True,
    )
    if not env["owner_inbox"]:
        print("WARN  missing owner inbox — the email turn will fail")

    config = load_config()
    ui_lock = PresenceLock(ui_lock_path(config))
    if not ui_lock.acquire():
        print("FAIL  Arelis glass is already open (ui lock held).")
        print("      Close that window, then re-run this board so measurement")
        print("      can attach to the same process that types the prompts.")
        return 2
    cap = _Cap()
    app = None
    window = None
    loop = None
    thread = None
    seat = None
    try:
        app, window, seat, loop, thread = _open_glass(config, cap)
        _pump(app, 400)
        skipped = _skip_parked(window, app)
        if skipped:
            print(f"  skipped {skipped} parked confirm(s)", flush=True)
        print("  waiting for model warmup…", flush=True)
        _wait_warmup(window, app)
        print("  glass ready", flush=True)
        max_attempts = max(1, int(args.max_attempts or 1))
        if not args.until_pass:
            max_attempts = 1
        exit_code = 1
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                token = _fresh_token()
                print(f"\n=== attempt {attempt}/{max_attempts}  token={token} ===", flush=True)
            else:
                print(f"\n=== attempt {attempt}/{max_attempts}  token={token} ===", flush=True)
            rows, _extra = _run_turns(
                window=window,
                app=app,
                cap=cap,
                seat=seat,
                loop=loop,
                out=out,
                token=token,
                only=args.only,
            )
            if window is not None:
                _grab(window, out / "99_final.png")
            passed = sum(1 for r in rows if r.get("ok"))
            print()
            print(
                f"summary  {passed}/{len(rows)} turns  token={token}  "
                f"wrote {out / 'report.md'}",
                flush=True,
            )
            if passed == len(rows) and rows:
                exit_code = 0
                break
            if attempt < max_attempts:
                print("retrying with a new token and new prompts…", flush=True)
                _pump(app, 1200)
        print("glass stays open so you can read the thread. Close it when done.", flush=True)
        if app is not None:
            app.setQuitOnLastWindowClosed(True)
            app.exec()
        return exit_code
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
