"""House watch — the doors Arelis opened, not a security operations center.

The chat model cannot sit on the network. This module can: inbound rate
limits, bad-token lockout, an outbound API budget, and a snapshot the
``watch`` tool and the house chip read.
"""

from __future__ import annotations

from arelis.guard.watch import (
    Admit,
    EgressMutedError,
    Listener,
    Watch,
    WatchSnapshot,
    attach_watch,
    get_watch,
    reset_watch,
)

__all__ = (
    "Admit",
    "EgressMutedError",
    "Listener",
    "Watch",
    "WatchSnapshot",
    "attach_watch",
    "get_watch",
    "reset_watch",
)
