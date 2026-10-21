"""Load a config that still names the retired chat server.

Christopher chose llama.cpp as the only engine. An old config.local.yaml may
still set ``llm.provider`` to the retired name, or keep a top-level block of
that server's keys. Loading either must not crash. Chat uses llama.cpp.
"""

from __future__ import annotations

from typing import Any

# The retired server. This file is the only place that name remains.
LEGACY_PROVIDER = "ollama"
LEGACY_SECTION = "ollama"

_LLAMA = frozenset({"llamacpp", "llama.cpp", "llama-server"})


def migrate_engine_config(config: dict[str, Any]) -> dict[str, Any]:
    """Force llama.cpp and drop the retired server's settings."""
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
    return config
