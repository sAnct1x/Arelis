"""Readiness snapshot shaping — mocked Ollama / secrets / ingest."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from arelis.calendar.secrets import CalendarSecrets, GoogleCalendarCreds
from arelis.mail import MailAccount
from arelis.presence.readiness import ChipLevel, probe_readiness


class _FakeProvider:
    def __init__(self, names: list[str] | None = None, *, fail: bool = False) -> None:
        self._names = names or []
        self._fail = fail
        self.closed = False

    async def list_models(self) -> list[str]:
        if self._fail:
            raise ConnectionError("ollama down")
        return list(self._names)

    async def close(self) -> None:
        self.closed = True


def _comfy(healthy: bool):
    async def _probe(*_a: object, **_k: object) -> bool:
        return healthy

    return _probe


@pytest.fixture(autouse=True)
def _no_live_comfy(monkeypatch: pytest.MonkeyPatch) -> None:
    """The image chip probes a real port; a suite must not depend on one."""
    monkeypatch.setattr(
        "arelis.tools.comfy_lifecycle.comfy_is_healthy_async",
        _comfy(False),
    )


def _base_config() -> dict:
    return {
        "models": {
            "fast": "qwen2.5:7b",
            "research": "qwen2.5:14b",
            "code": "qwen2.5-coder:7b",
        },
        "router": {"default_role": "fast"},
        "memory": {"embed_model": "nomic-embed-text"},
        "tools": {
            "calendar": {"enabled": True},
            "sms": {
                "enabled": True,
                "inbound": {"enabled": True, "ingest": {"enabled": True, "port": 8765}},
            },
            "email": {"enabled": True},
        },
    }


@pytest.mark.asyncio
async def test_probe_ok_when_tags_and_integrations_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "arelis.presence.readiness.load_calendar_secrets",
        lambda: CalendarSecrets(
            google=GoogleCalendarCreds(
                client_id="id",
                client_secret="secret",
                refresh_token="rt",
                calendar_id="primary",
            ),
            outlook=None,
        ),
    )
    # "Ingest is healthy" now means "this user's own ingest is healthy". The chip
    # asks find_my_ingest_port first, because on a shared PC a reply on :8765 may
    # be another account's core, and reporting that as ready showed a green SMS
    # chip to someone whose own ingest had never bound.
    monkeypatch.setattr(
        "arelis.presence.readiness.find_my_ingest_port",
        lambda config: 8765,
    )
    monkeypatch.setattr(
        "arelis.presence.readiness.probe_ingest_health",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        "arelis.presence.readiness.load_account",
        lambda: MailAccount(address="me@example.com", password="pw"),
    )
    router = SimpleNamespace(
        provider=_FakeProvider(
            [
                "qwen2.5:7b",
                "qwen2.5:14b",
                "qwen2.5-coder:7b",
                "nomic-embed-text",
            ]
        ),
        active_role="fast",
        active_model="qwen2.5:7b",
        model_for=lambda role=None: "qwen2.5:7b",
    )

    monkeypatch.setattr(
        "arelis.tools.comfy_lifecycle.comfy_is_healthy_async",
        _comfy(True),
    )

    snap = await probe_readiness(_base_config(), router=router)
    assert [c.key for c in snap.chips] == [
        "ollama",
        "models",
        "role",
        "confirm",
        "calendar",
        "sms",
        "mail",
        "embed",
        "search",
        "ocr",
        "image",
    ]
    assert snap.chip("image") and snap.chip("image").status == ChipLevel.OK
    assert snap.chip("ollama") and snap.chip("ollama").status == ChipLevel.OK
    assert snap.chip("models") and snap.chip("models").status == ChipLevel.OK
    assert snap.chip("role") and snap.chip("role").status == ChipLevel.OK
    role_detail = snap.chip("role").detail if snap.chip("role") else ""
    assert snap.chip("role").label == "Model"
    assert "hot model" in role_detail.lower()
    assert "fast" in role_detail.lower()
    assert snap.chip("confirm") and snap.chip("confirm").status == ChipLevel.OK
    assert snap.chip("confirm").label == "Allow gates"
    assert "browser" in (snap.chip("confirm").detail if snap.chip("confirm") else "")
    assert snap.chip("calendar") and snap.chip("calendar").status == ChipLevel.OK
    assert snap.chip("sms") and snap.chip("sms").status == ChipLevel.OK
    assert snap.chip("mail") and snap.chip("mail").status == ChipLevel.OK
    assert snap.chip("embed") and snap.chip("embed").status == ChipLevel.OK
    assert snap.chip("search") is not None
    assert snap.chip("ocr") is not None
    line = snap.status_line()
    assert line.startswith("ready ")
    assert "ollama=ok" in line
    assert "models=ok" in line
    # Never shop for alternate models in detail text.
    blob = " ".join(c.detail.lower() for c in snap.chips)
    assert "instead" not in blob
    assert "try " not in blob
    assert "download" not in blob


@pytest.mark.asyncio
async def test_probe_warns_on_missing_configured_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "arelis.presence.readiness.load_calendar_secrets",
        lambda: CalendarSecrets(google=None, outlook=None),
    )
    monkeypatch.setattr(
        "arelis.presence.readiness.probe_ingest_health",
        lambda **kwargs: False,
    )
    monkeypatch.setattr("arelis.presence.readiness.load_account", lambda: None)

    provider = _FakeProvider(["qwen2.5:7b"])
    snap = await probe_readiness(_base_config(), provider=provider)

    models = snap.chip("models")
    assert models is not None
    assert models.status == ChipLevel.WARN
    assert "qwen2.5:14b" in models.detail
    assert "qwen2.5-coder:7b" in models.detail
    assert "alternative" not in models.detail.lower()

    embed = snap.chip("embed")
    assert embed is not None
    assert embed.status == ChipLevel.WARN
    assert "nomic-embed-text" in embed.detail

    role = snap.chip("role")
    assert role is not None
    assert role.status == ChipLevel.WARN
    assert "cold" in role.detail.lower() or "router not attached" in role.detail

    assert snap.chip("calendar") and snap.chip("calendar").status == ChipLevel.OFF
    assert snap.chip("sms") and snap.chip("sms").status == ChipLevel.WARN
    assert snap.chip("mail") and snap.chip("mail").status == ChipLevel.WARN


@pytest.mark.asyncio
async def test_probe_ollama_down_marks_dependent_chips_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "arelis.presence.readiness.load_calendar_secrets",
        lambda: CalendarSecrets(
            google=GoogleCalendarCreds(
                client_id="id",
                client_secret="secret",
                refresh_token="",
            ),
            outlook=None,
        ),
    )
    monkeypatch.setattr(
        "arelis.presence.readiness.probe_ingest_health",
        lambda **kwargs: False,
    )
    monkeypatch.setattr("arelis.presence.readiness.load_account", lambda: None)

    snap = await probe_readiness(_base_config(), provider=_FakeProvider(fail=True))
    assert snap.chip("ollama") and snap.chip("ollama").status == ChipLevel.OFF
    assert snap.chip("models") and snap.chip("models").status == ChipLevel.OFF
    assert snap.chip("embed") and snap.chip("embed").status == ChipLevel.OFF
    cal = snap.chip("calendar")
    assert cal is not None
    assert cal.status == ChipLevel.WARN
    assert "refresh token" in cal.detail.lower()


@pytest.mark.asyncio
async def test_search_and_ocr_chips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "arelis.presence.readiness.load_calendar_secrets",
        lambda: CalendarSecrets(google=None, outlook=None),
    )
    monkeypatch.setattr(
        "arelis.presence.readiness.probe_ingest_health",
        lambda **kwargs: False,
    )
    monkeypatch.setattr("arelis.presence.readiness.load_account", lambda: None)
    monkeypatch.setattr("arelis.tools.ocr.tesseract_available", lambda: True)

    cfg = _base_config()
    cfg["tools"]["search"] = {"enabled": True}
    cfg["tools"]["ocr"] = {"enabled": True}
    snap = await probe_readiness(cfg, provider=_FakeProvider(["qwen2.5:7b"]))
    search = snap.chip("search")
    assert search is not None and search.status == ChipLevel.OK
    assert "duckduckgo" in search.detail.lower()
    ocr = snap.chip("ocr")
    assert ocr is not None and ocr.status == ChipLevel.OK


@pytest.mark.asyncio
async def test_image_chip_says_comfy_is_missing_before_she_tries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Draw-me-a-picture is offered to everyone; only some machines can do it."""
    monkeypatch.setattr(
        "arelis.presence.readiness.load_calendar_secrets",
        lambda: CalendarSecrets(google=None, outlook=None),
    )
    monkeypatch.setattr(
        "arelis.presence.readiness.probe_ingest_health",
        lambda **kwargs: False,
    )
    monkeypatch.setattr("arelis.presence.readiness.load_account", lambda: None)

    cfg = _base_config()
    cfg["tools"]["image"] = {"enabled": True, "comfy_url": "http://127.0.0.1:8188"}
    snap = await probe_readiness(cfg, provider=_FakeProvider(["qwen2.5:7b"]))
    chip = snap.chip("image")
    assert chip is not None
    assert chip.status == ChipLevel.WARN
    assert "unavailable" in chip.detail

    # Auto-start configured is a different sentence: it will come up by itself.
    cfg["tools"]["image"]["auto_start"] = True
    cfg["tools"]["image"]["launch_cwd"] = "C:/ComfyUI"
    snap = await probe_readiness(cfg, provider=_FakeProvider(["qwen2.5:7b"]))
    chip = snap.chip("image")
    assert chip is not None
    assert chip.status == ChipLevel.WARN
    assert "starts it" in chip.detail

    cfg["tools"]["image"]["enabled"] = False
    snap = await probe_readiness(cfg, provider=_FakeProvider(["qwen2.5:7b"]))
    chip = snap.chip("image")
    assert chip is not None
    assert chip.status == ChipLevel.OFF


