"""Phone hub bind. The glass still owns widgets; this wires ingest.mobile."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

log = logging.getLogger(__name__)

def bind_mobile_hub(window) -> None:
    """Let the phone ask whether this window can think."""
    ingest = window.sms_ingest
    if ingest is None:
        return
    from arelis.config import load_persona

    def transcribe(path: Path) -> str:
        voice = window.voice
        if voice is None or not voice.stt_enabled:
            raise RuntimeError("voice is off on the PC")
        fut = asyncio.run_coroutine_threadsafe(
            voice.stt.transcribe(path),
            window.loop,
        )
        return str(fut.result(timeout=90) or "")

    def speak_for_phone(text: str) -> bytes | None:
        voice = window.voice
        if voice is None or not voice.tts_enabled:
            return None
        from arelis.paths import outputs_dir
        from arelis.voice.speech_text import prepare_spoken_text

        spoken = prepare_spoken_text(text or "", max_chars=voice.max_spoken_chars)
        if not spoken:
            return None
        dest = outputs_dir() / "voice" / "mobile-speak.wav"
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            fut = asyncio.run_coroutine_threadsafe(
                voice.tts.synthesize(spoken, dest),
                window.loop,
            )
            path = fut.result(timeout=90)
            data = Path(path).read_bytes()
            return data or None
        except Exception:
            log.exception("phone speech failed")
            return None

    def place() -> dict:
        rooms = window.config.get("_rooms")
        room = getattr(rooms, "active", None) if rooms is not None else None
        return {
            "workspace": window.workspace_roots.active,
            "roots": window.workspace_roots.names(),
            "room": (
                {
                    "id": room.id,
                    "name": room.name,
                    "root": room.root,
                }
                if room is not None
                else None
            ),
        }

    def list_files(scope: str, rel: str, room_id: str = "") -> dict:
        from arelis.mobile import browse_files

        rooms = window.config.get("_rooms")
        room = None
        if rooms is not None and room_id:
            room = rooms.get(room_id)
        return browse_files(
            window.workspace_roots,
            scope=scope,
            rel=rel,
            room_name=getattr(room, "name", "") or "",
            room_root=getattr(room, "root", "") or "",
        )

    def open_file(path: str) -> tuple[bytes, str, str] | None:
        import mimetypes

        from arelis.mobile import GLANCE_MAX_BYTES

        hit = window.workspace_roots.resolve_read(path)
        if not hit.path.is_file():
            return None
        data = hit.path.read_bytes()
        if len(data) > GLANCE_MAX_BYTES:
            raise ValueError("file is larger than 8 MB — open it on the PC")
        mime, _ = mimetypes.guess_type(hit.path.name)
        return data, mime or "application/octet-stream", hit.path.name

    def list_chats() -> list:
        store = window.store
        if store is None:
            return []
        return [
            {
                "id": str(row.get("id") or ""),
                "started_at": str(row.get("started_at") or ""),
                "title": str(row.get("title") or ""),
                "room_id": str(row.get("room_id") or ""),
            }
            for row in store.list_sessions(limit=80)
        ]

    def current_chat() -> dict:
        store = window.store
        if store is None:
            return {}
        sid = str(store.session_id or "")
        if not sid:
            return {}
        row = store.get_session(sid) or {}
        title = str(row.get("title") or "").strip() or "(untitled)"
        return {
            "id": sid,
            "title": title,
            "started_at": str(row.get("started_at") or ""),
            "room_id": str(row.get("room_id") or ""),
        }

    def view_chat(sid: str) -> dict | None:
        store = window.store
        if store is None:
            return None
        wanted = str(sid or "").strip()
        row = store.get_session(wanted) if wanted else None
        if row is None:
            return None
        rooms = window.config.get("_rooms")
        room_id = str(row.get("room_id") or "")
        room = rooms.get(room_id) if rooms is not None and room_id else None
        title = str(row.get("title") or "").strip() or "(untitled)"
        transcript = []
        for msg in store.get_messages(wanted):
            role = str(msg.get("role") or "")
            text = str(msg.get("content") or "")
            if role in {"user", "assistant"} and text:
                transcript.append({"role": role, "text": text, "glances": []})
        return {
            "chat": {
                "id": wanted,
                "title": title,
                "started_at": str(row.get("started_at") or ""),
                "room_id": room_id,
            },
            "transcript": transcript,
            "place": {
                "workspace": window.workspace_roots.active,
                "roots": window.workspace_roots.names(),
                "room": (
                    {
                        "id": room.id,
                        "name": room.name,
                        "root": room.root,
                    }
                    if room is not None
                    else None
                ),
            },
        }

    def mint_chat() -> dict | None:
        store = window.store
        if store is None:
            return None
        sid = store.mint_session()
        return view_chat(sid)

    ingest.mobile.bind(
        warmup=lambda: bool(
            getattr(window.router, "warmup_pending", lambda: False)()
        ),
        busy=lambda: bool(window._turn_busy),
        model=lambda: str(getattr(window, "_current_model", "") or ""),
        session_ready=lambda: True,
        transcribe=transcribe,
        persona=lambda: load_persona(window.config),
        files=list_files,
        open_file=open_file,
        place=place,
        chats=list_chats,
        current_chat=current_chat,
        view_chat=view_chat,
        mint_chat=mint_chat,
        speak=speak_for_phone,
    )
    # Phone status is this hub, not the desktop widget. Seed the open
    # thread so a reconnect during warmup still has the real conversation,
    # then Gemma lines from the pocket can copy in on top.
    store = window.store
    sid = str(getattr(store, "session_id", "") or "")
    if store is not None and sid:
        ingest.mobile.replace_transcript(
            [
                {"role": row.get("role"), "content": row.get("content")}
                for row in store.get_messages(sid)
            ]
        )

