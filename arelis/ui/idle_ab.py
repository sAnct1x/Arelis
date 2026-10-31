"""Idle A/B diagnostics, read once at startup. Defaults keep today's behaviour.

Atria gpuab (2026-10-31): idle sat at 28-59 fps (p50 33 ms) while a turn held
54-60. Two suspects get a switch each, so a run can turn one off at a time:

ARELIS_IDLE_TIMERS=off     no 300 ms Night/Sodium full-window atmosphere
                           update and no 40 ms idle orb timer.
ARELIS_PRESERVE_BUFFER=off her renderer is made with preserveDrawingBuffer
                           false (nothing reads her canvas back).
ARELIS_AVATAR_BACKDROP=opaque  her page is painted with the room's bg0 instead
                           of transparent. A transparent page puts her view on
                           Qt's always-on-top translucent compose path; the
                           blank-frame A/B (m1-blank2) flips this to test it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

TIMERS_VAR = "ARELIS_IDLE_TIMERS"
BUFFER_VAR = "ARELIS_PRESERVE_BUFFER"
BACKDROP_VAR = "ARELIS_AVATAR_BACKDROP"

_state: dict[str, bool] | None = None


def _on(env: Mapping[str, str], var: str) -> bool:
    return str(env.get(var) or "on").strip().lower() not in ("off", "0", "false", "no")


def load(env: Mapping[str, str] | None = None) -> dict[str, bool]:
    """Read the switches. Called at startup; later calls reuse the result."""
    global _state
    if _state is None or env is not None:
        source = os.environ if env is None else env
        _state = {
            "timers": _on(source, TIMERS_VAR),
            "buffer": _on(source, BUFFER_VAR),
            "opaque": str(source.get(BACKDROP_VAR) or "").strip().lower() == "opaque",
        }
    return _state


def idle_timers() -> bool:
    return load()["timers"]


def preserve_buffer() -> bool:
    return load()["buffer"]


def opaque_backdrop() -> bool:
    return load()["opaque"]


def line() -> str:
    state = load()
    return (
        f"graphics idle_ab idle_timers={'on' if state['timers'] else 'off'} "
        f"preserve_buffer={'on' if state['buffer'] else 'off'} "
        f"backdrop={'opaque' if state['opaque'] else 'transparent'}"
    )
