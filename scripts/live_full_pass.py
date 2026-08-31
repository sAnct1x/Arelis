"""Overnight live pass of the whole tool surface.

Direct bounce plus live multi-tool turns: calendar, SMS, email, inbox,
image generate, image edit, OCR, vision, document convert (md/pdf/csv/docx),
workspace coding, python, git, analyze, plot, CAS, units, weather, search,
scrape, fetch, research, memory, recall, tasks, goals, rooms, tile, watch,
clipboard, contacts, schedule, catalog, browser screenshot.

Does not print phones, addresses, or names. Artifacts: outputs/live_full_pass/
"""

from __future__ import annotations

import asyncio
import json
import time
import traceback
from datetime import UTC, datetime, timedelta
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from arelis.config import load_config, load_persona
from arelis.contacts import resolve_contact
from arelis.eval.conversation import ConversationSession, ConversationTurn
from arelis.llm import build_router
from arelis.mail import load_account, owner_inbox
from arelis.memory import MemoryStore
from arelis.paths import outputs_dir
from arelis.sms_android import load_sms_account
from arelis.tools import build_tool_registry
from arelis.tools.base import ToolRegistry
from arelis.tools.comfy_lifecycle import comfy_is_healthy, ensure_comfy_running
from arelis.tools.ocr import tesseract_available


def _snip(text: str, n: int = 200) -> str:
    one = " ".join((text or "").split())
    one = one.encode("ascii", "replace").decode("ascii")
    return one if len(one) <= n else one[: n - 1] + "..."


def _redact(status: str) -> str:
    return f"{status.lower()} (detail redacted)"


async def _call(reg: ToolRegistry, name: str, **kwargs: Any) -> tuple[str, str, int]:
    tool = reg.get(name)
    if tool is None:
        return "SKIP", f"{name} not registered", 0
    t0 = time.perf_counter()
    try:
        result = await tool.run(**kwargs)
    except Exception as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        return "FAIL", f"{type(exc).__name__}: {exc}", ms
    ms = int((time.perf_counter() - t0) * 1000)
    return ("PASS" if result.ok else "FAIL"), _snip(result.output), ms


