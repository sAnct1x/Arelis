"""Fresh profiles stay quiet about phone notify until the user turns it on.

Catches the shipped default plus a missing pairing token appending a chat
notice that names a local secrets path. Existing explicit true/false must
keep their meaning; the notice, when it does appear, has to point at Settings.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import re
import socket
from pathlib import Path

import pytest
import yaml

from arelis.config import DEFAULT_CONFIG_PATH, load_config
from arelis.core.events import Event, EventType
from arelis.i18n import tr
from arelis.presence.inbound_runtime import attach_inbound
from arelis.ui.event_host import dispatch_event

# English source. inbound_runtime.PHONE_NOTIFY_NEEDS_PAIRING must match once it exists.
PHONE_NOTIFY_NEEDS_PAIRING = (
    "Phone notifications are turned on but not set up yet. "
    "To finish, open Settings, go to Notify, and pick Create a pairing code."
)

PATH_IN_USER_TEXT = re.compile(
    r"(?i)(?:\bdata[/\\]|\.ya?ml\b|\b[a-z]:[\\/]|appdata|%localappdata%)"
)

_NOTICE_PRODUCERS = (
    Path("arelis") / "presence" / "inbound_runtime.py",
    Path("arelis") / "presence" / "glass_inbound.py",
)


def _shipped_config() -> dict:
    return copy.deepcopy(load_config(DEFAULT_CONFIG_PATH))


async def _attach(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    config: dict,
    *,
    token: str | None,
):
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "seat"))
    if token:
        monkeypatch.setenv("ARELIS_INGEST_TOKEN", token)
    else:
        monkeypatch.delenv("ARELIS_INGEST_TOKEN", raising=False)
    monkeypatch.setattr(
        "arelis.presence.inbound_runtime.load_ingest_token",
        lambda: token,
    )
    monkeypatch.setattr(
        "arelis.presence.inbound_runtime.load_sms_account",
        lambda: None,
    )
    from arelis.core.bus import EventBus

    bus = EventBus()
    loop = asyncio.get_running_loop()
    bus_task = asyncio.create_task(bus.run())
    runtime = attach_inbound(bus, loop, config, owned=True)
    return runtime, bus, bus_task


async def _stop(runtime, bus, bus_task) -> None:
    await runtime.stop()
    bus.stop()
    bus_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await bus_task


async def test_fresh_default_config_shows_no_phone_notice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A new profile has ingest auto and no token: no listener, no notice."""
    runtime, bus, bus_task = await _attach(monkeypatch, tmp_path, _shipped_config(), token=None)
    try:
        assert runtime.status_messages == []
        assert runtime.ingest is None
    finally:
        await _stop(runtime, bus, bus_task)


async def test_enabled_without_token_says_so_without_a_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Someone who set ingest true by hand still gets a notice, not a file path."""
    config = _shipped_config()
    config["tools"]["sms"]["inbound"]["ingest"]["enabled"] = True
    runtime, bus, bus_task = await _attach(monkeypatch, tmp_path, config, token=None)
    try:
        assert len(runtime.status_messages) == 1
        text = runtime.status_messages[0]
        assert text == PHONE_NOTIFY_NEEDS_PAIRING
        assert text.startswith("Phone notifications")
        assert not text.startswith("Phone notifications: http")
        assert PATH_IN_USER_TEXT.search(text) is None
        assert "Settings" in text
        assert "Notify" in text
        assert "Create a pairing code" in text
    finally:
        await _stop(runtime, bus, bus_task)


async def test_paired_profile_keeps_listening_on_the_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A pairing token still starts ingest on the shipped default."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    config = _shipped_config()
    ingest = config["tools"]["sms"]["inbound"]["ingest"]
    ingest["host"] = "127.0.0.1"
    ingest["port"] = port
    runtime, bus, bus_task = await _attach(monkeypatch, tmp_path, config, token="test-token-xyz")
    try:
        assert runtime.ingest is not None
    finally:
        await _stop(runtime, bus, bus_task)


async def test_explicit_true_on_existing_config_is_preserved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """config.local.yaml with enabled true still listens when a token exists."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    config = _shipped_config()
    ingest = config["tools"]["sms"]["inbound"]["ingest"]
    ingest["enabled"] = True
    ingest["host"] = "127.0.0.1"
    ingest["port"] = port
    runtime, bus, bus_task = await _attach(monkeypatch, tmp_path, config, token="test-token-xyz")
    try:
        assert runtime.ingest is not None
        assert ingest["enabled"] is True
    finally:
        await _stop(runtime, bus, bus_task)


