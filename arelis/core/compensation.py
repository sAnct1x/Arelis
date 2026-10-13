"""The ``agent.compensation.regex_routing`` switch.

True, the default, is today's regex and keyword routing.
False skips those paths so the model picks tools itself.

This module does not read ``agent.native_tool_calling`` and does not
turn on native schema hints, native argument blocks, or the native
"tools owed" nudge.
"""

from __future__ import annotations

from typing import Any


def regex_routing(agent_cfg: dict[str, Any] | None) -> bool:
    """True unless ``agent.compensation.regex_routing`` is boolean false.

    A missing block, a missing key, or a non-boolean value stays on.
    Only a real YAML boolean false turns the routing off.
    """
    if not isinstance(agent_cfg, dict):
        return True
    block = agent_cfg.get("compensation")
    if not isinstance(block, dict):
        return True
    value = block.get("regex_routing", True)
    if isinstance(value, bool):
        return value
    return True


def agent_cfg_of(loop: Any) -> dict[str, Any]:
    """Agent dict from a loop, a round, or a test stand-in. Empty if absent."""
    if loop is None:
        return {}
    direct = getattr(loop, "agent_cfg", None)
    if isinstance(direct, dict):
        return direct
    cfg = getattr(loop, "config", None)
    if isinstance(cfg, dict):
        agent = cfg.get("agent")
        if isinstance(agent, dict):
            return agent
    return {}
