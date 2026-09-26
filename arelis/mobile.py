"""Pocket Arelis: the phone is a window onto this PC, not a second brain.

The ingest server on :8765 already authenticates the companion. These helpers
are the talk path: status, a live turn streamed as NDJSON, glance-once files,
Allow/Deny, and copying a Gemma-on-the-phone transcript back into this session.

The phone decides "On the phone" when this host is unreachable. When we answer,
the mode is always "at_the_house".
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import queue
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from arelis.attachments import display_session_title
from arelis.core.events import Event, EventType

if TYPE_CHECKING:
    from arelis.presence.pending_confirms import PendingConfirm

log = logging.getLogger(__name__)

GLANCE_LIMIT = 24
TRANSCRIPT_LIMIT = 40
NOTICE_LIMIT = 20
GLANCE_MAX_BYTES = 8 * 1024 * 1024
TURN_WAIT_S = 600
PHONE_PERSONA_TAIL = (
    "You are Arelis (ah-REL-is), the user's local assistant. You are not Gemini, "
    "ChatGPT, Claude, Grok, or a generic Google chatbot. Do not say you were "
    "trained by Google or that you have no model name. "
    "Right now you are on the phone. The on-phone brain is Gemma 4 E2B, running "
    "locally on this device. You can talk, keep this chat, and look at a photo "
    "they attach. You cannot send mail, send texts, open PC files, or use tools "
    "until the house (the PC) is back. If they ask what you can do, split it: on "
    "the phone = talk and photos; at the house = files, mail, web, and tools. Do "
    "not pretend you already did house work from here."
)

GlanceKind = str  # "image" | "file"


@dataclass
class Glance:
    id: str
    title: str
    kind: GlanceKind
    path: str


@dataclass
class MobileNotice:
    id: str
    kind: str  # allow | job
    title: str
    body: str


@dataclass
class Bubble:
    role: str
    text: str
    glances: list[dict[str, str]] = field(default_factory=list)


class MobileHub:
    """In-process state the ingest HTTP thread reads while a turn runs.

    Bind callables from the window so status can say whether the session can
    think. Core-only ingest leaves those unset, and /mobile/turn answers 503.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.glances: dict[str, Glance] = {}
        self._glance_order: deque[str] = deque()
        self.confirm: PendingConfirm | None = None
        self.notices: deque[MobileNotice] = deque()
        self.transcript: deque[Bubble] = deque()
        self.warmup_fn: Callable[[], bool] | None = None
        self.busy_fn: Callable[[], bool] | None = None
        self.model_fn: Callable[[], str] | None = None
        self.session_fn: Callable[[], bool] | None = None
        self.transcribe_fn: Callable[[Path], str] | None = None
        self.persona_fn: Callable[[], str] | None = None
        self.files_fn: Callable[..., dict[str, Any]] | None = None
        self.open_fn: Callable[[str], tuple[bytes, str, str] | None] | None = None
        self.place_fn: Callable[[], dict[str, Any]] | None = None
        self.chats_fn: Callable[[], list[dict[str, Any]]] | None = None
        self.current_chat_fn: Callable[[], dict[str, Any]] | None = None
        self.view_chat_fn: Callable[[str], dict[str, Any] | None] | None = None
        self.mint_chat_fn: Callable[[], dict[str, Any] | None] | None = None
        self.speak_fn: Callable[[str], bytes | None] | None = None
        self._turn_q: queue.Queue[dict[str, Any] | None] | None = None
        self._turn_lock = threading.Lock()
        self._load_q: queue.Queue[dict[str, Any] | None] | None = None
        self._turn_session_id = ""
        self._turn_foreign = False
        self._turn_speak = False
        self._turn_language = ""
        self._confirm_session_id = ""

    def bind(
        self,
        *,
        warmup: Callable[[], bool] | None = None,
        busy: Callable[[], bool] | None = None,
        model: Callable[[], str] | None = None,
        session_ready: Callable[[], bool] | None = None,
        transcribe: Callable[[Path], str] | None = None,
        persona: Callable[[], str] | None = None,
        files: Callable[..., dict[str, Any]] | None = None,
        open_file: Callable[[str], tuple[bytes, str, str] | None] | None = None,
        place: Callable[[], dict[str, Any]] | None = None,
        chats: Callable[[], list[dict[str, Any]]] | None = None,
        current_chat: Callable[[], dict[str, Any]] | None = None,
        view_chat: Callable[[str], dict[str, Any] | None] | None = None,
        mint_chat: Callable[[], dict[str, Any] | None] | None = None,
        speak: Callable[[str], bytes | None] | None = None,
    ) -> None:
        self.warmup_fn = warmup
        self.busy_fn = busy
        self.model_fn = model
        self.session_fn = session_ready
        self.transcribe_fn = transcribe
        self.persona_fn = persona
        self.files_fn = files
        self.open_fn = open_file
        self.place_fn = place
        self.chats_fn = chats
        self.current_chat_fn = current_chat
        self.view_chat_fn = view_chat
        self.mint_chat_fn = mint_chat
        self.speak_fn = speak

    def session_ready(self) -> bool:
        fn = self.session_fn
        if fn is None:
            return False
        try:
            return bool(fn())
        except Exception:
            return False

    def _pc_chat(self) -> dict[str, Any]:
        if self.current_chat_fn is None:
            return {}
        try:
            return dict(self.current_chat_fn() or {})
        except Exception:
            return {}

    def _foreign_turn(self, session_id: str) -> bool:
        sid = (session_id or "").strip()
        if not sid:
            return False
        current = str(self._pc_chat().get("id") or "")
        return bool(current) and sid != current

    def status(self, focus: str = "") -> dict[str, Any]:
        warmup = False
        busy = False
        model = ""
        if self.warmup_fn is not None:
            try:
                warmup = bool(self.warmup_fn())
            except Exception:
                warmup = False
        if self.busy_fn is not None:
            try:
                busy = bool(self.busy_fn())
            except Exception:
                busy = False
        if self.model_fn is not None:
            try:
                model = str(self.model_fn() or "")
            except Exception:
                model = ""
        with self._lock:
            confirm = None
            if self.confirm is not None:
                confirm = {
                    "id": self.confirm.id,
                    "tool": self.confirm.tool,
                    "headline": self.confirm.headline,
                    "summary": self.confirm.summary,
                    "detail": self.confirm.detail,
                }
            notices = [
                {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body}
                for n in list(self.notices)
            ]
            glances = [
                {
                    "id": self.glances[gid].id,
                    "title": self.glances[gid].title,
                    "kind": self.glances[gid].kind,
                }
                for gid in list(self._glance_order)
                if gid in self.glances
            ]
            transcript = [
                {"role": b.role, "text": b.text, "glances": list(b.glances)}
                for b in list(self.transcript)
            ]
        ready = self.session_ready()
        place: dict[str, Any] = {}
        if self.place_fn is not None:
            try:
                place = dict(self.place_fn() or {})
            except Exception:
                place = {}
        chat = self._pc_chat()
        pc_chat = dict(chat)
        wanted = (focus or "").strip()
        pc_id = str(chat.get("id") or "")
        missing_chat = False
        if wanted and wanted != pc_id:
            viewed: dict[str, Any] | None = None
            if self.view_chat_fn is not None:
                try:
                    viewed = self.view_chat_fn(wanted)
                except Exception:
                    viewed = None
            if viewed:
                chat = dict(viewed.get("chat") or {}) or {"id": wanted}
                transcript = list(viewed.get("transcript") or [])
                if isinstance(viewed.get("place"), dict):
                    place = dict(viewed["place"])
            else:
                chat = {}
                transcript = []
                missing_chat = True
        pending = confirm
        if wanted and wanted != pc_id and wanted != self._confirm_session_id:
            pending = None
        return {
            "ok": True,
            "mode": "at_the_house",
            "session": ready,
            "warmup": warmup,
            "busy": busy,
            "model": model,
            "pending_confirm": pending,
            "notices": notices,
            "glances": glances[-8:],
            "transcript": transcript,
            "place": place,
            "chat": chat,
            "pc_chat": pc_chat,
            "missing_chat": missing_chat,
        }

    def persona_payload(self) -> dict[str, Any]:
        body = ""
        if self.persona_fn is not None:
            try:
                body = str(self.persona_fn() or "").strip()
            except Exception:
                body = ""
        if not body:
            body = "You are Arelis, a helpful local research assistant."
        # Gemma has a small window. Keep the house persona, then the offline rule.
        clipped = body[:2400].rstrip()
        return {
            "ok": True,
            "system": clipped + "\n\n" + PHONE_PERSONA_TAIL,
        }

    def register_glance(self, *, title: str, kind: GlanceKind, path: str) -> Glance | None:
        dest = Path(path)
        if not dest.is_file():
            return None
        glance = Glance(id=uuid4().hex[:16], title=title or dest.name, kind=kind, path=str(dest))
        with self._lock:
            self.glances[glance.id] = glance
            self._glance_order.append(glance.id)
            while len(self._glance_order) > GLANCE_LIMIT:
                old = self._glance_order.popleft()
                self.glances.pop(old, None)
            if self.transcript:
                last = self.transcript[-1]
                last.glances.append({"id": glance.id, "title": glance.title, "kind": glance.kind})
        return glance

    def file_bytes(self, glance_id: str) -> tuple[bytes, str, str] | None:
        with self._lock:
            glance = self.glances.get(glance_id)
        if glance is None:
            return None
        path = Path(glance.path)
        try:
            data = path.read_bytes()
        except OSError:
            return None
        if len(data) > GLANCE_MAX_BYTES:
            return None
        mime, _ = mimetypes.guess_type(path.name)
        return data, mime or "application/octet-stream", glance.title

    def set_confirm(self, confirm: PendingConfirm) -> None:
        with self._lock:
            self.confirm = confirm
            self.notices.append(
                MobileNotice(
                    id=f"allow:{confirm.id}",
                    kind="allow",
                    title=confirm.headline or "Allow",
                    body=confirm.summary,
                )
            )
            _trim_notices(self.notices)

    def clear_confirm(self, confirm_id: str = "") -> None:
        with self._lock:
            if not confirm_id or (self.confirm and self.confirm.id == confirm_id):
                self.confirm = None
                self._confirm_session_id = ""

    def push_notice(self, kind: str, title: str, body: str) -> None:
        if kind not in {"allow", "job"}:
            return
        with self._lock:
            self.notices.append(
                MobileNotice(id=uuid4().hex[:16], kind=kind, title=title, body=body)
            )
            _trim_notices(self.notices)

    def ack_notice(self, notice_id: str) -> None:
        with self._lock:
            self.notices = deque(n for n in self.notices if n.id != notice_id)

    def list_chats(self) -> list[dict[str, Any]]:
        fn = self.chats_fn
        if fn is None:
            return []
        try:
            rows = fn()
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        if not isinstance(rows, list):
            return out
        for row in rows:
            if not isinstance(row, dict):
                continue
            sid = str(row.get("id") or "").strip()
            if not sid:
                continue
            title = display_session_title(str(row.get("title") or ""))
            out.append(
                {
                    "id": sid,
                    "title": title,
                    "started_at": str(row.get("started_at") or ""),
                    "room_id": str(row.get("room_id") or ""),
                }
            )
        return out

    def current_chat(self) -> dict[str, Any]:
        """The conversation the phone is supposed to copy into.

        Sync used to call this and crash because only ``current_chat_fn``
        existed. ``list_chats`` already wraps its callback; this is the same
        shape. Empty means the phone had no house thread yet.
        """
        fn = self.current_chat_fn
        if fn is None:
            return {}
        try:
            chat = dict(fn() or {})
        except Exception:
            return {}
        sid = str(chat.get("id") or "").strip()
        if not sid:
            return {}
        title = display_session_title(str(chat.get("title") or ""))
        return {"id": sid, "title": title}

    def busy(self) -> bool:
        fn = self.busy_fn
        if fn is None:
            return False
        try:
            return bool(fn())
        except Exception:
            return False

    def replace_transcript(self, messages: list[Any]) -> None:
        """Paint an archived conversation. Same window as the PC history dock."""
        bubbles: deque[Bubble] = deque()
        if isinstance(messages, list):
            for row in messages:
                if not isinstance(row, dict):
                    continue
                role = str(row.get("role") or "").strip().lower()
                text = str(row.get("content") or row.get("text") or "").strip()
                if role in {"user", "assistant"} and text:
                    bubbles.append(Bubble(role=role, text=text))
        while len(bubbles) > TRANSCRIPT_LIMIT:
            bubbles.popleft()
        with self._lock:
            self.transcript = bubbles
            self.confirm = None

    def begin_load_wait(self) -> queue.Queue[dict[str, Any] | None]:
        q: queue.Queue[dict[str, Any] | None] = queue.Queue()
        with self._turn_lock:
            self._load_q = q
        return q

    def abandon_load_wait(self) -> None:
        with self._turn_lock:
            self._load_q = None

    def _emit_load(self, payload: dict[str, Any]) -> None:
        with self._turn_lock:
            q = self._load_q
        if q is not None:
            q.put(payload)

    def observe(self, event: Event) -> None:
        """Mirror bus events for status, glances, and an in-flight turn stream."""
        payload = event.payload or {}
        if event.type == EventType.SESSION_LOADED:
            if payload.get("ok") and not payload.get("silent"):
                messages = payload.get("messages") or []
                if isinstance(messages, list):
                    self.replace_transcript(messages)
                else:
                    self.replace_transcript([])
            self._emit_load(dict(payload) if isinstance(payload, dict) else {})
            return
        if event.type == EventType.USER_MESSAGE:
            text = str(payload.get("text") or "").strip()
            sid = str(payload.get("session_id") or "")
            foreign = bool(payload.get("foreign")) or self._foreign_turn(sid)
            self._turn_session_id = sid
            self._turn_foreign = foreign
            self._turn_speak = bool(payload.get("speak"))
            self._turn_language = str(payload.get("language") or "")
            if text and not foreign:
                with self._lock:
                    self.transcript.append(Bubble(role="user", text=text))
                    _trim_transcript(self.transcript)
            self._emit({"type": "user", "text": text})
            return
        if event.type == EventType.ASSISTANT_DELTA:
            self._emit({"type": "delta", "text": str(payload.get("text") or "")})
            return
        if event.type == EventType.ASSISTANT_RETRACT:
            self._emit({"type": "retract"})
            return
        if event.type == EventType.ASSISTANT_DONE:
            text = str(payload.get("text") or "")
            if not self._turn_foreign:
                with self._lock:
                    self.transcript.append(Bubble(role="assistant", text=text))
                    _trim_transcript(self.transcript)
            self._emit({"type": "done", "text": text})
            want_speech = self._turn_speak
            self._turn_session_id = ""
            self._turn_foreign = False
            self._turn_speak = False
            if want_speech:
                threading.Thread(
                    target=self._phone_speech,
                    args=(text, self._turn_language),
                    daemon=True,
                    name="arelis-phone-tts",
                ).start()
                return
            self._end_turn()
            return
        if event.type == EventType.ERROR:
            if str(payload.get("scope") or "") == "voice":
                return
            message = str(payload.get("message") or "turn failed")
            self._emit({"type": "error", "message": message})
            self._turn_session_id = ""
            self._turn_foreign = False
            self._turn_speak = False
            self._end_turn()
            return
        if event.type == EventType.TOOL_CONFIRM:
            # Lazy: presence.__init__ imports ingest, which imports this module.
            from arelis.presence.pending_confirms import (
                pending_from_event_payload,
                pending_from_payload,
            )

            confirm = pending_from_event_payload(payload) or pending_from_payload(
                payload
            )
            if not confirm.headline:
                confirm.headline = str(
                    payload.get("headline") or payload.get("summary") or "Allow"
                )
            self.set_confirm(confirm)
            self._confirm_session_id = self._turn_session_id or str(
                self._pc_chat().get("id") or ""
            )
            self._emit(
                {
                    "type": "confirm",
                    "id": confirm.id,
                    "tool": confirm.tool,
                    "headline": confirm.headline,
                    "summary": confirm.summary,
                    "detail": confirm.detail,
                }
            )
            return
        if event.type == EventType.TOOL_CONFIRM_REPLY:
            self.clear_confirm(str(payload.get("id") or ""))
            self._emit(
                {
                    "type": "confirm_reply",
                    "id": str(payload.get("id") or ""),
                    "decision": str(payload.get("decision") or ""),
                }
            )
            return
        if event.type == EventType.IMAGE_READY:
            path = str(payload.get("path") or "").strip()
            if path:
                glance = self.register_glance(title=Path(path).name, kind="image", path=path)
                if glance is not None:
                    self._emit(
                        {
                            "type": "glance",
                            "id": glance.id,
                            "title": glance.title,
                            "kind": glance.kind,
                        }
                    )
            return
        if event.type == EventType.FILE_READY:
            path = str(payload.get("abs_path") or payload.get("path") or "").strip()
            title = str(payload.get("title") or "").strip() or (Path(path).name if path else "file")
            if path:
                kind: GlanceKind = "image" if Path(path).suffix.lower() in {
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".webp",
                    ".gif",
                } else "file"
                glance = self.register_glance(title=title, kind=kind, path=path)
                if glance is not None:
                    self._emit(
                        {
                            "type": "glance",
                            "id": glance.id,
                            "title": glance.title,
                            "kind": glance.kind,
                        }
                    )
            return

    def begin_turn_wait(self) -> queue.Queue[dict[str, Any] | None]:
        q: queue.Queue[dict[str, Any] | None] = queue.Queue()
        with self._turn_lock:
            self._turn_q = q
        return q

    def abandon_turn_wait(self) -> None:
        with self._turn_lock:
            self._turn_q = None

    def normalize_sync(self, messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Gemma transcript lines for MOBILE_SYNC. No tools, no side effects."""
        out: list[dict[str, str]] = []
        for raw in messages:
            if not isinstance(raw, dict):
                continue
            role = str(raw.get("role") or "").strip().lower()
            text = str(raw.get("text") or raw.get("content") or "").strip()
            if role not in {"user", "assistant"} or not text:
                continue
            out.append({"role": role, "text": text[:8000]})
            if len(out) >= 40:
                break
        return out

    def apply_sync(self, messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Copy pocket lines onto the live hub transcript."""
        out = self.normalize_sync(messages)
        with self._lock:
            for row in out:
                self.transcript.append(Bubble(role=row["role"], text=row["text"]))
            if out:
                _trim_transcript(self.transcript)
        return out

    def _emit(self, item: dict[str, Any]) -> None:
        with self._turn_lock:
            q = self._turn_q
        if q is not None:
            q.put(item)

    def _phone_speech(self, text: str, language: str) -> None:
        """Kokoro for the phone speaker. Does not play on the PC."""
        try:
            from arelis.talk_language import is_english

            if not is_english(language):
                return
            fn = self.speak_fn
            blob = fn(text) if fn is not None else None
            if blob:
                self._emit(
                    {
                        "type": "speech",
                        "audio_wav_b64": base64.standard_b64encode(blob).decode("ascii"),
                    }
                )
        except Exception:
            log.exception("phone speech failed")
        finally:
            self._end_turn()

    def _end_turn(self) -> None:
        with self._turn_lock:
            q = self._turn_q
            self._turn_q = None
        if q is not None:
            q.put(None)


def decode_data_url_or_b64(raw: str) -> bytes:
    text = (raw or "").strip()
    if not text:
        return b""
    if "," in text and text.lower().startswith("data:"):
        text = text.split(",", 1)[1]
    try:
        return base64.b64decode(text, validate=False)
    except Exception:
        return b""


def ndjson_line(obj: dict[str, Any]) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _trim_transcript(items: deque[Bubble]) -> None:
    while len(items) > TRANSCRIPT_LIMIT:
        items.popleft()


def _trim_notices(items: deque[MobileNotice]) -> None:
    while len(items) > NOTICE_LIMIT:
        items.popleft()


# Listing junk that would drown a phone. Hidden files still show; these
# directories never should.
LIST_SKIP = frozenset(
    {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "dist",
        "build",
    }
)
LIST_CAP = 300


def _path_escaped(rel: str) -> bool:
    return any(part == ".." for part in Path(rel.replace("\\", "/")).parts)


def _contained(child: Path, root: Path) -> bool:
    try:
        child.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


def list_tree(root: Path, rel: str = "", *, cap: int = LIST_CAP) -> dict[str, Any]:
    """Directory listing under one workspace root. Raises PermissionError on .."""
    rel_norm = rel.replace("\\", "/").strip("/")
    if _path_escaped(rel_norm):
        raise PermissionError("path escaped the workspace")
    try:
        base = root.resolve()
        folder = (base / rel_norm).resolve() if rel_norm else base
    except OSError as exc:
        raise FileNotFoundError(str(exc)) from exc
    if not _contained(folder, base):
        raise PermissionError("path escaped the workspace")
    if not folder.is_dir():
        raise FileNotFoundError(rel_norm or str(folder))
    try:
        children = list(folder.iterdir())
    except OSError as exc:
        raise FileNotFoundError(str(exc)) from exc
    children.sort(key=lambda p: (not p.is_dir(), p.name.casefold()))
    items: list[dict[str, Any]] = []
    for child in children:
        if child.name in LIST_SKIP:
            continue
        rel_child = f"{rel_norm}/{child.name}" if rel_norm else child.name
        try:
            size = child.stat().st_size if child.is_file() else 0
        except OSError:
            size = 0
        items.append(
            {
                "name": child.name,
                "dir": child.is_dir(),
                "path": rel_child.replace("\\", "/"),
                "bytes": int(size),
            }
        )
        if len(items) >= cap:
            break
    parent: str | None
    if not rel_norm:
        parent = None
    else:
        parent = str(Path(rel_norm).parent.as_posix())
        if parent == ".":
            parent = ""
    return {
        "ok": True,
        "cwd": rel_norm,
        "parent": parent,
        "items": items,
        "capped": len([c for c in children if c.name not in LIST_SKIP]) > len(items),
    }


def _qualify_listing(data: dict[str, Any], prefix: str) -> dict[str, Any]:
    """Stamp project: onto relative paths so resolve_read can open them."""
    for item in data["items"]:
        item["path"] = prefix + str(item["path"])
    cwd = str(data.get("cwd") or "")
    data["cwd"] = prefix + cwd if cwd else prefix
    parent = data.get("parent")
    if parent is None:
        pass
    elif parent == "":
        data["parent"] = prefix
    else:
        data["parent"] = prefix + str(parent)
    data["qualified_prefix"] = prefix
    return data


def browse_files(
    roots: Any,
    *,
    scope: str = "workspace",
    rel: str = "",
    room_name: str = "",
    room_root: str = "",
) -> dict[str, Any]:
    """List a room folder or a workspace project. Path-jail is the roots."""
    from arelis.workspace import WorkspaceRoots

    if not isinstance(roots, WorkspaceRoots):
        raise TypeError("browse_files needs WorkspaceRoots")
    scope = (scope or "workspace").strip().lower()
    rel = (rel or "").replace("\\", "/").strip()
    if scope == "room":
        name = (room_root or roots.active).strip()
        entry = roots.root_named(name) or roots.active_root()
        data = list_tree(entry.path, rel)
        data["scope"] = "room"
        data["project"] = entry.name
        data["label"] = room_name or entry.name
        return _qualify_listing(data, f"{entry.name}:")
    if not rel:
        if len(roots) == 1:
            entry = roots.roots[0]
            data = list_tree(entry.path, "")
            data["scope"] = "workspace"
            data["project"] = entry.name
            data["label"] = entry.name
            return _qualify_listing(data, f"{entry.name}:")
        return {
            "ok": True,
            "scope": "workspace",
            "cwd": "",
            "parent": None,
            "project": roots.active,
            "label": "workspace",
            "qualified_prefix": "",
            "items": [
                {
                    "name": r.name,
                    "dir": True,
                    "path": f"{r.name}:",
                    "bytes": 0,
                }
                for r in roots.roots
            ],
            "capped": False,
        }
    known = set(roots.names())
    project = ""
    rest = rel
    if ":" in rel:
        head, tail = rel.split(":", 1)
        if head in known:
            project = head
            rest = tail.lstrip("/")
    if project:
        entry = roots.root_named(project)
        if entry is None:
            raise FileNotFoundError(project)
        data = list_tree(entry.path, rest)
        data["scope"] = "workspace"
        data["project"] = entry.name
        data["label"] = entry.name
        qualified = _qualify_listing(data, f"{entry.name}:")
        if not rest and len(roots) > 1:
            qualified["parent"] = ""
        return qualified
    entry = roots.active_root()
    data = list_tree(entry.path, rel)
    data["scope"] = "workspace"
    data["project"] = entry.name
    data["label"] = entry.name
    return _qualify_listing(data, f"{entry.name}:")
