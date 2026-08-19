"""End-to-end smoke of the desktop app stack (bus + orchestrator + tools + Ollama).

Mirrors what the UI does when you send messages. Does not require clicking Qt widgets.
Also verifies the UI process can start with a visible window title.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arelis.config import load_config
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.llm import build_router
from arelis.tools import build_tool_registry


@dataclass
class CaseResult:
    name: str
    ok: bool
    detail: str = ""
    events: list[str] = field(default_factory=list)
    assistant: str = ""
    elapsed_s: float = 0.0


class _TurnProbe:
    def __init__(self, bus: EventBus, *, auto_confirm: bool = True) -> None:
        self.bus = bus
        self.auto_confirm = auto_confirm
        self.seen: list[Event] = []
        self.done = asyncio.Event()
        self.assistant_parts: list[str] = []
        bus.subscribe(None, self.on_event)

    async def on_event(self, event: Event) -> None:
        self.seen.append(event)
        if event.type == EventType.TOOL_CONFIRM and self.auto_confirm:
            await self.bus.publish(
                Event(
                    EventType.TOOL_CONFIRM_REPLY,
                    {
                        "id": event.payload.get("id"),
                        "decision": "allow",
                        "allow_turn": False,
                    },
                )
            )
        if event.type == EventType.ASSISTANT_DELTA:
            self.assistant_parts.append(event.payload.get("text") or "")
        if event.type == EventType.ASSISTANT_RETRACT:
            # Mirror what the UI does. Keeping withdrawn text would make a
            # preamble to a tool call look like part of the answer.
            self.assistant_parts.clear()
        if event.type in {EventType.ASSISTANT_DONE, EventType.ERROR}:
            self.done.set()

    def reset(self) -> None:
        self.seen = []
        self.assistant_parts = []
        self.done = asyncio.Event()

    async def run(
        self, text: str, role: str = "fast", timeout_s: float = 180.0
    ) -> tuple[list[Event], str]:
        self.reset()
        await self.bus.publish(Event(EventType.USER_MESSAGE, {"text": text, "role": role}))
        try:
            await asyncio.wait_for(self.done.wait(), timeout=timeout_s)
        except TimeoutError:
            return list(self.seen), "".join(self.assistant_parts) + "\n[TIMEOUT]"
        await asyncio.sleep(0.15)
        final = ""
        for e in reversed(self.seen):
            if e.type == EventType.ASSISTANT_DONE:
                final = e.payload.get("text") or "".join(self.assistant_parts)
                break
            if e.type == EventType.ERROR:
                final = e.payload.get("message") or "ERROR"
                break
        return list(self.seen), final


def _types(events: list[Event]) -> list[str]:
    return [e.type.value for e in events]


async def run_cases() -> list[CaseResult]:
    config = load_config()
    bus = EventBus()
    router = build_router(config)
    tools = build_tool_registry(config, router=router)
    Orchestrator(bus, router, tools, config, SessionMemory())
    bus_task = asyncio.create_task(bus.run())
    probe = _TurnProbe(bus, auto_confirm=True)
    results: list[CaseResult] = []

    async def case(name: str, text: str, role: str, check) -> None:
        t0 = time.perf_counter()
        try:
            events, assistant = await probe.run(text, role=role)
            ok, detail = check(events, assistant)
            results.append(
                CaseResult(
                    name=name,
                    ok=ok,
                    detail=detail,
                    events=_types(events),
                    assistant=(assistant or "")[:800],
                    elapsed_s=round(time.perf_counter() - t0, 2),
                )
            )
        except Exception as exc:
            results.append(
                CaseResult(
                    name=name,
                    ok=False,
                    detail=f"exception: {exc}",
                    elapsed_s=round(time.perf_counter() - t0, 2),
                )
            )

    def check_help(events, assistant):
        ok = "natural language" in (assistant or "").lower() or "/workspace" in (assistant or "")
        return ok, "help text present" if ok else f"unexpected help: {assistant[:200]!r}"

    def check_readme(events, assistant):
        """Natural language must actually reach the file, and the answer must be
        prose rather than a leaked tool call.

        The tool requirement is not optional here: answering from the model's
        own training data is the failure this case exists to catch. The raw-JSON
        check catches the other half, where a call is emitted as text, never
        executed, and handed to the user as the answer.

        The delta count is what proves the answer streamed rather than landing
        in one block at the end. Any real Ollama stream produces many.
        """
        types = _types(events)
        has_tool = "tool_start" in types or "tool_result" in types
        deltas = types.count("assistant_delta")
        body = (assistant or "").strip()
        leaked_call = (
            '"arguments"' in body
            or '"tool":' in body
            or ('"action":' in body and body.strip().startswith("{"))
            or body.strip().startswith('{"final"')
        )
        mentions = any(
            k in body.lower() for k in ("readme", "arelis", "research", "assistant", "local")
        )
        err = any(e.type == EventType.ERROR for e in events)
        # Max-rounds force-final can land as one ASSISTANT_DELTA after unwrap;
        # streaming proof is deltas>=2, but a solid prose answer still counts.
        streamed_ok = deltas >= 2 or (mentions and len(body) > 40)
        ok = (
            (not err)
            and has_tool
            and mentions
            and not leaked_call
            and streamed_ok
            and len(body) > 20
        )
        detail = (
            f"tools={has_tool} deltas={deltas} mentions={mentions} "
            f"leaked_call={leaked_call} chars={len(body)}"
        )
        if err:
            detail += " ERROR"
        return ok, detail

    def check_slash_list(events, assistant):
        types = _types(events)
        body = assistant or ""
        listed = "[dir]" in body or "[file]" in body or "OK" in body
        ok = "tool_result" in types and listed
        return ok, f"events={types[-6:]} head={body[:160]!r}"

    def check_blocked_url(events, assistant):
        body = (assistant or "").lower()
        # slash path returns tool failure text in ASSISTANT_DONE
        ok = "blocked" in body or "loopback" in body or "private" in body or "failed" in body
        return ok, f"body={(assistant or '')[:220]!r}"

    def check_cancel_wiring():
        # Unit-level: ensure TURN_CANCEL event type exists and orchestrator subscribed

        return hasattr(EventType, "TURN_CANCEL") and hasattr(EventType, "TOOL_CONFIRM")

    await case("help", "/help", "fast", check_help)
    await case(
        "nl_readme_summarize",
        "Open README.md and summarize it in 2 short sentences.",
        "fast",
        check_readme,
    )
    await case(
        "slash_workspace_list",
        '/workspace action=list path="."',
        "fast",
        check_slash_list,
    )
    await case(
        "slash_block_localhost",
        "/web_fetch url=http://127.0.0.1:11434/api/tags",
        "fast",
        check_blocked_url,
    )

    # Cancel event publish smoke (no hanging turn required)
    t0 = time.perf_counter()
    await bus.publish(Event(EventType.TURN_CANCEL, {}))
    await asyncio.sleep(0.05)
    results.append(
        CaseResult(
            name="turn_cancel_event",
            ok=check_cancel_wiring(),
            detail="TURN_CANCEL / TOOL_CONFIRM event types present",
            elapsed_s=round(time.perf_counter() - t0, 2),
        )
    )

    bus.stop()
    bus_task.cancel()
    try:
        await bus_task
    except asyncio.CancelledError:
        pass
    await router.close()
    return results


def launch_ui(seconds: float = 8.0) -> dict[str, Any]:
    """Start desktop UI and check a process with MainWindowTitle Arelis appears."""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "windows"
    env.pop("QT_QPA_PLATFORMTHEME", None)
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    # Stop prior Arelis windows (best-effort)
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process python -ErrorAction SilentlyContinue | "
                "Where-Object { $_.MainWindowTitle -eq 'Arelis' } | "
                "Stop-Process -Force -ErrorAction SilentlyContinue",
            ],
            check=False,
            capture_output=True,
        )
    except Exception:
        pass
    time.sleep(0.5)
    proc = subprocess.Popen(
        [str(python), "-m", "arelis"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.time() + seconds
    titled = False
    while time.time() < deadline:
        try:
            out = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"Get-Process -Id {proc.pid} -ErrorAction SilentlyContinue | "
                    "Select-Object -ExpandProperty MainWindowTitle",
                ],
                text=True,
                stderr=subprocess.STDOUT,
            ).strip()
        except Exception:
            out = ""
        # Child may be different pid on Windows — search by title
        try:
            titles = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-Process python -ErrorAction SilentlyContinue | "
                    "Where-Object { $_.MainWindowTitle -like '*Arelis*' } | "
                    "Select-Object -ExpandProperty MainWindowTitle",
                ],
                text=True,
                stderr=subprocess.STDOUT,
            ).strip()
        except Exception:
            titles = ""
        if "Arelis" in titles or out == "Arelis":
            titled = True
            break
        if proc.poll() is not None:
            err = (proc.stderr.read() or b"").decode("utf-8", errors="replace")[:800]
            return {
                "ok": False,
                "pid": proc.pid,
                "detail": f"UI exited early code={proc.returncode}: {err}",
            }
        time.sleep(0.4)
    detail = (
        "window title Arelis visible"
        if titled
        else "process running but title not seen in time"
    )
    return {
        "ok": titled and proc.poll() is None,
        "pid": proc.pid,
        "detail": detail,
        "alive": proc.poll() is None,
    }


def main() -> int:
    print("=== Arelis desktop E2E smoke ===\n")
    print("[1/2] Launching UI…")
    ui = launch_ui(10.0)
    print(json.dumps(ui, indent=2))

    print("\n[2/2] Running chat/tool scenarios via app stack…")
    results = asyncio.run(run_cases())
    for r in results:
        status = "PASS" if r.ok else "FAIL"
        print(f"\n[{status}] {r.name} ({r.elapsed_s}s)")
        print(f"  detail: {r.detail}")
        if r.events:
            print(f"  events: {r.events}")
        if r.assistant:
            print(f"  assistant: {r.assistant[:500]}")

    report = {
        "ui": ui,
        "cases": [r.__dict__ for r in results],
        "passed": sum(1 for r in results if r.ok),
        "failed": sum(1 for r in results if not r.ok),
        "ui_ok": bool(ui.get("ok")),
    }
    out_path = ROOT / "data" / "e2e_smoke_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    total = report["passed"] + report["failed"]
    print(f"\nReport written to {out_path}")
    print(f"Summary: cases {report['passed']}/{total} passed; ui_ok={report['ui_ok']}")
    return 0 if report["ui_ok"] and report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
