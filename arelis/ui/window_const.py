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
# the model. Armed only after Stop on a turn that is still busy.
BUSY_WATCHDOG_MS = 8000

# Ceiling on a live turn, armed when busy starts. Override with ui.hung_turn_s.
# The 8s watchdog above is post-Stop recovery; this is the "tool hung" unlock.
# Hung means no progress, not a long turn. HUNG_TURN_S is the longest gap
# between streamed tokens. Prompt reading that moves forward, and a tool
# that has not returned, restart HUNG_FIRST_TOKEN_S. HUNG_TURN_CAP_S bounds
# the whole turn, including a tool that never comes back.
# If she already has tool results, the ceiling asks her to close. This is how
# long that close gets before a real hang still cuts the turn.
HUNG_TURN_S = 60
HUNG_FIRST_TOKEN_S = 180
HUNG_TURN_CAP_S = 600
HUNG_CLOSE_GRACE_S = 180
HUNG_TURN_MAX_S = 3600

THINK_PULSE_MS = 600

# A hotkey press that arrives within this window of the last one is the same
# press echoing, not the user asking twice.
VOICE_HOTKEY_ECHO_S = 0.12
