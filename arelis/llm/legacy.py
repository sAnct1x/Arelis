"""Load a config that still names the retired chat server.

Christopher chose llama.cpp as the only engine. An old config.local.yaml may
still set ``llm.provider`` to the retired name, keep a top-level block of
that server's keys, or pin a role to a ``name:tag`` model. Loading any of
that must not crash. Those role names become the 35B. Chat uses llama.cpp.
"""

from __future__ import annotations

import re
from typing import Any

# The retired server. This file is the only place that name remains.
LEGACY_PROVIDER = "ollama"
LEGACY_SECTION = "ollama"

# Shipped chat name. Same key as llamacpp.context_caps. The file is the
# Unsloth UD-Q4_K_M GGUF. llama_launch resolves a bare file name on disk.
SHIPPED_CHAT_MODEL = "Qwen3.6-35B-A3B"
SHIPPED_GGUF_NAME = "Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"

_LLAMA = frozenset({"llamacpp", "llama.cpp", "llama-server"})
# Retired server tags look like qwen3.5:9b. A path, a URL, or a bare GGUF
# name does not. Only this shape is rewritten.
_OLLAMA_TAG = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._+-]*:[A-Za-z0-9][A-Za-z0-9._+-]*$"
)


def migrate_engine_config(config: dict[str, Any]) -> dict[str, Any]:
    """Force llama.cpp, drop the retired server, and retarget old model tags."""
    if not isinstance(config, dict):
        return config
    llm = config.get("llm")
    if not isinstance(llm, dict):
        llm = {}
        config["llm"] = llm
    kind = str(llm.get("provider") or "").strip().lower()
    if kind not in _LLAMA:
        llm["provider"] = "llamacpp"
    config.pop(LEGACY_SECTION, None)
    _retarget_legacy_models(config)
    _ensure_shipped_gguf(config)
    return config


def _retarget_legacy_models(config: dict[str, Any]) -> None:
    """Point any ``name:tag`` role at the 35B. Other names stay as written."""
    models = config.get("models")
    if not isinstance(models, dict):
        return
    for role, value in list(models.items()):
        if _is_ollama_tag(value):
            models[role] = SHIPPED_CHAT_MODEL


def _ensure_shipped_gguf(config: dict[str, Any]) -> None:
    """Fill llamacpp.model when an old file never named a GGUF."""
    lc = config.get("llamacpp")
    if not isinstance(lc, dict):
        lc = {}
        config["llamacpp"] = lc
    if not str(lc.get("model") or "").strip():
        lc["model"] = SHIPPED_GGUF_NAME


def _is_ollama_tag(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or "/" in text or "\\" in text:
        return False
    return _OLLAMA_TAG.fullmatch(text) is not None
