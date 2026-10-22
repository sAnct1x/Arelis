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
LLAMACPP_MODEL_NOTICE = (
    "The local model server does not have that model loaded. "
    "Check the model file you started it with."
)
LLAMACPP_GENERIC_NOTICE = (
    "The model failed mid-turn. "
    "Check that the local model server is still running, then send again."
)
LLAMACPP_RESTART_NOTICE = (
    "The model server hit an error and needs a restart. "
    "Sending again will fail until it is restarted."
)
LLAMACPP_DEVICE_NOTICE = (
    "The model server needs a restart. "
    "The graphics card stopped answering, and sending again will fail until it is restarted."
)

# llama-server sets this exact message when decode returns below -1.
# HTTP code and error type are the same on every server failure.
_COMPUTE_MESSAGE = "Compute error."


class LlamaComputeError(RuntimeError):
    """llama-server returned HTTP 500. Sending again fails until a restart."""


class LlamaDeviceLostError(LlamaComputeError):
    """The error object is the compute failure. The graphics card stopped."""


def _structured_error(payload: object) -> Any:
    """The ``error`` object, or the payload itself when that is the object."""
    if not isinstance(payload, dict):
        return None
    inner = payload.get("error")
    if isinstance(inner, dict):
        return inner
    return payload


def is_llamacpp_compute_error(payload: object) -> bool:
    """True when the structured error is llama-server's compute failure.

    Every HTTP 500 from this server carries code 500 and type
    ``server_error``. The message field is the fixed string
    ``Compute error.`` when decode returns below -1, which is the
    device-lost case. Other failures keep a different message. The
    check is those three fields. It does not search free text.
    """
    err = _structured_error(payload)
    if not isinstance(err, dict):
        return False
    if err.get("message") != _COMPUTE_MESSAGE:
        return False
    if err.get("type") != "server_error":
        return False
    raw = err.get("code")
    if raw is None:
        return False
    try:
        code = int(raw)
    except (TypeError, ValueError):
        return False
    return code == 500


def restart_error(message: str, payload: object) -> LlamaComputeError:
    """HTTP 500. The graphics-card line is only the compute error object."""
    if is_llamacpp_compute_error(payload):
        return LlamaDeviceLostError(message)
    return LlamaComputeError(message)


def restart_notice(payload: object) -> str:
    """Chat line for an HTTP 500 body."""
    if is_llamacpp_compute_error(payload):
        return LLAMACPP_DEVICE_NOTICE
    return LLAMACPP_RESTART_NOTICE


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
    if isinstance(exc, LlamaDeviceLostError):
        # Decode cannot run. Another completion hits the same graphics card.
        return ModelFailure(LLAMACPP_DEVICE_NOTICE, detail, skip_tool_fallback=True)
    if isinstance(exc, LlamaComputeError):
        # The process is still listening. Another completion hits the same error.
        return ModelFailure(LLAMACPP_RESTART_NOTICE, detail, skip_tool_fallback=True)
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
    # Other 4xx, including 400 on the tools array, still get one JSON fallback.
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
    return " ".join(parts)
