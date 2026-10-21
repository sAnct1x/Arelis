"""Launch line for the 35B llama-server.

Config C at ncmoe 32, measured 2026-10-20. Q8 mmproj, flash attention off,
1024 image tokens, f16 KV, context 32768, batch 4096, ubatch 2048. The
patched template stays: ``--jinja``, and ``qwen36_35b_insys.jinja`` beside
the weights when that file is already there.

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
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __version__
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
_CACHE_DEPTH = 5

_OFFLINE = (
    "I could not download the picture file for the 35B. Connect and try again."
)
_MISMATCH = (
    "The picture file for the 35B did not match, so I deleted it and stopped."
)
_DISK = "This computer does not have enough free space for the picture file."
_LATER = (
    "I could not download the picture file for the 35B. Try again in a little while."
)
_MISSING_BINARY = "llama-server was not found, so the 35B did not start."
_SLOW = "The 35B server did not finish starting. Try again in a little while."

_lock = threading.Lock()
_proc: subprocess.Popen[bytes] | None = None


def mmproj_for(model: Path) -> Path:
    """Q8 projector next to the model GGUF. Same directory, no second store."""
    return model.parent / MMPROJ_FILENAME


def llama_server_args(
    *,
    binary: str,
    model: str,
    mmproj: str,
    template: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> list[str]:
    """Argv for the 35B server. This is the only place those flags are built."""
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
        "32768",
        "-np",
        "1",
        "--n-cpu-moe",
        "32",
        "-ub",
        "2048",
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
    args.extend(["--host", host, "--port", str(port)])
    return args


def launch_args_for(config: dict[str, Any] | None) -> list[str] | None:
    """Args for the configured 35B, or None when the weights are not on disk."""
    try:
        return _launch_args_for(config or {})
    except OSError as exc:
        log.warning("Could not build llama-server args: %s", exc)
        return None


def ensure_server(base_url: str, args: list[str] | None) -> None:
    """Start llama-server when the chat port is down. Leave a live one alone."""
    if not args:
        return
    with _lock:
        if _health_ok(base_url):
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
        if not _wait_health(base_url, proc, _HEALTH_WAIT_S):
            raise RuntimeError(_SLOW)


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
    )


def locate_model_gguf(config: dict[str, Any]) -> Path | None:
    """The UD-Q4_K_M file, from config or the same folders other weights use.

    A bare file name is looked up beside the other weights. A full path that
    is not on disk stays missing: no server, no exception.
    """
    lc = config.get("llamacpp") or {}
    explicit = str(lc.get("model") or "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            return path
        if path.parent == Path("."):
            return _find_weight(path.name)
        return None
    return _find_weight(MODEL_FILENAME)


def _find_weight(name: str) -> Path | None:
    """One file name in the model folder, its llm subfolder, or the cache."""
    from arelis.paths import models_dir

    folder = models_dir()
    for candidate in (folder / name, folder / "llm" / name):
        if candidate.is_file():
            return candidate
    for root in _cache_roots():
        found = _find_named(root, name)
        if found is not None:
            return found
    return None


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


def _wait_health(base_url: str, proc: subprocess.Popen[bytes], timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        if _health_ok(base_url):
            return True
        time.sleep(0.5)
    return _health_ok(base_url)


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
        kwargs["creationflags"] = no_window | new_group
    else:
        kwargs["start_new_session"] = True
    log.info("Starting llama-server")
    try:
        return subprocess.Popen(args, **kwargs)
    except FileNotFoundError as exc:
        raise RuntimeError(_MISSING_BINARY) from exc
    finally:
        if handle is not None:
            handle.close()


def _ensure_mmproj(dest: Path) -> None:
    if dest.is_file() and _sha256(dest) == MMPROJ_SHA256:
        return
    dest.unlink(missing_ok=True)
    _require_space(dest.parent, MMPROJ_BYTES + 64 * 1024 * 1024)
    partial = dest.with_name(dest.name + ".partial")
    partial.unlink(missing_ok=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": f"arelis/{__version__}"}
    timeout = httpx.Timeout(600.0, connect=15.0)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", MMPROJ_URL, headers=headers) as response:
                response.raise_for_status()
                _stream_into(response, partial)
    except RuntimeError:
        partial.unlink(missing_ok=True)
        raise
    except httpx.TransportError as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeError(_OFFLINE) from exc
    except httpx.HTTPError as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeError(_LATER) from exc
    if _sha256(partial) != MMPROJ_SHA256:
        partial.unlink(missing_ok=True)
        raise RuntimeError(_MISMATCH)
    partial.replace(dest)


def _stream_into(response: httpx.Response, dest: Path) -> None:
    total = 0
    with dest.open("wb") as handle:
        for chunk in response.iter_bytes(1024 * 1024):
            total += len(chunk)
            if total > MMPROJ_BYTES:
                raise RuntimeError(_LATER)
            handle.write(chunk)
    if total != MMPROJ_BYTES:
        raise RuntimeError(_MISMATCH)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
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
