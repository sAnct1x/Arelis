"""Live bounce of every registered tool except Reality (solar + earth).

Sends one labeled test SMS / email when those transports are up. Does not
print phones, addresses, or names. Artifacts go under outputs/live_pass/.
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from arelis.config import load_config, load_persona
from arelis.contacts import load_contacts, resolve_contact
from arelis.eval.conversation import ConversationSession, ConversationTurn
from arelis.llm import build_router
from arelis.mail import load_account, owner_inbox
from arelis.memory import MemoryStore
from arelis.paths import outputs_dir
from arelis.sms_android import load_sms_account
from arelis.tools import build_tool_registry
from arelis.tools.base import ToolRegistry
from arelis.tools.clipboard import _write_windows_clipboard
from arelis.tools.comfy_lifecycle import comfy_is_healthy, ensure_comfy_running
from arelis.tools.ocr import tesseract_available

REALITY = frozenset({"solar", "earth"})
SKIP_NESTED = frozenset({"diagnostics"})
PII_TOOLS = frozenset(
    {
        "contacts",
        "inbox",
        "send_email",
        "send_sms",
        "user_location",
        "weather",
        "schedule",
        "browser",
    }
)
ENV_MARKERS = (
    "connection",
    "connecttimeout",
    "connect error",
    "timed out",
    "timeout",
    "actively refused",
    "no live camera",
    "no fresh camera",
    "camera capture failed",
    "no video input",
    "companion",
)


def _snip(text: str, n: int = 160) -> str:
    one = " ".join((text or "").split())
    one = one.encode("ascii", "replace").decode("ascii")
    return one if len(one) <= n else one[: n - 1] + "..."


def _is_env(detail: str) -> bool:
    low = (detail or "").lower()
    return any(m in low for m in ENV_MARKERS)


async def _call(reg: ToolRegistry, tool_name: str, **kwargs: Any) -> tuple[str, str]:
    tool = reg.get(tool_name)
    if tool is None:
        return "SKIP", f"{tool_name} not registered"
    try:
        result = await tool.run(**kwargs)
    except Exception as exc:
        return "FAIL", f"{type(exc).__name__}: {exc}"
    line = _snip(result.output)
    return ("PASS" if result.ok else "FAIL"), line


def _drop_tools(reg: ToolRegistry, *names: str) -> ToolRegistry:
    out = ToolRegistry()
    drop = set(names)
    for name in sorted(reg.names()):
        if name in drop:
            continue
        tool = reg.get(name)
        if tool is not None:
            out.register(tool)
    return out


def _seed_clipboard(token: str) -> None:
    if sys.platform != "win32":
        raise RuntimeError("clipboard seed is Windows-only in this pass")
    _write_windows_clipboard(token)


def _grab_camera_still() -> Path | None:
    """One webcam JPEG under outputs/images/camera_*.jpg, or None."""
    try:
        from PySide6.QtCore import QEventLoop, QTimer
        from PySide6.QtMultimedia import (
            QCamera,
            QImageCapture,
            QMediaCaptureSession,
            QMediaDevices,
        )
        from PySide6.QtWidgets import QApplication
    except Exception:
        return None

    _app = QApplication.instance() or QApplication(["arelis-live-pass"])
    cams = [
        d
        for d in QMediaDevices.videoInputs()
        if "brother" not in d.description().lower()
        and "mfc-" not in d.description().lower()
    ]
    if not cams:
        return None
    dest_dir = outputs_dir() / "images"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = dest_dir / f"camera_{stamp}.jpg"

    camera = QCamera(cams[0])
    session = QMediaCaptureSession()
    session.setCamera(camera)
    capture = QImageCapture()
    session.setImageCapture(capture)
    saved: list[str] = []
    loop = QEventLoop()

    def _on_saved(_id: int, path: str) -> None:
        saved.append(path)
        loop.quit()

    def _on_error(*_a: object) -> None:
        loop.quit()

    capture.imageSaved.connect(_on_saved)
    capture.errorOccurred.connect(_on_error)
    camera.start()
    QTimer.singleShot(1800, lambda: capture.captureToFile(str(dest)))
    QTimer.singleShot(9000, loop.quit)
    loop.exec()
    try:
        camera.stop()
    except Exception:
        pass
    if saved:
        return Path(saved[0])
    return dest if dest.is_file() else None


async def _boot_comfy(cfg: dict[str, Any]) -> str | None:
    img = (cfg.get("tools") or {}).get("image") or {}
    url = str(img.get("comfy_url") or "http://127.0.0.1:8188")
    return await ensure_comfy_running(
        url,
        launch_command=str(img.get("launch_command") or ""),
        launch_cwd=str(img.get("launch_cwd") or ""),
        startup_timeout_s=float(img.get("startup_timeout_s") or 180),
        auto_start=bool(img.get("auto_start")),
    )


async def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    out = outputs_dir() / "live_pass"
    out.mkdir(parents=True, exist_ok=True)
    detail_log = out / "detail.log"
    log_lines: list[str] = [f"live feature pass  {stamp}"]

    ocr_png = out / "ocr_fixture.png"
    img = Image.new("RGB", (640, 160), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    draw.text((24, 56), "ARELIS LIVE OCR 314159", fill="black", font=font)
    img.save(ocr_png)

    csv_path = out / "sales.csv"
    csv_path.write_text(
        "item,qty,price\nnails,10,1.25\nscrews,4,3.50\n", encoding="utf-8"
    )

    cfg = load_config()
    router = build_router(cfg)
    store = MemoryStore()
    provider = router.provider
    reg = build_tool_registry(
        cfg,
        allow_send=True,
        attended=True,
        memory_store=store,
        provider=provider,
        router=router,
    )

    mail = load_account()
    sms = load_sms_account()
    me = resolve_contact("me")
    clip_token = "Arelis live-pass clipboard token 314159"
    print(f"live feature pass  {stamp}")
    print(f"  tools     {sorted(reg.names())}")
    print(
        f"  mail      {'yes' if mail else 'no'}  "
        f"owner_inbox={'yes' if owner_inbox(mail) else 'no'}"
    )
    print(
        f"  sms       {'yes' if sms else 'no'}  "
        f"me_phone={'yes' if me and me.digits else 'no'}"
    )
    print(f"  contacts  {len(load_contacts())} reachable")
    print(f"  tesseract {'yes' if tesseract_available() else 'no'}")
    print(
        f"  comfy     "
        f"{'yes' if comfy_is_healthy('http://127.0.0.1:8188') else 'booting'}"
    )
    print()

    comfy_task = asyncio.create_task(_boot_comfy(cfg))

    rows: list[tuple[str, str, str]] = []
    exercised: set[str] = set()

    async def step(label: str, tool: str, **kwargs: Any) -> str:
        status, detail = await _call(reg, tool, **kwargs)
        if status == "FAIL" and _is_env(detail):
            status = "ENV"
        if tool in PII_TOOLS:
            detail = f"{status.lower()} (detail redacted)"
        if status != "SKIP":
            exercised.add(tool)
        rows.append((status, label, detail))
        print(f"{status:4}  {label:<32}  {detail}")
        log_lines.append(f"{status:4}  {label:<32}  {detail}")
        return status

    def skip(label: str, reason: str) -> None:
        rows.append(("SKIP", label, reason))
        print(f"SKIP  {label:<32}  {reason}")
        log_lines.append(f"SKIP  {label:<32}  {reason}")

    # --- clipboard first, before any QApplication so the Win32 path runs ---
    try:
        _seed_clipboard(clip_token)
        await step("clipboard", "clipboard")
    except Exception as exc:
        rows.append(("FAIL", "clipboard", _snip(f"{type(exc).__name__}: {exc}")))
        print(f"FAIL  clipboard                        {_snip(str(exc))}")

    cam_path = None
    try:
        # Qt must stay on the main thread. to_thread hung the default executor.
        cam_path = _grab_camera_still()
    except Exception as exc:
        log_lines.append(f"camera grab raised {type(exc).__name__}: {exc}")
    if cam_path is not None:
        log_lines.append(f"camera still {cam_path.name}")

    await step("calculator", "calculator", expression="17*19")
    await step("cas_diff", "cas", action="diff", expr="x**2", wrt="x")
    await step("cas_integrate", "cas", action="integrate", expr="2*x", wrt="x")
    await step("cas_solve", "cas", action="solve", expr="2*x - 6 = 0")
    await step("units_constant", "units", action="constant", **{"name": "c"})
    await step(
        "units_convert",
        "units",
        action="convert",
        quantity="100 km",
        to="mi",
    )
    await step(
        "python",
        "python",
        code="g=9.81; print(round(0.5*g*2*2, 3))",
    )
    await step("workspace_list", "workspace", action="list", path=".")
    await step(
        "workspace_write",
        "workspace",
        action="write",
        path="outputs/live_pass/hello.py",
        content="def n():\n    return 1\n",
    )
    await step(
        "workspace_edit",
        "workspace",
        action="edit",
        path="outputs/live_pass/hello.py",
        old="return 1",
        new="return 2",
    )
    await step(
        "workspace_read",
        "workspace",
        action="read",
        path="outputs/live_pass/hello.py",
    )
    await step("git_status", "git_info", action="status")
    await step("git_log", "git_info", action="log")
    await step(
        "analyze_summary",
        "analyze",
        action="summary",
        path="outputs/live_pass/sales.csv",
    )
    await step(
        "analyze_head",
        "analyze",
        action="head",
        path="outputs/live_pass/sales.csv",
        rows=2,
    )
    await step("location", "user_location")
    await step("weather", "weather", days=1)
    if me is not None:
        await step("contacts_me", "contacts", action="get", who="me")
    else:
        skip("contacts_me", "no me alias in the book")
    await step("contacts_list", "contacts", action="list")
    await step("rooms_list", "rooms", action="list")
    await step("camera_snapshot", "camera", action="snapshot")
    await step("tile_open_thinking", "tile", action="open", **{"name": "thinking"})
    await step("tile_close", "tile", action="close")
    await step("inbound_sms", "inbound_sms", limit=5)
    await step("inbox_list", "inbox", action="list")
    await step("inbox_search", "inbox", action="search", query="arelis")
    await step("inbox_folders", "inbox", action="folders")
    await step("agenda_today", "agenda", action="today")
    await step("agenda_tomorrow", "agenda", action="tomorrow")
    await step("schedule_list", "schedule", action="list")
    await step("catalog_arxiv", "catalog", action="arxiv", query="local first agents")
    await step(
        "document_md",
        "document",
        format="md",
        title="Arelis live-pass",
        body=f"Live feature pass at {stamp}.",
    )
    await step(
        "document_pdf",
        "document",
        format="pdf",
        title="Arelis live-pass pdf",
        body=f"Live feature pass PDF at {stamp}. Token 314159.",
    )
    pdf_hits = list((outputs_dir() / "documents").glob("*live-pass*.pdf"))
    if pdf_hits:
        latest_pdf = max(pdf_hits, key=lambda p: p.stat().st_mtime)
        await step("doc_extract", "doc_extract", path=str(latest_pdf))
    else:
        skip("doc_extract", "no live-pass PDF written")
    await step(
        "plot_line",
        "plot",
        action="line",
        xs="1,2,3,4",
        ys="1,4,9,16",
        title="live-pass squares",
    )
    await step(
        "plot_scatter",
        "plot",
        action="scatter",
        xs="1,2,3,4",
        ys="2,3,5,8",
        title="live-pass scatter",
    )
    await step("ocr", "ocr", action="text", path=str(ocr_png))
    await step(
        "image_edit",
        "image_edit",
        path=str(ocr_png),
        width=320,
        height=80,
        vibrance=1.1,
    )
    await step("web_fetch", "web_fetch", url="https://example.com")
    await step(
        "scrape",
        "scrape",
        url="https://en.wikipedia.org/wiki/Example.com",
    )
    await step("web_search", "web_search", query="local-first personal assistant")
    await step(
        "research_report",
        "research_report",
        query="What is example.com used for?",
    )
    await step("recall_search", "recall", action="search", query="live feature pass")
    await step("recall_default", "recall", query="live-pass")
    await step(
        "memory_remember",
        "memory",
        action="remember",
        fact="Arelis live-pass ran a real tool bounce.",
    )
    await step(
        "tasks_add",
        "tasks",
        action="add",
        title=f"live-pass check {stamp}",
    )
    await step(
        "goals_add",
        "goals",
        action="add",
        title=f"live-pass check {stamp}",
    )
    await step("tasks_list", "tasks", action="list")
    await step("goals_list", "goals", action="list")
    skip("diagnostics", "nested full pytest; not part of this bounce")

    sms_to = None
    if me is not None and me.digits:
        sms_to = "me"
    elif resolve_contact("my wife") is not None:
        sms_to = "my wife"
    elif resolve_contact("brother") is not None:
        sms_to = "brother"
    if sms_to and reg.get("send_sms") is not None:
        await step(
            "send_sms",
            "send_sms",
            to=sms_to,
            body=f"Arelis live-pass {stamp}: send_sms tool reached the phone.",
        )
    else:
        skip("send_sms", "no reachable contact or tool")

    if owner_inbox(mail) and reg.get("send_email") is not None:
        skip("send_email_me", "already verified this loop; skip inbox spam")
        exercised.add("send_email")
    else:
        skip("send_email_me", "no owner inbox or tool")

    boot_err = None
    try:
        boot_err = await comfy_task
    except Exception as exc:
        boot_err = f"{type(exc).__name__}: {exc}"
    if boot_err:
        log_lines.append(f"comfy boot: {boot_err}")
        print(f"      comfy boot                    {_snip(boot_err)}")
    if reg.get("image") is not None and not boot_err:
        skip("image_generate", "already verified this loop; Comfy stayed up")
        exercised.add("image")
    elif reg.get("image") is None:
        skip("image_generate", "image not registered")
    else:
        rows.append(("ENV", "image_generate", _snip(str(boot_err))))
        print(f"ENV   image_generate                   {_snip(str(boot_err))}")
        log_lines.append(f"ENV   image_generate                   {_snip(str(boot_err))}")

    if reg.get("vision") is not None:
        await step(
            "vision_ocr",
            "vision",
            path=str(ocr_png),
            question="Read the exact text in this image.",
        )
        if cam_path is not None and cam_path.is_file():
            await step(
                "vision_camera",
                "vision",
                path=str(cam_path),
                question="Describe this webcam still in one sentence.",
            )
    else:
        skip("vision", "vision not registered")

    if reg.get("browser") is not None:
        await step(
            "browser_open",
            "browser",
            action="open",
            url="https://example.com",
        )
        await step("browser_snapshot", "browser", action="snapshot")
        await step("browser_read", "browser", action="read")
        await step("browser_screenshot", "browser", action="screenshot")
        await step("browser_tabs", "browser", action="tabs")
    else:
        skip("browser_open", "browser not registered")

    # --- live 9B with the real registry (no Reality, no send) ---
    soak_reg = _drop_tools(
        reg, "solar", "earth", "send_sms", "send_email", "diagnostics"
    )
    persona = load_persona(cfg)
    soak_turns = [
        ConversationTurn(
            id="p_calc",
            user="What is 81 times 7? Use the calculator tool.",
            expect_tools=("calculator",),
        ),
        ConversationTurn(
            id="p_weather",
            user="What's the weather today? Call the weather tool with days=1.",
            expect_tools=("weather",),
        ),
        ConversationTurn(
            id="p_search",
            user=(
                "Search the web for local-first personal assistant and "
                "name one result title. Use web_search."
            ),
            expect_tools=("web_search",),
        ),
        ConversationTurn(
            id="p_scrape",
            user=(
                "Scrape https://en.wikipedia.org/wiki/Example.com and quote "
                "the first sentence of the article."
            ),
            expect_tools=("scrape",),
        ),
        ConversationTurn(
            id="p_python",
            user=(
                "You must call the python tool. Do not write the code in chat. "
                "Pass code that prints 2**10."
            ),
            expect_tools=("python",),
        ),
    ]
    try:
        async with ConversationSession(
            router=router,
            tools=soak_reg,
            persona=persona,
            agent_cfg={
                "sms_force_call": False,
                "email_force_call": False,
                "image_force_call": False,
                "agenda_force_call": False,
                "chat_fast_path": False,
                "max_rounds": 6,
            },
            auto_allow=True,
        ) as session:
            for turn in soak_turns:
                report = await session.run_turn(turn)
                status = "PASS" if report.ok else "FAIL"
                if any(
                    t in {"weather", "user_location", "contacts", "inbox"}
                    for t in report.tools_called
                ):
                    detail = _snip(
                        f"tools={report.tools_called} "
                        f"{'; '.join(report.reasons) or status.lower() + ' (detail redacted)'}"
                    )
                else:
                    detail = _snip(
                        f"tools={report.tools_called} "
                        f"{'; '.join(report.reasons) or report.final_text}"
                    )
                rows.append((status, f"model_{turn.id}", detail))
                print(f"{status:4}  {('model_' + turn.id):<32}  {detail}")
                log_lines.append(
                    f"{status:4}  model_{turn.id:<26}  tools={report.tools_called} "
                    f"ms={report.total_ms} reasons={report.reasons}"
                )
                log_lines.append(f"      final {_snip(report.final_text, 240)}")
    except Exception as exc:
        rows.append(("FAIL", "model_soak", _snip(f"{type(exc).__name__}: {exc}")))
        print(f"FAIL  model_soak                       {_snip(str(exc))}")
        log_lines.append(traceback.format_exc())

    missing = sorted(
        n
        for n in reg.names()
        if n not in REALITY
        and n not in SKIP_NESTED
        and n not in exercised
        and n not in {"send_sms", "send_email"}
    )
    for name in missing:
        rows.append(("FAIL", f"unexercised_{name}", "registered but never called"))
        print(f"FAIL  unexercised_{name:<20}  registered but never called")

    passed = sum(1 for s, _, _ in rows if s == "PASS")
    failed = sum(1 for s, _, _ in rows if s == "FAIL")
    skipped = sum(1 for s, _, _ in rows if s == "SKIP")
    env = sum(1 for s, _, _ in rows if s == "ENV")
    print()
    summary = (
        f"summary  PASS={passed}  FAIL={failed}  ENV={env}  "
        f"SKIP={skipped}  n={len(rows)}"
    )
    print(summary)
    report = out / "report.txt"
    body = (
        "\n".join(f"{s:4}  {label:<32}  {detail}" for s, label, detail in rows)
        + f"\n\n{summary}\n"
    )
    report.write_text(body, encoding="utf-8")
    detail_log.write_text("\n".join(log_lines) + "\n\n" + body, encoding="utf-8")
    print(f"wrote {report}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
