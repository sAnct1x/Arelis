"""Escape on an open Allow card declines a complete send.

The key is a real QTest.keyClick on the card. The conversation stage shortcut
is the handler. Nothing here calls the deny slot.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import asyncio
import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from arelis.contacts import Contact, normalize_phone
from arelis.core.email_complete import complete_email_draft, draft_send_email_args
from arelis.core.sms_complete import complete_sms_draft, draft_send_sms_args
from arelis.presence.confirm_persist import ConfirmPersister
from arelis.presence.pending_confirms import PendingConfirm
from arelis.tools.base import ToolResult
from arelis.tools.policy import describe_call


def _book() -> dict[str, Contact]:
    phone = "+15551234567"
    return {
        "brian": Contact(
            alias="brian",
            name="Brian",
            phone=phone,
            digits=normalize_phone(phone),
            email="brian@example.com",
            aliases=("brian",),
        )
    }


def _block_sends(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record a send if one starts, and never touch the network."""
    ran: list[str] = []

    async def _email(self, **kwargs: object) -> ToolResult:
        ran.append("send_email")
        return ToolResult(ok=False, output="blocked by test")

    async def _sms(self, **kwargs: object) -> ToolResult:
        ran.append("send_sms")
        return ToolResult(ok=False, output="blocked by test")

    monkeypatch.setattr("arelis.tools.email_send.SendEmailTool.run", _email)
    monkeypatch.setattr("arelis.tools.sms_send.SendSmsTool.run", _sms)

    from arelis.ui import confirm_host

    original = confirm_host.execute_pending_confirm

    async def _execute(item: PendingConfirm, config: dict) -> tuple[bool, str]:
        ran.append(f"execute:{item.tool}")
        return await original(item, config)

    monkeypatch.setattr(confirm_host, "execute_pending_confirm", _execute)
    return ran


class _Loop:
    """The window publishes the reply on its asyncio loop. That loop has to be running."""

    def __init__(self, window) -> None:
        self.window = window
        self.thread = threading.Thread(
            target=window.loop.run_forever,
            name="confirm-escape-loop",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()
        loop = self.window.loop
        for _ in range(100):
            if loop.is_running():
                break
            self.thread.join(0.01)
        if not loop.is_running():
            raise RuntimeError("event loop did not start")

        async def _boot() -> None:
            asyncio.get_running_loop().create_task(self.window.bus.run())

        asyncio.run_coroutine_threadsafe(_boot(), loop).result(timeout=2)
        ConfirmPersister(self.window.bus, self.window._pending_store).start()

    def stop(self) -> None:
        if self.thread.ident is None:
            return
        loop = self.window.loop
        if loop.is_running():

            async def _halt() -> None:
                current = asyncio.current_task()
                pending = [task for task in asyncio.all_tasks() if task is not current]
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)

            asyncio.run_coroutine_threadsafe(_halt(), loop).result(timeout=2)
            loop.call_soon_threadsafe(loop.stop)
        self.thread.join(timeout=2)


def _stage_escape(window) -> QShortcut:
    stage = window.conversation
    found = [
        shortcut
        for shortcut in stage.findChildren(QShortcut)
        if shortcut.parent() is stage and shortcut.key() == QKeySequence(Qt.Key_Escape)
    ]
    assert len(found) == 1
    return found[0]


def _show_allow_card(window, qtbot, item: PendingConfirm):
    window._pending_store.upsert(item)
    window.resize(900, 700)
    with qtbot.waitExposed(window, timeout=3000):
        window.show()
        handle = window.windowHandle()
        if handle is not None:
            handle.requestActivate()
        window.activateWindow()
        window.raise_()
    window.queue_pending_confirms([item])
    card = window.conversation.confirm
    qtbot.waitUntil(
        lambda: card.isVisible() and bool(card._confirm_id) and card.allow_btn.isVisible(),
        timeout=3000,
    )
    active = QApplication.activeWindow()
    assert isinstance(active, QWidget)
    assert active is window or active.window() is window
    assert card.allow_btn.text() == "allow"
    assert window._pending_queue and window._pending_queue[0].id == item.id
    assert window._pending_store.get(item.id) is not None
    return card


def _escape_declines(window, qtbot, qt_app, item: PendingConfirm, ran: list[str], *needles: str) -> None:
    hits: list[str] = []
    decisions: list[str] = []
    shortcut = _stage_escape(window)
    shortcut.activated.connect(lambda: hits.append("escape"))
    window.conversation.confirm_decided.connect(
        lambda _cid, decision, _batch: decisions.append(decision)
    )
    card = _show_allow_card(window, qtbot, item)
    shown = card.detail.toPlainText()
    for needle in needles:
        assert needle in shown
    # The card itself, through the normal shortcut. Not confirm._skip().
    QTest.keyClick(card, Qt.Key_Escape)
    qt_app.processEvents()
    qtbot.waitUntil(
        lambda: not window.conversation.confirm_open() and not window._pending_store.list(),
        timeout=3000,
    )
    qt_app.processEvents()
    assert hits == ["escape"]
    assert decisions == ["skip"]
    assert window._pending_queue == []
    assert window._pending_store.list() == []
    assert ran == []
    assert not card.isVisible()


def test_escape_declines_a_complete_email_draft(
    qtbot, qt_app, arelis_window, tmp_path, monkeypatch
) -> None:
    assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    book = _book()
    draft = complete_email_draft(
        "Email Brian about Running late: Stuck in traffic",
        contacts=book,
    )
    assert draft is not None and draft.complete
    args = {key: str(value) for key, value in draft_send_email_args(draft).items()}
    assert args["subject"] == "Running late"
    assert args["body"] == "Stuck in traffic"
    item = PendingConfirm(
        id="email-escape",
        tool="send_email",
        args=args,
        summary="email Brian",
        detail=describe_call("send_email", args),
        batch_ok=False,
    )
    ran = _block_sends(monkeypatch)
    window = arelis_window(
        {"presence": {"pending_confirms_path": str(tmp_path / "pending.json")}}
    )
    loop = _Loop(window)
    try:
        loop.start()
        qtbot.wait(50)
        _escape_declines(
            window,
            qtbot,
            qt_app,
            item,
            ran,
            "Running late",
            "Stuck in traffic",
        )
    finally:
        loop.stop()


def test_escape_declines_a_complete_text_draft(
    qtbot, qt_app, arelis_window, tmp_path, monkeypatch
) -> None:
    assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    book = _book()
    monkeypatch.setattr("arelis.contacts.load_contacts", lambda: book)
    draft = complete_sms_draft("Text Brian: Running late", contacts=book)
    assert draft is not None and draft.complete
    args = {key: str(value) for key, value in draft_send_sms_args(draft).items()}
    assert args["body"] == "Running late"
    assert args["to"] == "brian"
    item = PendingConfirm(
        id="sms-escape",
        tool="send_sms",
        args=args,
        summary="text Brian",
        detail=describe_call("send_sms", args),
        batch_ok=False,
    )
    ran = _block_sends(monkeypatch)
    window = arelis_window(
        {"presence": {"pending_confirms_path": str(tmp_path / "pending.json")}}
    )
    loop = _Loop(window)
    try:
        loop.start()
        qtbot.wait(50)
        _escape_declines(window, qtbot, qt_app, item, ran, "Running late")
    finally:
        loop.stop()