async def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    out = outputs_dir() / "live_full_pass"
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    exercised: set[str] = set()
    log: list[str] = [f"live full pass  {stamp}"]

    ocr_png = out / "ocr_fixture.png"
    img = Image.new("RGB", (720, 180), "white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 60), "ARELIS FULL PASS 271828", fill="black", font=ImageFont.load_default())
    img.save(ocr_png)

    cfg = load_config()
    router = build_router(cfg)
    store = MemoryStore()
    reg = build_tool_registry(
        cfg,
        allow_send=True,
        attended=True,
        memory_store=store,
        provider=router.provider,
        router=router,
    )
    mail = load_account()
    sms = load_sms_account()
    me = resolve_contact("me")
    wife = resolve_contact("my wife") or resolve_contact("wife")

    print(f"live full pass  {stamp}")
    print(f"  tesseract {tesseract_available()}  comfy {comfy_is_healthy('http://127.0.0.1:8188')}")
    print(f"  mail {bool(mail)}  sms {bool(sms)}  me {bool(me and me.digits)}")
    print()

    async def step(label: str, tool: str, *, redact: bool = False, **kwargs: Any) -> str:
        status, detail, ms = await _call(reg, tool, **kwargs)
        if status != "SKIP":
            exercised.add(tool)
        shown = _redact(status) if redact else detail
        rows.append({"status": status, "label": label, "detail": shown, "ms": ms})
        line = f"{status:4}  {label:<36}  {ms:>6}ms  {shown}"
        print(line)
        log.append(line)
        return status

    # --- calendar ---
    await step("agenda_today", "agenda", action="today")
    await step("agenda_tomorrow", "agenda", action="tomorrow")
    await step("agenda_list", "agenda", action="list")
    await step("agenda_sync", "agenda", action="sync", provider="all")
    start = (datetime.now().astimezone() + timedelta(days=1)).replace(
        hour=10, minute=15, second=0, microsecond=0
    )
    create = await step(
        "agenda_create",
        "agenda",
        action="create",
        summary=f"Arelis live-pass {stamp}",
        start=start.isoformat(),
        description="Overnight verification event. Safe to delete.",
    )
    event_id = ""
    if create == "PASS":
        tool = reg.get("agenda")
        if tool is not None:
            listed = await tool.run(action="list")
            data = getattr(listed, "data", None) or {}
            events = data.get("events") or []
            for ev in events:
                if isinstance(ev, dict) and "live-pass" in str(ev.get("summary") or ""):
                    event_id = str(ev.get("id") or ev.get("event_id") or "")
                    break
        if event_id:
            await step(
                "agenda_update",
                "agenda",
                action="update",
                event_id=event_id,
                summary=f"Arelis live-pass updated {stamp}",
            )
            await step("agenda_delete", "agenda", action="delete", event_id=event_id)
        else:
            rows.append(
                {
                    "status": "ENV",
                    "label": "agenda_update",
                    "detail": "created but no event_id in list",
                    "ms": 0,
                }
            )
            print("ENV   agenda_update                         created but no event_id")

    # --- SMS / email (one labeled ping each; no PII in the log) ---
    sms_alias = "me" if (me and me.digits) else ("wife" if wife else "")
    if sms_alias and reg.get("send_sms") is not None:
        await step(
            "send_sms",
            "send_sms",
            redact=True,
            to=sms_alias,
            body=f"Arelis overnight test {stamp}. Ignore — verification only.",
        )
    else:
        rows.append({"status": "SKIP", "label": "send_sms", "detail": "no alias or tool", "ms": 0})
        print("SKIP  send_sms")

    dest = owner_inbox(mail)
    if dest and reg.get("send_email") is not None:
        await step(
            "send_email",
            "send_email",
            redact=True,
            to="me",
            subject=f"Arelis overnight test {stamp}",
            body="Overnight verification. Ignore this message.",
        )
    else:
        rows.append({"status": "SKIP", "label": "send_email", "detail": "no owner inbox", "ms": 0})
        print("SKIP  send_email")

    await step("inbox_list", "inbox", redact=True, action="list")
    await step("inbox_search", "inbox", redact=True, action="search", query="arelis")
    await step("inbound_sms", "inbound_sms", redact=True, limit=3)
    await step("contacts_list", "contacts", action="list")
    if me is not None:
        await step("contacts_me", "contacts", redact=True, action="get", who="me")

    await step("calculator", "calculator", expression="19*21")
    await step("cas_diff", "cas", action="diff", expr="x**2", wrt="x")
    await step("cas_integrate", "cas", action="integrate", expr="2*x", wrt="x")
    await step("units_convert", "units", action="convert", quantity="100 km", to="mi")
    await step("python", "python", code="print(2**12)")
    csv_path = out / "sales.csv"
    csv_path.write_text("item,qty,price\nnails,10,1.25\nscrews,4,3.50\n", encoding="utf-8")
    await step("analyze", "analyze", action="summary", path="outputs/live_full_pass/sales.csv")
    await step(
        "workspace_write",
        "workspace",
        action="write",
        path="outputs/live_full_pass/hello.py",
        content="def n():\n    return 41\n",
    )
    await step(
        "workspace_edit",
        "workspace",
        action="edit",
        path="outputs/live_full_pass/hello.py",
        old="return 41",
        new="return 42",
    )
    await step("workspace_read", "workspace", action="read", path="outputs/live_full_pass/hello.py")
    await step("workspace_list", "workspace", action="list", path="outputs/live_full_pass")
    await step("git_status", "git_info", action="status")
    await step("git_log", "git_info", action="log")
    await step(
        "document_md",
        "document",
        format="md",
        title="Overnight pass",
        body="token 271828",
    )
    await step(
        "document_pdf",
        "document",
        format="pdf",
        title="Overnight pass pdf",
        body="token 271828 converted to PDF.",
    )
    await step(
        "document_csv",
        "document",
        format="csv",
        title="Overnight pass table",
        body="a,b\n1,2\n",
    )
    await step(
        "document_docx",
        "document",
        format="docx",
        title="Overnight pass docx",
        body="token 271828 as Word.",
    )
    md_hits = list((outputs_dir() / "documents").glob("*Overnight-pass*.md")) + list(
        (outputs_dir() / "documents").glob("*overnight-pass*.md")
    )
    if md_hits:
        src = max(md_hits, key=lambda p: p.stat().st_mtime)
        await step(
            "document_convert_pdf",
            "document",
            format="pdf",
            from_path=str(src),
            title="Overnight converted",
        )
    pdf_hits = list((outputs_dir() / "documents").glob("*pass*.pdf"))
    if pdf_hits:
        latest_pdf = max(pdf_hits, key=lambda p: p.stat().st_mtime)
        await step("doc_extract", "doc_extract", path=str(latest_pdf))
    await step(
        "plot_line",
        "plot",
        action="line",
        xs="1,2,3,4",
        ys="1,4,9,16",
        title="overnight squares",
    )
    await step("location", "user_location")
    await step("weather", "weather", days=1)
    await step("rooms_list", "rooms", action="list")
    await step("tile_open", "tile", action="open", **{"name": "thinking"})
    await step("tile_close", "tile", action="close")
    await step("schedule_list", "schedule", action="list")
    await step("catalog_arxiv", "catalog", action="arxiv", query="local first agents")
    await step("web_fetch", "web_fetch", url="https://example.com")
    await step("scrape", "scrape", url="https://en.wikipedia.org/wiki/Example.com")
    await step("web_search", "web_search", query="local-first personal assistant")
    await step("research_report", "research_report", query="What is example.com used for?")
    await step("recall_search", "recall", action="search", query="271828")
    await step(
        "memory_remember",
        "memory",
        action="remember",
        fact="Overnight live pass token 271828.",
    )
    await step("tasks_add", "tasks", action="add", title=f"overnight check {stamp}")
    await step("goals_add", "goals", action="add", title=f"overnight check {stamp}")
    await step("tasks_list", "tasks", action="list")
    await step("goals_list", "goals", action="list")
    await step("watch", "watch")
    try:
        from arelis.tools.clipboard import _write_windows_clipboard

        _write_windows_clipboard("Arelis overnight clipboard 271828")
        await step("clipboard", "clipboard")
    except Exception as exc:
        rows.append({"status": "FAIL", "label": "clipboard", "detail": _snip(str(exc)), "ms": 0})
        print(f"FAIL  clipboard  {exc}")

    await step("ocr", "ocr", action="text", path=str(ocr_png))
    await step(
        "image_edit",
        "image_edit",
        path=str(ocr_png),
        width=640,
        height=160,
        vibrance=1.2,
    )

    if reg.get("image") is not None:
        boot = await ensure_comfy_running(
            "http://127.0.0.1:8188",
            launch_command=str(((cfg.get("tools") or {}).get("image") or {}).get("launch_command") or ""),
            launch_cwd=str(((cfg.get("tools") or {}).get("image") or {}).get("launch_cwd") or ""),
            startup_timeout_s=180,
            auto_start=bool(((cfg.get("tools") or {}).get("image") or {}).get("auto_start")),
        )
        if boot:
            rows.append({"status": "ENV", "label": "image", "detail": _snip(str(boot)), "ms": 0})
            print(f"ENV   image                                {_snip(str(boot))}")
        else:
            await step(
                "image",
                "image",
                prompt="a small sodium-orange glass bead on black velvet, no text",
            )
    else:
        rows.append({"status": "SKIP", "label": "image", "detail": "not registered", "ms": 0})

    if reg.get("vision") is not None:
        await step(
            "vision",
            "vision",
            path=str(ocr_png),
            question="Read the exact text painted in this image.",
        )
    if reg.get("browser") is not None:
        await step("browser_open", "browser", redact=True, action="open", url="https://example.com")
        await step("browser_screenshot", "browser", redact=True, action="screenshot")

    # --- live model, multi-tool ---
    persona = load_persona(cfg)
    soak_reg = ToolRegistry()
    for name in sorted(reg.names()):
        if name in {"solar", "earth", "camera", "diagnostics"}:
            continue
        tool = reg.get(name)
        if tool is not None:
            soak_reg.register(tool)

    turns = [
        ConversationTurn(
            id="calc_weather",
            user=(
                "What is 23 times 17? Use the calculator. Then call the weather "
                "tool for today with days=1."
            ),
            expect_tools=("calculator", "weather"),
        ),
        ConversationTurn(
            id="search_scrape",
            user=(
                "Search the web for 'example.com IANA' then scrape the most "
                "official URL from the results. Do not guess a URL."
            ),
            expect_tools=("web_search", "scrape"),
        ),
        ConversationTurn(
            id="agenda_ask",
            user="What's on my calendar today? Call the agenda tool with action=today.",
            expect_tools=("agenda",),
        ),
        ConversationTurn(
            id="python_units",
            user=(
                "Call the python tool with code that prints 2**12. Then convert "
                "100 km to miles with the units tool."
            ),
            expect_tools=("python", "units"),
        ),
        ConversationTurn(
            id="remember_recall",
            user=(
                "Remember this durable fact via the memory tool: overnight live "
                "pass token 271828. Then recall 271828."
            ),
            expect_tools=("memory", "recall"),
        ),
        ConversationTurn(
            id="doc_write",
            user=(
                "Write a short markdown document titled Overnight model pass with "
                "body 'token 271828' using the document tool."
            ),
            expect_tools=("document",),
        ),
        ConversationTurn(
            id="doc_convert",
            user=(
                "Convert that markdown to a PDF with the document tool. "
                "Pass format=pdf and from_path to the file you just wrote."
            ),
            expect_tools=("document",),
        ),
        ConversationTurn(
            id="code_workspace",
            user=(
                "Using the workspace tool, write outputs/live_full_pass/twice.py "
                "containing def twice(x): return x*2. Then call the python tool "
                "to import nothing — just print(twice(21)) by defining the same "
                "function in the snippet."
            ),
            expect_tools=("workspace", "python"),
        ),
        ConversationTurn(
            id="image_edit_ask",
            user=(
                f"Edit the existing image at {ocr_png.as_posix()} with image_edit: "
                "width=320 height=80 vibrance=1.1. Do not generate a new picture."
            ),
            expect_tools=("image_edit",),
        ),
        ConversationTurn(
            id="image_gen",
            user=(
                "Generate an image with the image tool. Prompt: a small sodium-"
                "orange glass bead on black velvet, no text. Width 512 height 512."
            ),
            expect_tools=("image",),
        ),
    ]
    try:
        async with ConversationSession(
            router=router,
            tools=soak_reg,
            persona=persona,
            agent_cfg={
                "chat_fast_path": False,
                "max_rounds": 8,
                "skill_tool_subset": False,
            },
            auto_allow=True,
        ) as session:
            for turn in turns:
                report = await session.run_turn(turn)
                status = "PASS" if report.ok else "FAIL"
                detail = _snip(
                    f"tools={report.tools_called} {'; '.join(report.reasons) or report.final_text}"
                )
                if any(t in {"weather", "inbox", "contacts", "send_sms", "send_email"} for t in report.tools_called):
                    detail = _snip(f"tools={report.tools_called} {'; '.join(report.reasons) or status}")
                rows.append(
                    {
                        "status": status,
                        "label": f"model_{turn.id}",
                        "detail": detail,
                        "ms": report.total_ms,
                        "model_ms": report.model_ms,
                        "first_paint_ms": report.first_paint_ms,
                        "tools": report.tools_called,
                    }
                )
                line = (
                    f"{status:4}  model_{turn.id:<30}  {report.total_ms:>6}ms  "
                    f"paint={report.first_paint_ms}  {detail}"
                )
                print(line)
                log.append(line)
                log.append(f"      final {_snip(report.final_text, 240)}")
    except Exception as exc:
        rows.append({"status": "FAIL", "label": "model_soak", "detail": _snip(str(exc)), "ms": 0})
        print(f"FAIL  model_soak  {exc}")
        log.append(traceback.format_exc())

    await router.close()

    skip_unexercised = {"solar", "earth", "camera", "diagnostics"}
    for name in sorted(reg.names()):
        if name in skip_unexercised or name in exercised:
            continue
        rows.append(
            {
                "status": "FAIL",
                "label": f"unexercised_{name}",
                "detail": "registered but never called",
                "ms": 0,
            }
        )
        print(f"FAIL  unexercised_{name}  registered but never called")
        log.append(f"FAIL  unexercised_{name}  registered but never called")

    passed = sum(1 for r in rows if r["status"] == "PASS")
    failed = sum(1 for r in rows if r["status"] == "FAIL")
    skipped = sum(1 for r in rows if r["status"] == "SKIP")
    env = sum(1 for r in rows if r["status"] == "ENV")
    summary = f"summary  PASS={passed}  FAIL={failed}  ENV={env}  SKIP={skipped}  n={len(rows)}"
    print()
    print(summary)
    log.append(summary)
    (out / "report.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (out / "report.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    print(f"wrote {out / 'report.txt'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
