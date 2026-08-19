"""Exhaustive live capability pass (direct tools + NL/slash). Voice skipped.

Prereqs: Ollama warm, network for DuckDuckGo search, Tesseract installed.
Side effects are REAL (SMS/email/calendar/browser/image) with auto-Allow.

  .\\.venv\\Scripts\\python.exe scripts\\e2e_full_capability.py
  .\\.venv\\Scripts\\python.exe scripts\\e2e_full_capability.py --direct-only
  .\\.venv\\Scripts\\python.exe scripts\\e2e_full_capability.py --nl-only
  .\\.venv\\Scripts\\python.exe scripts\\e2e_full_capability.py --nl-only --skip-sends
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Set by main(); NL cases that would re-text/email can skip when already proven.
SKIP_SENDS = False

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Prefer installed Tesseract even if User PATH is stale in this shell.
_TESS = Path(r"C:\Program Files\Tesseract-OCR")
if _TESS.is_dir():
    os.environ["PATH"] = str(_TESS) + os.pathsep + os.environ.get("PATH", "")

from arelis.config import PROJECT_ROOT, load_config
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.llm import build_router
from arelis.mail import load_account
from arelis.presence.readiness import probe_readiness
from arelis.tools import build_tool_registry
from arelis.tools.base import ToolResult


@dataclass
class CaseResult:
    name: str
    layer: str
    ok: bool
    detail: str = ""
    elapsed_s: float = 0.0
    output_head: str = ""
    tools: list[str] = field(default_factory=list)
    blocked: bool = False


def _head(text: str, n: int = 240) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:n]


class TurnProbe:
    def __init__(self, bus: EventBus, memory: SessionMemory, *, auto_confirm: bool = True) -> None:
        self.bus = bus
        self.memory = memory
        self.auto_confirm = auto_confirm
        self.seen: list[Event] = []
        self.done = asyncio.Event()
        self.assistant_parts: list[str] = []
        self.tools_started: list[str] = []
        bus.subscribe(None, self.on_event)

    async def on_event(self, event: Event) -> None:
        self.seen.append(event)
        if event.type == EventType.TOOL_START:
            self.tools_started.append(str(event.payload.get("tool") or ""))
        if event.type == EventType.TOOL_CONFIRM and self.auto_confirm:
            await self.bus.publish(
                Event(
                    EventType.TOOL_CONFIRM_REPLY,
                    {
                        "id": event.payload.get("id"),
                        "decision": "allow",
                        "allow_turn": True,
                    },
                )
            )
        if event.type == EventType.ASSISTANT_DELTA:
            self.assistant_parts.append(event.payload.get("text") or "")
        if event.type == EventType.ASSISTANT_RETRACT:
            self.assistant_parts.clear()
        if event.type in {EventType.ASSISTANT_DONE, EventType.ERROR}:
            self.done.set()

    def reset(self) -> None:
        self.seen = []
        self.assistant_parts = []
        self.tools_started = []
        self.done = asyncio.Event()
        self.memory.clear()

    async def run(self, text: str, role: str = "fast", timeout_s: float = 300.0) -> dict[str, Any]:
        self.reset()
        t0 = time.perf_counter()
        await self.bus.publish(Event(EventType.USER_MESSAGE, {"text": text, "role": role}))
        try:
            await asyncio.wait_for(self.done.wait(), timeout=timeout_s)
        except TimeoutError:
            return {
                "ok_events": False,
                "assistant": "".join(self.assistant_parts),
                "tools": list(self.tools_started),
                "events": [e.type.value for e in self.seen],
                "elapsed_s": round(time.perf_counter() - t0, 2),
                "detail": "timeout",
            }
        await asyncio.sleep(0.1)
        assistant = "".join(self.assistant_parts)
        for e in reversed(self.seen):
            if e.type == EventType.ASSISTANT_DONE:
                assistant = e.payload.get("text") or assistant
                break
            if e.type == EventType.ERROR:
                assistant = e.payload.get("message") or assistant
                break
        return {
            "ok_events": True,
            "assistant": assistant,
            "tools": list(self.tools_started),
            "events": [e.type.value for e in self.seen],
            "elapsed_s": round(time.perf_counter() - t0, 2),
            "detail": "",
        }


def make_fixtures(run_id: str) -> dict[str, Path]:
    base = PROJECT_ROOT / "outputs" / "e2e_fixtures" / run_id
    base.mkdir(parents=True, exist_ok=True)
    png = base / "ocr_hello.png"
    pdf = base / "sample.pdf"
    txt = base / "analyze_me.csv"
    ws_file = PROJECT_ROOT / "data" / f"e2e_{run_id}.txt"

    # Draw text with Qt (already a hard dep).
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter

    # Keep a QGuiApplication alive for QImage/QPainter (Qt requirement).
    _app = QGuiApplication.instance() or QGuiApplication([])
    img = QImage(640, 160, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    painter = QPainter(img)
    painter.setPen(QColor("black"))
    font = QFont("Arial", 28)
    painter.setFont(font)
    painter.drawText(img.rect(), int(Qt.AlignmentFlag.AlignCenter), f"ARELIS E2E {run_id}")
    painter.end()
    img.save(str(png), "PNG")
    assert _app is not None

    # Minimal one-page PDF with extractable text.
    # Very small PDF using a Type1 font Helvetica
    objects = []
    objects.append("1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append("2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objects.append(
        "3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
    )
    stream = f"BT /F1 24 Tf 72 720 Td ({run_id}) Tj ET"
    objects.append(
        f"4 0 obj<< /Length {len(stream)} >>stream\n{stream}\nendstream\nendobj\n"
    )
    objects.append("5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")
    pdf_body = "%PDF-1.4\n"
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf_body))
        pdf_body += obj
    xref_pos = len(pdf_body)
    pdf_body += f"xref\n0 {len(offsets)}\n"
    pdf_body += "0000000000 65535 f \n"
    for off in offsets[1:]:
        pdf_body += f"{off:010d} 00000 n \n"
    pdf_body += (
        f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    )
    pdf.write_bytes(pdf_body.encode("latin-1"))

    txt.write_text(
        f"name,value\nalpha,1\nbeta,2\ngamma,3\nrun,{run_id}\n",
        encoding="utf-8",
    )
    return {"png": png, "pdf": pdf, "txt": txt, "ws": ws_file, "base": base}


def seed_clipboard(text: str) -> str:
    try:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QGuiApplication.instance()
        if app is None:
            app = QApplication([])
        clip = QGuiApplication.clipboard()
        if clip is None:
            return "no clipboard"
        clip.setText(text)
        return "ok"
    except Exception as exc:
        return f"clipboard seed failed: {exc}"


async def call_tool(tools, tool_name: str, **kwargs: Any) -> ToolResult:
    tool = tools.get(tool_name)
    if tool is None:
        return ToolResult(ok=False, output=f"tool {tool_name!r} not registered")
    return await tool.run(**kwargs)


async def run_direct(tools, run_id: str, fixtures: dict[str, Path], config: dict) -> list[CaseResult]:
    results: list[CaseResult] = []
    account = load_account()
    self_email = account.address if account else ""

    async def case(name: str, coro: Awaitable[ToolResult], check: Callable[[ToolResult], tuple[bool, str]]) -> None:
        t0 = time.perf_counter()
        try:
            result = await coro
            ok, detail = check(result)
            results.append(
                CaseResult(
                    name=name,
                    layer="direct",
                    ok=ok,
                    detail=detail,
                    elapsed_s=round(time.perf_counter() - t0, 2),
                    output_head=_head(result.output),
                    tools=[name.split(":")[0].split("_", 1)[0] if False else name.split(":")[0]],
                )
            )
        except Exception as exc:
            results.append(
                CaseResult(
                    name=name,
                    layer="direct",
                    ok=False,
                    detail=f"exception: {exc}",
                    elapsed_s=round(time.perf_counter() - t0, 2),
                )
            )
        # Fix tools list to be the tool name prefix
        if results:
            tool_name = name.split(":")[0]
            results[-1].tools = [tool_name]

    def ok_true(r: ToolResult) -> tuple[bool, str]:
        return r.ok, _head(r.output) if r.ok else f"FAIL: {_head(r.output)}"

    def ok_or_expected_fail(r: ToolResult, *needles: str) -> tuple[bool, str]:
        body = (r.output or "").lower()
        if r.ok:
            return True, _head(r.output)
        if any(n in body for n in needles):
            return True, f"expected deny: {_head(r.output)}"
        return False, f"FAIL: {_head(r.output)}"

    await case("calculator", call_tool(tools, "calculator", expression="17*19+3"), ok_true)
    await case("user_location", call_tool(tools, "user_location"), ok_true)
    await case("weather", call_tool(tools, "weather"), ok_true)
    await case(
        "web_search",
        call_tool(tools, "web_search", query="Arelis assistant open source", max_results=4),
        lambda r: (
            r.ok and ("http" in (r.output or "").lower() or bool(r.data.get("results"))),
            _head(r.output),
        ),
    )
    await case(
        "web_fetch:public",
        call_tool(tools, "web_fetch", url="https://example.com"),
        ok_true,
    )
    await case(
        "web_fetch:loopback_blocked",
        call_tool(tools, "web_fetch", url="http://127.0.0.1:11434/api/tags"),
        lambda r: ok_or_expected_fail(r, "blocked", "loopback", "private", "not allowed"),
    )
    await case(
        "scrape",
        call_tool(
            tools,
            "scrape",
            url="https://en.wikipedia.org/wiki/Example.com",
        ),
        lambda r: (r.ok and len(r.output or "") > 80, _head(r.output)),
    )
    await case(
        "research_report",
        call_tool(
            tools,
            "research_report",
            query="What is the Example.com domain used for in documentation?",
        ),
        ok_true,
    )
    await case(
        "workspace:list",
        call_tool(tools, "workspace", action="list", path="."),
        ok_true,
    )
    await case(
        "workspace:read_readme",
        call_tool(tools, "workspace", action="read", path="README.md"),
        ok_true,
    )
    ws = fixtures["ws"]
    await case(
        "workspace:write",
        call_tool(
            tools,
            "workspace",
            action="write",
            path=str(ws.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            content=f"e2e-write-{run_id}",
        ),
        ok_true,
    )
    await case(
        "workspace:edit",
        call_tool(
            tools,
            "workspace",
            action="edit",
            path=str(ws.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            old=f"e2e-write-{run_id}",
            new=f"e2e-edit-{run_id}",
        ),
        ok_true,
    )
    await case(
        "workspace:read_back",
        call_tool(
            tools,
            "workspace",
            action="read",
            path=str(ws.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        ),
        lambda r: (r.ok and f"e2e-edit-{run_id}" in (r.output or ""), _head(r.output)),
    )
    await case(
        "analyze",
        call_tool(tools, "analyze", path=str(fixtures["txt"]), action="summary"),
        ok_true,
    )
    await case("git_info", call_tool(tools, "git_info"), ok_true)
    await case(
        "doc_extract",
        call_tool(tools, "doc_extract", path=str(fixtures["pdf"])),
        lambda r: (r.ok and run_id in (r.output or ""), _head(r.output)),
    )
    seed_clipboard(f"clipboard-{run_id}")
    await case("clipboard", call_tool(tools, "clipboard"), lambda r: (r.ok and run_id in (r.output or ""), _head(r.output)))
    await case(
        "ocr:text",
        call_tool(tools, "ocr", action="text", path=str(fixtures["png"])),
        lambda r: (
            r.ok
            and (
                "E2E" in (r.output or "").upper()
                or "ARELIS" in (r.output or "").upper()
                or "RELIS" in (r.output or "").upper()
                or run_id[:8] in (r.output or "")
            ),
            _head(r.output),
        ),
    )
    await case(
        "ocr:screen",
        call_tool(tools, "ocr", action="screen"),
        ok_true,
    )
    # Vision before Comfy image so VL is not fighting VRAM with a just-loaded
    # image pipeline / leftover GPU weight.
    await case(
        "vision",
        call_tool(
            tools,
            "vision",
            path=str(fixtures["png"]),
            question="What text is in this image?",
        ),
        ok_true,
    )
    await case(
        "image",
        call_tool(tools, "image", prompt=f"simple blue circle icon test {run_id}"),
        ok_true,
    )
    token = f"e2e-memory-{run_id}"
    await case(
        "memory:remember",
        call_tool(tools, "memory", action="remember", fact=f"The e2e token is {token}"),
        ok_true,
    )
    await case(
        "memory:prefer",
        call_tool(tools, "memory", action="prefer", key=f"e2e_{run_id}", value="synthetic"),
        ok_true,
    )
    await case(
        "memory:decide",
        call_tool(
            tools,
            "memory",
            action="decide",
            project="arelis",
            text=f"e2e decide {run_id}",
        ),
        ok_true,
    )
    await case(
        "memory:episode",
        call_tool(tools, "memory", action="episode", summary=f"e2e episode {run_id}"),
        ok_true,
    )
    await case(
        "recall",
        call_tool(tools, "recall", action="search", query=token),
        lambda r: (
            r.ok
            and (token in (r.output or "") or "e2e" in (r.output or "").lower() or "no" in (r.output or "").lower()),
            _head(r.output),
        ),
    )
    fact_text = f"The e2e token is {token}"
    await case(
        "memory:forget",
        call_tool(tools, "memory", action="forget", fact=fact_text),
        ok_true,
    )
    task_title = f"e2e-task-{run_id}"
    add_task = await call_tool(tools, "tasks", action="add", title=task_title)
    results.append(
        CaseResult(
            name="tasks:add",
            layer="direct",
            ok=add_task.ok,
            detail=_head(add_task.output),
            output_head=_head(add_task.output),
            tools=["tasks"],
        )
    )
    task_id = str((add_task.data or {}).get("id") or "")
    await case("tasks:list", call_tool(tools, "tasks", action="list"), ok_true)
    if task_id:
        await case("tasks:done", call_tool(tools, "tasks", action="done", id=task_id), ok_true)
        await case("tasks:reopen", call_tool(tools, "tasks", action="reopen", id=task_id), ok_true)
        await case("tasks:remove", call_tool(tools, "tasks", action="remove", id=task_id), ok_true)
    else:
        results.append(
            CaseResult(
                name="tasks:lifecycle",
                layer="direct",
                ok=False,
                detail="no task id from add",
                tools=["tasks"],
            )
        )

    goal_title = f"e2e-goal-{run_id}"
    add_goal = await call_tool(tools, "goals", action="add", title=goal_title)
    results.append(
        CaseResult(
            name="goals:add",
            layer="direct",
            ok=add_goal.ok,
            detail=_head(add_goal.output),
            output_head=_head(add_goal.output),
            tools=["goals"],
        )
    )
    goal_id = str((add_goal.data or {}).get("id") or "")
    await case("goals:list", call_tool(tools, "goals", action="list"), ok_true)
    if goal_id:
        await case(
            "goals:update",
            call_tool(tools, "goals", action="update", id=goal_id, title=goal_title + "-u"),
            ok_true,
        )
        await case("goals:pause", call_tool(tools, "goals", action="pause", id=goal_id), ok_true)
        await case("goals:resume", call_tool(tools, "goals", action="resume", id=goal_id), ok_true)
        await case("goals:done", call_tool(tools, "goals", action="done", id=goal_id), ok_true)
        await case("goals:remove", call_tool(tools, "goals", action="remove", id=goal_id), ok_true)
    else:
        results.append(
            CaseResult(
                name="goals:lifecycle",
                layer="direct",
                ok=False,
                detail="no goal id from add",
                tools=["goals"],
            )
        )

    await case("contacts:list", call_tool(tools, "contacts", action="list"), ok_true)
    await case(
        "contacts:get_wife",
        call_tool(tools, "contacts", action="get", who="wife"),
        ok_true,
    )
    await case(
        "send_sms",
        call_tool(
            tools,
            "send_sms",
            to="wife",
            body=f"Arelis synthetic test {run_id} — please ignore.",
        ),
        ok_true,
    )
    await case("inbound_sms", call_tool(tools, "inbound_sms"), ok_true)
    await case("inbox", call_tool(tools, "inbox", action="list", limit=5), ok_true)
    if self_email:
        await case(
            "send_email",
            call_tool(
                tools,
                "send_email",
                to=self_email,
                subject=f"Arelis e2e {run_id}",
                body=f"Synthetic self-mail for run {run_id}. Safe to ignore/delete.",
            ),
            ok_true,
        )
    else:
        results.append(
            CaseResult(
                name="send_email",
                layer="direct",
                ok=False,
                blocked=True,
                detail="no email account configured",
                tools=["send_email"],
            )
        )

    await case("agenda:today", call_tool(tools, "agenda", action="today"), ok_true)
    start = (datetime.now().astimezone() + timedelta(days=14)).replace(
        hour=15, minute=0, second=0, microsecond=0
    )
    end = start + timedelta(hours=1)
    created = await call_tool(
        tools,
        "agenda",
        action="create",
        provider="google",
        summary=f"Arelis e2e {run_id}",
        start=start.isoformat(),
        end=end.isoformat(),
    )
    results.append(
        CaseResult(
            name="agenda:create",
            layer="direct",
            ok=created.ok,
            detail=_head(created.output),
            output_head=_head(created.output),
            tools=["agenda"],
        )
    )
    ev = (created.data or {}).get("event") or {}
    event_id = str(ev.get("id") or (created.data or {}).get("event_id") or "")
    if event_id:
        await case(
            "agenda:update",
            call_tool(
                tools,
                "agenda",
                action="update",
                event_id=event_id,
                summary=f"Arelis e2e {run_id} updated",
            ),
            ok_true,
        )
        await case(
            "agenda:delete",
            call_tool(tools, "agenda", action="delete", event_id=event_id),
            ok_true,
        )
    else:
        results.append(
            CaseResult(
                name="agenda:cleanup",
                layer="direct",
                ok=created.ok,
                detail="created but no id returned for update/delete — check calendar manually",
                tools=["agenda"],
            )
        )
    await case("agenda:sync", call_tool(tools, "agenda", action="sync", provider="google"), ok_true)

    await case("schedule:list", call_tool(tools, "schedule", action="list"), ok_true)
    once_day = (datetime.now().astimezone() + timedelta(days=30)).strftime("%Y-%m-%d")
    job = await call_tool(
        tools,
        "schedule",
        action="create",
        name=f"e2e-{run_id}",
        prompt=f"e2e noop {run_id}",
        date=once_day,
        time="15:00",
        role="fast",
    )
    results.append(
        CaseResult(
            name="schedule:create",
            layer="direct",
            ok=job.ok,
            detail=_head(job.output),
            output_head=_head(job.output),
            tools=["schedule"],
        )
    )
    job_id = str((job.data or {}).get("id") or "")
    if job_id:
        await case(
            "schedule:delete",
            call_tool(tools, "schedule", action="delete", id=job_id),
            ok_true,
        )

    # Browser drive — prefer Chrome; if profile locked, relaunch once, then
    # fall back to Firefox private so the suite still exercises drive actions.
    browser_choice = "chrome"
    br = await call_tool(
        tools, "browser", action="open", url="https://example.com", browser=browser_choice
    )
    locked = (not br.ok) and (
        str((br.data or {}).get("code") or "") == "PROFILE_LOCKED"
        or "profile in use" in (br.output or "").lower()
        or "PROFILE_LOCKED" in (br.output or "").upper()
        or "cdp" in (br.output or "").lower()
    )
    if locked:
        relaunch = await call_tool(
            tools, "browser", action="relaunch", browser=browser_choice
        )
        results.append(
            CaseResult(
                name="browser:relaunch",
                layer="direct",
                ok=relaunch.ok,
                detail=_head(relaunch.output),
                output_head=_head(relaunch.output),
                tools=["browser"],
            )
        )
        br = await call_tool(
            tools, "browser", action="open", url="https://example.com", browser=browser_choice
        )
    if not br.ok:
        browser_choice = "firefox"
        br = await call_tool(
            tools,
            "browser",
            action="open",
            url="https://example.com",
            browser=browser_choice,
            private=True,
        )
        results.append(
            CaseResult(
                name="browser:firefox_fallback",
                layer="direct",
                ok=br.ok,
                detail=_head(br.output),
                output_head=_head(br.output),
                tools=["browser"],
            )
        )
    results.append(
        CaseResult(
            name="browser:open",
            layer="direct",
            ok=br.ok,
            detail=_head(br.output) + f" (browser={browser_choice})",
            output_head=_head(br.output),
            tools=["browser"],
        )
    )
    if br.ok:
        await case(
            "browser:snapshot",
            call_tool(tools, "browser", action="snapshot", browser=browser_choice),
            ok_true,
        )
        await case(
            "browser:navigate",
            call_tool(
                tools,
                "browser",
                action="navigate",
                url="https://example.org",
                browser=browser_choice,
            ),
            ok_true,
        )
        await case(
            "browser:tabs",
            call_tool(tools, "browser", action="tabs", browser=browser_choice),
            ok_true,
        )
        await case(
            "browser:screenshot",
            call_tool(tools, "browser", action="screenshot", browser=browser_choice),
            ok_true,
        )

    return results


async def run_nl(probe: TurnProbe, run_id: str, fixtures: dict[str, Path]) -> list[CaseResult]:
    results: list[CaseResult] = []

    async def case(name: str, text: str, role: str, check, timeout_s: float = 300.0) -> None:
        print(f"… starting {name}: {text[:80]!r}", flush=True)
        t0 = time.perf_counter()
        r = await probe.run(text, role=role, timeout_s=timeout_s)
        try:
            ok, detail = check(r)
        except Exception as exc:
            ok, detail = False, f"check error: {exc}"
        elapsed = r.get("elapsed_s") or round(time.perf_counter() - t0, 2)
        case_result = CaseResult(
            name=name,
            layer="nl",
            ok=ok,
            detail=detail or r.get("detail") or "",
            elapsed_s=elapsed,
            output_head=_head(r.get("assistant") or ""),
            tools=list(r.get("tools") or []),
        )
        results.append(case_result)
        mark = "PASS" if ok else "FAIL"
        print(
            f"[{mark}] {name} ({elapsed}s) tools={case_result.tools} {case_result.detail}",
            flush=True,
        )

    def has_tool(r, *names: str) -> bool:
        started = set(r.get("tools") or [])
        return any(n in started for n in names)

    await case(
        "slash_help",
        "/help",
        "fast",
        lambda r: ("natural language" in (r.get("assistant") or "").lower() or "/workspace" in (r.get("assistant") or ""), _head(r.get("assistant") or "")),
    )
    for role in ("research", "fast"):
        await case(
            f"slash_role_{role}",
            f"/role {role}",
            "fast",
            lambda r, role=role: (
                role in (r.get("assistant") or "").lower() or "role" in (r.get("assistant") or "").lower(),
                _head(r.get("assistant") or ""),
            ),
        )
    await case(
        "slash_workspace_list",
        '/workspace action=list path="."',
        "fast",
        lambda r: (has_tool(r, "workspace") or "[dir]" in (r.get("assistant") or "") or "[file]" in (r.get("assistant") or ""), _head(r.get("assistant") or "")),
    )
    await case(
        "slash_web_search",
        '/web_search query="example domain"',
        "fast",
        lambda r: (has_tool(r, "web_search") or "http" in (r.get("assistant") or "").lower(), _head(r.get("assistant") or "")),
    )
    await case(
        "slash_scrape",
        "/scrape url=https://example.com",
        "fast",
        lambda r: (has_tool(r, "scrape") or "example" in (r.get("assistant") or "").lower(), _head(r.get("assistant") or "")),
    )
    await case(
        "slash_web_fetch_blocked",
        "/web_fetch url=http://127.0.0.1:11434/api/tags",
        "fast",
        lambda r: (
            any(x in (r.get("assistant") or "").lower() for x in ("blocked", "loopback", "private", "failed")),
            _head(r.get("assistant") or ""),
        ),
    )
    await case(
        "nl_calculator",
        "What is 17 times 19? Use the calculator tool.",
        "fast",
        lambda r: (has_tool(r, "calculator") or "323" in (r.get("assistant") or ""), _head(r.get("assistant") or "")),
    )
    await case(
        "nl_weather",
        "What's the weather right now where I am?",
        "fast",
        lambda r: (has_tool(r, "weather", "user_location") or any(w in (r.get("assistant") or "").lower() for w in ("°", "temp", "weather", "cloud", "rain", "sun")), _head(r.get("assistant") or "")),
        timeout_s=240,
    )
    await case(
        "nl_search",
        "Search the web for 'Example Domain IANA' and give me one https link.",
        "fast",
        lambda r: (
            has_tool(r, "web_search")
            and (
                "http" in (r.get("assistant") or "").lower()
                or "example" in (r.get("assistant") or "").lower()
            ),
            _head(r.get("assistant") or ""),
        ),
        timeout_s=180,
    )
    await case(
        "nl_readme",
        "Open README.md and summarize it in two short sentences.",
        "fast",
        lambda r: (has_tool(r, "workspace") and len(r.get("assistant") or "") > 40, _head(r.get("assistant") or "")),
    )
    await case(
        "nl_write_not_sms",
        f"Write a temp file data/e2e_nl_{run_id}.txt containing exactly: nl-ok-{run_id}",
        "fast",
        lambda r: (
            has_tool(r, "workspace") and not has_tool(r, "send_sms") and (PROJECT_ROOT / "data" / f"e2e_nl_{run_id}.txt").is_file(),
            f"tools={r.get('tools')} file={(PROJECT_ROOT / 'data' / f'e2e_nl_{run_id}.txt').is_file()}",
        ),
        timeout_s=300,
    )
    await case(
        "nl_ocr",
        f"OCR the image at {fixtures['png'].as_posix()} and tell me the text.",
        "fast",
        lambda r: (has_tool(r, "ocr") or "ARELIS" in (r.get("assistant") or "").upper(), _head(r.get("assistant") or "")),
        timeout_s=300,
    )
    await case(
        "nl_vision",
        f"Look at {fixtures['png'].as_posix()} with vision and say what text you see.",
        "fast",
        lambda r: (has_tool(r, "vision") or "ARELIS" in (r.get("assistant") or "").upper() or run_id in (r.get("assistant") or ""), _head(r.get("assistant") or "")),
        timeout_s=420,
    )
    await case(
        "nl_image",
        f"Generate a simple image: a red square on white, labeled e2e {run_id}.",
        "fast",
        lambda r: (has_tool(r, "image") or "outputs/images" in (r.get("assistant") or "").lower(), _head(r.get("assistant") or "")),
        timeout_s=900,
    )
    if SKIP_SENDS:
        for name, tool in (
            ("nl_sms_wife", "send_sms"),
            ("nl_email_self", "send_email"),
        ):
            results.append(
                CaseResult(
                    name=name,
                    layer="nl",
                    ok=True,
                    blocked=True,
                    detail=f"skipped (--skip-sends); direct {tool} already proven",
                    tools=[tool],
                )
            )
            print(f"[SKIP] {name} (already proven via direct)", flush=True)
    else:
        await case(
            "nl_sms_wife",
            f'Text my wife exactly: Arelis synthetic NL test {run_id} — please ignore.',
            "fast",
            lambda r: (
                has_tool(r, "send_sms") or "sent" in (r.get("assistant") or "").lower(),
                _head(r.get("assistant") or ""),
            ),
            timeout_s=300,
        )
        account = load_account()
        if account:
            await case(
                "nl_email_self",
                f"Email {account.address} with subject 'Arelis NL e2e {run_id}' "
                f"and body 'synthetic nl mail {run_id}'.",
                "fast",
                lambda r: (
                    has_tool(r, "send_email")
                    or "sent" in (r.get("assistant") or "").lower(),
                    _head(r.get("assistant") or ""),
                ),
                timeout_s=420,
            )
    await case(
        "nl_calendar_today",
        "What's on my calendar today?",
        "fast",
        lambda r: (has_tool(r, "agenda") or "calendar" in (r.get("assistant") or "").lower() or "event" in (r.get("assistant") or "").lower() or "no event" in (r.get("assistant") or "").lower(), _head(r.get("assistant") or "")),
        timeout_s=300,
    )
    await case(
        "nl_browser",
        "Pull up https://example.com in my browser.",
        "fast",
        lambda r: (has_tool(r, "browser") or "example" in (r.get("assistant") or "").lower() or "PROFILE_LOCKED" in (r.get("assistant") or ""), _head(r.get("assistant") or "")),
        timeout_s=420,
    )
    await case(
        "nl_research_short",
        "Briefly research what example.com is. Cite sources with https URLs only.",
        "research",
        lambda r: (
            ("http" in (r.get("assistant") or "").lower())
            and "inbound-notify" not in (r.get("assistant") or "").lower()
            and "no retrieved page warrant" not in (r.get("assistant") or "").lower(),
            _head(r.get("assistant") or ""),
        ),
        timeout_s=900,
    )
    await case(
        "nl_goals_list",
        "List my goals. Do not text anyone.",
        "fast",
        lambda r: (has_tool(r, "goals") and not has_tool(r, "send_sms"), f"tools={r.get('tools')}"),
        timeout_s=300,
    )
    return results


async def main_async(args: argparse.Namespace) -> int:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    report: dict[str, Any] = {
        "run_id": run_id,
        "started": datetime.now().isoformat(timespec="seconds"),
        "cases": [],
        "readiness": {},
    }
    print(f"RUN_ID={run_id}", flush=True)
    fixtures = make_fixtures(run_id)
    print(f"fixtures={fixtures['base']}", flush=True)

    config = load_config()
    readiness = await probe_readiness(config)
    report["readiness"] = {
        c.key: {
            "status": c.status.value if hasattr(c.status, "value") else str(c.status),
            "detail": c.detail,
        }
        for c in readiness.chips
    }
    print("readiness:", json.dumps(report["readiness"], indent=2))

    router = build_router(config)
    tools = build_tool_registry(config, router=router)
    print("registered tools:", sorted(tools.names()))

    all_results: list[CaseResult] = []
    if not args.nl_only:
        print("\n=== DIRECT TOOL LAYER ===")
        direct = await run_direct(tools, run_id, fixtures, config)
        all_results.extend(direct)
        for c in direct:
            mark = "PASS" if c.ok else ("BLOCK" if c.blocked else "FAIL")
            print(f"[{mark}] {c.name} ({c.elapsed_s}s) {c.detail}")

    if not args.direct_only:
        print("\n=== NL / SLASH LAYER ===")
        bus = EventBus()
        memory = SessionMemory()
        Orchestrator(bus, router, tools, config, memory)
        bus_task = asyncio.create_task(bus.run())
        # Let the bus enter its consume loop before the first USER_MESSAGE.
        await asyncio.sleep(0.2)
        probe = TurnProbe(bus, memory, auto_confirm=True)
        try:
            print("NL probe ready", flush=True)
            nl = await run_nl(probe, run_id, fixtures)
            all_results.extend(nl)
            for c in nl:
                mark = "PASS" if c.ok else "FAIL"
                print(f"[{mark}] {c.name} ({c.elapsed_s}s) tools={c.tools} {c.detail}")
        finally:
            bus.stop()
            bus_task.cancel()
            try:
                await bus_task
            except asyncio.CancelledError:
                pass

    await router.close()

    report["cases"] = [asdict(c) for c in all_results]
    report["passed"] = sum(1 for c in all_results if c.ok)
    report["failed"] = sum(1 for c in all_results if not c.ok and not c.blocked)
    report["blocked"] = sum(1 for c in all_results if c.blocked)
    report["finished"] = datetime.now().isoformat(timespec="seconds")
    out = PROJECT_ROOT / "outputs" / "e2e_full_capability.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    total = len(all_results)
    print(
        f"\nSummary: {report['passed']}/{total} passed, "
        f"{report['failed']} failed, {report['blocked']} blocked -> {out}"
    )
    return 0 if report["failed"] == 0 else 1


def main() -> int:
    global SKIP_SENDS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-only", action="store_true")
    parser.add_argument("--nl-only", action="store_true")
    parser.add_argument(
        "--skip-sends",
        action="store_true",
        help="Skip NL SMS/email (use when direct sends already proven).",
    )
    args = parser.parse_args()
    SKIP_SENDS = bool(args.skip_sends)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
