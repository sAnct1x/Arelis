"""A send and an inbound text must not leave a phone or an email in the logs.

One turn, the real audit, turn, and ledger writers, then one ingest POST.
The chat events still carry the addresses. The files keep a count or the
marker for that field.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from pathlib import Path
from types import ModuleType, SimpleNamespace

import httpx
import pytest

from arelis.contacts import Contact, normalize_phone
from arelis.core import event_audit, receipts, turn_telemetry
from arelis.core.bus import EventBus
from arelis.core.event_audit import attach_event_audit
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.mail import MailAccount
from arelis.memory.store import MemoryStore
from arelis.sms_inbound import SeenMessageStore
from arelis.sms_ingest import InboundIngestServer
from arelis.tools.base import ToolRegistry
from arelis.tools.email_send import SendEmailTool
from arelis.tools.memory_tool import MemoryTool
from arelis.tools.sms_send import SendSmsTool
from arelis.ui.panels.thinking import ThinkingPanel
from arelis.workspace import RootEntry, WorkspaceRoots
from tests.hardening_helpers import _config, _ScriptedRouter

PHONE = "555-0100"
EMAIL = "test@example.com"
USER = "Send a text. Send an email, and remember this."
FACT = f"reach {PHONE} or {EMAIL}"
REPLY = f"Done. Phone {PHONE}. Mail {EMAIL}."
_SECRETS = (PHONE, "5550100", EMAIL)


class _SmsProvider:
    async def send(self, *, phone: str, body: str) -> str:
        del phone, body
        return "sms-1"


class _Mailer:
    async def send_async(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        attachments: list[Path] | None = None,
    ) -> str:
        del to, subject, body, attachments
        return "mail-1"


class _QuietChat:
    def add_thought_line(self, line: str) -> None:
        del line

    def extend_thought(self, chunk: str) -> None:
        del chunk

    def show_idle_note(self, line: str) -> None:
        del line


def _detach(module: ModuleType, logger_name: str) -> None:
    lg = logging.getLogger(logger_name)
    tag = module._HANDLER_TAG
    for handler in list(lg.handlers):
        if getattr(handler, "_arelis_tag", "") == tag:
            handler.flush()
            handler.close()
            lg.removeHandler(handler)
    module._attached = False


def _flush() -> None:
    names = (
        "",
        "arelis.event.audit",
        "arelis.turn.trace",
        "arelis.sms_ingest",
        "arelis.ui.panels.thinking",
    )
    for name in names:
        for handler in logging.getLogger(name).handlers:
            handler.flush()


def _call(name: str, arguments: dict[str, str]) -> dict[str, object]:
    return {
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


@pytest.mark.asyncio
async def test_send_and_ingest_logs_omit_phone_and_email(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qt_app
) -> None:
    """Fake phone and email survive the send and the ingest, and stay out of the logs."""
    del qt_app
    monkeypatch.setattr(turn_telemetry, "logs_dir", lambda: tmp_path)
    monkeypatch.setattr(event_audit, "logs_dir", lambda: tmp_path)
    monkeypatch.setattr(receipts, "DEFAULT_LEDGER_PATH", tmp_path / "action_ledger.jsonl")
    _detach(event_audit, "arelis.event.audit")
    _detach(turn_telemetry, "arelis.turn.trace")

    root = logging.getLogger()
    saved_level = root.level
    app_log = logging.FileHandler(tmp_path / "arelis.log", encoding="utf-8")
    app_log.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(app_log)
    root.setLevel(logging.INFO)
    store = MemoryStore(tmp_path / "memory.db")
    bus = EventBus()
    server: InboundIngestServer | None = None
    task: asyncio.Task[None] | None = None
    try:
        panel = ThinkingPanel()
        panel.bind(SimpleNamespace(chat=_QuietChat(), _turn_busy=True))
        seen: list[Event] = []

        def _allow(event: Event) -> None:
            if event.type != EventType.TOOL_CONFIRM:
                return
            bus.publish_nowait(
                Event(
                    EventType.TOOL_CONFIRM_REPLY,
                    {"id": event.payload.get("id"), "decision": "allow"},
                )
            )

        def _mirror(event: Event) -> None:
            seen.append(event)
            if event.type == EventType.THINKING:
                text = str(event.payload.get("text") or "")
                if event.payload.get("stream"):
                    panel.extend_stream(text)
                else:
                    panel.append(text)
            elif event.type == EventType.STATUS:
                panel.append(str(event.payload.get("message") or ""), kind="status")

        bus.subscribe(None, _allow)
        bus.subscribe(None, _mirror)
        cfg = _config()
        cfg["agent"]["chat_fast_path"] = False
        cfg["agent"]["turn_telemetry"] = True
        cfg["agent"]["event_telemetry"] = True
        cfg["agent"]["max_rounds"] = 8
        cfg["agent"]["confirm_timeout_s"] = 5
        assert attach_event_audit(bus, cfg) is True

        book = {
            "pat": Contact(
                alias="pat",
                name="Pat",
                phone=PHONE,
                digits=normalize_phone(PHONE),
            )
        }
        tools = ToolRegistry()
        tools.register(SendSmsTool(_SmsProvider(), contacts_loader=lambda: book))
        tools.register(
            SendEmailTool(
                MailAccount(address="owner@example.com", password="test-password"),
                _Mailer(),
            )
        )
        tools.register(MemoryTool(store))
        router = _ScriptedRouter(
            [
                [
                    (
                        "tool_calls",
                        [
                            _call("send_sms", {"to": PHONE, "body": "on my way"}),
                            _call(
                                "send_email",
                                {
                                    "to": EMAIL,
                                    "subject": "note",
                                    "body": "hello",
                                },
                            ),
                            _call(
                                "memory",
                                {"action": "remember", "fact": FACT},
                            ),
                        ],
                    )
                ],
                [("token", REPLY)],
            ]
        )
        Orchestrator(
            bus,
            router,  # type: ignore[arg-type]
            tools,
            cfg,
            SessionMemory(),
            WorkspaceRoots([RootEntry(name="work", path=tmp_path)]),
        )
        task = asyncio.create_task(bus.run())
        await bus.publish(
            Event(EventType.USER_MESSAGE, {"text": USER, "source": "chat"})
        )
        await bus.drain()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        server = InboundIngestServer(
            bus,
            asyncio.get_running_loop(),
            token="test-token",
            host="127.0.0.1",
            port=port,
            seen=SeenMessageStore(tmp_path / "seen.json"),
        )
        server.start()
        async with httpx.AsyncClient() as client:
            posted = await client.post(
                f"http://127.0.0.1:{port}/inbound/sms",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "id": "msg-1",
                    "from": PHONE,
                    "body": "ping",
                    "source": "notification",
                },
            )
        assert posted.status_code == 200
        assert posted.json()["published"] is True
        await asyncio.sleep(0.05)
        await bus.drain()
        _flush()

        events_log = (tmp_path / "events.log").read_text(encoding="utf-8")
        arelis_log = (tmp_path / "arelis.log").read_text(encoding="utf-8")
        turns_log = (tmp_path / "turns.log").read_text(encoding="utf-8")
        turns_json = (tmp_path / "turns.jsonl").read_text(encoding="utf-8")
        ledger = (tmp_path / "action_ledger.jsonl").read_text(encoding="utf-8")
        for secret in _SECRETS:
            assert secret not in events_log, secret
            assert secret not in arelis_log, secret
            assert secret not in turns_log, secret
            assert secret not in turns_json, secret
            assert secret not in ledger, secret
        assert USER not in events_log
        assert USER not in turns_json
        assert "preview=" not in events_log
        assert '"to":' not in ledger

        outputs = [
            str(event.payload.get("output") or "")
            for event in seen
            if event.type == EventType.TOOL_RESULT and event.payload.get("ok")
        ]
        assert any(PHONE in output and "Sent SMS" in output for output in outputs)
        assert any(EMAIL in output and "Sent email" in output for output in outputs)
        assert any(output == f"Remembered: {FACT}" for output in outputs)
        for output in outputs:
            assert f"chars={len(output)}" in events_log

        done = [
            str(event.payload.get("text") or "")
            for event in seen
            if event.type == EventType.ASSISTANT_DONE
        ]
        assert done and done[-1]
        assert f"chars={len(done[-1])}" in events_log
        assert f"chars={len(USER)}" in events_log
        assert "tool=send_sms" in events_log
        assert "tool=send_email" in events_log
        assert "tool=memory" in events_log

        inbound = [
            event
            for event in seen
            if event.type == EventType.SMS_RECEIVED
        ]
        assert inbound
        assert inbound[-1].payload.get("from") == PHONE
        assert "from=sender" in events_log
        assert "Inbound ingest published" in arelis_log
        assert "from=sender" in arelis_log
        assert "tool=send_sms" in arelis_log
        assert "tool=memory chars=" in arelis_log

        assert "send_sms" in ledger
        assert "send_email" in ledger
        assert "to_chars" in ledger
        assert f'"to_chars": {len(PHONE)}' in ledger
        assert f'"to_chars": {len(EMAIL)}' in ledger
    finally:
        if server is not None:
            server.stop()
        bus.stop()
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        store.close()
        _detach(event_audit, "arelis.event.audit")
        _detach(turn_telemetry, "arelis.turn.trace")
        app_log.flush()
        app_log.close()
        root.removeHandler(app_log)
        root.setLevel(saved_level)
