"""Launch line for the 35B llama-server.

Config C at ncmoe 32. Q8 mmproj, flash attention off, 1024 image tokens,
f16 KV, context 32768, batch 4096, ubatch 512. 512 was measured on the
target machine. 1024 used 11.88 GB at peak, over the 11.2 GB memory budget.
Q3 was measured at -ub 2048: prompt 2.2x faster than 512, same generation
speed, lower VRAM (short prompt).
The patched template stays: ``--jinja``, and ``qwen36_35b_insys.jinja``
beside the weights when that file is already there.

The picture file sits in the same directory as the model GGUF. If it is
missing, it is downloaded there once. Arelis starts llama-server only when
the chat port is down.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __version__
from arelis.llm.errors import restart_error, restart_notice
from arelis.llm.legacy import SHIPPED_GGUF_NAME

log = logging.getLogger(__name__)

MODEL_FILENAME = SHIPPED_GGUF_NAME
MMPROJ_FILENAME = "mmproj-Qwen3.6-35B-A3B-Q8_0.gguf"
TEMPLATE_FILENAME = "qwen36_35b_insys.jinja"
# ggml-org LFS oid. Same repo that published this Q8 projector.
MMPROJ_SHA256 = "904cbf8c8e876220066ab3bf676c7efa40f3da372276fdaf8b01d2fb2a37a51d"
MMPROJ_BYTES = 614_194_304
MMPROJ_URL = (
    "https://huggingface.co/ggml-org/Qwen3.6-35B-A3B-GGUF/resolve/main/"
    + MMPROJ_FILENAME
)
_HEALTH_WAIT_S = 180.0
# A cold first token on this card can take most of a minute. A dead device
# answers in well under a second, so this wait is not a retry loop.
READY_TIMEOUT_S = 60.0
_CACHE_DEPTH = 5

_OFFLINE = (
    "Arelis could not download the picture file. Check that this PC is online, "
    "then try again."
)
_MISMATCH = (
    "The picture file did not match what we expected. Try the download again."
)
_DISK = "This computer does not have enough free space for the picture file."
_LATER = (
    "The picture file download stopped. Try again in a little while."
)
_MISSING_BINARY = "llama-server was not found, so the 35B did not start."
_SLOW = "The 35B server did not finish starting. Try again in a little while."
_NO_TOKEN = "The 35B server did not answer a one token check."

_READ_TIMEOUT_S = 1.0
_CONNECT_TIMEOUT_S = 5.0
_STALL_LIMIT_S = 90.0
_READ = 64 * 1024
_CHUNK = 1024 * 1024

_lock = threading.Lock()
_proc: subprocess.Popen[bytes] | None = None
# Command line of the server we stopped or last started. Restore uses this
# exact list so a restart does not add flags the original launch did not have.
_saved_args: list[str] | None = None
Cancel = Callable[[], bool]

# Windows: leave the process outside Arelis's tree and job, like a manual start.
_DETACHED_PROCESS = 0x00000008
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


class _MmprojCancelledError(Exception):
    """First-run cancel. The unfinished picture file stays."""


def mmproj_for(model: Path) -> Path:
    """Q8 projector next to the model GGUF. Same directory, no second store."""
    return model.parent / MMPROJ_FILENAME


def _config_int(section: dict[str, Any], key: str, default: int) -> int:
    raw = section.get(key)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return value


HEADROOM_KEY = "avatar_headroom"
HEADROOM_SPARE_CORES = 2


def headroom_threads(physical: int | None = None) -> int:
    """llama-server threads that leave two physical cores for the GUI and her render thread.

    During generation llama-server keeps every core busy, so the GUI and render threads
    are scheduled late (Atria frametrace: frames over 33 ms went from 3% idle to 17-27%
    while generating, with only 4-12 ms of render work per frame).
    """
    if physical is None:
        physical = _physical_cores()
    return max(1, int(physical or 1) - HEADROOM_SPARE_CORES)


def _physical_cores() -> int:
    try:
        import psutil  # type: ignore

        count = psutil.cpu_count(logical=False)
    except ImportError:
        count = None
    if not count:
        logical = os.cpu_count() or 2
        count = max(1, logical // 2)
    return int(count)


def headroom_on(config: dict[str, Any] | None) -> bool:
    """``llamacpp.avatar_headroom``: on unless set to false."""
    lc = config.get("llamacpp") if isinstance(config, dict) else None
    return not (isinstance(lc, dict) and lc.get(HEADROOM_KEY) is False)


def llama_server_args(
    *,
    binary: str,
    model: str,
    mmproj: str,
    template: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8080,
    config: dict[str, Any] | None = None,
) -> list[str]:
    """Argv for the 35B server. This is the only place those flags are built.

    ``--n-cpu-moe``, ``-c``, and ``-ub`` come from config when set. Same
    defaults for Q3 and Q4: 32, 32768, 512. Q3 setup pins catalog ubatch 2048.
    """
    lc = config.get("llamacpp") if isinstance(config, dict) else None
    if not isinstance(lc, dict):
        lc = {}
    ctx = _config_int(lc, "default_cap", 32768)
    n_cpu_moe = _config_int(lc, "n_cpu_moe", 32)
    ubatch = _config_int(lc, "ubatch", 512)
    args = [
        binary,
        "-m",
        model,
        "--mmproj",
        mmproj,
        "-ngl",
        "99",
        "-fa",
        "off",
        "-c",
        str(ctx),
        "-np",
        "1",
        "--n-cpu-moe",
        str(n_cpu_moe),
        # 512 was measured on the target machine. 1024 used 11.88 GB
        # at peak, over the 11.2 GB memory budget.
        # Q3 was measured at -ub 2048: prompt 2.2x faster than 512,
        # same generation speed, lower VRAM (short prompt).
        "-ub",
        str(ubatch),
        "-b",
        "4096",
        "--cache-type-k",
        "f16",
        "--cache-type-v",
        "f16",
        "--image-max-tokens",
        "1024",
        "--jinja",
    ]
    if template:
        # --jinja has to come first or llama-server ignores the file.
        args.extend(["--chat-template-file", template])
    if headroom_on(config):
        # _spawn also starts the server at below normal priority when --threads is set.
        args.extend(["--threads", str(headroom_threads())])
    args.extend(["--host", host, "--port", str(port)])
    return args


def launch_args_for(config: dict[str, Any] | None) -> list[str] | None:
    """Args for the configured 35B, or None when the weights are not on disk."""
    try:
        return _launch_args_for(config or {})
    except OSError as exc:
        log.warning("Could not build llama-server args: %s", exc)
        return None


def restore_args(config: dict[str, Any] | None) -> list[str] | None:
    """The command we stopped or started, unchanged. Built args only if none."""
    with _lock:
        saved = list(_saved_args) if _saved_args else None
    if saved:
        return saved
    return launch_args_for(config)


def _remember_args(args: list[str] | None) -> None:
    global _saved_args
    if not args:
        return
    _saved_args = list(args)


def _cmdline_for_pid(pid: int) -> list[str] | None:
    try:
        import psutil
    except ImportError:
        return None
    try:
        cmd = psutil.Process(int(pid)).cmdline()
    except Exception:
        # The process may already have exited; keep the last saved command.
        return None
    if not cmd:
        return None
    return [str(part) for part in cmd]


def one_token_payload(model: str = "") -> dict[str, Any]:
    """Readiness body. One token, no tools. /health cannot see a dead GPU."""
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }
    name = (model or "").strip()
    if name:
        payload["model"] = name
    return payload


def decode_probe_state(status_code: int) -> str:
    """``ok``, ``dead``, or ``down``. HTTP 500 fails again until a restart.

    Callers stop instead of posting the prompt again. The graphics-card
    line depends on the error object, not on this status alone.
    """
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return "down"
    if code == 500:
        return "dead"
    if 0 < code < 400:
        return "ok"
    return "down"


def ensure_server(base_url: str, args: list[str] | None) -> None:
    """Start llama-server when the chat port is down.

    A listening port is not enough. ``/health`` stays ok after the graphics
    device is lost, so one generated token has to succeed before this
    returns. A compute failure raises, and does not start a second server.
    """
    if not args:
        return
    with _lock:
        if _health_ok(base_url):
            _require_decode(base_url, READY_TIMEOUT_S)
            return
        mmproj = _flag_value(args, "--mmproj")
        if mmproj:
            _ensure_mmproj(Path(mmproj))
        global _proc
        if _proc is not None and _proc.poll() is None:
            proc = _proc
        else:
            proc = _spawn(args)
            _proc = proc
        if not _wait_ready(base_url, proc, _HEALTH_WAIT_S):
            raise RuntimeError(_SLOW)


def stop_server(base_url: str = "http://127.0.0.1:8080", *, timeout_s: float = 8.0) -> bool:
    """Stop llama-server so another GPU job can use the card.

    Stops the process Arelis started, then a leftover listener on that
    local port only. Launch arguments are not changed. Returns True if a
    process was stopped.
    """
    stopped = False
    with _lock:
        global _proc
        proc = _proc
        _proc = None
        if proc is not None and proc.poll() is None:
            remembered = _cmdline_for_pid(int(proc.pid))
            if remembered:
                _remember_args(remembered)
            log.info("Stopping llama-server (pid=%s) to free the GPU", proc.pid)
            stopped = _terminate_proc(proc, timeout_s=timeout_s) or stopped
    host, port = _listen(base_url)
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return stopped
    if not _health_ok(base_url):
        return stopped
    return _kill_local_port(port) or stopped


def start_server_nowait(base_url: str, args: list[str] | None) -> None:
    """Spawn llama-server if the chat port is down. Do not wait for ready.

    Used when the app is quitting and must not leave chat dead, but also
    must not block on a full model load.
    """
    if not args:
        return
    with _lock:
        if _health_ok(base_url):
            return
        global _proc
        if _proc is not None and _proc.poll() is None:
            return
        _proc = _spawn(args)


def _terminate_proc(proc: subprocess.Popen[bytes], *, timeout_s: float) -> bool:
    try:
        proc.terminate()
        try:
            proc.wait(timeout=max(1.0, float(timeout_s)))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    except Exception:
        log.warning(
            "Could not stop llama-server pid %s",
            getattr(proc, "pid", "?"),
            exc_info=True,
        )
        return False
    return True


def _kill_local_port(port: int) -> bool:
    """Terminate listeners on a loopback port."""
    if port <= 0 or port > 65535:
        return False
    pids = _pids_on_port(port)
    if not pids:
        return False
    self_pid = os.getpid()
    killed = False
    for pid in pids:
        if pid <= 0 or pid == self_pid:
            continue
        remembered = _cmdline_for_pid(int(pid))
        if remembered:
            _remember_args(remembered)
        log.info("Stopping leftover llama-server listener pid=%s port=%s", pid, port)
        if _terminate_pid(pid):
            killed = True
    return killed


def _pids_on_port(port: int) -> list[int]:
    try:
        import psutil
    except ImportError:
        return []
    pids: list[int] = []
    try:
        for conn in psutil.net_connections(kind="tcp"):
            laddr = getattr(conn, "laddr", None)
            if laddr is None:
                continue
            if int(getattr(laddr, "port", 0) or 0) != int(port):
                continue
            status = str(getattr(conn, "status", "") or "").upper()
            if status not in {"LISTEN", "NONE"}:
                continue
            pid = getattr(conn, "pid", None)
            if pid:
                pids.append(int(pid))
    except Exception:
        log.warning("Could not list listeners on port %s", port, exc_info=True)
        return []
    return pids


def _terminate_pid(pid: int) -> bool:
    try:
        import psutil

        proc = psutil.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
        return True
    except Exception:
        log.warning("Could not stop pid %s", pid, exc_info=True)
        return False


def _launch_args_for(config: dict[str, Any]) -> list[str] | None:
    model = locate_model_gguf(config)
    if model is None:
        return None
    model = model.resolve()
    template_path = locate_template(config, model)
    lc = config.get("llamacpp") or {}
    host, port = _listen(str(lc.get("base_url") or "http://127.0.0.1:8080"))
    return llama_server_args(
        binary=_binary(config),
        model=str(model),
        mmproj=str(mmproj_for(model).resolve()),
        template=str(template_path.resolve()) if template_path else None,
        host=host,
        port=port,
        config=config,
    )


def locate_model_gguf(config: dict[str, Any]) -> Path | None:
    """The UD-Q4_K_M file, from config or the same folders other weights use.

    A bare file name is looked up beside the other weights. A relative path
    is resolved from the data directory, not from the process working
    directory, so a Start-menu launch and a shell launch find the same file.
    A full path that is not on disk stays missing: no server, no exception.
    """
    lc = config.get("llamacpp") or {}
    explicit = str(lc.get("model") or "").strip()
    if not explicit:
        return _find_weight(MODEL_FILENAME)
    path = Path(explicit).expanduser()
    if path.is_file():
        return path
    if path.is_absolute():
        return None
    found = _find_relative(path)
    if found is not None:
        return found
    if path.parent == Path("."):
        return _find_weight(path.name)
    return None


def _model_roots() -> list[Path]:
    """Folders that hold a bare GGUF name. The installed profile is included.

    A checkout, or a fresh data dir, does not own the weights the installed
    copy already has. Voice files already fall back there. The 35B does too.
    """
    from arelis.paths import models_dir, published_data_dir

    roots = [models_dir()]
    published = published_data_dir()
    if published is not None:
        extra = published / "models"
        if extra not in roots:
            roots.append(extra)
    return roots


def _find_weight(name: str) -> Path | None:
    """One file name in the model folder, its llm subfolder, or the cache."""
    for folder in _model_roots():
        for candidate in (folder / name, folder / "llm" / name):
            if candidate.is_file():
                return candidate
    for root in _cache_roots():
        found = _find_named(root, name)
        if found is not None:
            return found
    return None


def _find_relative(path: Path) -> Path | None:
    """A relative model path, from the data dir rather than the working dir."""
    from arelis.paths import published_data_dir, user_data_dir

    bases = [user_data_dir()]
    published = published_data_dir()
    if published is not None:
        bases.append(published)
    for base in bases:
        candidate = base / path
        if candidate.is_file():
            return candidate
    parts = path.parts
    if len(parts) > 1 and parts[0] == "models":
        return _find_weight(str(Path(*parts[1:])))
    return None


def mmproj_beside_running_server(config: dict[str, Any]) -> bool:
    """Picture file next to the GGUF a live llama-server already loaded.

    ``ensure_server`` leaves a healthy port alone. A fresh profile with no
    model path still talks to that process. ``/props`` names the GGUF it
    loaded (``model_path``, the same ``-m`` the launcher would pass). Vision
    is on only when the Q8 file sits next to that GGUF. A missing file stays
    off, including when ``modalities.vision`` is true.
    """
    lc = config.get("llamacpp") or {}
    explicit = str(lc.get("model") or "").strip()
    if explicit and Path(explicit).expanduser().is_absolute():
        return False
    base = str(lc.get("base_url") or "").strip()
    if not base:
        return False
    url = base.rstrip("/") + "/props"
    try:
        response = httpx.get(url, timeout=0.4, follow_redirects=False)
    except httpx.HTTPError:
        return False
    if response.status_code >= 400:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    if not isinstance(payload, dict):
        return False
    raw = str(payload.get("model_path") or "").strip()
    if not raw:
        return False
    model = Path(raw).expanduser()
    if not model.is_file():
        return False
    return mmproj_for(model).is_file()


def locate_template(config: dict[str, Any], model: Path) -> Path | None:
    """Patched jinja beside the weights, or the path already set in config."""
    lc = config.get("llamacpp") or {}
    explicit = str(lc.get("template") or "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            return path
    sibling = model.parent / TEMPLATE_FILENAME
    if sibling.is_file():
        return sibling
    return None


def _binary(config: dict[str, Any]) -> str:
    lc = config.get("llamacpp") or {}
    explicit = str(lc.get("binary") or "").strip()
    if explicit:
        return explicit
    found = shutil.which("llama-server")
    return found or "llama-server"


def _listen(base_url: str) -> tuple[str, int]:
    parsed = urlparse((base_url or "").strip() or "http://127.0.0.1:8080")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8080
    return host, port


def _cache_roots() -> list[Path]:
    roots: list[Path] = []
    env = os.environ.get("LLAMA_CACHE", "").strip()
    if env:
        roots.append(Path(env).expanduser())
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        roots.append(Path(local) / "llama.cpp")
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    if xdg:
        roots.append(Path(xdg).expanduser() / "llama.cpp")
    else:
        roots.append(Path.home() / ".cache" / "llama.cpp")
    return roots


def _find_named(root: Path, name: str, max_depth: int = _CACHE_DEPTH) -> Path | None:
    if not root.is_dir():
        return None
    base = root.resolve()
    for dirpath, dirnames, filenames in os.walk(base):
        depth = len(Path(dirpath).relative_to(base).parts)
        if depth >= max_depth:
            dirnames[:] = []
        if name in filenames:
            return Path(dirpath) / name
    return None


def _flag_value(args: list[str], flag: str) -> str | None:
    try:
        index = args.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(args):
        return None
    return args[index + 1]


def _health_ok(base_url: str) -> bool:
    url = base_url.rstrip("/") + "/health"
    try:
        response = httpx.get(url, timeout=2.0)
    except httpx.HTTPError:
        return False
    return response.status_code < 400


def _json_body(response: httpx.Response) -> object:
    try:
        return response.json()
    except (UnicodeDecodeError, ValueError):
        return None


def _token_state(base_url: str, timeout_s: float) -> str:
    url = base_url.rstrip("/") + "/v1/chat/completions"
    try:
        response = httpx.post(url, json=one_token_payload(), timeout=timeout_s)
    except httpx.HTTPError:
        return "down"
    state = decode_probe_state(response.status_code)
    if state == "dead":
        payload = _json_body(response)
        raise restart_error(restart_notice(payload), payload)
    return state


def _require_decode(base_url: str, timeout_s: float) -> None:
    """The process is listening. One token has to come back."""
    state = _token_state(base_url, timeout_s)
    if state == "ok":
        return
    raise RuntimeError(_NO_TOKEN)


def _wait_ready(base_url: str, proc: subprocess.Popen[bytes], timeout_s: float) -> bool:
    """Wait until the new process can decode one token.

    A compute failure is raised immediately. Polling ``/health`` only tells
    us the process has finished loading.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        if _health_ok(base_url):
            left = max(0.1, deadline - time.monotonic())
            state = _token_state(base_url, min(READY_TIMEOUT_S, left))
            if state == "ok":
                return True
        time.sleep(0.5)
    return False


