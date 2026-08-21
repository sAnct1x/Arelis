"""Single-instance lock for `arelis --core` and helpers to detect it."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from arelis.identity import is_mine
from arelis.paths import state_dir, user_data_dir
from arelis.presence.ports import candidates

log = logging.getLogger(__name__)

DEFAULT_LOCK_NAME = "arelis-core.lock"
DEFAULT_UI_LOCK_NAME = "arelis-ui.lock"


def core_lock_path(config: dict[str, Any] | None = None) -> Path:
    """Path for the core process lock file (beside the user's state by default)."""
    raw = ""
    if config:
        presence = config.get("presence") or {}
        raw = str(presence.get("lock_path") or "").strip()
    path = Path(raw) if raw else state_dir() / DEFAULT_LOCK_NAME
    if not path.is_absolute():
        path = user_data_dir() / path
    return path


def ui_lock_path(config: dict[str, Any] | None = None) -> Path:
    """Path for the glass UI single-instance lock."""
    raw = ""
    if config:
        presence = config.get("presence") or {}
        raw = str(presence.get("ui_lock_path") or "").strip()
    path = Path(raw) if raw else state_dir() / DEFAULT_UI_LOCK_NAME
    if not path.is_absolute():
        path = user_data_dir() / path
    return path


class PresenceLock:
    """Non-blocking exclusive lock so two cores do not fight over :8765."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._fh: Any = None
        self._mutex: Any = None

    @property
    def held(self) -> bool:
        return self._fh is not None or self._mutex is not None

    def acquire(self) -> bool:
        """Return True if this process now owns the lock."""
        if self.held:
            return True
        # Windows: named mutex is reliable across python.exe/pythonw.exe races
        # where a 1-byte msvcrt file lock can occasionally double-admit.
        if os.name == "nt":
            try:
                import ctypes

                kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
                name = (
                    "Local\\ArelisLock_"
                    + hashlib.sha1(
                        str(self.path.resolve()).encode("utf-8", "replace")
                    ).hexdigest()[:16]
                )
                kernel32.SetLastError(0)
                # bInitialOwner=True so this process owns the mutex immediately.
                handle = kernel32.CreateMutexW(None, True, name)
                if not handle:
                    return False
                # ERROR_ALREADY_EXISTS == 183 — another living process holds it.
                if int(kernel32.GetLastError()) == 183:
                    kernel32.CloseHandle(handle)
                    return False
                self._mutex = handle
            except Exception:
                self._mutex = None

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            if self._mutex is not None and os.name == "nt":
                try:
                    import ctypes

                    ctypes.windll.kernel32.CloseHandle(self._mutex)  # type: ignore[attr-defined]
                except Exception:
                    pass
                self._mutex = None
            return False
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        self._fh = fh
        try:
            _pid_sidecar(self.path).write_text(str(os.getpid()), encoding="utf-8")
        except OSError:
            pass
        return True

    def release(self) -> None:
        fh = self._fh
        self._fh = None
        mutex = self._mutex
        self._mutex = None
        if fh is not None:
            try:
                if os.name == "nt":
                    import msvcrt

                    fh.seek(0)
                    try:
                        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl

                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                fh.close()
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
            try:
                _pid_sidecar(self.path).unlink(missing_ok=True)
            except OSError:
                pass
        if mutex is not None and os.name == "nt":
            try:
                import ctypes

                ctypes.windll.kernel32.CloseHandle(mutex)  # type: ignore[attr-defined]
            except Exception:
                pass


def _pid_sidecar(path: Path | str) -> Path:
    """Unlocked neighbour of the lock file, so a waiter can read the holder pid."""
    lock = Path(path)
    return lock.with_name(lock.name + ".pid")


def lock_file_pid(path: Path | str) -> int | None:
    """PID of the process that holds this lock, if we can read it.

    Windows mandatory-locks the first byte of the lock file itself, so another
    handle cannot read that file while it is held. The pid is also written to a
    sidecar that is not locked.
    """
    lock = Path(path)
    for candidate in (_pid_sidecar(lock), lock):
        try:
            raw = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not raw:
            continue
        token = raw.split()[0]
        try:
            pid = int(token)
        except ValueError:
            continue
        if pid > 0:
            return pid
    return None


def pid_is_alive(pid: int) -> bool:
    """True when that OS process still exists."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        process_query_limited = 0x1000
        still_active = 259
        access_denied = 5
        kernel32.SetLastError(0)
        handle = kernel32.OpenProcess(process_query_limited, False, int(pid))
        if not handle:
            return int(kernel32.GetLastError()) == access_denied
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return int(code.value) == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def lock_held_by_other(path: Path | str) -> bool:
    """True when another living process appears to hold the core lock."""
    probe = PresenceLock(path)
    if probe.acquire():
        probe.release()
        return False
    return True


def probe_ingest_health(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 0.4,
    mine_only: bool = False,
) -> bool:
    """True when something answers GET /inbound/health on the ingest port.

    ``mine_only`` additionally requires the reply to name this user's instance.
    It is off by default because most callers -- the hardware harness, the
    settings Test button -- are asking the literal question "is anything serving
    on this port", and answering that with a silent identity check would make a
    correct probe report failure. Callers deciding *what to attach to* pass it,
    and for them a reply from another account's core is not merely unhelpful but
    the thing to be avoided.
    """
    # Health is bound on 0.0.0.0 but we always probe loopback from this machine.
    url = f"http://{host}:{int(port)}/inbound/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            if not 200 <= getattr(resp, "status", 200) < 300:
                return False
            if not mine_only:
                return True
            body = resp.read(4096)
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
    try:
        claimed = json.loads(body.decode("utf-8", "replace")).get("instance")
    except (ValueError, AttributeError):
        # Something is serving this port and it is not an Arelis that speaks the
        # handshake. Not ours, by the same reasoning as an absent claim.
        return False
    return is_mine(claimed)


def find_my_ingest_port(config: dict[str, Any]) -> int | None:
    """The port this user's own inbound ingest is answering on, if any.

    Scans the fall-forward range rather than trusting the configured number,
    because on a shared PC the second account's ingest is one or two ports along
    (see ``arelis.presence.ports``). Identity is what makes scanning safe: the
    first port that answers is not necessarily ours, and the first port that
    answers *as us* is.
    """
    sms = (config.get("tools") or {}).get("sms") or {}
    ingest = (sms.get("inbound") or {}).get("ingest") or {}
    preferred = int(ingest.get("port") or 8765)
    for candidate in candidates(preferred):
        if probe_ingest_health(port=candidate, mine_only=True):
            return candidate
    return None


def external_core_available(config: dict[str, Any]) -> bool:
    """Whether *this user's* detached core is already listening.

    The identity requirement is the whole of the fix here. This decides whether
    the UI attaches to an existing core instead of starting its own, and it used
    to be satisfied by any reply on port 8765. On a machine with two accounts
    logged in, the second user's UI therefore attached to the first user's core
    and began receiving their texts and confirmation prompts.
    """
    if find_my_ingest_port(config) is not None:
        return True
    return lock_held_by_other(core_lock_path(config))
