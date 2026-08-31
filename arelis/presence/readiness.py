"""Aggregate local readiness signals into a compact snapshot for UI/CLI.

Reports only whether configured tags and integrations are present — never
suggests alternate models or shopping for replacements.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from arelis.calendar.secrets import load_calendar_secrets, load_ics_url
from arelis.llm.startup import missing_models, model_is_available
from arelis.mail import load_account
from arelis.memory import DEFAULT_EMBED_MODEL
from arelis.presence.lock import find_my_ingest_port, probe_ingest_health
from arelis.sms_android import load_sms_account

log = logging.getLogger(__name__)


class ChipLevel(str, Enum):
    OK = "ok"
    WARN = "warn"
    OFF = "off"


@dataclass(frozen=True)
class ReadinessChip:
    key: str
    label: str
    status: ChipLevel
    detail: str


@dataclass(frozen=True)
class ReadinessSnapshot:
    chips: tuple[ReadinessChip, ...]

    def chip(self, key: str) -> ReadinessChip | None:
        for item in self.chips:
            if item.key == key:
                return item
        return None

    def status_line(self) -> str:
        """One compact STATUS line for CLI / logs."""
        parts = [f"{c.key}={c.status.value}" for c in self.chips]
        return "ready " + " ".join(parts)


_CHIP_ORDER = (
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


def _configured_chat_models(config: dict[str, Any]) -> dict[str, str]:
    return {
        str(role): str(name).strip()
        for role, name in (config.get("models") or {}).items()
        if str(name or "").strip()
    }


def _embed_tag(config: dict[str, Any]) -> str:
    return str(
        (config.get("memory") or {}).get("embed_model") or DEFAULT_EMBED_MODEL
    ).strip()


async def probe_readiness(
    config: dict[str, Any],
    *,
    router: Any | None = None,
    provider: Any | None = None,
) -> ReadinessSnapshot:
    """Probe Ollama + local integrations. Never raises into the UI loop."""
    chips: dict[str, ReadinessChip] = {}
    prov = provider
    owns_provider = False
    if prov is None and router is not None:
        prov = getattr(router, "provider", None)
    if prov is None:
        from arelis.llm.ollama import OllamaProvider

        ollama_cfg = config.get("ollama") or {}
        prov = OllamaProvider(
            base_url=str(ollama_cfg.get("base_url") or "http://127.0.0.1:11434"),
            timeout_s=float(ollama_cfg.get("timeout_s") or 30),
        )
        owns_provider = True

    available: list[str] | None = None
    ollama_error: str | None = None
    try:
        available = await prov.list_models()
    except Exception as exc:
        ollama_error = str(exc) or type(exc).__name__
        log.info("Readiness Ollama probe failed: %s", exc)

    if owns_provider:
        try:
            await prov.close()
        except Exception:
            pass

    if available is not None:
        chips["ollama"] = ReadinessChip(
            "ollama",
            "Ollama",
            ChipLevel.OK,
            f"Reachable ({len(available)} tags listed).",
        )
    else:
        chips["ollama"] = ReadinessChip(
            "ollama",
            "Ollama",
            ChipLevel.OFF,
            f"Unreachable{f': {ollama_error}' if ollama_error else ''}.",
        )

    configured = _configured_chat_models(config)
    if available is None:
        chips["models"] = ReadinessChip(
            "models",
            "Models",
            ChipLevel.OFF,
            "Cannot check configured tags while Ollama is down.",
        )
    elif not configured:
        chips["models"] = ReadinessChip(
            "models",
            "Models",
            ChipLevel.WARN,
            "No chat models configured in models.*.",
        )
    else:
        absent = missing_models(available, configured)
        if not absent:
            tags = ", ".join(f"{role}:{name}" for role, name in configured.items())
            chips["models"] = ReadinessChip(
                "models",
                "Models",
                ChipLevel.OK,
                f"All configured tags present ({tags}).",
            )
        else:
            missing_bits = ", ".join(f"{role}:{name}" for role, name in absent)
            n_unique = len(set(configured.values()))
            level = (
                ChipLevel.OFF if len(absent) >= n_unique else ChipLevel.WARN
            )
            chips["models"] = ReadinessChip(
                "models",
                "Models",
                level,
                f"Configured tags not present: {missing_bits}.",
            )

    chips["role"] = _role_chip(config, router, configured)
    chips["confirm"] = _confirm_chip(config)
    chips["watch"] = _watch_chip(config)
    chips["calendar"] = _calendar_chip(config)
    chips["sms"] = _sms_chip(config)
    chips["mail"] = _mail_chip(config)
    chips["embed"] = _embed_chip(config, available)
    chips["search"] = await _search_chip(config)
    chips["ocr"] = _ocr_chip(config)
    chips["image"] = await _image_chip(config)

    ordered = tuple(chips[key] for key in _CHIP_ORDER if key in chips)
    return ReadinessSnapshot(chips=ordered)


def _watch_chip(config: dict[str, Any]) -> ReadinessChip:
    """The doors Arelis opened — not a scan of the rest of the PC."""
    watch_cfg = ((config.get("agent") or {}).get("watch") or {})
    if not bool(watch_cfg.get("enabled", True)):
        return ReadinessChip(
            "watch",
            "Watch",
            ChipLevel.OFF,
            "Watch disabled in config.",
        )
    from arelis.guard import get_watch

    snap = get_watch().snapshot()
    level = {
        "ok": ChipLevel.OK,
        "warn": ChipLevel.WARN,
        "off": ChipLevel.OFF,
    }.get(snap.level, ChipLevel.OK)
    return ReadinessChip("watch", "Watch", level, snap.detail)


def _confirm_chip(config: dict[str, Any]) -> ReadinessChip:
    """Surface Allow gates so browser/vision confirms are not invisible (L6)."""
    agent = config.get("agent") or {}
    flags = {
        "writes": bool(agent.get("confirm_writes", True)),
        "browser": bool(agent.get("confirm_browser", True)),
        "vision": bool(agent.get("confirm_vision", True)),
        "send": bool(agent.get("confirm_send", True)),
        "image": bool(agent.get("confirm_image", True)),
    }
    on = [k for k, v in flags.items() if v]
    off = [k for k, v in flags.items() if not v]
    detail = "Allow gates on: " + (", ".join(on) if on else "none")
    if off:
        detail += f". Off: {', '.join(off)}"
    detail += ". Cards still appear in chat when a gated action runs."
    if not on:
        status = ChipLevel.OFF
    elif off:
        status = ChipLevel.WARN
    else:
        status = ChipLevel.OK
    return ReadinessChip("confirm", "Allow gates", status, detail)


def _role_chip(
    config: dict[str, Any],
    router: Any | None,
    configured: dict[str, str],
) -> ReadinessChip:
    default_role = str(
        (config.get("router") or {}).get("default_role") or "fast"
    ).strip() or "fast"
    if router is not None:
        role = str(getattr(router, "active_role", None) or default_role)
        active = getattr(router, "active_model", None)
        try:
            model = str(active or router.model_for(role))
        except Exception:
            model = configured.get(role) or configured.get(default_role) or ""
        if active:
            return ReadinessChip(
                "role",
                "Model",
                ChipLevel.OK,
                f"Hot model {role}:{model} (VRAM pin). "
                "Composer fast/research picks the reply role for the next message; "
                "auto-routing may load a different model for a turn.",
            )
        if model:
            return ReadinessChip(
                "role",
                "Model",
                ChipLevel.WARN,
                f"Model not pinned yet — cold {role}:{model}. "
                "Composer reply-role picker is separate.",
            )
        return ReadinessChip(
            "role",
            "Model",
            ChipLevel.OFF,
            "No model resolved for the active router role.",
        )
    model = configured.get(default_role) or ""
    if model:
        return ReadinessChip(
            "role",
            "Model",
            ChipLevel.WARN,
            f"Default {default_role}:{model} (router not attached). "
            "Composer reply-role picker is separate.",
        )
    return ReadinessChip(
        "role",
        "Model",
        ChipLevel.OFF,
        "No default role model configured.",
    )


def _calendar_chip(config: dict[str, Any]) -> ReadinessChip:
    cal_cfg = (config.get("tools") or {}).get("calendar") or {}
    if not bool(cal_cfg.get("enabled", True)):
        return ReadinessChip(
            "calendar",
            "Calendar",
            ChipLevel.OFF,
            "Calendar tool disabled in config.",
        )
    secrets = load_calendar_secrets()
    google = secrets.google
    outlook = secrets.outlook
    if secrets.any_authorized():
        if google is not None and google.authorized:
            return ReadinessChip(
                "calendar",
                "Calendar",
                ChipLevel.OK,
                f"Google authorized (calendar {google.calendar_id}).",
            )
        if outlook is not None and outlook.authorized:
            return ReadinessChip(
                "calendar",
                "Calendar",
                ChipLevel.OK,
                "Outlook authorized.",
            )
    if load_ics_url():
        return ReadinessChip(
            "calendar",
            "Calendar",
            ChipLevel.OK,
            "ICS feed configured.",
        )
    if google is not None and google.configured:
        return ReadinessChip(
            "calendar",
            "Calendar",
            ChipLevel.WARN,
            "Google client present but refresh token missing.",
        )
    if outlook is not None and outlook.configured:
        return ReadinessChip(
            "calendar",
            "Calendar",
            ChipLevel.WARN,
            "Outlook client present but refresh token missing.",
        )
    return ReadinessChip(
        "calendar",
        "Calendar",
        ChipLevel.OFF,
        "Calendar not connected.",
    )


def _sms_chip(config: dict[str, Any]) -> ReadinessChip:
    sms = (config.get("tools") or {}).get("sms") or {}
    if not bool(sms.get("enabled", True)):
        return ReadinessChip(
            "sms",
            "SMS",
            ChipLevel.OFF,
            "SMS tool disabled in config.",
        )
    inbound = sms.get("inbound") or {}
    if not bool(inbound.get("enabled", True)):
        return ReadinessChip(
            "sms",
            "SMS",
            ChipLevel.OFF,
            "SMS inbound disabled in config.",
        )
    ingest = inbound.get("ingest") or {}
    if not bool(ingest.get("enabled", True)):
        return ReadinessChip(
            "sms",
            "SMS",
            ChipLevel.OFF,
            "SMS ingest disabled in config.",
        )
    account = load_sms_account()
    if account is None:
        return ReadinessChip(
            "sms",
            "SMS",
            ChipLevel.OFF,
            "Phone not paired.",
        )
    port = int(ingest.get("port") or 8765)
    # Asks which port *this user's* ingest is on, not whether anything answers on
    # the configured one. On a shared PC the two differ, and reporting the other
    # account's healthy ingest as ours showed a green SMS chip to a user whose own
    # ingest had never bound.
    mine = find_my_ingest_port(config)
    if mine is not None:
        detail = (
            f"Ingest healthy on :{mine}."
            if mine == port
            else f"Ingest healthy on :{mine} (:{port} was taken)."
        )
        return ReadinessChip("sms", "SMS", ChipLevel.OK, detail)
    if probe_ingest_health(port=port):
        return ReadinessChip(
            "sms",
            "SMS",
            ChipLevel.WARN,
            f":{port} is serving another Arelis on this PC; yours is not up.",
        )
    return ReadinessChip(
        "sms",
        "SMS",
        ChipLevel.WARN,
        f"Ingest not answering on :{port}.",
    )


def _mail_chip(config: dict[str, Any]) -> ReadinessChip:
    email_cfg = (config.get("tools") or {}).get("email") or {}
    if not bool(email_cfg.get("enabled", True)):
        return ReadinessChip(
            "mail",
            "Mail",
            ChipLevel.OFF,
            "Mail tool disabled in config.",
        )
    account = load_account()
    if account is None:
        return ReadinessChip(
            "mail",
            "Mail",
            ChipLevel.OFF,
            "Mail account not configured.",
        )
    return ReadinessChip(
        "mail",
        "Mail",
        ChipLevel.OK,
        f"Account ready ({account.address}).",
    )


def _embed_chip(config: dict[str, Any], available: list[str] | None) -> ReadinessChip:
    tag = _embed_tag(config)
    if not tag:
        return ReadinessChip(
            "embed",
            "Embed",
            ChipLevel.OFF,
            "No embed_model configured.",
        )
    if available is None:
        return ReadinessChip(
            "embed",
            "Embed",
            ChipLevel.OFF,
            f"Cannot check `{tag}` while Ollama is down.",
        )
    if model_is_available(available, tag):
        return ReadinessChip(
            "embed",
            "Embed",
            ChipLevel.OK,
            f"Configured embed tag `{tag}` present.",
        )
    return ReadinessChip(
        "embed",
        "Embed",
        ChipLevel.WARN,
        f"Configured embed tag `{tag}` not present.",
    )


async def _search_chip(config: dict[str, Any]) -> ReadinessChip:
    """web_search enabled → DuckDuckGo (no local container to probe)."""
    tools = config.get("tools") or {}
    search = tools.get("search") or {}
    if not bool(search.get("enabled", True)):
        return ReadinessChip(
            "search",
            "Search",
            ChipLevel.OFF,
            "web_search disabled in config.",
        )
    return ReadinessChip(
        "search",
        "Search",
        ChipLevel.OK,
        "DuckDuckGo (no API key; may rate-limit under heavy use).",
    )


def _ocr_chip(config: dict[str, Any]) -> ReadinessChip:
    tools = config.get("tools") or {}
    ocr = tools.get("ocr") or {}
    if not bool(ocr.get("enabled", True)):
        return ReadinessChip(
            "ocr",
            "OCR",
            ChipLevel.OFF,
            "ocr tool disabled in config.",
        )
    from arelis.tools.ocr import tesseract_available

    if tesseract_available():
        return ReadinessChip(
            "ocr",
            "OCR",
            ChipLevel.OK,
            "tesseract available (CPU OCR).",
        )
    return ReadinessChip(
        "ocr",
        "OCR",
        ChipLevel.WARN,
        "tesseract not on PATH; ocr tool will soft-fail until installed.",
    )


async def _image_chip(config: dict[str, Any]) -> ReadinessChip:
    """Whether a picture can actually be made right now.

    The image tool stays registered whether or not ComfyUI is up, because
    ComfyUI is a separate program the user can start at any moment and a
    registry built at launch would keep saying no for the rest of the session.
    That leaves this chip as the honest signal, re-probed on the same 30s tick
    as the rest of the strip.
    """
    image_cfg = (config.get("tools") or {}).get("image") or {}
    if not bool(image_cfg.get("enabled", True)):
        return ReadinessChip(
            "image",
            "Image",
            ChipLevel.OFF,
            "image tool disabled in config.",
        )
    url = str(image_cfg.get("comfy_url") or "http://127.0.0.1:8188").strip()
    from arelis.tools.comfy_lifecycle import comfy_is_healthy_async

    if await comfy_is_healthy_async(url, timeout_s=1.5):
        return ReadinessChip(
            "image",
            "Image",
            ChipLevel.OK,
            f"ComfyUI answering at {url}.",
        )
    auto = bool(image_cfg.get("auto_start", False)) and bool(
        str(image_cfg.get("launch_cwd") or "").strip()
    )
    if auto:
        return ReadinessChip(
            "image",
            "Image",
            ChipLevel.WARN,
            f"ComfyUI not running at {url}; the first image starts it.",
        )
    return ReadinessChip(
        "image",
        "Image",
        ChipLevel.WARN,
        f"ComfyUI not running at {url}, so image generation is unavailable. "
        "Start ComfyUI, or set tools.image.auto_start with tools.image.launch_cwd.",
    )
