"""Which copy of Arelis a loopback service belongs to.

Two accounts on one Windows PC share one installation and one loopback
interface, and until this existed nothing distinguished their processes. The
per-user lock in ``arelis.presence.lock`` correctly lets both accounts run a
core; what it cannot do is stop the second account's *UI* from talking to the
first account's core, because "is a core listening on 8766?" was answered by
opening a socket and seeing a reply.

Three separate consequences, all of which read as unrelated bugs:

* the UI bridge attaches to the other account's core, so one person's inbound
  texts, tool confirmations and status lines are published onto the other
  person's bus -- a cross-account leak of exactly the material Arelis exists to
  handle;
* the second-instance path (``activate_existing_ui``) reports success after
  raising the other person's window in their session, so the second user's
  launch does nothing at all and Arelis appears not to start;
* readiness reports inbound as up while the second user's own ingest never
  bound.

So every loopback service states who it belongs to, and every client requires
the answer to match before it trusts the connection. Identity is derived from
the data root rather than stored in it: ``%LOCALAPPDATA%`` is already per
account, it is already the thing that makes two users two users, and a derived
value cannot go stale, cannot fail to be written on a read-only profile, and
needs no first-run step.

Not a secret and not a security boundary. Any local process could connect to a
loopback port and speak the protocol, and no token here would change that --
the operating system's account separation is what protects these ports. This
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
    """Whether a service that identified itself as ``claimed`` is this user's.

    A missing or empty claim is answered False, which is the decision that
    matters most here. It means an older Arelis that predates this handshake is
    treated as somebody else's rather than assumed to be ours -- the safe
    direction, since being wrong the other way is the cross-account leak this
    module exists to prevent. The cost of being wrong this way is starting a
    second core that then falls forward to another port.
    """
    if not isinstance(claimed, str) or not claimed.strip():
        return False
    return claimed.strip() == instance_id()
