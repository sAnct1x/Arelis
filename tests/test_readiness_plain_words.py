"""House menu status lines stay in plain words.

The chip detail is the row text and the Ollama tooltip. It may say what is
ready, off, or not set up yet. It may not name settings, folders, or the
error Ollama raised.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx
import pytest

from arelis.calendar.secrets import CalendarSecrets
from arelis.presence.readiness import ReadinessSnapshot, probe_readiness

pytestmark = pytest.mark.no_ui

_LEAK = "zz-connect-refused-9f3a"
_SNAKE = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")
_KEYS = (
    "ollama",
    "models",
    "role",
    "confirm",
    "watch",
    "calendar",
    "sms",
    "mail",
    "embed",
    "search",
    "ocr",
    "image",
)


class _Down:
    async def list_models(self) -> list[str]:
        raise httpx.ConnectError(_LEAK)


class _Up:
    def __init__(self, names: list[str]) -> None:
        self._names = names

    async def list_models(self) -> list[str]:
        return list(self._names)


class _Loaded:
    active_role = "fast"
    active_model = "chat-model"

    def model_for(self, _role: str) -> str:
        return "chat-model"


def _config(*, on: bool, embed: str | None = None, models: dict | None = None) -> dict:
    data: dict = {
        "models": models or {},
        "agent": {"watch": {"enabled": on}},
        "tools": {
            name: {"enabled": on} for name in ("calendar", "sms", "email", "search", "ocr", "image")
        },
    }
    if embed is not None:
        data["memory"] = {"embed_model": embed}
    return data


def _problems(detail: str) -> list[str]:
    found: list[str] = []
    if "config" in detail.lower():
        found.append("config")
    if "tools." in detail:
        found.append("tools.")
    if "models." in detail:
        found.append("models.")
    if "PATH" in detail:
        found.append("PATH")
    if "`" in detail:
        found.append("backtick")
    snake = _SNAKE.search(detail)
    if snake:
        found.append(f"snake_case {snake.group(0)}")
    if "soft-fail" in detail.lower():
        found.append("soft-fail")
    if "/" in detail or "\\" in detail:
        found.append("path separator")
    if _LEAK in detail:
        found.append("exception text")
    return found


def _assert_plain(snapshot: ReadinessSnapshot) -> None:
    bad = [
        f"{chip.key}: {_problems(chip.detail)} :: {chip.detail}"
        for chip in snapshot.chips
        if _problems(chip.detail)
    ]
    assert not bad, "status lines still use settings talk:\n" + "\n".join(bad)


def _levels(snapshot: ReadinessSnapshot) -> dict[str, str]:
    return {chip.key: chip.status.value for chip in snapshot.chips}


@pytest.mark.asyncio
async def test_probe_readiness_details_stay_plain(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "arelis.presence.readiness.load_calendar_secrets",
        lambda *_a, **_k: CalendarSecrets(None, None),
    )
    monkeypatch.setattr(
        "arelis.presence.readiness.load_ics_url",
        lambda *_a, **_k: "",
    )
    monkeypatch.setattr(
        "arelis.presence.readiness.load_account",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "arelis.presence.readiness.load_sms_account",
        lambda *_a, **_k: None,
    )
    caplog.set_level(logging.INFO, logger="arelis.presence.readiness")

    def _install(*, tesseract: bool, healthy: bool, found: Path | None) -> None:
        monkeypatch.setattr(
            "arelis.tools.ocr.tesseract_available",
            lambda: tesseract,
        )

        async def _probe(*_a, **_k) -> bool:
            return healthy

        monkeypatch.setattr(
            "arelis.tools.comfy_lifecycle.comfy_is_healthy_async",
            _probe,
        )
        monkeypatch.setattr(
            "arelis.tools.comfy_lifecycle.discover_comfy",
            lambda *_a, **_k: found,
        )

    _install(tesseract=False, healthy=False, found=None)
    down_blank = await probe_readiness(
        _config(on=False, embed=" "),
        provider=_Down(),
    )
    down_embed = await probe_readiness(_config(on=False), provider=_Down())

    _install(tesseract=False, healthy=False, found=Path("/opt/picture-studio"))
    on_folder = await probe_readiness(_config(on=True), provider=_Up([]))

    _install(tesseract=False, healthy=False, found=None)
    on_nowhere = await probe_readiness(_config(on=True), provider=_Up([]))
    on_missing = await probe_readiness(
        _config(on=True, models={"fast": "chat-model"}),
        provider=_Up([]),
    )

    monkeypatch.setattr(
        "arelis.presence.readiness.load_ics_url",
        lambda *_a, **_k: "https://example.com/feed.ics",
    )
    on_feed = await probe_readiness(_config(on=True), provider=_Up([]))
    monkeypatch.setattr(
        "arelis.presence.readiness.load_ics_url",
        lambda *_a, **_k: "",
    )

    _install(tesseract=True, healthy=True, found=None)
    ready_names = ["chat-model", "nomic-embed-text"]
    on_ready = await probe_readiness(
        _config(on=True, models={"fast": "chat-model"}),
        provider=_Up(ready_names),
    )
    on_loaded = await probe_readiness(
        _config(on=True, models={"fast": "chat-model"}),
        provider=_Up(ready_names),
        router=_Loaded(),
    )

    for snapshot in (
        down_blank,
        down_embed,
        on_folder,
        on_nowhere,
        on_missing,
        on_feed,
        on_ready,
        on_loaded,
    ):
        assert tuple(chip.key for chip in snapshot.chips) == _KEYS
        _assert_plain(snapshot)

    assert _LEAK in caplog.text

    off = {
        "ollama": "off",
        "models": "off",
        "role": "off",
        "confirm": "ok",
        "watch": "off",
        "calendar": "off",
        "sms": "off",
        "mail": "off",
        "embed": "off",
        "search": "off",
        "ocr": "off",
        "image": "off",
    }
    quiet = {
        "ollama": "ok",
        "models": "warn",
        "role": "off",
        "confirm": "ok",
        "watch": "ok",
        "calendar": "off",
        "sms": "off",
        "mail": "off",
        "embed": "warn",
        "search": "ok",
        "ocr": "warn",
        "image": "warn",
    }
    assert _levels(down_blank) == off
    assert _levels(down_embed) == off
    assert _levels(on_folder) == quiet
    assert _levels(on_nowhere) == quiet
    assert _levels(on_missing) == {
        **quiet,
        "models": "off",
        "role": "warn",
    }
    assert _levels(on_feed) == {**quiet, "calendar": "ok"}
    ready = {
        "ollama": "ok",
        "models": "ok",
        "role": "warn",
        "confirm": "ok",
        "watch": "ok",
        "calendar": "off",
        "sms": "off",
        "mail": "off",
        "embed": "ok",
        "search": "ok",
        "ocr": "ok",
        "image": "ok",
    }
    assert _levels(on_ready) == ready
    assert _levels(on_loaded) == {**ready, "role": "ok"}