def _log_path() -> Path | None:
    try:
        from arelis.paths import ensure, logs_dir

        return ensure(logs_dir()) / "llama-server.log"
    except OSError:
        return None


def _spawn(args: list[str]) -> subprocess.Popen[bytes]:
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.STDOUT,
    }
    handle = None
    log_path = _log_path()
    if log_path is not None:
        handle = log_path.open("ab")
        kwargs["stdout"] = handle
    if sys.platform == "win32":
        no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        flags = no_window | new_group | _DETACHED_PROCESS | _CREATE_BREAKAWAY_FROM_JOB
        if "--threads" in args:  # only llama_server_args with avatar headroom on adds it
            flags |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000)
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    _remember_args(args)
    log.info("Starting llama-server")
    try:
        return subprocess.Popen(args, **kwargs)
    except FileNotFoundError as exc:
        raise RuntimeError(_MISSING_BINARY) from exc
    finally:
        if handle is not None:
            handle.close()


def _ensure_mmproj(dest: Path, cancelled: Cancel | None = None) -> None:
    try:
        _download_mmproj(dest, cancelled=cancelled)
    except _MmprojCancelledError as exc:
        raise RuntimeError(
            "The download was stopped. The unfinished file is still here, "
            "so the next try can continue."
        ) from exc


