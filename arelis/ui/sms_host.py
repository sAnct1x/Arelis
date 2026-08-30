"""Inbound SMS tiles and doorbell. ArelisWindow methods stay as delegates.

Notify chrome, taskbar flash, and the turn/speech floor stay on the
window. This module is the text that arrived and the tile that sends back.
"""

from __future__ import annotations

import asyncio
from typing import Any

from arelis.core.events import Event, EventType
from arelis.notify import new_notice
from arelis.sms import (
    SmsSendError,
    explain_sms_error,
    resolve_operator_sms_target,
    send_operator_sms,
)
from arelis.sms_inbound import InboundSms, format_held_inbound_voice_cue
from arelis.ui.sms_chat import room_owns_doorbell, seed_bodies


def on_sms_received(window, payload: dict[str, Any]) -> None:
    """Bubble first. A visible room swallows the doorbell. Voice waits on the floor."""
    if window._force_quit or window._disposed:
        return
    msg = InboundSms(
        id=str(payload.get("id") or ""),
        sender=str(payload.get("from") or "(unknown)"),
        body=str(payload.get("body") or ""),
        time=str(payload.get("time") or ""),
        contact_alias=str(payload.get("contact_alias") or ""),
        contact_name=str(payload.get("contact_name") or ""),
        media_path=str(payload.get("media_path") or ""),
        media_url=str(payload.get("media_url") or ""),
        media_kind=str(payload.get("media_kind") or ""),
    )
    alias = msg.contact_alias or ""
    title = msg.display_from
    window.sms_chats.append_inbound(
        body=msg.body,
        alias=alias,
        phone=msg.sender,
        sender=msg.sender,
        title=title,
        media_path=msg.media_path,
        media_kind=msg.media_kind,
    )
    window._alert_if_background()
    _window, state = window.sms_chats.room_state(
        alias=alias, phone=msg.sender, sender=msg.sender
    )
    if room_owns_doorbell(state):
        return
    notice = window.notify_center.add(
        new_notice(
            kind="sms",
            title=title,
            body=msg.body,
            group_key=f"sms:{alias or msg.sender}",
            voice_cue=format_held_inbound_voice_cue([msg]),
            data={
                "from": msg.sender,
                "alias": alias,
                "time": msg.time,
                "message_id": msg.id,
            },
        )
    )
    window._sync_notify_surface()
    if notice is None:
        return
    if window._floor_busy():
        window._held_inbound.append(msg)
        return
    window._maybe_voice_sms([msg])


def flush_held_inbound(window) -> None:
    if not window._held_inbound or window._floor_busy():
        return
    held = window._held_inbound
    window._held_inbound = []
    window._maybe_voice_sms(held)


def maybe_voice_sms(window, messages: list[InboundSms]) -> None:
    if not messages:
        return
    if window.notify_center.mode("sms") != "voice":
        return
    known = [m for m in messages if m.contact_alias or m.contact_name]
    if not known:
        return
    if window.voice is None or not window.voice.speak_enabled:
        return
    cue = format_held_inbound_voice_cue(known)
    if not cue:
        return
    window._arm_speech()
    asyncio.run_coroutine_threadsafe(
        window.bus.publish(Event(EventType.VOICE_SPEAK, {"text": cue})),
        window.loop,
    )


def on_notice_reply(window, notice_id: str) -> None:
    window._open_sms_chat(notice_id)


def on_sms_tile_shown(window, alias: str, phone: str) -> None:
    """Showing a room marks that person's SMS group read so the pill drops."""
    from arelis.contacts import normalize_phone

    keys: list[str] = []
    if alias:
        keys.append(f"sms:{alias}")
    if phone:
        keys.append(f"sms:{phone}")
        digits = normalize_phone(phone)
        if digits and f"sms:{digits}" not in keys:
            keys.append(f"sms:{digits}")
    marked = False
    for key in keys:
        notice = window.notify_center.find_group(key)
        if notice is not None and notice.unread:
            window.notify_center.mark_read(notice.id)
            marked = True
    if marked:
        window._sync_notify_surface()


def open_sms_chat(window, notice_id: str) -> None:
    notice = window.notify_center.find(notice_id)
    if notice is None or notice.kind != "sms":
        return
    alias = str(notice.data.get("alias") or "").strip()
    phone = str(notice.data.get("from") or "").strip()
    window = window.sms_chats.open(
        alias=alias,
        phone=phone,
        sender=phone,
        title=notice.title,
        seed=seed_bodies(notice),
    )
    if window is None:
        window.thinking.append(
            "No number on that text — cannot open a chat.",
            kind="status",
        )
        return
    if notice.unread:
        window.notify_center.mark_read(notice.id)
        window._sync_notify_surface()


def on_sms_tile_send(window, key: str, body: str, alias: str, phone: str) -> None:
    if window.loop is None or not window.loop.is_running():
        window.sms_chats.system(key, "Arelis is not ready to send.")
        return
    future = asyncio.run_coroutine_threadsafe(
        window._operator_send_sms(alias, phone, body),
        window.loop,
    )
    future.add_done_callback(
        lambda fut, k=key: window._sms_send_resolved(fut, k)
    )


async def operator_send_sms(window, alias: str, phone: str, body: str) -> None:
    from arelis.sms_android import AndroidSmsProvider, load_sms_account

    resolved = resolve_operator_sms_target(alias=alias, phone=phone)
    if isinstance(resolved, str):
        raise SmsSendError(resolved)
    account = load_sms_account()
    if account is None:
        raise SmsSendError("SMS is not configured.")
    await send_operator_sms(
        phone=resolved.phone_e164,
        body=body,
        provider=AndroidSmsProvider(account, live=True),
    )


def sms_send_resolved(window, future, key: str) -> None:
    try:
        future.result()
    except Exception as exc:
        try:
            window.sms_send_finished.emit(key, False, explain_sms_error(exc))
        except RuntimeError:
            pass
        return
    try:
        window.sms_send_finished.emit(key, True, "")
    except RuntimeError:
        pass


def on_sms_send_finished(window, key: str, ok: bool, error: str) -> None:
    if not ok:
        window.sms_chats.system(key, error or "Send failed.")


def push_mobile_notice(window, kind: str, title: str, body: str) -> None:
    ingest = window.sms_ingest
    hub = getattr(ingest, "mobile", None) if ingest is not None else None
    if hub is not None:
        hub.push_notice(kind, title, body)

