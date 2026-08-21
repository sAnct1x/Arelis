"""Pocket Arelis talk path — no live phone."""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import httpx
import pytest

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.mobile import PHONE_PERSONA_TAIL, MobileHub, PendingConfirm
from arelis.sms_inbound import SeenMessageStore
from arelis.sms_ingest import InboundIngestServer


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_status_says_at_the_house_when_session_is_live() -> None:
    hub = MobileHub()
    hub.bind(session_ready=lambda: True, warmup=lambda: False, model=lambda: "qwen3.5:9b")
    status = hub.status()
    assert status["mode"] == "at_the_house"
    assert status["session"] is True
    assert status["model"] == "qwen3.5:9b"
    assert status["pending_confirm"] is None


def test_persona_forbids_tools_on_the_phone() -> None:
    hub = MobileHub()
    hub.bind(persona=lambda: "You are Arelis.")
    body = hub.persona_payload()["system"]
    assert "You are Arelis." in body
    assert PHONE_PERSONA_TAIL[:40] in body
    assert "cannot send mail" in body


def test_sync_normalizes_and_caps(tmp_path: Path) -> None:
    hub = MobileHub()
    rows = hub.apply_sync(
        [
            {"role": "user", "text": "hello from the plane"},
            {"role": "assistant", "text": "I am on the phone."},
            {"role": "system", "text": "ignore me"},
            {"role": "user", "text": ""},
        ]
    )
    assert rows == [
        {"role": "user", "text": "hello from the plane"},
        {"role": "assistant", "text": "I am on the phone."},
    ]
    texts = [row["text"] for row in hub.status()["transcript"]]
    assert texts == ["hello from the plane", "I am on the phone."]


def test_glance_serves_small_file(tmp_path: Path) -> None:
    hub = MobileHub()
    dest = tmp_path / "plot.png"
    dest.write_bytes(b"\x89PNG" + b"\x00" * 20)
    glance = hub.register_glance(title="plot.png", kind="image", path=str(dest))
    assert glance is not None
    data, mime, name = hub.file_bytes(glance.id) or (b"", "", "")
    assert data.startswith(b"\x89PNG")
    assert "png" in mime
    assert name == "plot.png"


def test_allow_notice_is_not_sms() -> None:
    hub = MobileHub()
    hub.set_confirm(
        PendingConfirm(id="c1", tool="send_sms", headline="text wife", summary="hello")
    )
    status = hub.status()
    assert status["pending_confirm"]["id"] == "c1"
    assert status["notices"][0]["kind"] == "allow"
    hub.push_notice("job", "image finished", "the plot is ready")
    kinds = {n["kind"] for n in hub.status()["notices"]}
    assert kinds == {"allow", "job"}
    hub.push_notice("sms", "Robin", "hi")
    kinds = {n["kind"] for n in hub.status()["notices"]}
    assert "sms" not in kinds


