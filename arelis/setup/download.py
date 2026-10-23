"""Download a chat GGUF from Hugging Face into the models folder.

HTTP Range resume. An interrupt or a network error leaves the .partial
file so the next try can continue. The finished file is checked for size
and SHA256, then renamed into place.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from collections.abc import Callable
from pathlib import Path

import httpx

from arelis import __version__
from arelis.llm.llama_launch import MMPROJ_BYTES, _ensure_mmproj, mmproj_for
from arelis.paths import ensure, models_dir
from arelis.setup.catalog import (
    HF_REPO,
    Q3_FILENAME,
    Q4_FILENAME,
    CatalogModel,
)

log = logging.getLogger(__name__)

Progress = Callable[[str, int, int], None]
Cancel = Callable[[], bool]

HF_RESOLVE = f"https://huggingface.co/{HF_REPO}/resolve/main/"
# Hugging Face LFS pointers on main. Q4 22134528992, Q3 16600710112.
EXPECTED: dict[str, tuple[int, str]] = {
    Q4_FILENAME: (
        22_134_528_992,
        "ac0e2c1189e055faa36eff361580e79c5bd6f8e76bffb4ce547f167d53e31a61",
    ),
    Q3_FILENAME: (
        16_600_710_112,
        "1b715841683f960bd9a49f008181bd910ee169b78d4cf465b6fde7f4d929ff99",
    ),
}

_SLACK_BYTES = 64 * 1024 * 1024
_CHUNK = 1024 * 1024
_GB = 1000**3

_DISK = "This computer does not have enough free space for the chat model."
_OFFLINE = (
    "Arelis could not download the chat model. Check that this PC is online, "
    "then try again. The unfinished file was kept, so the next try can continue."
)
_LATER = (
    "The chat model download stopped. Try again in a little while. "
    "The unfinished file was kept, so the next try can continue."
)
_MISMATCH = (
    "The chat model file did not match what we expected. Try the download again."
)
_STOPPED = (
    "The download was stopped. The unfinished file is still here, so the "
    "next try can continue."
)
_UNKNOWN = "That chat model is not on the list."


class DownloadCancelledError(Exception):
    """The person stopped the download. The partial file stays."""


def download_model(
    model: CatalogModel,
    *,
    dest_dir: Path | None = None,
    progress: Progress | None = None,
    cancelled: Cancel | None = None,
) -> Path:
    """Fetch the GGUF, then the picture file beside it."""
    expected = EXPECTED.get(model.filename)
    if expected is None:
        raise RuntimeError(_UNKNOWN)
    size, digest = expected
    folder = dest_dir or models_dir()
    ensure(folder)
    dest = folder / model.filename
    url = HF_RESOLVE + model.filename
    if dest.is_file() and _file_matches(dest, size, digest):
        _report(progress, "The chat model is already on this PC.")
        _fetch_mmproj(dest, progress=progress)
        return dest
    _require_space(folder, size + MMPROJ_BYTES + _SLACK_BYTES)
    _report(progress, _status_line(0, size), 0, size)
    download_file(
        url,
        dest,
        expected_bytes=size,
        sha256=digest,
        progress=progress,
        cancelled=cancelled,
    )
    _fetch_mmproj(dest, progress=progress)
    return dest


def download_file(
    url: str,
    dest: Path,
    *,
    expected_bytes: int,
    sha256: str,
    progress: Progress | None = None,
    cancelled: Cancel | None = None,
) -> Path:
    """Write ``dest``, resuming from ``dest.partial`` when that file exists."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and _file_matches(dest, expected_bytes, sha256):
        return dest
    partial = dest.with_name(dest.name + ".partial")
    have = _usable_partial(partial, expected_bytes, sha256)
    if have == expected_bytes and _file_matches(partial, expected_bytes, sha256):
        partial.replace(dest)
        return dest
    _require_space(dest.parent, max(0, expected_bytes - have) + _SLACK_BYTES)
    headers = {"User-Agent": f"arelis/{__version__}"}
    if have:
        headers["Range"] = f"bytes={have}-"
    timeout = httpx.Timeout(600.0, connect=15.0)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", url, headers=headers) as response:
                have = _begin_stream(response, partial, have)
                _stream_into(
                    response,
                    partial,
                    have=have,
                    expected=expected_bytes,
                    progress=progress,
                    cancelled=cancelled,
                )
    except DownloadCancelledError:
        raise RuntimeError(_STOPPED) from None
    except RuntimeError:
        raise
    except httpx.TransportError as exc:
        raise RuntimeError(_OFFLINE) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(_LATER) from exc
    if not _file_matches(partial, expected_bytes, sha256):
        if partial.is_file() and partial.stat().st_size == expected_bytes:
            partial.unlink(missing_ok=True)
        raise RuntimeError(_MISMATCH)
    partial.replace(dest)
    return dest


def _fetch_mmproj(model: Path, *, progress: Progress | None) -> None:
    _report(progress, "Getting the picture file for this model…")
    _ensure_mmproj(mmproj_for(model))


def _usable_partial(partial: Path, expected: int, digest: str) -> int:
    if not partial.is_file():
        return 0
    size = partial.stat().st_size
    if size <= 0:
        return 0
    if size > expected:
        partial.unlink(missing_ok=True)
        return 0
    if size == expected and not _file_matches(partial, expected, digest):
        partial.unlink(missing_ok=True)
        return 0
    return size


def _begin_stream(response: httpx.Response, partial: Path, have: int) -> int:
    if have and response.status_code == 206:
        return have
    if have and response.status_code == 200:
        # Server ignored Range. Start the file again.
        have = 0
    response.raise_for_status()
    if have == 0:
        partial.write_bytes(b"")
    return have


def _stream_into(
    response: httpx.Response,
    dest: Path,
    *,
    have: int,
    expected: int,
    progress: Progress | None,
    cancelled: Cancel | None,
) -> None:
    mode = "ab" if have else "wb"
    with dest.open(mode) as handle:
        for chunk in response.iter_bytes(_CHUNK):
            if cancelled is not None and cancelled():
                raise DownloadCancelledError()
            handle.write(chunk)
            have += len(chunk)
            if have > expected:
                raise RuntimeError(_MISMATCH)
            _report(progress, _status_line(have, expected), have, expected)
    if have < expected:
        raise RuntimeError(_LATER)


def _file_matches(path: Path, expected: int, digest: str) -> bool:
    try:
        if path.stat().st_size != expected:
            return False
    except OSError:
        return False
    return _sha256(path) == digest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
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


def _status_line(done: int, total: int) -> str:
    if total <= 0:
        return "Downloading the chat model…"
    return (
        f"Downloading the chat model… {done / _GB:.1f} of {total / _GB:.1f} GB"
    )


def _report(
    progress: Progress | None,
    status: str,
    done: int = 0,
    total: int = 0,
) -> None:
    if progress is not None:
        progress(status, done, total)
