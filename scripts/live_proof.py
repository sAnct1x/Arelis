"""Live proof: SMS, email, image, calendar, no PII in the log.

Artifacts under outputs/live_proof/. Does not print phones or addresses.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from arelis.config import load_config
from arelis.contacts import resolve_contact
from arelis.mail import load_account, owner_inbox
from arelis.memory import MemoryStore
from arelis.paths import outputs_dir
from arelis.sms_android import load_sms_account
from arelis.tools import build_tool_registry
from arelis.tools.comfy_lifecycle import comfy_is_healthy, ensure_comfy_running


def _ok(label: str, ok: bool, detail: str) -> None:
    status = "PASS" if ok else "FAIL"
    print(f"{status:4}  {label:<28}  {detail}", flush=True)


async def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    out = outputs_dir() / "live_proof"
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []

    cfg = load_config()
    from arelis.llm import build_router

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

    async def call(label: str, tool: str, *, redact: bool = False, **kwargs):
        t = reg.get(tool)
        if t is None:
            _ok(label, False, f"{tool} not registered")
            rows.append({"label": label, "ok": False, "detail": "missing"})
            return None
        try:
            result = await t.run(**kwargs)
        except Exception as exc:
            _ok(label, False, type(exc).__name__)
            rows.append({"label": label, "ok": False, "detail": type(exc).__name__})
            return None
        detail = "ok" if result.ok else "failed"
        if redact:
            detail = "ok (redacted)" if result.ok else "failed (redacted)"
        elif result.ok and result.output:
            detail = " ".join(result.output.split())[:160]
        elif not result.ok:
            detail = " ".join((result.output or "").split())[:160]
        _ok(label, result.ok, detail)
        rows.append({"label": label, "ok": result.ok, "detail": detail})
        return result

    mail = load_account()
    sms = load_sms_account()
    print(f"live proof  {stamp}", flush=True)
    print(
        f"  sms={bool(sms)} mail={bool(mail)} "
        f"owner={bool(owner_inbox(mail))} "
        f"comfy={comfy_is_healthy('http://127.0.0.1:8188')} "
        f"wife={bool(resolve_contact('wife') or resolve_contact('my wife'))} "
        f"me={bool(resolve_contact('me') and resolve_contact('me').digits)}",
        flush=True,
    )

    if resolve_contact("wife") or resolve_contact("my wife"):
        await call(
            "sms_wife",
            "send_sms",
            redact=True,
            to="wife",
            body=f"Arelis live proof {stamp}. Ignore — verification only.",
        )
    if resolve_contact("me") and resolve_contact("me").digits:
        await call(
            "sms_me",
            "send_sms",
            redact=True,
            to="me",
            body=f"Arelis live proof {stamp}. Ignore — verification only.",
        )
    await call(
        "email_me",
        "send_email",
        redact=True,
        subject=f"Arelis live proof {stamp}",
        body="Overnight live verification. Ignore this message.",
    )

    start = (datetime.now().astimezone() + timedelta(hours=2)).replace(
        minute=0, second=0, microsecond=0
    )
    created = await call(
        "agenda_create_google",
        "agenda",
        action="create",
        provider="google",
        summary=f"Arelis live proof {stamp}",
        start=start.isoformat(),
        description="Live verification event. Safe to delete.",
    )
    ics = Path("data/calendar.ics")
    if ics.is_file():
        uid = f"arelis-live-proof-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        dt = start.strftime("%Y%m%dT%H%M%S")
        block = (
            "BEGIN:VEVENT\n"
            f"UID:{uid}\n"
            f"DTSTART:{dt}\n"
            f"SUMMARY:Arelis live proof {stamp}\n"
            "DESCRIPTION:Local ICS proof event. Safe to delete.\n"
            "END:VEVENT\n"
        )
        text = ics.read_text(encoding="utf-8")
        if "END:VCALENDAR" in text:
            text = text.replace("END:VCALENDAR", block + "END:VCALENDAR", 1)
            ics.write_text(text, encoding="utf-8")
            _ok("agenda_ics_write", True, "wrote local ICS event")
            rows.append({"label": "agenda_ics_write", "ok": True})
        await call("agenda_list_after", "agenda", action="list")
    if created is not None and created.ok:
        ev = (created.data or {}).get("event") or {}
        eid = str(ev.get("id") or ev.get("event_id") or "")
        if eid:
            (out / "calendar_event_id.txt").write_text("created", encoding="utf-8")

    img_cfg = (cfg.get("tools") or {}).get("image") or {}
    boot = await ensure_comfy_running(
        str(img_cfg.get("comfy_url") or "http://127.0.0.1:8188"),
        launch_command=str(img_cfg.get("launch_command") or ""),
        launch_cwd=str(img_cfg.get("launch_cwd") or ""),
        startup_timeout_s=float(img_cfg.get("startup_timeout_s") or 180),
        auto_start=True if img_cfg.get("launch_command") else bool(img_cfg.get("auto_start")),
    )
    if boot:
        _ok("comfy_boot", False, "not running")
        rows.append({"label": "comfy_boot", "ok": False, "detail": "not running"})
    else:
        _ok("comfy_boot", True, "healthy")
        await call(
            "image_generate",
            "image",
            prompt="a small sodium-orange glass bead on black velvet, no text, no letters",
            width=512,
            height=512,
        )

    await router.close()
    (out / "report.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"wrote {out / 'report.json'}", flush=True)
    return 0 if all(r.get("ok") for r in rows if r.get("label") != "agenda_create_google") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
