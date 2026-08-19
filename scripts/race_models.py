"""Race live Ollama brains on this PC with real tools.

Does not send SMS or email. Does not write default.yaml or config.local.yaml.
Pins fast/research in memory for one model at a time.

  .\\.venv\\Scripts\\python.exe scripts\\race_models.py --pull
  .\\.venv\\Scripts\\python.exe scripts\\race_models.py --skip-pull
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TESS = Path(r"C:\Program Files\Tesseract-OCR")
if _TESS.is_dir():
    os.environ["PATH"] = str(_TESS) + os.pathsep + os.environ.get("PATH", "")

from arelis.config import PROJECT_ROOT, load_config
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.llm import build_router
from arelis.tools import build_tool_registry

_DEFAULT_MODELS = "qwen2.5:7b,qwen3.5:9b,qwen2.5:14b,qwen3:14b"
_BASELINE_LOGS = (
    "foundation_bench.json",
    "utilization_bench.json",
    "latency_bench.json",
)


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _head(text: str, n: int = 220) -> str:
    return (text or "").replace("\n", " ").strip()[:n]


def _fast_class(tag: str) -> bool:
    low = tag.lower()
    return any(x in low for x in ("7b", "8b", "9b", "12b")) and "14b" not in low


class TurnProbe:
    def __init__(self, bus: EventBus, memory: SessionMemory) -> None:
        self.bus = bus
        self.memory = memory
        self.seen: list[Event] = []
        self.done = asyncio.Event()
        self.assistant_parts: list[str] = []
        self.tools_started: list[str] = []
        bus.subscribe(None, self.on_event)

    async def on_event(self, event: Event) -> None:
        self.seen.append(event)
        if event.type == EventType.TOOL_START:
            self.tools_started.append(str(event.payload.get("tool") or ""))
        if event.type == EventType.TOOL_CONFIRM:
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
                "assistant": "".join(self.assistant_parts),
                "tools": list(self.tools_started),
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
            "assistant": assistant,
            "tools": list(self.tools_started),
            "elapsed_s": round(time.perf_counter() - t0, 2),
            "detail": "",
        }


def _make_ocr_png(run_id: str) -> Path:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter

    base = PROJECT_ROOT / "outputs" / "race_fixtures" / run_id
    base.mkdir(parents=True, exist_ok=True)
    png = base / "ocr_hello.png"
    _app = QGuiApplication.instance() or QGuiApplication([])
    img = QImage(640, 160, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    painter = QPainter(img)
    painter.setPen(QColor("black"))
    painter.setFont(QFont("Arial", 28))
    painter.drawText(img.rect(), int(Qt.AlignmentFlag.AlignCenter), f"ARELIS RACE {run_id}")
    painter.end()
    img.save(str(png), "PNG")
    assert _app is not None
    return png


def _ollama_tags(base_url: str) -> set[str]:
    import httpx

    try:
        tags = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=5.0).json()
    except Exception:
        return set()
    names: set[str] = set()
    for m in tags.get("models") or []:
        for key in ("name", "model"):
            val = m.get(key)
            if val:
                names.add(str(val))
    return names


def _have_model(available: set[str], tag: str) -> bool:
    if tag in available:
        return True
    return any((a or "").startswith(tag) or (a or "").startswith(tag + ":") for a in available)


def _pull(tag: str) -> tuple[bool, str]:
    print(f"\n>>> ollama pull {tag}", flush=True)
    try:
        proc = subprocess.run(
            ["ollama", "pull", tag],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=3600,
        )
    except FileNotFoundError:
        return False, "ollama not on PATH"
    except subprocess.TimeoutExpired:
        return False, "pull timed out"
    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        return False, out[-800:] or f"exit {proc.returncode}"
    return True, "pulled"


def _copy_baselines(race_dir: Path) -> None:
    src = ROOT / "logs"
    dest = race_dir / "baseline_logs"
    dest.mkdir(parents=True, exist_ok=True)
    for name in _BASELINE_LOGS:
        path = src / name
        if path.is_file():
            shutil.copy2(path, dest / name)


def _pin_config(model: str, num_ctx: int) -> dict[str, Any]:
    config = load_config()
    models = dict(config.get("models") or {})
    models["fast"] = model
    models["research"] = model
    config["models"] = models
    ollama = dict(config.get("ollama") or {})
    ollama["num_ctx"] = int(num_ctx)
    ollama["research_num_ctx"] = int(num_ctx)
    config["ollama"] = ollama
    router = dict(config.get("router") or {})
    router["warm_on_start"] = False
    config["router"] = router
    return config


async def _run_jobs(
    *,
    model: str,
    num_ctx: int,
    run_id: str,
    with_browser: bool,
) -> list[dict[str, Any]]:
    png = _make_ocr_png(run_id)
    write_rel = f"data/race_{run_id}.txt"
    write_path = PROJECT_ROOT / write_rel
    token = f"race-ok-{run_id}"

    config = _pin_config(model, num_ctx)
    router = build_router(config)
    tools = build_tool_registry(config, router=router)
    bus = EventBus()
    memory = SessionMemory()
    Orchestrator(bus, router, tools, config, memory)
    bus_task = asyncio.create_task(bus.run())
    await asyncio.sleep(0.2)
    probe = TurnProbe(bus, memory)
    rows: list[dict[str, Any]] = []

    jobs: list[tuple[str, str, str, int, Any]] = [
        (
            "calculator",
            "What is 17 times 19? Use the calculator tool.",
            "fast",
            180,
            lambda r: (
                "calculator" in r["tools"] and "323" in (r["assistant"] or ""),
                "need calculator tool and 323",
            ),
        ),
        (
            "weather",
            "What's the weather right now where I am?",
            "fast",
            240,
            lambda r: (
                any(t in r["tools"] for t in ("weather", "user_location")),
                "need weather or user_location tool",
            ),
        ),
        (
            "search",
            "Search the web for 'Example Domain IANA' and give me one https link.",
            "fast",
            180,
            lambda r: (
                "web_search" in r["tools"] and "http" in (r["assistant"] or "").lower(),
                "need web_search and an https link",
            ),
        ),
        (
            "scrape",
            "Scrape https://example.com and quote the visible heading.",
            "fast",
            180,
            lambda r: (
                "scrape" in r["tools"] and "example" in (r["assistant"] or "").lower(),
                "need scrape tool and example in the answer",
            ),
        ),
        (
            "readme",
            "Open README.md and summarize it in two short sentences.",
            "fast",
            180,
            lambda r: (
                "workspace" in r["tools"] and len(r["assistant"] or "") > 40,
                "need workspace tool and a real summary",
            ),
        ),
        (
            "write",
            f"Write a temp file {write_rel} containing exactly: {token}",
            "fast",
            240,
            lambda r: (
                "workspace" in r["tools"]
                and "send_sms" not in r["tools"]
                and write_path.is_file()
                and token in write_path.read_text(encoding="utf-8", errors="replace"),
                f"need workspace write of {write_rel}",
            ),
        ),
        (
            "ocr",
            f"OCR the image at {png.as_posix()} and tell me the text.",
            "fast",
            240,
            lambda r: (
                "ocr" in r["tools"] and "ARELIS" in (r["assistant"] or "").upper(),
                "need ocr tool and ARELIS in the answer",
            ),
        ),
        (
            "research",
            "Briefly research what example.com is. Cite sources with https URLs only.",
            "research",
            420,
            lambda r: (
                "http" in (r["assistant"] or "").lower()
                and any(t in r["tools"] for t in ("web_search", "scrape", "web_fetch", "research_report")),
                "need a web tool and an https citation",
            ),
        ),
    ]
    if with_browser:
        jobs.append(
            (
                "browser",
                "Pull up https://example.com in my browser.",
                "fast",
                300,
                lambda r: (
                    "browser" in r["tools"]
                    or "PROFILE_LOCKED" in (r["assistant"] or "")
                    or "example" in (r["assistant"] or "").lower(),
                    "need browser tool or a locked-profile note",
                ),
            )
        )

    try:
        for name, prompt, role, timeout_s, check in jobs:
            print(f"  job {name} …", flush=True)
            result = await probe.run(prompt, role, timeout_s=timeout_s)
            ok, need = check(result)
            if result.get("detail") == "timeout":
                ok = False
                need = "timeout"
            row = {
                "name": name,
                "ok": bool(ok),
                "need": need,
                "tools": result.get("tools") or [],
                "elapsed_s": result.get("elapsed_s"),
                "assistant_head": _head(str(result.get("assistant") or "")),
                "detail": result.get("detail") or "",
            }
            rows.append(row)
            mark = "PASS" if ok else "FAIL"
            print(
                f"  [{mark}] {name} ({row['elapsed_s']}s) tools={row['tools']} {row['assistant_head']}",
                flush=True,
            )
    finally:
        bus.stop()
        bus_task.cancel()
        try:
            await bus_task
        except asyncio.CancelledError:
            pass
        await router.close()
        try:
            if write_path.is_file():
                write_path.unlink()
        except OSError:
            pass
    return rows


def _run_utilization(model: str, out: Path, compare_ctx: str) -> int:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "bench_utilization.py"),
        "--models",
        model,
        "--cold-warm",
        "--out",
        str(out),
    ]
    if "," in compare_ctx:
        cmd.extend(["--compare-ctx", compare_ctx])
    else:
        cmd.extend(["--num-ctx", compare_ctx])
    print(f"\n>>> {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT))
    return int(proc.returncode)


def _summarize(report: dict[str, Any]) -> str:
    lines = [
        f"# Model race {report.get('run_id')}",
        "",
        "Real tools. No SMS/email. Defaults not changed.",
        "",
        "| Model | Jobs | Warm TTFT s | tok/s | VRAM GiB | Notes |",
        "|---|---|---|---|---|---|",
    ]
    for tag, block in (report.get("models") or {}).items():
        jobs = block.get("jobs") or []
        passed = sum(1 for j in jobs if j.get("ok"))
        total = len(jobs)
        util = block.get("utilization") or {}
        warm = None
        tps = None
        vram = None
        for run in util.get("runs") or []:
            if run.get("phase") == "warm" and int(run.get("num_ctx") or 0) == 8192:
                warm = run.get("ttft_s")
                tps = run.get("tokens_per_s")
                host = run.get("host") or {}
                vram = host.get("gpu_dedicated_peak_gib") or run.get("ollama_size_vram_gib")
        pull_err = block.get("pull_error")
        note = pull_err or ("" if passed == total else "job failures")
        lines.append(
            f"| `{tag}` | {passed}/{total} | {warm} | {tps} | {vram} | {note} |"
        )
    lines.append("")
    lines.append(
        "A challenger wins a slot only if jobs >= baseline and warm TTFT is not worse."
    )
    lines.append("Do not edit default.yaml from this file.")
    return "\n".join(lines) + "\n"


async def main_async(args: argparse.Namespace) -> int:
    run_id = _stamp() + "-" + uuid.uuid4().hex[:6]
    race_dir = Path(args.out_dir) if args.out_dir else (ROOT / "logs" / "races" / run_id)
    race_dir.mkdir(parents=True, exist_ok=True)
    _copy_baselines(race_dir)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    config = load_config()
    base_url = str((config.get("ollama") or {}).get("base_url") or "http://127.0.0.1:11434")
    available = _ollama_tags(base_url)
    if not available and not args.skip_pull:
        print(f"Cannot reach Ollama at {base_url}", flush=True)
        return 1

    report: dict[str, Any] = {
        "run_id": run_id,
        "started": datetime.now().isoformat(timespec="seconds"),
        "num_ctx_jobs": 8192,
        "with_browser": bool(args.with_browser),
        "models": {},
        "defaults_unchanged": True,
        "sends": False,
    }

    for tag in models:
        print(f"\n======== {tag} ========", flush=True)
        block: dict[str, Any] = {"tag": tag, "jobs": [], "utilization": None}
        if not _have_model(available, tag):
            if args.skip_pull:
                block["pull_error"] = "not pulled"
                report["models"][tag] = block
                print(f"  SKIP {tag}: not pulled", flush=True)
                continue
            ok, detail = _pull(tag)
            if not ok:
                block["pull_error"] = detail
                report["models"][tag] = block
                print(f"  SKIP {tag}: {detail[-400:]}", flush=True)
                continue
            available = _ollama_tags(base_url)

        jobs = await _run_jobs(
            model=tag,
            num_ctx=8192,
            run_id=f"{run_id}-{tag.replace(':', '_').replace('.', '_')}",
            with_browser=bool(args.with_browser),
        )
        block["jobs"] = jobs
        block["jobs_passed"] = sum(1 for j in jobs if j.get("ok"))
        block["jobs_total"] = len(jobs)

        ctx = "4096,8192,16384" if _fast_class(tag) else "8192"
        util_path = race_dir / f"utilization_{tag.replace(':', '_').replace('.', '_')}.json"
        _run_utilization(tag, util_path, ctx)
        if util_path.is_file():
            block["utilization"] = json.loads(util_path.read_text(encoding="utf-8"))
        report["models"][tag] = block

        score_path = race_dir / "scoreboard.json"
        score_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    report["finished"] = datetime.now().isoformat(timespec="seconds")
    (race_dir / "scoreboard.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = _summarize(report)
    (race_dir / "summary.md").write_text(summary, encoding="utf-8")
    print("\n" + summary, flush=True)
    print(f"wrote {race_dir}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default=_DEFAULT_MODELS)
    parser.add_argument("--skip-pull", action="store_true")
    parser.add_argument(
        "--pull",
        action="store_true",
        help="Pull missing tags (default unless --skip-pull).",
    )
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        help="Skip the Chrome example.com turn (default is to open it).",
    )
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()
    args.with_browser = not bool(args.skip_browser)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
