"""User-facing copy when Ollama dies or rejects a turn.

Chat gets a short instruction. The exception, URL, and model tag belong in
Thinking — not in the transcript as ``LLM error: ConnectError(...)``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
OLLAMA_VRAM_NOTICE = (
    "The research model could not fit on the GPU. I unloaded it and put the "
    "conversation model back so the machine stays usable. Close other GPU apps "
    "(ComfyUI, games, extra Chrome), then try the research ask again — or stay "
    "on `/role fast`."
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
    """True when a 14B load lost the VRAM fight — never JSON-fallback this."""
    lower = (str(exc) if not isinstance(exc, str) else exc).lower()
    return any(marker in lower for marker in _VRAM_MARKERS)

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
) -> OllamaFailure:
    """Map an Ollama exception to chat copy plus a Thinking line."""
    detail = _debug_detail(exc, model=model, base_url=base_url)
    text = str(exc)
    lower = text.lower()
    tag = _model_tag(text, model)

    if isinstance(exc, _UNREACHABLE):
        return OllamaFailure(OLLAMA_DOWN_NOTICE, detail, skip_tool_fallback=True)
    if is_vram_failure(lower):
        return OllamaFailure(OLLAMA_VRAM_NOTICE, detail, skip_tool_fallback=True)
    if _is_missing_model(lower):
        return OllamaFailure(
            OLLAMA_MODEL_NOTICE.format(model=tag),
            detail,
            skip_tool_fallback=True,
        )
    if _http_status(text) >= 500:
        return OllamaFailure(OLLAMA_DOWN_NOTICE, detail, skip_tool_fallback=True)
    if lower.startswith("ollama ") or "ollama returned http" in lower:
        # HTTP 400 on the tools array is the one case JSON fallback may still fix.
        status = _http_status(text)
        skip = status not in {0, 400}
        return OllamaFailure(OLLAMA_REJECT_NOTICE, detail, skip_tool_fallback=skip)
    return OllamaFailure(OLLAMA_GENERIC_NOTICE, detail, skip_tool_fallback=False)


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


def _debug_detail(exc: BaseException, *, model: str, base_url: str) -> str:
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
    return "Ollama " + " ".join(parts)
