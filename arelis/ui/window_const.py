"""Timings and metrics shared by the window mixins. One copy each.

`app.py` was split into `window_build`, `window_chrome`, `window_lifetime` and
`window_turn`, and this four-line block was copied into all four. Only three of
them use anything from it, and no two use the same member: `_THINK_PULSE_MS` is
read in build, `_WINDOW_RADIUS` and `_VOICE_HOTKEY_ECHO_S` in chrome,
`_BUSY_WATCHDOG_MS` in turn, and lifetime uses none of them.

Four copies of a number is one place to change it and three to forget, and the
failure is silent: nothing breaks, the window just behaves differently
depending on which mixin drew it.
"""

from __future__ import annotations

from arelis.ui.theme import GLASS

WINDOW_RADIUS = int(GLASS["radius"])

# How long a turn may look busy before the UI stops believing it. Recovery for
# a turn that died without publishing a terminal event; it is not a timeout on
# the model. Armed only after Stop.
BUSY_WATCHDOG_MS = 8000

# Ceiling on a live turn, armed when busy starts. Override with ui.hung_turn_s.
# The 8s watchdog above is post-Stop recovery; this is the "tool hung" unlock.
HUNG_TURN_S = 90
HUNG_TURN_TICK_MS = 1000
HUNG_TURN_MAX_S = 3600

THINK_PULSE_MS = 600

# A hotkey press that arrives within this window of the last one is the same
# press echoing, not the user asking twice.
VOICE_HOTKEY_ECHO_S = 0.12
