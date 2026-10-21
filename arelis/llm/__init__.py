from __future__ import annotations

import logging
from typing import Any

from arelis.llm.legacy import migrate_engine_config
from arelis.llm.llama_launch import launch_args_for
from arelis.llm.llamacpp import LlamaCppProvider
from arelis.llm.router import ModelRouter
from arelis.llm.startup import (
    PrefixWarmup,
    prefix_warmup_for,
    run_auto_lessons,
    run_model_preflight,
    run_model_warmup,
    seed_prefix_cache,
)

log = logging.getLogger(__name__)

__all__ = [
    "LlamaCppProvider",
    "ModelRouter",
    "PrefixWarmup",
    "build_router",
    "prefix_warmup_for",
    "run_auto_lessons",
    "run_model_preflight",
    "run_model_warmup",
    "seed_prefix_cache",
]


def _provider_for(config: dict[str, Any]) -> LlamaCppProvider:
    """The only chat server: llama.cpp."""
    lc = config.get("llamacpp") or {}
    raw_caps = lc.get("context_caps") or {}
    caps = (
        {str(key): int(value) for key, value in raw_caps.items() if value}
        if isinstance(raw_caps, dict)
        else {}
    )
    default_cap = lc.get("default_cap")
    embed_url = str(lc.get("embed_url") or "").strip()
    try:
        launch_args = launch_args_for(config)
    except Exception:
        log.warning("Could not build llama-server args", exc_info=True)
        launch_args = None
    return LlamaCppProvider(
        base_url=str(lc.get("base_url") or "http://127.0.0.1:8080"),
        timeout_s=float(lc.get("timeout_s", 300)),
        context_caps=caps,
        default_cap=int(default_cap) if default_cap else None,
        embed_url=embed_url or None,
        launch_args=launch_args,
    )


def build_router(config: dict[str, Any]) -> ModelRouter:
    """Construct the llama.cpp provider and router from config.

    Single place on purpose. The desktop app, the CLI, and the e2e scripts all
    need this wiring, and when each built its own the e2e runs quietly used
    different settings from the app they were meant to be testing.
    """
    migrate_engine_config(config)
    router_cfg = config.get("router", {}) or {}
    provider = _provider_for(config)
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
        options={},
        role_num_ctx=None,
    )