async def test_mobile_http_status_and_unauthorized(tmp_path: Path) -> None:
    bus = EventBus()
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(bus.run())
    port = _free_port()
    server = InboundIngestServer(
        bus,
        loop,
        token="test-token",
        host="127.0.0.1",
        port=port,
        seen=SeenMessageStore(tmp_path / "seen.json"),
    )
    server.mobile.bind(session_ready=lambda: True)
    server.start()
    base = f"http://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient() as client:
            denied = await client.get(f"{base}/mobile/status")
            assert denied.status_code == 401
            ok = await client.get(
                f"{base}/mobile/status",
                headers={"X-Arelis-Token": "test-token"},
            )
            assert ok.status_code == 200
            body = ok.json()
            assert body["ok"] is True
            assert body["mode"] == "at_the_house"
            assert body["session"] is True
    finally:
        server.stop()
        bus.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_mobile_turn_streams_until_done(tmp_path: Path) -> None:
    bus = EventBus()
    loop = asyncio.get_running_loop()

    async def echo(event: Event) -> None:
        if event.type != EventType.USER_MESSAGE:
            return
        if event.payload.get("source") != "mobile":
            return
        await bus.publish(Event(EventType.ASSISTANT_DELTA, {"text": "hi "}))
        await bus.publish(Event(EventType.ASSISTANT_DONE, {"text": "hi there"}))

    bus.subscribe(EventType.USER_MESSAGE, echo)
    task = asyncio.create_task(bus.run())
    port = _free_port()
    server = InboundIngestServer(
        bus,
        loop,
        token="test-token",
        host="127.0.0.1",
        port=port,
        seen=SeenMessageStore(tmp_path / "seen.json"),
    )
    server.mobile.bind(session_ready=lambda: True, busy=lambda: False)
    server.start()
    base = f"http://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{base}/mobile/turn",
                headers={"X-Arelis-Token": "test-token"},
                json={"text": "hello"},
            )
            assert resp.status_code == 200
            lines = [json.loads(row) for row in resp.text.splitlines() if row.strip()]
            types = [row["type"] for row in lines]
            assert "delta" in types
            assert types[-1] == "done"
            assert any(row.get("text") == "hi there" for row in lines if row["type"] == "done")
    finally:
        server.stop()
        bus.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_mobile_turn_without_session_is_503(tmp_path: Path) -> None:
    bus = EventBus()
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(bus.run())
    port = _free_port()
    server = InboundIngestServer(
        bus,
        loop,
        token="test-token",
        host="127.0.0.1",
        port=port,
        seen=SeenMessageStore(tmp_path / "seen.json"),
    )
    server.start()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://127.0.0.1:{port}/mobile/turn",
                headers={"X-Arelis-Token": "test-token"},
                json={"text": "hello"},
            )
            assert resp.status_code == 503
            assert "open Arelis" in resp.json()["error"]
    finally:
        server.stop()
        bus.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_mobile_confirm_and_sync_publish(tmp_path: Path) -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(None, capture)
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(bus.run())
    port = _free_port()
    server = InboundIngestServer(
        bus,
        loop,
        token="test-token",
        host="127.0.0.1",
        port=port,
        seen=SeenMessageStore(tmp_path / "seen.json"),
    )
    server.mobile.bind(
        session_ready=lambda: True,
        current_chat=lambda: {"id": "s1", "title": "hello"},
    )
    server.mobile.set_confirm(
        PendingConfirm(id="c9", tool="send_email", headline="mail", summary="hi")
    )
    server.start()
    base = f"http://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient() as client:
            denied = await client.post(
                f"{base}/mobile/confirm",
                headers={"X-Arelis-Token": "test-token"},
                json={"id": "c9", "decision": "deny"},
            )
            assert denied.status_code == 200
            assert denied.json()["decision"] == "skip"
            copied = await client.post(
                f"{base}/mobile/sync",
                headers={"X-Arelis-Token": "test-token"},
                json={
                    "session_id": "s1",
                    "messages": [
                        {"role": "user", "text": "plane thought"},
                        {"role": "assistant", "text": "noted"},
                    ]
                },
            )
            assert copied.status_code == 200
            assert copied.json()["copied"] == 2
        await asyncio.sleep(0.05)
        types = [e.type for e in seen]
        assert EventType.TOOL_CONFIRM_REPLY in types
        assert EventType.MOBILE_SYNC in types
    finally:
        server.stop()
        bus.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_orchestrator_sync_appends_without_a_turn() -> None:
    from arelis.core.orchestrator import Orchestrator
    from arelis.tools.base import ToolRegistry

    class _StubRouter:
        default_role = "fast"
        active_model = "stub"

    memory = SessionMemory()
    bus = EventBus()
    orch = Orchestrator(
        bus,
        _StubRouter(),  # type: ignore[arg-type]
        ToolRegistry(),
        {"_persona_path": "persona.md", "workspace": {"roots": ["."]}},
        memory,
    )
    await orch.on_mobile_sync(
        Event(
            EventType.MOBILE_SYNC,
            {
                "messages": [
                    {"role": "user", "text": "plane thought"},
                    {"role": "assistant", "text": "noted"},
                ]
            },
        )
    )
    roles = [m.role for m in memory.messages]
    assert "notice" not in roles
    assert memory.messages[-2].content == "plane thought"
    assert memory.messages[-1].content == "noted"
    assert orch._turn_task is None


