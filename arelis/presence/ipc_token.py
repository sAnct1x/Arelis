"""Session token for the loopback IPC bridge.

Any local program can open 127.0.0.1. Without a token, that program received
confirm cards (a draft mail body included) and inbound texts the moment the
socket connected, and it could allow a send or shut the core down.

The token is a file in the user's state directory. The first process of a
session rotates it. Every other process reads it. Clients send it on hello.
The user never sees the value, and it is never written into a status line.

Two Windows accounts have two data roots, so they have two tokens. That is
what keeps one account's bridge from answering the other's hello.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from arelis.paths import state_dir
from arelis.presence.lock import PresenceLock

_TOKEN_NAME = "ipc.token"


def token_path() -> Path:
    """Where this user's session token is stored."""
    return state_dir() / _TOKEN_NAME


def read_token() -> str | None:
    """The current token, or None when the file is missing or unusable."""
    try:
        raw = token_path().read_bytes()
    except OSError:
        return None
    try:
        text = raw.decode("ascii").strip()
    except UnicodeDecodeError:
        return None
    if not text or any(ch.isspace() for ch in text):
        return None
    return text


def ensure_token(rotate: bool = False) -> str:
    """Return the session token, writing a new one when ``rotate`` is set.

    A false rotate leaves an existing file alone. A missing file is created
    either way, so a seat that comes up alone still has a token to hand out.
    The write goes to a temp file opened at mode 0600, then replaced into
    place, so a reader never sees a half-written token. On Windows the
    mode argument is ignored; LOCALAPPDATA is already private to the account.
    """
    if not rotate:
        current = read_token()
        if current:
            return current
    token = secrets.token_urlsafe(32)
    _write_token(token_path(), token)
    return token


def claim_session_token(other_lock: PresenceLock) -> str:
    """Rotate only when this process is the first seat of the session.

    The caller has already taken its own lock, the core lock or the UI lock.
    If the other seat's lock is free, nobody else is up, so the token rotates.
    If the other seat is up, the file it wrote is the one both sides share,
    and replacing it would lock that seat out of the bridge.
    """
    other_free = other_lock.acquire()
    try:
        return ensure_token(rotate=other_free)
    finally:
        if other_free:
            other_lock.release()


def _write_token(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = token.encode("ascii")
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("could not write the IPC session token")
            view = view[written:]
    except Exception:
        os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.close(fd)
    try:
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
