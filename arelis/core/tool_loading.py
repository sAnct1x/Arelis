"""Whether agent.tool_loading is on.

Off (the shipped default) keeps the session tool list exactly as it was
before this flag. On registers the load_tools definition and nothing else.
The call reports a group. It does not add or remove any other tool.
"""

from __future__ import annotations

from typing import Any


def tool_loading(agent_cfg: dict[str, Any] | None) -> bool:
    """True only when agent.tool_loading is explicitly true."""
    if agent_cfg is None:
        return False
    return bool(agent_cfg.get("tool_loading", False))