def test_list_tree_skips_junk_and_blocks_escape(tmp_path: Path) -> None:
    from arelis.mobile import browse_files, list_tree
    from arelis.workspace import WorkspaceRoots

    proj = tmp_path / "work"
    (proj / "notes").mkdir(parents=True)
    (proj / "notes" / "idea.md").write_text("hello", encoding="utf-8")
    (proj / ".git" / "obj").mkdir(parents=True)
    (proj / ".git" / "obj" / "pack").write_text("no", encoding="utf-8")
    listing = list_tree(proj, "")
    names = {row["name"] for row in listing["items"]}
    assert "notes" in names
    assert ".git" not in names
    nested = list_tree(proj, "notes")
    assert nested["items"][0]["name"] == "idea.md"
    try:
        list_tree(proj, "..")
        raise AssertionError("escape should fail")
    except PermissionError:
        pass
    roots = WorkspaceRoots.from_paths([str(proj)])
    room = browse_files(
        roots, scope="room", rel="", room_name="Physics", room_root=roots.active
    )
    assert room["scope"] == "room"
    assert room["label"] == "Physics"
    assert any(row["name"] == "notes" for row in room["items"])


async def test_mobile_files_http_jails_to_workspace(tmp_path: Path) -> None:
    from arelis.mobile import GLANCE_MAX_BYTES, browse_files
    from arelis.workspace import WorkspaceRoots

    proj = tmp_path / "lab"
    proj.mkdir()
    (proj / "plot.png").write_bytes(b"\x89PNG" + b"\x00" * 12)
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    roots = WorkspaceRoots.from_paths([str(proj)])

    def list_files(scope: str, rel: str) -> dict:
        return browse_files(roots, scope=scope, rel=rel)

    def open_file(path: str) -> tuple[bytes, str, str] | None:
        hit = roots.resolve_read(path)
        if not hit.path.is_file():
            return None
        data = hit.path.read_bytes()
        if len(data) > GLANCE_MAX_BYTES:
            raise ValueError("too big")
        return data, "image/png", hit.path.name

    bus = EventBus()
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(bus.run())
    port = _free_port()
    server = InboundIngestServer(
        bus,
        loop,
        token="test-token",
        host="127.0.0.1",
        port=port,
        seen=SeenMessageStore(tmp_path / "seen.json"),
    )
    server.mobile.bind(
        session_ready=lambda: True,
        files=list_files,
        open_file=open_file,
        place=lambda: {
            "workspace": roots.active,
            "roots": roots.names(),
            "room": None,
        },
    )
    server.start()
    base = f"http://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient() as client:
            denied = await client.get(f"{base}/mobile/files")
            assert denied.status_code == 401
            listed = await client.get(
                f"{base}/mobile/files",
                params={"scope": "workspace", "path": ""},
                headers={"X-Arelis-Token": "test-token"},
            )
            assert listed.status_code == 200
            names = {row["name"] for row in listed.json()["items"]}
            assert "plot.png" in names
            path = next(
                row["path"] for row in listed.json()["items"] if row["name"] == "plot.png"
            )
            opened = await client.get(
                f"{base}/mobile/open",
                params={"path": path},
                headers={"X-Arelis-Token": "test-token"},
            )
            assert opened.status_code == 200
            assert opened.content.startswith(b"\x89PNG")
            escaped = await client.get(
                f"{base}/mobile/files",
                params={"scope": "workspace", "path": ".."},
                headers={"X-Arelis-Token": "test-token"},
            )
            assert escaped.status_code == 403
            status = await client.get(
                f"{base}/mobile/status",
                headers={"X-Arelis-Token": "test-token"},
            )
            assert status.json()["place"]["workspace"] == roots.active
    finally:
        server.stop()
        bus.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_session_loaded_replaces_phone_transcript() -> None:
    hub = MobileHub()
    hub.replace_transcript([{"role": "user", "content": "old"}])
    hub.observe(
        Event(
            EventType.SESSION_LOADED,
            {
                "ok": True,
                "session_id": "s2",
                "messages": [{"role": "user", "content": "loaded"}],
            },
        )
    )
    rows = hub.status()["transcript"]
    assert [row["text"] for row in rows] == ["loaded"]


