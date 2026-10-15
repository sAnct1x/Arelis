"""Fresh profiles stay quiet about phone notify until the user turns it on.

Catches the shipped default plus a missing pairing token appending a chat
notice that names a local secrets path. Existing explicit true/false must
keep their meaning; the notice, when it does appear, has to point at Settings.
"""

from __future__ import annotations

import asyncio
import copy
import re
import socket
from pathlib import Path

import pytest
import yaml

from arelis.config import DEFAULT_CONFIG_PATH, load_config
from arelis.i18n import tr
from arelis.presence.inbound_runtime import attach_inbound

# English source. inbound_runtime.PHONE_NOTIFY_NEEDS_PAIRING must match once it exists.
PHONE_NOTIFY_NEEDS_PAIRING = (
    "Phone notifications are turned on but not set up yet. "
    "To finish, open Settings, go to Notify, pick Create a pairing code."
)
PHONE_NOTIFY_NEEDS_PAIRING_ZH = (
    "手机通知已经打开，但还没配对好。请打开设置，进入通知，点生成配对码。"
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


def _load_with_local_ingest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    enabled: bool | str,
    host: str | None = None,
    port: int | None = None,
) -> dict:
    """Startup path: default.yaml plus data/config.local.yaml in a temp seat."""
    ingest: dict = {"enabled": enabled}
    if host is not None:
        ingest["host"] = host
    if port is not None:
        ingest["port"] = port
    local = tmp_path / "data" / "config.local.yaml"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(
        yaml.safe_dump(
            {"tools": {"sms": {"inbound": {"ingest": ingest}}}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("arelis.config.LOCAL_CONFIG_PATH", local)
    return load_config()


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


async def test_explicit_true_on_existing_config_is_preserved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """config.local.yaml with enabled true still loads as True and listens."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    config = _load_with_local_ingest(
        monkeypatch,
        tmp_path,
        enabled=True,
        host="127.0.0.1",
        port=port,
    )
    # Real merge must keep the bool True, not collapse it to the shipped "auto".
    assert config["tools"]["sms"]["inbound"]["ingest"]["enabled"] is True
    runtime, bus, bus_task = await _attach(monkeypatch, tmp_path, config, token="test-token-xyz")
    try:
        assert runtime.ingest is not None
    finally:
        await _stop(runtime, bus, bus_task)


async def test_explicit_false_stays_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """config.local.yaml with enabled false loads as False and stays quiet."""
    config = _load_with_local_ingest(monkeypatch, tmp_path, enabled=False)
    assert config["tools"]["sms"]["inbound"]["ingest"]["enabled"] is False
    runtime, bus, bus_task = await _attach(monkeypatch, tmp_path, config, token="test-token-xyz")
    try:
        assert runtime.ingest is None
        assert runtime.status_messages == []
    finally:
        await _stop(runtime, bus, bus_task)


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


