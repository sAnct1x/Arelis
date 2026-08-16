"""Find out whether a newer Arelis has been published, and install it if asked to.

The shape of this
=================

An installed Arelis asks GitHub once a day whether there is a newer release, offers it, and
on a yes downloads the setup .exe, checks it against the digest published beside it, runs it
silently and lets it start the new version. The server half already existed: the release
workflow uploads ``Arelis-<version>-win64-setup.exe`` and a ``.sha256`` next to it, which is
exactly the pair this needs.

Only for copies that came from the installer
============================================

Three things have to be true, and each rules out a real situation rather than a theoretical
one. Windows, because that is the only installer there is. Not a source checkout, because a
checkout updates with ``git pull`` and would otherwise be offered a release that overwrites
nothing it is running. And an install this program can recognise as its own, which is why
``install_root`` looks for the uninstaller: pip-installing Arelis into a virtualenv produces
a copy that is not a checkout either, and downloading a setup .exe and running it over
somebody's venv would be a rude way to find that out.

Published, not draft
====================

``releases/latest`` is used rather than the list, and that is a design choice worth naming.
It excludes drafts and prereleases, and the release workflow publishes drafts. So tagging
builds an installer and offers it to nobody; pressing publish on GitHub is what ships it.
The staging area is the default, and no flag here can accidentally skip it.

What the digest does and does not buy
=====================================

The .sha256 comes from the same release as the .exe, so anyone who can replace one can
replace the other. It is not a signature and this file does not pretend otherwise. What it
does catch is the thing that actually happens: a download that was truncated, corrupted, or
served stale by something in the middle. The trust anchor is HTTPS to api.github.com. Real
signing is a certificate away and documented in win-installer/README.md as not bought.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

from arelis import __source_url__, __version__
from arelis.paths import PACKAGE_ROOT, cache_dir, ensure, is_source_checkout

log = logging.getLogger(__name__)

# Once a day. Frequent enough that a release reaches people the day it lands, rare enough
# that a laptop opened twenty times makes one request. Unauthenticated GitHub allows sixty
# an hour per address, which this is in no danger of.
CHECK_INTERVAL = timedelta(days=1)

SETUP_SUFFIX = "-setup.exe"
DIGEST_SUFFIX = "-setup.exe.sha256"

# Windows process-creation flags, spelled out because subprocess only defines them on
# Windows and this module is imported everywhere, including in CI on Linux.
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200


class UpdateError(RuntimeError):
    """An update could not be checked, downloaded or verified."""


@dataclass(frozen=True)
class Release:
    """A published release that carries an installer.

    ``version`` is parsed rather than kept as the tag, because "v0.10.0" is newer than
    "v0.9.0" and string comparison says otherwise.
    """

    version: Version
    tag: str
    setup_name: str
    setup_url: str
    digest_url: str
    size: int
    page_url: str

    @property
    def size_text(self) -> str:
        return f"{self.size / (1024 * 1024):.0f}MB" if self.size else "unknown size"


def api_url() -> str:
    """The releases endpoint for whatever repository this build says it came from.

    Derived from ``__source_url__`` instead of written out again, so a fork does not ship a
    build that offers its users the upstream's releases.
    """
    slug = __source_url__.removeprefix("https://github.com/").strip("/")
    return f"https://api.github.com/repos/{slug}/releases/latest"


def install_root() -> Path | None:
    """The directory the installer owns, or None if the installer did not put us here.

    The layout is fixed by the build: ``<root>\\Lib\\site-packages\\arelis``. The
    uninstaller sits at the root, and its presence is the only cheap proof that this tree
    was produced by our setup .exe rather than by pip into a virtualenv that happens to
    have the same depth.
    """
    try:
        root = PACKAGE_ROOT.parents[2]
    except IndexError:
        return None
    return root if (root / "unins000.exe").is_file() else None


def updates_supported() -> tuple[bool, str]:
    """Whether this copy may update itself, and in plain words why not when it may not."""
    if sys.platform != "win32":
        return False, "the Arelis installer is Windows-only"
    if is_source_checkout():
        return False, "this is a source checkout -- update it with git pull"
    if install_root() is None:
        return False, "this copy was not put here by the Arelis installer"
    return True, ""


def _stamp_path() -> Path:
    return cache_dir() / "update-check.json"


def last_checked() -> datetime | None:
    try:
        stamp = json.loads(_stamp_path().read_text(encoding="utf-8"))
        return datetime.fromisoformat(str(stamp["checked_at"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def record_check(when: datetime | None = None) -> None:
    """Remember that we looked, and never fail because we could not write it down.

    A cache that cannot be written turns into checking on every launch, which is worse
    manners than it is a bug. Not a reason to interrupt anybody.
    """
    when = when or datetime.now(UTC)
    try:
        ensure(_stamp_path().parent)
        _stamp_path().write_text(
            json.dumps({"checked_at": when.isoformat(), "version": __version__}, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        log.debug("could not record the update check: %s", exc)


def check_is_due(now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    previous = last_checked()
    if previous is None:
        return True
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=UTC)
    # A stamp in the future means a clock that moved. Checking once is a better answer
    # than waiting out an interval measured from a time that never happened.
    return previous > now or now - previous >= CHECK_INTERVAL


def parse_release(payload: dict[str, Any]) -> Release | None:
    """Turn the GitHub payload into a Release, or None if it does not carry an installer.

    None rather than an exception for every one of these: a release with no Windows asset
    is a normal thing for a project to publish, and a source-only or notes-only release
    must not turn into an error dialog on somebody's desktop.
    """
    if payload.get("draft") or payload.get("prerelease"):
        return None
    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        return None
    try:
        version = Version(tag.lstrip("vV"))
    except InvalidVersion:
        log.debug("ignoring release with an unparseable tag: %r", tag)
        return None

    assets = payload.get("assets") or []
    setup = next((a for a in assets if str(a.get("name", "")).endswith(SETUP_SUFFIX)), None)
    digest = next((a for a in assets if str(a.get("name", "")).endswith(DIGEST_SUFFIX)), None)
    if setup is None or digest is None:
        return None

    return Release(
        version=version,
        tag=tag,
        setup_name=str(setup["name"]),
        setup_url=str(setup["browser_download_url"]),
        digest_url=str(digest["browser_download_url"]),
        size=int(setup.get("size") or 0),
        page_url=str(payload.get("html_url") or f"{__source_url__}/releases"),
    )


def fetch_latest(timeout: float = 10.0) -> Release | None:
    """Ask GitHub for the newest published release. None if there is not one yet."""
    import httpx

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        # GitHub requires one and rejects the request without it.
        "User-Agent": f"arelis/{__version__}",
    }
    response = httpx.get(api_url(), headers=headers, timeout=timeout, follow_redirects=True)
    # 404 is the ordinary answer while every release is still a draft, which is where a
    # release starts. Not an error, just nothing to offer.
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return parse_release(response.json())


def available_update(
    current: str = __version__,
    fetch: Callable[[], Release | None] = fetch_latest,
) -> Release | None:
    """The newer release, or None. Never raises for a reason the user cannot act on."""
    try:
        release = fetch()
    except Exception as exc:
        # Offline, DNS down, rate limited, GitHub having a morning. A background check
        # that cannot reach the network is not news.
        log.info("could not check for updates: %s", exc)
        return None
    if release is None:
        return None
    try:
        if release.version <= Version(current):
            return None
    except InvalidVersion:
        log.warning("this build's own version %r does not parse", current)
        return None
    return release


def expected_digest(text: str) -> str:
    """Pull the hash out of a ``<sha256>  <filename>`` line, as sha256sum writes it."""
    for line in text.splitlines():
        head = line.strip().split()
        if head and len(head[0]) == 64:
            try:
                int(head[0], 16)
            except ValueError:
                continue
            return head[0].lower()
    raise UpdateError(f"no sha256 digest found in {text[:80]!r}")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(
    release: Release,
    into: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    timeout: float = 60.0,
) -> Path:
    """Fetch the installer and refuse to return one whose digest does not match.

    Streamed to a ``.part`` and renamed only once verified, so an interrupted download can
    never be mistaken for an installer. A mismatch deletes the file: leaving 150MB of
    something-unexpected on a user's disk, named as though it were the real installer, is
    the one outcome worse than failing.
    """
    import httpx

    target_dir = into or (cache_dir() / "updates")
    ensure(target_dir)
    final = target_dir / release.setup_name
    partial = final.with_suffix(final.suffix + ".part")

    headers = {"User-Agent": f"arelis/{__version__}"}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        digest_text = client.get(release.digest_url).raise_for_status().text
        wanted = expected_digest(digest_text)

        received = 0
        with client.stream("GET", release.setup_url) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or release.size or 0)
            with partial.open("wb") as handle:
                for chunk in response.iter_bytes(1024 * 256):
                    handle.write(chunk)
                    received += len(chunk)
                    if progress is not None:
                        progress(received, total)

    got = file_digest(partial)
    if got != wanted:
        partial.unlink(missing_ok=True)
        raise UpdateError(
            f"{release.setup_name} did not match its published digest.\n"
            f"  expected {wanted}\n  got      {got}\n"
            "Nothing was installed and the download has been deleted."
        )

    final.unlink(missing_ok=True)
    partial.rename(final)
    _remove_stale_downloads(target_dir, keep=final)
    return final


def _remove_stale_downloads(directory: Path, keep: Path) -> None:
    for path in directory.glob("*setup.exe*"):
        if path == keep:
            continue
        try:
            path.unlink()
        except OSError as exc:
            log.debug("could not remove the old download %s: %s", path, exc)


def start_installer(installer: Path) -> None:
    """Hand off to the setup .exe and return, so the caller can quit.

    Quitting is not optional and not tidiness: an upgrade replaces the interpreter and the
    DLLs of the process doing the asking, and Windows will not let it while they are open.
    The installer is given /relaunch=yes, which arelis.iss reads to start the new version
    once the files are in place -- the [Run] entry a user clicks is skipped in silent mode,
    so without it an update would end with Arelis closed and no explanation.

    Detached and in its own process group, so it survives us exiting a few milliseconds
    later, which is the entire point.
    """
    if sys.platform != "win32":
        raise UpdateError("the Arelis installer only runs on Windows")
    log.info("starting %s for a silent upgrade", installer.name)
    subprocess.Popen(
        [str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/relaunch=yes"],
        creationflags=_DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