def _download_mmproj(dest: Path, cancelled: Cancel | None = None) -> None:
    if dest.is_file() and _sha256(dest, cancelled=cancelled) == MMPROJ_SHA256:
        return
    dest.unlink(missing_ok=True)
    _require_space(dest.parent, MMPROJ_BYTES + 64 * 1024 * 1024)
    partial = dest.with_name(dest.name + ".partial")
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_byte_at = time.monotonic()
    timeout = httpx.Timeout(
        connect=_CONNECT_TIMEOUT_S,
        read=_READ_TIMEOUT_S,
        write=15.0,
        pool=15.0,
    )
    restarted_from_416 = False
    try:
        while True:
            if cancelled is not None and cancelled():
                raise _MmprojCancelledError()
            if time.monotonic() - last_byte_at >= _STALL_LIMIT_S:
                raise RuntimeError(_LATER)
            have = partial.stat().st_size if partial.is_file() else 0
            if have < 0:
                have = 0
            headers = {"User-Agent": f"arelis/{__version__}"}
            if have:
                headers["Range"] = f"bytes={have}-"
            try:
                with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                    with client.stream("GET", MMPROJ_URL, headers=headers) as response:
                        if (
                            response.status_code == 416
                            and have
                            and not restarted_from_416
                        ):
                            partial.unlink(missing_ok=True)
                            restarted_from_416 = True
                            continue
                        response.raise_for_status()
                        if have and response.status_code == 200:
                            have = 0
                        last_byte_at = _stream_into(
                            response,
                            partial,
                            have=have,
                            cancelled=cancelled,
                            last_byte_at=last_byte_at,
                        )
            except httpx.TimeoutException:
                if cancelled is not None and cancelled():
                    raise _MmprojCancelledError() from None
                continue
            break
    except RuntimeError:
        raise
    except httpx.TransportError as exc:
        raise RuntimeError(_OFFLINE) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(_LATER) from exc
    if _sha256(partial, cancelled=cancelled) != MMPROJ_SHA256:
        partial.unlink(missing_ok=True)
        raise RuntimeError(_MISMATCH)
    partial.replace(dest)


def _stream_into(
    response: httpx.Response,
    dest: Path,
    *,
    have: int = 0,
    cancelled: Cancel | None = None,
    last_byte_at: float = 0.0,
) -> float:
    total = have
    mode = "ab" if have else "wb"
    chunks = response.iter_bytes(_READ)
    with dest.open(mode) as handle:
        if have == 0:
            handle.truncate(0)
        while True:
            if cancelled is not None and cancelled():
                raise _MmprojCancelledError()
            try:
                chunk = next(chunks)
            except StopIteration:
                break
            total += len(chunk)
            if total > MMPROJ_BYTES:
                raise RuntimeError(_LATER)
            handle.write(chunk)
            last_byte_at = time.monotonic()
    if total != MMPROJ_BYTES:
        raise RuntimeError(_MISMATCH)
    return last_byte_at


def _sha256(path: Path, cancelled: Cancel | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            if cancelled is not None and cancelled():
                raise _MmprojCancelledError()
            digest.update(chunk)
    return digest.hexdigest()


def _require_space(folder: Path, need: int) -> None:
    probe = folder
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError as exc:
        raise RuntimeError(_DISK) from exc
    if free < need:
        raise RuntimeError(_DISK)
