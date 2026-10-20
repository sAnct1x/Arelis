from __future__ import annotations

from typing import Any

from arelis.llm.llamacpp import LlamaCppProvider
from arelis.llm.ollama import (
    DEFAULT_EMBED_KEEP_ALIVE,
    DEFAULT_EMBED_NUM_GPU,
    OllamaProvider,
    ollama_base_url,
)
from arelis.llm.router import ModelRouter
from arelis.llm.startup import (
    PrefixWarmup,
    prefix_warmup_for,
    run_auto_lessons,
    run_model_preflight,
    run_model_warmup,
    seed_prefix_cache,
)

__all__ = [
    "LlamaCppProvider",
    "ModelRouter",
    "OllamaProvider",
    "PrefixWarmup",
    "build_router",
    "prefix_warmup_for",
    "run_auto_lessons",
    "run_model_preflight",
    "run_model_warmup",
    "seed_prefix_cache",
]


def _provider_for(
    config: dict[str, Any],
    ollama_cfg: dict[str, Any],
    memory_cfg: dict[str, Any],
) -> OllamaProvider | LlamaCppProvider:
    """Ollama unless config asks for a llama-server that is already running."""
    kind = str((config.get("llm") or {}).get("provider") or "ollama").strip().lower()
    if kind not in {"llamacpp", "llama.cpp", "llama-server"}:
        return OllamaProvider(
            base_url=ollama_base_url(config),
            timeout_s=ollama_cfg.get("timeout_s", 300),
            embed_keep_alive=memory_cfg.get("embed_keep_alive", DEFAULT_EMBED_KEEP_ALIVE),
            embed_num_gpu=int(memory_cfg.get("embed_num_gpu", DEFAULT_EMBED_NUM_GPU)),
        )
    lc = config.get("llamacpp") or {}
    raw_caps = lc.get("context_caps") or {}
    caps = (
        {str(key): int(value) for key, value in raw_caps.items() if value}
        if isinstance(raw_caps, dict)
        else {}
    )
    default_cap = lc.get("default_cap")
    return LlamaCppProvider(
        base_url=str(lc.get("base_url") or "http://127.0.0.1:8080"),
        timeout_s=float(lc.get("timeout_s", 300)),
        context_caps=caps,
        default_cap=int(default_cap) if default_cap else None,
    )


def build_router(config: dict[str, Any]) -> ModelRouter:
    """Construct the provider and router from config.

    Single place on purpose. The desktop app, the CLI, and the e2e scripts all
    need this wiring, and when each built its own the e2e runs quietly used
    different settings from the app they were meant to be testing.
    """
    ollama_cfg = config.get("ollama", {}) or {}
    router_cfg = config.get("router", {}) or {}
    memory_cfg = config.get("memory") or {}
    provider = _provider_for(config, ollama_cfg, memory_cfg)

    options: dict[str, Any] = {}
    num_ctx = ollama_cfg.get("num_ctx")
    if num_ctx:
        options["num_ctx"] = int(num_ctx)
    role_num_ctx: dict[str, int] = {}
    research_ctx = ollama_cfg.get("research_num_ctx")
    if research_ctx:
        role_num_ctx["research"] = int(research_ctx)

    return ModelRouter(
        provider,
        config.get("models", {}),
        keep_alive=router_cfg.get("keep_alive", "5m"),
        default_role=router_cfg.get("default_role", "fast"),
        default_keep_alive=router_cfg.get("default_keep_alive", "30m"),
        warm_on_start=bool(router_cfg.get("warm_on_start", True)),
        rewarm_after_switch=bool(router_cfg.get("rewarm_after_switch", True)),
        rewarm_delay_s=float(router_cfg.get("rewarm_delay_s", 60)),
        sticky_hold_s=(
            float(router_cfg["sticky_hold_s"])
            if router_cfg.get("sticky_hold_s") is not None
            else None
        ),
        options=options,
        role_num_ctx=role_num_ctx or None,
    )
