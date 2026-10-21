"""User-facing copy when the chat server dies or rejects a turn.

Chat gets a short instruction. The exception, URL, and model tag belong in
Thinking, not in the transcript as ``LLM error: ConnectError(...)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

LLAMACPP_DOWN_NOTICE = (
    "The local model stopped responding. "
    "Check that it is still running, then send again."
)
LLAMACPP_REJECT_NOTICE = (
    "The local model returned an error. "
    "Check that it is still running, then send again."
)
LLAMACPP_MODEL_NOTICE = (
    "The local model server does not have that model loaded. "
    "Check the model file you started it with."
)
LLAMACPP_GENERIC_NOTICE = (
    "The model failed mid-turn. "
    "Check that the local model server is still running, then send again."
)

def vram_notice(role: str = "") -> str:
    """Chat copy when a heavy model will not fit."""
    del role
    return (
        "The research model could not fit on the GPU. I parked ComfyUI and put "
        "the conversation model back so the machine stays usable. Close games "
        "or extra Chrome if it still fails, or stay on `/role fast`."
    )


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


# Reachability and mid-stream drops. HTTP 4xx is RuntimeError, not these.
_UNREACHABLE = (httpx.NetworkError, httpx.TimeoutException)


@dataclass(frozen=True)
class ModelFailure:
    chat: str
    detail: str
    skip_tool_fallback: bool


def classify_model_failure(
    exc: BaseException,
    *,
    model: str = "",
    base_url: str = "",
    role: str = "",
    provider: str = "",
) -> ModelFailure:
    """Map a chat-server exception to chat copy plus a Thinking line."""
    del provider
    detail = _debug_detail(exc, model=model, base_url=base_url, llamacpp=True)
    text = str(exc)
    lower = text.lower()
    if isinstance(exc, _UNREACHABLE):
        return ModelFailure(LLAMACPP_DOWN_NOTICE, detail, skip_tool_fallback=True)
    if is_vram_failure(lower):
        return ModelFailure(vram_notice(role), detail, skip_tool_fallback=True)
    if _is_missing_model(lower):
        return ModelFailure(LLAMACPP_MODEL_NOTICE, detail, skip_tool_fallback=True)
    if is_context_overflow(lower):
        # Overflow is a window problem. JSON-tool fallback cannot shrink it.
        return ModelFailure(LLAMACPP_GENERIC_NOTICE, detail, skip_tool_fallback=True)
    if _http_status(text) >= 500:
        return ModelFailure(LLAMACPP_DOWN_NOTICE, detail, skip_tool_fallback=True)
    status = _http_status(text)
    if status >= 400:
        # A 400 on the tools array is the one reject JSON fallback can still fix.
        # Other 4xx stay on the notice. Overflow and a missing model already returned.
        skip = status != 400
        return ModelFailure(LLAMACPP_REJECT_NOTICE, detail, skip_tool_fallback=skip)
    return ModelFailure(LLAMACPP_GENERIC_NOTICE, detail, skip_tool_fallback=False)


def classify_turn_failure(
    exc: BaseException,
    *,
    model: str = "",
    role: str = "",
    config: dict[str, Any] | None = None,
    backend: object | None = None,
) -> ModelFailure:
    """Classify a chat-server failure. llama.cpp is the only engine."""
    cfg = config or {}
    base_url = str(getattr(backend, "base_url", "") or "").strip()
    if not base_url:
        base_url = str((cfg.get("llamacpp") or {}).get("base_url") or "")
    return classify_model_failure(
        exc, model=model, base_url=base_url, role=role, provider="llamacpp"
    )


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
    del llamacpp
    return "llama-server " + " ".join(parts)