async def test_explicit_false_stays_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _shipped_config()
    config["tools"]["sms"]["inbound"]["ingest"]["enabled"] = False
    runtime, bus, bus_task = await _attach(monkeypatch, tmp_path, config, token="test-token-xyz")
    try:
        assert runtime.ingest is None
        assert runtime.status_messages == []
    finally:
        await _stop(runtime, bus, bus_task)


def test_shipped_ingest_default_is_auto() -> None:
    data = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    ingest = ((data.get("tools") or {}).get("sms") or {}).get("inbound") or {}
    assert (ingest.get("ingest") or {}).get("enabled") == "auto"


def test_startup_notice_strings_have_no_local_paths() -> None:
    """STATUS copy that can reach chat must not name a file on this PC."""
    root = Path(__file__).resolve().parents[1]
    hits: list[str] = []
    for rel in _NOTICE_PRODUCERS:
        tree = ast.parse((root / rel).read_text(encoding="utf-8"), filename=str(rel))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if PATH_IN_USER_TEXT.search(node.value):
                    hits.append(f"{rel}:{node.lineno}:{node.value}")
    assert hits == []


def test_pairing_notice_is_in_the_translation_catalog() -> None:
    import arelis.presence.inbound_runtime as inbound_runtime
    from arelis.i18n import _ZH, set_ui_language

    assert getattr(inbound_runtime, "PHONE_NOTIFY_NEEDS_PAIRING", None) == (
        PHONE_NOTIFY_NEEDS_PAIRING
    )
    assert PHONE_NOTIFY_NEEDS_PAIRING in _ZH
    set_ui_language("zh")
    try:
        zh = tr(PHONE_NOTIFY_NEEDS_PAIRING)
        assert zh != PHONE_NOTIFY_NEEDS_PAIRING
        assert PATH_IN_USER_TEXT.search(zh) is None
        assert "\u2014" not in zh and "\u2013" not in zh
    finally:
        set_ui_language("en")
    assert tr(PHONE_NOTIFY_NEEDS_PAIRING) == PHONE_NOTIFY_NEEDS_PAIRING


def test_fresh_profile_window_shows_no_phone_notice(
    arelis_window, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Offscreen glass: shipped config, empty data dir, no chat or thinking notice."""
    import os

    assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "fresh"))
    monkeypatch.delenv("ARELIS_INGEST_TOKEN", raising=False)
    monkeypatch.setattr(
        "arelis.presence.inbound_runtime.load_ingest_token",
        lambda: None,
    )
    monkeypatch.setattr(
        "arelis.presence.inbound_runtime.load_sms_account",
        lambda: None,
    )
    window = arelis_window()
    said: list[str] = []
    window.chat.add_system = said.append  # type: ignore[method-assign]
    loop = asyncio.new_event_loop()
    bus_task = loop.create_task(window.bus.run())
    try:
        runtime = attach_inbound(window.bus, loop, _shipped_config(), owned=True)
        try:
            assert runtime.status_messages == []
            assert runtime.ingest is None
            for message in runtime.status_messages:
                dispatch_event(
                    window,
                    Event(EventType.STATUS, {"message": message}),
                )
            assert said == []
            assert "Phone notifications" not in window.thinking.footer.text()
        finally:
            loop.run_until_complete(runtime.stop())
    finally:
        window.bus.stop()
        bus_task.cancel()
        try:
            loop.run_until_complete(bus_task)
        except asyncio.CancelledError:
            pass
        loop.close()
