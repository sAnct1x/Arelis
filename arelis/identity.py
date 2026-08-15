"""Which copy of Arelis a loopback service belongs to.

"Is my core running?" used to be answered by opening a socket on a fixed port and
seeing a reply. A reply is not evidence: 8765 and 8766 are ordinary ports on an
interface every program on the machine shares, and something else answering there
is the common case, not the exotic one. Development servers, another
Arelis started from a different checkout, a stale process from before a crash --
each produces a reply that used to be trusted completely.

What that trust cost, in rough order of likelihood:

* the UI bridge attaches to whatever answered and republishes its traffic onto
  this bus -- at best noise, and if the thing that answered is another Arelis,
  someone else's inbound texts and confirmation prompts;
* the second-instance path (``activate_existing_ui``) reports success after
  handing its request to a stranger, so launching Arelis does nothing at all and
  the window never appears;
* readiness reports inbound as up on the strength of someone else's health
  endpoint while this user's own ingest never bound.

So every loopback service states who it belongs to, and every client requires the
answer to match. Identity is derived from the data root rather than stored in it:
the data root is already what distinguishes one copy of Arelis from another, and
a derived value cannot go stale, cannot fail to be written on a read-only
profile, and needs no first-run step.

The sharpest version of the problem is two Windows accounts signed into one PC,
since ``%LOCALAPPDATA%`` makes them two data roots sharing one loopback
interface, and the leak is then between two real people rather than between a
program and a stray socket. That is a real configuration and worth being correct
about, but it is uncommon and it is not why this exists -- a single user with a
port conflict hits the same three failures.

Not a secret and not a security boundary. Any local process could connect to a
loopback port and speak the protocol, and no token here would change that. This
answers the milder and likelier question of whether the thing that just replied
is *mine*.

Lives at the top level rather than under ``arelis.presence`` because
``arelis.sms_ingest`` serves the inbound health endpoint and must state its
identity there, while ``arelis.presence`` imports ``arelis.sms_ingest``. Putting
it in the package that needs it most would have made an import cycle.
"""

from __future__ import annotations

import hashlib

from arelis.paths import user_data_dir

# Enough to make an accidental collision between two accounts on one machine
# impossible in practice, and short enough to read in a log line.
_ID_CHARS = 16


def instance_id() -> str:
    """A stable identifier for this user's Arelis, cheap enough to call freely.

    Recomputed per call rather than cached, for the same reason
    ``user_data_dir()`` is: a test that sets ``ARELIS_DATA_DIR`` has to be
    believed, and a value frozen at import time would quietly describe whichever
    profile happened to be current when the module was first imported.

    Case-folded because Windows paths are case-insensitive, and ``C:\\Users``
    reaching us as ``c:\\users`` must not read as a different account.
    """
    raw = str(user_data_dir()).casefold().encode("utf-8", "surrogatepass")
    return hashlib.sha256(raw).hexdigest()[:_ID_CHARS]


def is_mine(claimed: object) -> bool:
    """Whether a service that identified itself as ``claimed`` is this copy's.

    A missing or empty claim is answered False, which is the decision that
    matters most here. It means anything that does not speak this handshake --
    an older Arelis, or something else entirely on the port -- is treated as not
    ours rather than assumed to be. The cost of being wrong in that direction is
    starting a core that falls forward to another port; the cost of being wrong
    in the other is attaching to a stranger, which is the failure this exists to
    prevent.
    """
    if not isinstance(claimed, str) or not claimed.strip():
        return False
    return claimed.strip() == instance_id()
