"""Single-instance lock for `arelis --core` and helpers to detect it."""

from __future__ import annotations

import hashlib
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from arelis.config import PROJECT_ROOT

log = logging.getLogger(__name__)

DEFAULT_LOCK_NAME = "arelis-core.lock"
DEFAULT_UI_LOCK_NAME = "arelis-ui.lock"


def core_lock_path(config: dict[str, Any] | None = None) -> Path:
    """Path for the core process lock file (under data/ by default)."""
    raw = ""
    if config:
        presence = config.get("presence") or {}
        raw = str(presence.get("lock_path") or "").strip()
    path = Path(raw) if raw else PROJECT_ROOT / "data" / DEFAULT_LOCK_NAME
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def ui_lock_path(config: dict[str, Any] | None = None) -> Path:
    """Path for the glass UI single-instance lock."""
    raw = ""
    if config:
        presence = config.get("presence") or {}
        raw = str(presence.get("ui_lock_path") or "").strip()
    path = Path(raw) if raw else PROJECT_ROOT / "data" / DEFAULT_UI_LOCK_NAME
    if not path.is_absolute():
        path = PROJECT_ROOT / path
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
        if mutex is not None and os.name == "nt":
            try:
                import ctypes

                ctypes.windll.kernel32.CloseHandle(mutex)  # type: ignore[attr-defined]
            except Exception:
                pass


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
) -> bool:
    """True when something answers GET /inbound/health on the ingest port."""
    # Health is bound on 0.0.0.0 but we always probe loopback from this machine.
    url = f"http://{host}:{int(port)}/inbound/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def external_core_available(config: dict[str, Any]) -> bool:
    """Whether a detached core is already listening (lock and/or health)."""
    sms = (config.get("tools") or {}).get("sms") or {}
    inbound = sms.get("inbound") or {}
    ingest = inbound.get("ingest") or {}
    port = int(ingest.get("port") or 8765)
    if probe_ingest_health(port=port):
        return True
    return lock_held_by_other(core_lock_path(config))
