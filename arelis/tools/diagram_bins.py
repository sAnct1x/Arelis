"""Fetch the flowchart helper the first time a diagram needs it.

The helper is a small MIT binary, not a Python dependency, so it is not in
the installer. It lands under the models folder, next to other weights, and
only after its download matches the pin for this release. A mismatch deletes
the file. Nothing here starts a shell: the bytes are unpacked in process.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

import httpx

from arelis import __version__
from arelis.paths import ensure, models_dir

VERSION = "0.3.1"
LICENSE = "MIT"
_RELEASE = (
    "https://github.com/1jehuang/mermaid-rs-renderer/releases/download/v0.3.1"
)

# Digests of the v0.3.1 release assets. The arm64 ones were read from that
# release (the asset bytes), same as the x86_64 pins. A changed file is refused.
ASSETS: dict[str, tuple[str, str]] = {
    "win_amd64": (
        "mmdr-x86_64-pc-windows-msvc.zip",
        "11df20c6a2b22c6dad95a8f0176c5530d4dc9de36ef289653ee9fea13027b14c",
    ),
    "win_arm64": (
        "mmdr-aarch64-pc-windows-msvc.zip",
        "965192bcb95912d22c6d2e7b74db82930949eefbf25c064076353bafa566ac07",
    ),
    "linux_x86_64": (
        "mmdr-x86_64-unknown-linux-gnu.tar.gz",
        "e1da47b758769bff21b82a480fad640a3b893a90fc0dc321551486f8b50c7200",
    ),
    "linux_arm64": (
        "mmdr-aarch64-unknown-linux-gnu.tar.gz",
        "a74a121a2dd3bc8d30c17c954b3a036e7467a53b21532e889601a26cc6dc39d9",
    ),
    "mac_x86_64": (
        "mmdr-x86_64-apple-darwin.tar.gz",
        "ad035258822b60ee6bb3c086c3c7325dafe314bfab16a3bb99d692c18fad59cd",
    ),
    "mac_arm64": (
        "mmdr-aarch64-apple-darwin.tar.gz",
        "562d0250cb8588adefe398a23e4bbdf67f242849ea8d888c38268bcc3edf3223",
    ),
}

OFFLINE = (
    "I could not draw that diagram because this computer is offline. "
    "Connect and try again."
)
MISMATCH = "That download did not match, so I deleted it and stopped."
_DISK = (
    "This computer does not have enough free space for that diagram. "
    "Free some space and try again."
)
_TOO_BIG = "That download is larger than expected, so I stopped."
_UNAVAILABLE = "I cannot draw that kind of diagram on this computer."
_BROKEN = "I could not prepare the diagram helper, so I stopped."
_LATER = "I could not download what I need to draw that. Try again in a little while."

# The zip is about 4 MB and the program about 9 MB. Ask for room before starting.
_NEED_FREE = 20 * 1024 * 1024
_UNPACK = 12 * 1024 * 1024
# Anything over this would need a person to allow it first. This helper is smaller.
_MAX_BYTES = 50 * 1024 * 1024
_BINARY_NAMES = frozenset({"mmdr", "mmdr.exe"})


class HelperError(Exception):
    """A sentence a person can read. No paths and no download details."""


def install_dir() -> Path:
    return models_dir() / "images" / f"mmdr-{VERSION}"


def platform_key() -> str:
    machine = platform.machine().lower()
    arm = machine in {"arm64", "aarch64", "arm64e"}
    if sys.platform == "win32":
        return "win_arm64" if arm else "win_amd64"
    if sys.platform == "darwin":
        return "mac_arm64" if arm else "mac_x86_64"
    if machine in {"x86_64", "amd64"}:
        return "linux_x86_64"
    if arm:
        return "linux_arm64"
    raise HelperError(_UNAVAILABLE)


def pinned_asset() -> tuple[str, str]:
    try:
        return ASSETS[platform_key()]
    except KeyError as exc:
        raise HelperError(_UNAVAILABLE) from exc


def binary_path() -> Path:
    name = "mmdr.exe" if sys.platform == "win32" else "mmdr"
    return install_dir() / name


def ensure_binary() -> Path:
    """Return the helper, downloading it the first time."""
    asset, digest = pinned_asset()
    root = ensure(install_dir())
    binary = binary_path()
    registry = root / "registry.json"
    if binary.is_file() and _registry_matches(registry, digest):
        return binary
    binary.unlink(missing_ok=True)
    url = f"{_RELEASE}/{asset}"
    archive = root / f"{asset}.part"
    try:
        _download(url, archive)
        accept_download(archive, digest)
        _extract(archive, asset, binary)
    except HelperError:
        archive.unlink(missing_ok=True)
        binary.unlink(missing_ok=True)
        raise
    archive.unlink(missing_ok=True)
    _write_registry(registry, url, digest)
    return binary


def accept_download(path: Path, expected: str) -> None:
    """Keep the file only when its digest matches. Otherwise delete it."""
    got = _sha256(path)
    if got != expected.strip().lower():
        path.unlink(missing_ok=True)
        raise HelperError(MISMATCH)


def _registry_matches(path: Path, digest: str) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        str(payload.get("sha256") or "").lower() == digest.lower()
        and str(payload.get("license") or "") == LICENSE
        and str(payload.get("version") or "") == VERSION
    )


def _write_registry(path: Path, source: str, digest: str) -> None:
    payload = {
        "name": "mmdr",
        "version": VERSION,
        "license": LICENSE,
        "source": source,
        "sha256": digest,
    }
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _download(url: str, dest: Path) -> None:
    if not url.startswith("https://"):
        raise HelperError(_LATER)
    _require_space(dest.parent, _NEED_FREE)
    headers = {"User-Agent": f"arelis/{__version__}"}
    existing = dest.stat().st_size if dest.is_file() else 0
    if existing:
        headers["Range"] = f"bytes={existing}-"
    timeout = httpx.Timeout(60.0, connect=15.0)
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
                _stream_into(response, dest, mode)
    except HelperError:
        dest.unlink(missing_ok=True)
        raise
    except httpx.HTTPError as exc:
        dest.unlink(missing_ok=True)
        if isinstance(exc, httpx.TransportError):
            raise HelperError(OFFLINE) from exc
        raise HelperError(_LATER) from exc


def _stream_into(response: httpx.Response, dest: Path, mode: str) -> None:
    total = dest.stat().st_size if mode == "ab" and dest.is_file() else 0
    length = response.headers.get("content-length")
    if length:
        try:
            incoming = int(length)
        except ValueError:
            incoming = 0
        if incoming and total + incoming > _MAX_BYTES:
            raise HelperError(_TOO_BIG)
        if incoming:
            _require_space(dest.parent, incoming + _UNPACK)
    with dest.open(mode) as handle:
        for chunk in response.iter_bytes(64 * 1024):
            total += len(chunk)
            if total > _MAX_BYTES:
                raise HelperError(_TOO_BIG)
            handle.write(chunk)


def _require_space(folder: Path, need: int) -> None:
    probe = folder
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    if shutil.disk_usage(probe).free < need:
        raise HelperError(_DISK)


def _extract(archive: Path, asset: str, binary: Path) -> None:
    data = _read_member(archive, asset)
    if not data:
        raise HelperError(_BROKEN)
    tmp = binary.with_name(binary.name + ".part")
    tmp.write_bytes(data)
    if sys.platform != "win32":
        tmp.chmod(0o755)
    os.replace(tmp, binary)


def _read_member(archive: Path, asset: str) -> bytes:
    if asset.endswith(".zip"):
        return _read_zip(archive)
    if asset.endswith(".tar.gz"):
        return _read_tar(archive)
    return b""


def _leaf_ok(name: str) -> bool:
    path = PurePosixPath(name)
    if ".." in path.parts:
        return False
    return path.name in _BINARY_NAMES


def _read_zip(archive: Path) -> bytes:
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if info.is_dir() or not _leaf_ok(info.filename):
                continue
            return bundle.read(info)
    return b""


def _read_tar(archive: Path) -> bytes:
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            if not member.isfile() or member.issym() or member.islnk():
                continue
            if not _leaf_ok(member.name):
                continue
            extracted = bundle.extractfile(member)
            if extracted is None:
                continue
            return extracted.read()
    return b""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
