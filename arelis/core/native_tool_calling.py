"""Helper for checking native_tool_calling experiment flag.

When `agent.native_tool_calling=true`, the regex/intent routing layer
is disabled so models with strong native tool calling can select tools
without deterministic preflight nudges or redirects fighting their choices.

Safety gates (SMS/email authorization, confirm-before-write, workspace
boundary, banned tools) stay ON regardless of this flag.
"""

from __future__ import annotations

from typing import Any


def native_tool_calling(agent_cfg: dict[str, Any] | None) -> bool:
    """Return true when native tool calling experiment is enabled.

    Args:
        agent_cfg: Agent configuration dict (may be None or empty)

    Returns:
        True when agent.native_tool_calling is explicitly true, else false
    """
    if agent_cfg is None:
        return False
    return bool(agent_cfg.get("native_tool_calling", False))
