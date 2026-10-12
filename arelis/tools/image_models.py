"""Image weights, downloaded on first use and run on the CPU.

The chat model keeps the GPU. These sessions use CPUExecutionProvider,
turn the memory arena off, and are dropped after a minute of idle so a
cutout does not sit on the RAM the rest of the turn needs.

Anything over 50 MB is named on the Allow card before the download starts.
A file that does not match its pinned digest is deleted. Non-commercial
weights are refused unless the caller explicitly opts in. None of the
models registered here need that.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from arelis import __version__
from arelis.paths import ensure, models_dir

ALLOW_ABOVE = 50 * 1024 * 1024
IDLE_S = 60.0
_GB = 1024**3

OFFLINE = (
    "I could not download that because this computer is offline. "
    "Connect and try again."
)
MISMATCH = "That download did not match, so I deleted it and stopped."
DISK = (
    "This computer does not have enough free space for that download. "
    "Free some space and try again."
)
LATER = "I could not download that. Try again in a little while."
UNLICENSED = "That model is not licensed for this, so I did not download it."
_RUNTIME = (
    "This needs onnxruntime, which should already be installed. "
    "Reinstall Arelis and try again."
)

_ALLOWED_LICENSES = frozenset(
    {"apache-2.0", "mit", "bsd-3", "bsd-3-clause", "bsd"}
)
_MATTING = ("isnet-general-use", "birefnet-general-lite", "u2netp")
_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)

_lock = threading.Lock()
_sessions: dict[str, tuple[Any, float]] = {}


class ModelError(Exception):
    """A sentence a person can read. No paths and no download details."""


@dataclass(frozen=True)
class ModelSpec:
    name: str
    version: str
    url: str
    sha256: str
    nbytes: int
    license: str
    input_size: tuple[int, int]
    filename: str
    mean: tuple[float, float, float] = (0.0, 0.0, 0.0)
    std: tuple[float, float, float] = (1.0, 1.0, 1.0)
    sigmoid: bool = False
    archive: bool = False

    @property
    def bytes(self) -> int:
        return self.nbytes


# Pinned to the release asset. A changed file is refused.
MODELS: dict[str, ModelSpec] = {
    "isnet-general-use": ModelSpec(
        name="isnet-general-use",
        version="v0.0.0",
        url=(
            "https://github.com/danielgatis/rembg/releases/download/"
            "v0.0.0/isnet-general-use.onnx"
        ),
        sha256="60920e99c45464f2ba57bee2ad08c919a52bbf852739e96947fbb4358c0d964a",
        nbytes=178_648_008,
        license="Apache-2.0",
        input_size=(1024, 1024),
        filename="isnet-general-use.onnx",
        mean=(0.5, 0.5, 0.5),
        std=(1.0, 1.0, 1.0),
    ),
    "birefnet-general-lite": ModelSpec(
        name="birefnet-general-lite",
        version="v0.0.0",
        url=(
            "https://github.com/danielgatis/rembg/releases/download/"
            "v0.0.0/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx"
        ),
        sha256="5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333",
        nbytes=224_005_088,
        license="MIT",
        input_size=(1024, 1024),
        filename="birefnet-general-lite.onnx",
        mean=_IMAGENET_MEAN,
        std=_IMAGENET_STD,
        sigmoid=True,
    ),
    "u2netp": ModelSpec(
        name="u2netp",
        version="v0.0.0",
        url=(
            "https://github.com/danielgatis/rembg/releases/download/"
            "v0.0.0/u2netp.onnx"
        ),
        sha256="309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8",
        nbytes=4_574_861,
        license="Apache-2.0",
        input_size=(320, 320),
        filename="u2netp.onnx",
        mean=_IMAGENET_MEAN,
        std=_IMAGENET_STD,
    ),
    "realesrgan-x4v3": ModelSpec(
        name="realesrgan-x4v3",
        version="v0.64.0",
        url=(
            "https://qaihub-public-assets.s3.us-west-2.amazonaws.com/"
            "qai-hub-models/models/real_esrgan_general_x4v3/releases/"
            "v0.64.0/real_esrgan_general_x4v3-onnx-float.zip"
        ),
        sha256="fc094329b24a00c936ebc1cc4c51bc59633e7dc36f4a553344342171cbd3c7cf",
        nbytes=4_540_895,
        license="BSD-3",
        input_size=(128, 128),
        filename="real_esrgan_general_x4v3.onnx",
        archive=True,
    ),
}


def license_allowed(license_name: str, *, opt_in: bool = False) -> bool:
    text = (license_name or "").strip().lower().replace("_", "-")
    if (
        "non-commercial" in text
        or "noncommercial" in text
        or text.endswith("-nc")
        or "/nc" in text
    ):
        return bool(opt_in)
    return text in _ALLOWED_LICENSES


def size_label(nbytes: int) -> str:
    mb = nbytes / 1_000_000
    if mb >= 10:
        return f"{round(mb)} MB"
    return f"{mb:.1f} MB"


def intra_threads() -> int:
    cores = os.cpu_count() or 2
    return max(2, cores // 2)


def total_ram_bytes() -> int:
    if sys.platform == "win32":
        import ctypes

        class _MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatus()
        status.dwLength = ctypes.sizeof(_MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys)
        return 0
    try:
        return int(os.sysconf("SC_PHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, ValueError):
        return 0


def matting_model_name(setting: str, ram_bytes: int) -> str:
    name = (setting or "auto").strip().lower()
    if name in {"", "auto"}:
        if ram_bytes >= 32 * _GB:
            return "birefnet-general-lite"
        return "isnet-general-use"
    if name not in _MATTING:
        raise ModelError("I do not know that background model.")
    return name


def install_dir(spec: ModelSpec) -> Path:
    return models_dir() / "images" / f"{spec.name}-{spec.version}"


def model_file(spec: ModelSpec) -> Path:
    root = install_dir(spec)
    if not spec.archive:
        return root / spec.filename
    found = [
        path
        for path in root.rglob(spec.filename)
        if path.is_file() and not path.name.endswith(".part")
    ]
    if found:
        return found[0]
    return root / "real_esrgan_general_x4v3-onnx-float" / spec.filename


def model_is_ready(spec: ModelSpec) -> bool:
    path = model_file(spec)
    if not path.is_file():
        return False
    if spec.archive and not path.with_suffix(".data").is_file():
        return False
    return _registry_matches(install_dir(spec) / "registry.json", spec)


def accept_download(path: Path, expected: str) -> None:
    """Keep the file only when its digest matches. Otherwise delete it."""
    if _sha256(path) != expected.strip().lower():
        path.unlink(missing_ok=True)
        raise ModelError(MISMATCH)


def ensure_model(name: str, *, opt_in: bool = False) -> Path:
    """Return the weights, downloading them the first time."""
    try:
        spec = MODELS[name]
    except KeyError as exc:
        raise ModelError("I do not know that model.") from exc
    _refuse_license(spec, opt_in=opt_in)
    if model_is_ready(spec):
        return model_file(spec)
    root = ensure(install_dir(spec))
    part = root / f"{spec.filename}.part"
    try:
        _download(spec.url, part, spec.nbytes)
        accept_download(part, spec.sha256)
        blob = part.read_bytes()
        return install_bytes(spec, blob, models_dir(), opt_in=opt_in)
    finally:
        part.unlink(missing_ok=True)


def install_bytes(
    spec: ModelSpec,
    blob: bytes,
    models_root: Path,
    *,
    opt_in: bool = False,
) -> Path:
    """Hash, unpack, and record one download. Refuses a bad license first."""
    _refuse_license(spec, opt_in=opt_in)
    digest = hashlib.sha256(blob).hexdigest()
    if digest != spec.sha256.strip().lower():
        raise ModelError(MISMATCH)
    folder = Path(models_root) / "images" / f"{spec.name}-{spec.version}"
    folder.mkdir(parents=True, exist_ok=True)
    if spec.archive:
        _extract_zip(blob, folder)
        found = [
            path
            for path in folder.rglob(spec.filename)
            if path.is_file() and not path.name.endswith(".part")
        ]
        if not found:
            raise ModelError(LATER)
        dest = found[0]
    else:
        dest = folder / spec.filename
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(blob)
        os.replace(tmp, dest)
    _write_registry(folder / "registry.json", spec)
    return dest


def open_cpu_session(path: Path) -> Any:
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise ModelError(_RUNTIME) from exc
    options = ort.SessionOptions()
    options.intra_op_num_threads = intra_threads()
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    return ort.InferenceSession(
        str(path),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )


def session_for(name: str) -> Any:
    """A live CPU session, created on first use and dropped after idle."""
    drop_idle()
    with _lock:
        hit = _sessions.get(name)
        if hit is not None:
            session, _used = hit
            _sessions[name] = (session, time.monotonic())
            return session
    path = ensure_model(name)
    session = open_cpu_session(path)
    with _lock:
        current = _sessions.get(name)
        if current is not None:
            return current[0]
        _sessions[name] = (session, time.monotonic())
    return session


def drop_idle(now: float | None = None) -> None:
    moment = time.monotonic() if now is None else now
    with _lock:
        stale = [
            name
            for name, (_session, used) in _sessions.items()
            if moment - used >= IDLE_S
        ]
        for name in stale:
            _sessions.pop(name, None)


def download_needs_allow(args: dict[str, Any] | None) -> bool:
    """True when this call would fetch more than 50 MB."""
    spec = _matting_spec(args or {})
    if spec is None or spec.nbytes <= ALLOW_ABOVE:
        return False
    return not model_is_ready(spec)


def allow_headline(args: dict[str, Any] | None) -> str:
    if not download_needs_allow(args):
        return ""
    spec = _matting_spec(args or {})
    if spec is None:
        return ""
    return f"download {size_label(spec.nbytes)}, then cut out the background"


def allow_detail(args: dict[str, Any] | None) -> str:
    if not download_needs_allow(args):
        return ""
    spec = _matting_spec(args or {})
    if spec is None:
        return ""
    return (
        f"This downloads about {size_label(spec.nbytes)} ({spec.license}) "
        "before cutting out the background."
    )


def _matting_spec(args: dict[str, Any]) -> ModelSpec | None:
    if not _truthy(args.get("remove_background")):
        return None
    from arelis.config import load_config

    tools = load_config().get("tools") or {}
    edit = tools.get("image_edit") or {}
    setting = str(edit.get("matting_model") or "auto")
    return MODELS[matting_model_name(setting, total_ram_bytes())]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _refuse_license(spec: ModelSpec, *, opt_in: bool) -> None:
    if not license_allowed(spec.license, opt_in=opt_in):
        raise ModelError(UNLICENSED)


def _registry_matches(path: Path, spec: ModelSpec) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    return (
        str(payload.get("sha256") or "").lower() == spec.sha256.lower()
        and str(payload.get("license") or "") == spec.license
        and str(payload.get("version") or "") == spec.version
    )


def _write_registry(path: Path, spec: ModelSpec) -> None:
    payload = {
        "name": spec.name,
        "version": spec.version,
        "license": spec.license,
        "source": spec.url,
        "sha256": spec.sha256,
        "bytes": spec.nbytes,
    }
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, dest: Path, nbytes: int) -> None:
    if not url.startswith("https://"):
        raise ModelError(LATER)
    ensure(dest.parent)
    _require_space(dest.parent, nbytes + 32 * 1024 * 1024)
    headers = {"User-Agent": f"arelis/{__version__}"}
    existing = dest.stat().st_size if dest.is_file() else 0
    if existing:
        headers["Range"] = f"bytes={existing}-"
    timeout = httpx.Timeout(120.0, connect=15.0)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", url, headers=headers) as response:
                if response.status_code == 416 and existing:
                    return
                if response.status_code == 206 and existing:
                    mode = "ab"
                elif response.status_code == 200:
                    if existing:
                        dest.unlink()
                    mode = "wb"
                else:
                    response.raise_for_status()
                    mode = "wb"
                _stream_into(response, dest, mode, nbytes)
    except ModelError:
        dest.unlink(missing_ok=True)
        raise
    except httpx.TransportError as exc:
        dest.unlink(missing_ok=True)
        raise ModelError(OFFLINE) from exc
    except httpx.HTTPError as exc:
        dest.unlink(missing_ok=True)
        raise ModelError(LATER) from exc


def _stream_into(response: httpx.Response, dest: Path, mode: str, nbytes: int) -> None:
    total = dest.stat().st_size if mode == "ab" and dest.is_file() else 0
    with dest.open(mode) as handle:
        for chunk in response.iter_bytes(1024 * 1024):
            total += len(chunk)
            if total > nbytes:
                raise ModelError(LATER)
            handle.write(chunk)


def _require_space(folder: Path, need: int) -> None:
    probe = folder
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    if shutil.disk_usage(probe).free < need:
        raise ModelError(DISK)


def _extract_zip(blob: bytes, folder: Path) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise ModelError(LATER) from exc
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            rel = PurePosixPath(info.filename)
            if rel.is_absolute() or ".." in rel.parts:
                raise ModelError(LATER)
            dest = folder.joinpath(*rel.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            tmp.write_bytes(archive.read(info))
            os.replace(tmp, dest)