def test_chats_bind_into_status() -> None:
    hub = MobileHub()
    hub.bind(
        session_ready=lambda: True,
        chats=lambda: [
            {"id": "s1", "title": "hello", "started_at": "2026-08-21T00:00:00Z"}
        ],
        current_chat=lambda: {"id": "s1", "title": "hello"},
    )
    listed = hub.list_chats()
    assert listed[0]["id"] == "s1"
    assert listed[0]["title"] == "hello"
    assert hub.status()["chat"]["id"] == "s1"


async def test_mobile_chats_http_and_new_chat(tmp_path: Path) -> None:
    bus = EventBus()
    loop = asyncio.get_running_loop()

    async def on_load(event: Event) -> None:
        if event.type != EventType.SESSION_LOAD:
            return
        await bus.publish(
            Event(
                EventType.SESSION_LOADED,
                {
                    "ok": True,
                    "session_id": "new-1",
                    "messages": [],
                    "new": True,
                },
            )
        )

    bus.subscribe(EventType.SESSION_LOAD, on_load)
    task = asyncio.create_task(bus.run())
    port = _free_port()
    server = InboundIngestServer(
        bus,
        loop,
        token="test-token",
        host="127.0.0.1",
        port=port,
        seen=SeenMessageStore(tmp_path / "seen.json"),
    )
    server.mobile.bind(
        session_ready=lambda: True,
        busy=lambda: False,
        chats=lambda: [{"id": "s1", "title": "hello", "started_at": "t"}],
        current_chat=lambda: {"id": "s1", "title": "hello"},
    )
    server.start()
    base = f"http://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            listed = await client.get(
                f"{base}/mobile/chats",
                headers={"X-Arelis-Token": "test-token"},
            )
            assert listed.status_code == 200
            body = listed.json()
            assert body["chats"][0]["id"] == "s1"
            created = await client.post(
                f"{base}/mobile/chat",
                headers={"X-Arelis-Token": "test-token"},
                json={"action": "new"},
            )
            assert created.status_code == 200
            assert created.json()["ok"] is True
    finally:
        server.stop()
        bus.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_sync_without_a_thread_starts_a_new_chat(tmp_path: Path) -> None:
    bus = EventBus()
    loads: list[Event] = []

    async def on_load(event: Event) -> None:
        loads.append(event)
        if event.type != EventType.SESSION_LOAD:
            return
        await bus.publish(
            Event(
                EventType.SESSION_LOADED,
                {
                    "ok": True,
                    "session_id": "pocket-1",
                    "messages": [],
                    "new": True,
                },
            )
        )

    bus.subscribe(EventType.SESSION_LOAD, on_load)
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(bus.run())
    port = _free_port()
    server = InboundIngestServer(
        bus,
        loop,
        token="test-token",
        host="127.0.0.1",
        port=port,
        seen=SeenMessageStore(tmp_path / "seen.json"),
    )
    server.mobile.bind(
        session_ready=lambda: True,
        current_chat=lambda: {"id": "old-tuesday", "title": "old"},
    )
    server.start()
    base = f"http://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            copied = await client.post(
                f"{base}/mobile/sync",
                headers={"X-Arelis-Token": "test-token"},
                json={
                    "messages": [
                        {"role": "user", "text": "from the plane"},
                        {"role": "assistant", "text": "here"},
                    ]
                },
            )
            assert copied.status_code == 200
            assert copied.json()["copied"] == 2
        assert any(e.payload.get("new") for e in loads)
        texts = [row["text"] for row in server.mobile.status()["transcript"]]
        assert texts == ["from the plane", "here"]
    finally:
        server.stop()
        bus.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