def test_readiness_strip_applies_statuses(qt_app) -> None:
    from arelis.presence.readiness import ReadinessChip, ReadinessSnapshot
    from arelis.ui.readiness_strip import ReadinessStrip

    strip = ReadinessStrip()
    snap = ReadinessSnapshot(
        chips=(
            ReadinessChip("ollama", "Ollama", ChipLevel.OK, "up"),
            ReadinessChip("models", "Models", ChipLevel.WARN, "missing tag"),
            ReadinessChip("role", "Model", ChipLevel.OFF, "cold"),
            ReadinessChip("confirm", "Allow gates", ChipLevel.OK, "gates on"),
            ReadinessChip("calendar", "Calendar", ChipLevel.OK, "auth"),
            ReadinessChip("sms", "SMS", ChipLevel.WARN, "down"),
            ReadinessChip("mail", "Mail", ChipLevel.OK, "me@x"),
            ReadinessChip("embed", "Embed", ChipLevel.WARN, "absent"),
        )
    )
    strip.apply(snap)
    assert strip._chips["ollama"].property("status") == "ok"
    # Primary strip is Ollama only; Model / Allow gates nest under Systems.
    assert "role" not in strip._chips
    assert "confirm" not in strip._chips
    assert "models" not in strip._chips
    assert strip.systems_btn.property("status") == "warn"
    assert "systems ·" in strip.systems_btn.text().lower()
    menu_text = " ".join(a.text() for a in strip._systems_menu.actions())
    assert "Model" in menu_text
    assert "Allow gates" in menu_text

    strip.set_confirm_waiting(True)
    assert "allow" in strip.systems_btn.text().lower()
    assert strip.systems_btn.property("status") in {"wait", "wait_dim"}
    strip.set_confirm_waiting(False)
    assert "allow" not in strip.systems_btn.text().lower()
    assert strip.systems_btn.property("status") == "warn"
