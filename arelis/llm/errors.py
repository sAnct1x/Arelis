"""User-facing copy when the chat server dies or rejects a turn.

Chat gets a short instruction. The exception, URL, and model tag belong in
Thinking, not in the transcript as ``LLM error: ConnectError(...)``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

_MODEL_IN_EXC = re.compile(r"model `([^`]+)`")

OLLAMA_DOWN_NOTICE = (
    "Ollama stopped responding. Check the Ollama chip in the title bar, then send again."
)
OLLAMA_MODEL_NOTICE = (
    "Ollama does not have `{model}` pulled. Pull it, then send again."
)
OLLAMA_REJECT_NOTICE = (
    "Ollama returned an error. Check the Ollama chip in the title bar, then send again."
)
OLLAMA_GENERIC_NOTICE = (
    "The model failed mid-turn. Check that Ollama is still running, then send again."
)
LLAMACPP_DOWN_NOTICE = (
    "The local model server stopped responding. "
    "Check that llama-server is still running, then send again."
)
LLAMACPP_REJECT_NOTICE = (
    "The local model server returned an error. "
    "Check that llama-server is still running, then send again."
)
LLAMACPP_MODEL_NOTICE = (
    "The local model server does not have that model loaded. "
    "Check the model file you started it with."
)
LLAMACPP_GENERIC_NOTICE = (
    "The model failed mid-turn. "
    "Check that the local model server is still running, then send again."
)

_LLAMACPP_KINDS = frozenset({"llamacpp", "llama.cpp", "llama-server"})


def vram_notice(role: str = "") -> str:
    """Chat copy when a heavy model will not fit."""
    del role
    return (
        "The research model could not fit on the GPU. I parked ComfyUI and put "
        "the conversation model back so the machine stays usable. Close games "
        "or extra Chrome if it still fails, or stay on `/role fast`."
    )


OLLAMA_VRAM_NOTICE = vram_notice("research")

_VRAM_MARKERS = (
    "could not load `",
    "still resident",
    "free vram",
    "12 gb card",
    "could not free vram",
    "gpu still has",
    "previous model fully unloaded",
    "another chat model until those are gone",
)


def is_vram_failure(exc: BaseException | str) -> bool:
    """True when a 14B load lost the VRAM fight, never JSON-fallback this."""
    lower = (str(exc) if not isinstance(exc, str) else exc).lower()
    return any(marker in lower for marker in _VRAM_MARKERS)


def is_context_overflow(detail: object) -> bool:
    """True when llama-server (or similar) refused the prompt as too long."""
    text = str(detail or "").lower()
    if "context" not in text:
        return False
    return "exceed" in text or "overflow" in text


def _is_llamacpp(provider: str, exc: BaseException) -> bool:
    kind = (provider or "").strip().lower()
    if kind in _LLAMACPP_KINDS:
        return True
    return "llama-server" in str(exc).lower()

# Reachability and mid-stream drops. HTTP 4xx from Ollama is RuntimeError, not these.
_UNREACHABLE = (httpx.NetworkError, httpx.TimeoutException)


@dataclass(frozen=True)
class OllamaFailure:
    chat: str
    detail: str
    skip_tool_fallback: bool


def classify_ollama_failure(
    exc: BaseException,
    *,
    model: str = "",
    base_url: str = "",
    role: str = "",
    provider: str = "",
) -> OllamaFailure:
    """Map a chat-server exception to chat copy plus a Thinking line."""
    llamacpp = _is_llamacpp(provider, exc)
    detail = _debug_detail(exc, model=model, base_url=base_url, llamacpp=llamacpp)
    text = str(exc)
    lower = text.lower()
    tag = _model_tag(text, model)
    down_notice = LLAMACPP_DOWN_NOTICE if llamacpp else OLLAMA_DOWN_NOTICE
    reject_notice = LLAMACPP_REJECT_NOTICE if llamacpp else OLLAMA_REJECT_NOTICE
    generic_notice = LLAMACPP_GENERIC_NOTICE if llamacpp else OLLAMA_GENERIC_NOTICE

    if isinstance(exc, _UNREACHABLE):
        return OllamaFailure(down_notice, detail, skip_tool_fallback=True)
    if is_vram_failure(lower):
        return OllamaFailure(vram_notice(role), detail, skip_tool_fallback=True)
    if _is_missing_model(lower):
        notice = (
            LLAMACPP_MODEL_NOTICE
            if llamacpp
            else OLLAMA_MODEL_NOTICE.format(model=tag)
        )
        return OllamaFailure(notice, detail, skip_tool_fallback=True)
    if llamacpp and is_context_overflow(lower):
        # Overflow is a window problem. JSON-tool fallback cannot shrink it.
        return OllamaFailure(generic_notice, detail, skip_tool_fallback=True)
    if _http_status(text) >= 500:
        return OllamaFailure(down_notice, detail, skip_tool_fallback=True)
    if lower.startswith("ollama ") or "ollama returned http" in lower:
        # HTTP 400 on the tools array is the one case JSON fallback may still fix.
        status = _http_status(text)
        skip = status not in {0, 400}
        return OllamaFailure(reject_notice, detail, skip_tool_fallback=skip)
    return OllamaFailure(generic_notice, detail, skip_tool_fallback=False)


def classify_turn_failure(
    exc: BaseException,
    *,
    model: str = "",
    role: str = "",
    config: dict[str, Any] | None = None,
    backend: object | None = None,
) -> OllamaFailure:
    """Classify using the loop's provider, not a hardcoded Ollama URL."""
    cfg = config or {}
    kind = str((cfg.get("llm") or {}).get("provider") or "").strip().lower()
    if kind not in _LLAMACPP_KINDS:
        name = type(backend).__name__ if backend is not None else ""
        if name == "LlamaCppProvider":
            kind = "llamacpp"
        else:
            kind = kind or "ollama"
    base_url = str(getattr(backend, "base_url", "") or "").strip()
    if not base_url:
        section = "llamacpp" if kind in _LLAMACPP_KINDS else "ollama"
        base_url = str((cfg.get(section) or {}).get("base_url") or "")
    return classify_ollama_failure(
        exc, model=model, base_url=base_url, role=role, provider=kind
    )


def _model_tag(text: str, fallback: str) -> str:
    hit = _MODEL_IN_EXC.search(text or "")
    if hit:
        return hit.group(1).strip()
    return (fallback or "").strip() or "the configured model"


def _is_missing_model(lower: str) -> bool:
    if "http 404" in lower:
        return True
    return "not found" in lower and "model" in lower


def _http_status(text: str) -> int:
    marker = "HTTP "
    idx = text.find(marker)
    if idx < 0:
        return 0
    rest = text[idx + len(marker) :]
    digits = []
    for ch in rest:
        if ch.isdigit():
            digits.append(ch)
            if len(digits) == 3:
                break
        elif digits:
            break
    if len(digits) != 3:
        return 0
    return int("".join(digits))


def _debug_detail(
    exc: BaseException, *, model: str, base_url: str, llamacpp: bool = False
) -> str:
    parts = [f"{type(exc).__name__}: {exc}"]
    extra = []
    url = (base_url or "").strip()
    if url:
        extra.append(url)
    tag = (model or "").strip()
    if tag:
        extra.append(f"model `{tag}`")
    if extra:
        parts.append("(" + ", ".join(extra) + ")")
    label = "llama-server" if llamacpp else "Ollama"
    return label + " " + " ".join(parts)
