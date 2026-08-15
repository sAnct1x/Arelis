"""What to do when the port Arelis wants is already taken.

The configured ports are fixed numbers -- 8765 for inbound texts from the phone
companion, 8766 for the UI/core bridge -- and a fixed number is a number something
else can already be using. Whatever the reason, the result was
``OSError: [WinError 10048]``: inbound ingest turned it into a status line naming
an error code, and the IPC failure was worse, happening inside a task nobody
awaited, so the UI received no core events and nothing anywhere said why.

Falling forward to the next free port is chosen over the two alternatives on
purpose. Binding port 0 and letting the OS choose would work for the bridge,
which is loopback-only and can be discovered, but not for inbound: that port is
typed into a phone by hand, and a number that changes on every launch cannot be.
Deriving a port from something machine-specific would change the common case,
moving a working single-user install off 8765 for no benefit and invalidating both
the setup instructions and any companion already configured.

So the first Arelis to start keeps the documented port, a later one lands a place
or two along and says so in plain words, and clients find the port that is theirs
by asking each candidate who it belongs to (see ``arelis.identity``). Nothing is
written down, so nothing can go stale.
"""

from __future__ import annotations

# More than enough for any plausible number of things sitting on these ports, and
# small enough that scanning the range is a handful of instant loopback refusals
# rather than something a user waits for.
PORT_SEARCH_SPAN = 6

_MAX_PORT = 65535


def candidates(preferred: int, span: int = PORT_SEARCH_SPAN) -> list[int]:
    """The preferred port first, then the next few above it.

    Preferred-first is the whole point: it keeps the documented port for the
    first Arelis to ask, so the ordinary single-user install is bit-for-bit
    unaffected by any of this and the setup instructions stay true.

    Ports above the ceiling are dropped rather than wrapped, since wrapping
    would hand out a low, likely-privileged port as a "next" candidate.
    """
    first = int(preferred)
    if first == 0:
        # "Let the operating system choose" cannot collide, so there is nothing
        # to fall forward to. Returning it alone keeps that request intact
        # instead of scanning 1..6, which are privileged ports.
        return [0]
    if first < 1 or first > _MAX_PORT:
        return []
    return [p for p in range(first, first + max(1, int(span))) if p <= _MAX_PORT]
