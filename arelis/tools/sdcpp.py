"""Built-in stable-diffusion.cpp backend for FLUX.2 klein 4B.

The command line, flags, files and quant match the Atria bench of 2026-11-09
(sd.cpp Vulkan master-1079-a3c49b1, klein 4B Q4_0, Qwen3-4B encoder, flux2 VAE,
1024 px, 4 steps, CFG 1.0, euler, --offload-to-cpu --diffusion-fa --vae-tiling).
No extra content filter is applied. Downloads are digest-pinned and use the
same licence allowlist as other image weights. Partial files are deleted on
failure or cancel.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from arelis import __version__
from arelis.paths import ensure, models_dir
from arelis.tools.image_models import (
    ALLOW_ABOVE,
    DISK,
    LATER,
    MISMATCH,
    OFFLINE,
    UNLICENSED,
    ModelError,
    license_allowed,
    size_label,
)

log = logging.getLogger(__name__)

Cancel = Callable[[], bool]

# Live sd-cli handle, tracked the same way llama-server tracks _proc, so
# quit can stop a picture that is still running.
_proc_lock = threading.Lock()
_proc: Any = None

# Pinned Windows Vulkan release used on Atria. Digest comes from the GitHub
# release asset, not from a local hash of a re-download.
SDCPP_RELEASE = "master-1079-a3c49b1"
SDCPP_ZIP_URL = (
    "https://github.com/leejet/stable-diffusion.cpp/releases/download/"
    f"{SDCPP_RELEASE}/sd-master-a3c49b1-bin-win-vulkan-x64.zip"
)
SDCPP_ZIP_SHA256 = "60991b744e21add68625c27386e3a6dbcfc72929a3101880cb4863f5f1e6c013"
SDCPP_ZIP_BYTES = 30_001_283

# Smallest set that produced a picture on Atria (~4.9 GB, ~2 min / image).
KLEIN_Q4_URL = (
    "https://huggingface.co/leejet/FLUX.2-klein-4B-GGUF/resolve/main/"
    "flux-2-klein-4b-Q4_0.gguf"
)
KLEIN_Q4_SHA256 = "d1023499ef3f2f82ff7c50e6778495195c1b6cc34835741778868428111f9ff4"
KLEIN_Q4_BYTES = 2_460_378_560

LLM_URL = (
    "https://huggingface.co/unsloth/Qwen3-4B-GGUF/resolve/main/"
    "Qwen3-4B-Q4_K_M.gguf"
)
LLM_SHA256 = "f6f851777709861056efcdad3af01da38b31223a3ba26e61a4f8bf3a2195813a"
LLM_BYTES = 2_497_281_312

VAE_URL = (
    "https://huggingface.co/Comfy-Org/Flux-2-Klein-4B/resolve/main/"
    "split_files/vae/flux2-vae.safetensors"
)
VAE_SHA256 = "868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3"
VAE_BYTES = 336_211_292

_READ = 64 * 1024
_CHUNK = 1024 * 1024
_GENERATE_TIMEOUT_S = 15 * 60
_STALL_LIMIT_S = 90.0

NOT_WINDOWS = (
    "The built-in picture tool ships a Windows program. "
    "On this computer, set the image backend to ComfyUI in Settings "
    "if you already run ComfyUI."
)
NOT_YET = (
    "Image editing is not ready yet on the built-in picture tool. "
    "You can set the image backend to ComfyUI in Settings if you already run ComfyUI."
)
STOPPED = "The picture was stopped."
DOWNLOAD_STOPPED = "The picture download was stopped."
NO_IMAGE = "The picture program finished but did not write an image."
CRASHED = "The picture program stopped before it finished."
SLOW = "The picture program did not finish in time."


class DownloadCancelledError(Exception):
    """The person stopped a download. Partial files are deleted."""


class GenerationCancelledError(Exception):
    """The person stopped a picture while it was being made."""


@dataclass(frozen=True)
class FileSpec:
    """One digest-pinned download."""

    key: str
    filename: str
    url: str
    sha256: str
    nbytes: int
    license: str
    # "zip" is unpacked into bin/; anything else is stored as a single file.
    kind: str = "file"


FILES: tuple[FileSpec, ...] = (
    FileSpec(
        key="bin",
        filename="sd-master-a3c49b1-bin-win-vulkan-x64.zip",
        url=SDCPP_ZIP_URL,
        sha256=SDCPP_ZIP_SHA256,
        nbytes=SDCPP_ZIP_BYTES,
        license="MIT",
        kind="zip",
    ),
    FileSpec(
        key="model",
        filename="flux-2-klein-4b-Q4_0.gguf",
        url=KLEIN_Q4_URL,
        sha256=KLEIN_Q4_SHA256,
        nbytes=KLEIN_Q4_BYTES,
        license="Apache-2.0",
    ),
    FileSpec(
        key="llm",
        filename="Qwen3-4B-Q4_K_M.gguf",
        url=LLM_URL,
        sha256=LLM_SHA256,
        nbytes=LLM_BYTES,
        license="Apache-2.0",
    ),
    FileSpec(
        key="vae",
        filename="flux2-vae.safetensors",
        url=VAE_URL,
        sha256=VAE_SHA256,
        nbytes=VAE_BYTES,
        license="Apache-2.0",
    ),
)


def resolve_backend(value: str | None) -> str:
    """``sdcpp`` or ``comfy``. Empty and unknown values use the built-in tool."""
    raw = (value or "sdcpp").strip().lower().replace("_", "").replace("-", "")
    if raw in {"comfy", "comfyui"}:
        return "comfy"
    return "sdcpp"


def install_root(config: dict[str, Any] | None = None) -> Path:
    image = _image_cfg(config)
    sdcpp = image.get("sdcpp") if isinstance(image.get("sdcpp"), dict) else {}
    raw = str((sdcpp or {}).get("model_dir") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return models_dir() / "sdcpp"


def bin_dir(config: dict[str, Any] | None = None) -> Path:
    image = _image_cfg(config)
    sdcpp = image.get("sdcpp") if isinstance(image.get("sdcpp"), dict) else {}
    raw = str((sdcpp or {}).get("bin_dir") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return install_root(config) / "bin"


def _image_cfg(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    tools = config.get("tools") or {}
    if not isinstance(tools, dict):
        return {}
    image = tools.get("image") or {}
    return image if isinstance(image, dict) else {}


def sdcpp_cfg(config: dict[str, Any] | None) -> dict[str, Any]:
    image = _image_cfg(config)
    section = image.get("sdcpp") or {}
    return section if isinstance(section, dict) else {}


def file_path(spec: FileSpec, config: dict[str, Any] | None = None) -> Path:
    if spec.kind == "zip":
        return bin_dir(config) / spec.filename
    return install_root(config) / spec.filename


def find_binary(config: dict[str, Any] | None = None) -> Path | None:
    """The unpacked Windows CLI, if it is already on disk."""
    folder = bin_dir(config)
    names = ("sd-cli.exe", "sd.exe", "sd-cli", "sd")
    for name in names:
        candidate = folder / name
        if candidate.is_file():
            return candidate
    if folder.is_dir():
        for name in names:
            found = list(folder.rglob(name))
            for hit in found:
                if hit.is_file():
                    return hit
    return None


def file_is_ready(spec: FileSpec, config: dict[str, Any] | None = None) -> bool:
    if spec.kind == "zip":
        return find_binary(config) is not None
    path = file_path(spec, config)
    if not path.is_file():
        return False
    try:
        return path.stat().st_size == spec.nbytes
    except OSError:
        return False


def missing_files(config: dict[str, Any] | None = None) -> list[FileSpec]:
    return [spec for spec in FILES if not file_is_ready(spec, config)]


def pending_download_bytes(config: dict[str, Any] | None = None) -> int:
    return sum(spec.nbytes for spec in missing_files(config))


def _load_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    if config is not None:
        return config
    try:
        from arelis.config import load_config

        return load_config()
    except Exception:
        # Missing or unreadable config still uses the built-in default backend.
        return None


def download_needs_allow(config: dict[str, Any] | None = None) -> bool:
    """True when a first-use download over 50 MB is still needed."""
    cfg = _load_config(config)
    if resolve_backend(str(_image_cfg(cfg).get("backend") or "sdcpp")) != "sdcpp":
        return False
    return any(spec.nbytes > ALLOW_ABOVE for spec in missing_files(cfg))


def allow_headline(
    args: dict[str, Any] | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> str:
    del args
    cfg = _load_config(config)
    if not download_needs_allow(cfg):
        return ""
    return (
        f"download about {size_label(pending_download_bytes(cfg))}, "
        "then make a picture"
    )


def allow_detail(
    args: dict[str, Any] | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> str:
    del args
    cfg = _load_config(config)
    if not download_needs_allow(cfg):
        return ""
    return (
        f"This downloads about {size_label(pending_download_bytes(cfg))} "
        "of picture files (Apache-2.0) and a small program (MIT). "
        "You only do this once."
    )


def refuse_unlicensed(spec: FileSpec) -> None:
    if not license_allowed(spec.license):
        raise ModelError(UNLICENSED)


def check_licenses() -> list[FileSpec]:
    """Return any file whose licence is not on the allowlist. Do not widen it."""
    blocked: list[FileSpec] = []
    for spec in FILES:
        if not license_allowed(spec.license):
            blocked.append(spec)
    return blocked


def ensure_files(
    config: dict[str, Any] | None = None,
    *,
    cancelled: Cancel | None = None,
) -> dict[str, Path]:
    """Download any missing klein 4B files and the Windows Vulkan binary."""
    blocked = check_licenses()
    if blocked:
        names = ", ".join(spec.filename for spec in blocked)
        raise ModelError(
            f"{UNLICENSED} Not downloaded: {names}."
        )
    for spec in FILES:
        refuse_unlicensed(spec)
        if file_is_ready(spec, config):
            continue
        _fetch_spec(spec, config, cancelled=cancelled)
    binary = find_binary(config)
    if binary is None:
        raise ModelError(LATER)
    root = install_root(config)
    return {
        "binary": binary,
        "model": root / "flux-2-klein-4b-Q4_0.gguf",
        "llm": root / "Qwen3-4B-Q4_K_M.gguf",
        "vae": root / "flux2-vae.safetensors",
    }


def _fetch_spec(
    spec: FileSpec,
    config: dict[str, Any] | None,
    *,
    cancelled: Cancel | None,
) -> None:
    dest = file_path(spec, config)
    ensure(dest.parent)
    part = dest.with_name(dest.name + ".part")
    try:
        _download(spec.url, part, spec.nbytes, cancelled=cancelled)
        digest = _sha256(part, cancelled=cancelled)
        if digest != spec.sha256.strip().lower():
            raise ModelError(MISMATCH)
        if spec.kind == "zip":
            _extract_zip(part, bin_dir(config))
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
        else:
            os.replace(part, dest)
    except DownloadCancelledError:
        _cleanup_partial(part, dest)
        raise ModelError(DOWNLOAD_STOPPED) from None
    except Exception:
        _cleanup_partial(part, dest)
        raise
    finally:
        part.unlink(missing_ok=True)


def _cleanup_partial(part: Path, dest: Path) -> None:
    part.unlink(missing_ok=True)
    # A half-replaced dest should not be kept either.
    if dest.is_file():
        try:
            if dest.suffix == ".zip":
                dest.unlink(missing_ok=True)
        except OSError:
            pass


def _download(
    url: str,
    dest: Path,
    nbytes: int,
    *,
    cancelled: Cancel | None = None,
) -> None:
    if not url.startswith("https://"):
        raise ModelError(LATER)
    _require_space(dest.parent, nbytes + 32 * 1024 * 1024)
    if cancelled is not None and cancelled():
        raise DownloadCancelledError()
    headers = {"User-Agent": f"arelis/{__version__}"}
    timeout = httpx.Timeout(120.0, connect=15.0)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                _stream_into(response, dest, nbytes, cancelled=cancelled)
    except DownloadCancelledError:
        dest.unlink(missing_ok=True)
        raise
    except ModelError:
        dest.unlink(missing_ok=True)
        raise
    except httpx.TransportError as exc:
        dest.unlink(missing_ok=True)
        raise ModelError(OFFLINE) from exc
    except httpx.HTTPError as exc:
        dest.unlink(missing_ok=True)
        raise ModelError(LATER) from exc


def _stream_into(
    response: httpx.Response,
    dest: Path,
    nbytes: int,
    *,
    cancelled: Cancel | None = None,
) -> None:
    total = 0
    last = time.monotonic()
    with dest.open("wb") as handle:
        handle.truncate(0)
        for chunk in response.iter_bytes(_READ):
            if cancelled is not None and cancelled():
                raise DownloadCancelledError()
            if not chunk:
                if time.monotonic() - last > _STALL_LIMIT_S:
                    raise ModelError(LATER)
                continue
            total += len(chunk)
            if total > nbytes:
                raise ModelError(LATER)
            handle.write(chunk)
            last = time.monotonic()
    if total != nbytes:
        raise ModelError(MISMATCH)


def _sha256(path: Path, cancelled: Cancel | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            if cancelled is not None and cancelled():
                raise DownloadCancelledError()
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
        raise ModelError(DISK) from exc
    if free < need:
        raise ModelError(DISK)


def _extract_zip(archive_path: Path, folder: Path) -> None:
    ensure(folder)
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise ModelError(LATER) from exc
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            rel = Path(info.filename)
            if rel.is_absolute() or ".." in rel.parts:
                raise ModelError(LATER)
            dest = folder.joinpath(*rel.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            try:
                tmp.write_bytes(archive.read(info))
                os.replace(tmp, dest)
            finally:
                tmp.unlink(missing_ok=True)


def default_size(config: dict[str, Any] | None = None) -> tuple[int, int]:
    section = sdcpp_cfg(config)
    width = _positive_int(section.get("width"), 1024)
    height = _positive_int(section.get("height"), 1024)
    return width, height


def build_command(
    *,
    binary: Path | str,
    model: Path | str,
    llm: Path | str,
    vae: Path | str,
    prompt_file: Path | str,
    output: Path | str,
    width: int = 1024,
    height: int = 1024,
    steps: int = 4,
    cfg: float = 1.0,
    sampler: str = "euler",
    seed: int = 42,
    offload_to_cpu: bool = True,
    diffusion_fa: bool = True,
    vae_tiling: bool = True,
) -> list[str]:
    """Argv proven on Atria for klein 4B. Flags follow the bench script."""
    args = [
        str(binary),
        "--diffusion-model",
        str(model),
        "--llm",
        str(llm),
        "--vae",
        str(vae),
        "--prompt-file",
        str(prompt_file),
        "--cfg-scale",
        str(cfg),
        "--steps",
        str(int(steps)),
        "--sampling-method",
        (sampler or "euler").strip() or "euler",
        "-W",
        str(int(width)),
        "-H",
        str(int(height)),
        "--seed",
        str(int(seed)),
    ]
    if offload_to_cpu:
        args.append("--offload-to-cpu")
    if diffusion_fa:
        args.append("--diffusion-fa")
    if vae_tiling:
        args.append("--vae-tiling")
    args.extend(["-v", "-o", str(output)])
    return args


def command_from_config(
    config: dict[str, Any] | None,
    *,
    binary: Path | str,
    model: Path | str,
    llm: Path | str,
    vae: Path | str,
    prompt_file: Path | str,
    output: Path | str,
    width: int | None = None,
    height: int | None = None,
    steps: int | None = None,
    cfg: float | None = None,
    sampler: str | None = None,
    seed: int = 42,
) -> list[str]:
    section = sdcpp_cfg(config)
    size_w, size_h = default_size(config)
    return build_command(
        binary=binary,
        model=model,
        llm=llm,
        vae=vae,
        prompt_file=prompt_file,
        output=output,
        width=size_w if width is None else int(width),
        height=size_h if height is None else int(height),
        steps=_positive_int(steps, _positive_int(section.get("steps"), 4)),
        cfg=_positive_float(cfg, _positive_float(section.get("cfg"), 1.0)),
        sampler=(
            sampler
            if sampler is not None
            else str(section.get("sampler") or "euler")
        ),
        seed=int(seed),
        offload_to_cpu=_flag(section.get("offload_to_cpu"), True),
        diffusion_fa=_flag(section.get("diffusion_fa"), True),
        vae_tiling=_flag(section.get("vae_tiling"), True),
    )


def run_cli(
    args: list[str],
    output: Path,
    *,
    cancelled: Cancel | None = None,
    timeout_s: float = _GENERATE_TIMEOUT_S,
    cwd: Path | None = None,
) -> None:
    """Run sd-cli and require a non-empty PNG. Tests should mock this."""
    if cancelled is not None and cancelled():
        raise GenerationCancelledError()
    proc = _spawn(args, cwd=cwd)
    deadline = time.monotonic() + max(1.0, float(timeout_s))
    try:
        while True:
            if cancelled is not None and cancelled():
                _stop_proc(proc)
                raise GenerationCancelledError()
            code = proc.poll()
            if code is not None:
                if code != 0:
                    raise RuntimeError(CRASHED)
                break
            if time.monotonic() >= deadline:
                _stop_proc(proc)
                raise RuntimeError(SLOW)
            time.sleep(0.2)
    except GenerationCancelledError:
        raise
    except Exception:
        _stop_proc(proc)
        raise
    finally:
        if proc.poll() is not None:
            _forget_proc(proc)
    if not output.is_file() or output.stat().st_size <= 1024:
        raise RuntimeError(NO_IMAGE)


def _spawn(args: list[str], *, cwd: Path | None = None) -> subprocess.Popen[bytes]:
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.STDOUT,
    }
    if cwd is not None:
        kwargs["cwd"] = str(cwd)
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
    log.info("Starting sd.cpp")
    try:
        proc = subprocess.Popen(args, **kwargs)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "The picture program was not found, so no picture was made."
        ) from exc
    else:
        _remember_proc(proc)
        return proc
    finally:
        if handle is not None:
            handle.close()


def stop_cli(*, timeout_s: float = 8.0) -> None:
    """Stop the live sd-cli process, if any. Used on quit and cancel."""
    global _proc
    with _proc_lock:
        proc = _proc
        _proc = None
    if proc is None:
        return
    _stop_proc(proc, timeout_s=timeout_s)


def _remember_proc(proc: subprocess.Popen[bytes]) -> None:
    global _proc
    with _proc_lock:
        _proc = proc


def _forget_proc(proc: object) -> None:
    global _proc
    with _proc_lock:
        if _proc is proc:
            _proc = None


def attach_proc_for_tests(proc: object | None) -> None:
    """Install or clear a stand-in sd-cli handle. Tests only."""
    global _proc
    with _proc_lock:
        _proc = proc


def reset_for_tests() -> None:
    attach_proc_for_tests(None)


def _stop_proc(proc: Any, *, timeout_s: float = 8.0) -> None:
    try:
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=max(0.2, float(timeout_s)))
            except subprocess.TimeoutExpired:
                _kill_group(proc)
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    log.warning(
                        "sd.cpp pid %s did not exit after kill",
                        getattr(proc, "pid", "?"),
                    )
            except Exception:
                log.warning(
                    "Could not terminate sd.cpp pid %s; killing the group",
                    getattr(proc, "pid", "?"),
                    exc_info=True,
                )
                _kill_group(proc)
        if sys.platform == "win32" and isinstance(proc, subprocess.Popen):
            # The child starts in a new group, so terminate can leave
            # helpers running after the parent has already exited.
            _kill_group(proc)
    except Exception:
        log.warning(
            "Could not stop sd.cpp pid %s", getattr(proc, "pid", "?"), exc_info=True
        )
    finally:
        _forget_proc(proc)


def _kill_group(proc: Any) -> None:
    """Kill sd-cli and its group. The process is started in a new session."""
    if sys.platform == "win32":
        pid = getattr(proc, "pid", None)
        if isinstance(proc, subprocess.Popen) and pid:
            try:
                flags = 0
                if hasattr(subprocess, "CREATE_NO_WINDOW"):
                    flags = int(subprocess.CREATE_NO_WINDOW)
                subprocess.run(
                    ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                    capture_output=True,
                    timeout=10,
                    check=False,
                    creationflags=flags,
                )
            except Exception:
                log.warning("Could not taskkill sd.cpp pid %s", pid, exc_info=True)
            return
        try:
            proc.kill()
        except Exception:
            log.warning(
                "Could not kill sd.cpp pid %s",
                getattr(proc, "pid", "?"),
                exc_info=True,
            )
        return
    pid = getattr(proc, "pid", None)
    if isinstance(proc, subprocess.Popen) and pid:
        try:
            pgid = os.getpgid(int(pid))
        except OSError:
            pgid = None
        # killpg of our own group would take down the caller, including a
        # test worker. start_new_session makes the child its own leader.
        if pgid and pgid == int(pid) and pgid != os.getpgrp():
            try:
                os.killpg(pgid, signal.SIGKILL)
                return
            except (ProcessLookupError, PermissionError, OSError):
                pass
    try:
        proc.kill()
    except Exception:
        log.warning(
            "Could not kill sd.cpp pid %s",
            getattr(proc, "pid", "?"),
            exc_info=True,
        )


def _log_path() -> Path | None:
    try:
        from arelis.paths import ensure as ensure_dir
        from arelis.paths import logs_dir

        return ensure_dir(logs_dir()) / "sdcpp.log"
    except OSError:
        return None


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _flag(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}
