"""Extra E2E: write confirm gate + public scrape (network)."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arelis.config import load_config
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.llm import build_router
from arelis.tools import build_tool_registry


class Probe:
    """Drives one turn at a time and records what the bus emitted.

    Owns the session memory so it can be cleared between cases. Sharing it made
    results order-dependent: a case whose write was skipped left the model
    convinced it had no file permissions, and the next case then refused to call
    any tool at all. Each case has to start from a clean session to mean
    anything on its own.
    """

    def __init__(self, bus: EventBus, memory: SessionMemory) -> None:
        self.bus = bus
        self.memory = memory
        self.seen: list[Event] = []
        self.done = asyncio.Event()
        self.confirm_seen = False
        self.decision = "allow"
        bus.subscribe(None, self.on_event)

    async def on_event(self, event: Event) -> None:
        self.seen.append(event)
        if event.type == EventType.TOOL_CONFIRM:
            self.confirm_seen = True
            await self.bus.publish(
                Event(
                    EventType.TOOL_CONFIRM_REPLY,
                    {
                        "id": event.payload.get("id"),
                        "decision": self.decision,
                        "allow_turn": False,
                    },
                )
            )
        if event.type in {EventType.ASSISTANT_DONE, EventType.ERROR}:
            self.done.set()

    def reset(self, decision: str) -> None:
        self.seen = []
        self.done = asyncio.Event()
        self.confirm_seen = False
        self.decision = decision
        self.memory.clear()

    async def run(self, text: str, role: str, decision: str, timeout_s: float = 240) -> dict:
        self.reset(decision)
        t0 = time.perf_counter()
        await self.bus.publish(Event(EventType.USER_MESSAGE, {"text": text, "role": role}))
        try:
            await asyncio.wait_for(self.done.wait(), timeout=timeout_s)
        except TimeoutError:
            return {
                "ok": False,
                "detail": "timeout",
                "events": [e.type.value for e in self.seen],
                "assistant": "",
                "confirm_seen": self.confirm_seen,
                "elapsed_s": round(time.perf_counter() - t0, 2),
            }
        await asyncio.sleep(0.15)
        assistant = ""
        for e in reversed(self.seen):
            if e.type == EventType.ASSISTANT_DONE:
                assistant = e.payload.get("text") or ""
                break
            if e.type == EventType.ERROR:
                assistant = e.payload.get("message") or ""
                break
        return {
            "events": [e.type.value for e in self.seen],
            "assistant": assistant[:700],
            "confirm_seen": self.confirm_seen,
            "elapsed_s": round(time.perf_counter() - t0, 2),
        }


async def main() -> int:
    config = load_config()
    bus = EventBus()
    router = build_router(config)
    tools = build_tool_registry(config, router=router)
    memory = SessionMemory()
    Orchestrator(bus, router, tools, config, memory)
    bus_task = asyncio.create_task(bus.run())
    probe = Probe(bus, memory)
    report: dict = {"cases": []}

    scratch = ROOT / "data" / "e2e_scratch.txt"
    if scratch.exists():
        scratch.unlink()

    r = await probe.run(
        "Create or overwrite the file data/e2e_scratch.txt with exactly the text: e2e-ok-skip",
        "code",
        "skip",
    )
    wrote = scratch.exists()
    case1 = {
        "name": "nl_write_skip",
        "ok": r["confirm_seen"] and not wrote,
        "detail": f"confirm={r['confirm_seen']} file_exists={wrote}",
        **r,
    }
    report["cases"].append(case1)
    print(json.dumps(case1, indent=2))

    r = await probe.run(
        "Write the file data/e2e_scratch.txt with exactly: e2e-ok-allow",
        "code",
        "allow",
    )
    content = scratch.read_text(encoding="utf-8") if scratch.exists() else ""
    case2 = {
        "name": "nl_write_allow",
        "ok": r["confirm_seen"] and "e2e-ok-allow" in content,
        "detail": f"confirm={r['confirm_seen']} content={content!r}",
        **r,
    }
    report["cases"].append(case2)
    print(json.dumps(case2, indent=2))

    r = await probe.run(
        "Scrape https://example.com and give me the page title plus a one sentence "
        "summary. Include a Sources section.",
        "fast",
        "allow",
    )
    body = (r.get("assistant") or "").lower()
    types = r.get("events") or []
    used_tool = "tool_start" in types
    case3 = {
        "name": "nl_scrape_example",
        "ok": used_tool and ("example" in body or "sources" in body) and len(body) > 40,
        "detail": f"tools={used_tool} has_sources={'sources' in body} chars={len(body)}",
        **r,
    }
    report["cases"].append(case3)
    print(json.dumps(case3, indent=2))

    bus.stop()
    bus_task.cancel()
    try:
        await bus_task
    except asyncio.CancelledError:
        pass
    await router.close()

    report["passed"] = sum(1 for c in report["cases"] if c["ok"])
    report["failed"] = sum(1 for c in report["cases"] if not c["ok"])
    out = ROOT / "data" / "e2e_extra_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    total = report["passed"] + report["failed"]
    print(f"\nExtra summary: {report['passed']}/{total} passed -> {out}")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
