from __future__ import annotations

from typing import Any

from arelis.llm.ollama import OllamaProvider
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


def build_router(config: dict[str, Any]) -> ModelRouter:
    """Construct the provider and router from config.

    Single place on purpose. The desktop app, the CLI, and the e2e scripts all
    need this wiring, and when each built its own the e2e runs quietly used
    different settings from the app they were meant to be testing.
    """
    ollama_cfg = config.get("ollama", {}) or {}
    router_cfg = config.get("router", {}) or {}

    provider = OllamaProvider(
        base_url=ollama_cfg.get("base_url", "http://127.0.0.1:11434"),
        timeout_s=ollama_cfg.get("timeout_s", 300),
    )

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
