"""The house copy of the Android companion — APK and offline brain.

The phone is a window onto this PC. It should take its updates from this PC
too, not from Play and not from a page the user has to hunt. That is the same
shape as the Windows self-updater: the published (or locally built) artefact
sits next to Arelis, the phone asks whether there is a newer one, and a tap
installs it.

Why the house, not GitHub
=========================

A store update can land a new phone against an old Arelis. A GitHub APK can
do the same if the user has not installed the matching desktop release. The
file this process serves is the one this Arelis actually has. Version numbers
on the two sides stay independent — companion 0.3.x is not Arelis 0.2.x —
and the comparison is the Android versionCode on the APK in this tree.

Signing stays out of git
========================

The repository is public. A keystore in the tree is a keystore everybody has.
Release signing reads ``ARELIS_ANDROID_KEYSTORE*`` from the environment.
Until those exist, a checkout serves whatever debug APK you built on this
machine. That is enough to update *your* phone. It is not enough to publish.

Gemma
=====

The offline brain is ~2.6 GB. It does not belong in the installer. The phone
used to pull it from Hugging Face itself. The house can cache the same file
under ``models/companion/`` and hand it to the phone over the LAN, so a
second phone (or a reinstall) does not hit the internet. Hugging Face remains
the fallback when this PC has not fetched the file yet.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

from arelis import __version__
from arelis.paths import INSTALL_PARENT, cache_dir, is_source_checkout, models_dir, user_data_dir

log = logging.getLogger(__name__)

APK_NAME = "arelis.apk"
SIDECAR_SUFFIX = ".json"
GEMMA_NAME = "gemma-4-E2B-it.litertlm"
GEMMA_MIN_BYTES = 50_000_000
GEMMA_URL = (
    "https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm/"
    "resolve/main/gemma-4-E2B-it.litertlm"
)

GRADLE_RELATIVE = Path("android/arelis-notify/app/build.gradle.kts")
_VERSION_CODE_RE = re.compile(r"versionCode\s*=\s*(\d+)")
_VERSION_NAME_RE = re.compile(r'versionName\s*=\s*"([^"]+)"')


@dataclass(frozen=True)
class ExpectedCompanion:
    version_code: int
    version_name: str
    source: str


@dataclass(frozen=True)
class ApkOffer:
    path: Path
    version_code: int
    version_name: str
    sha256: str
    size: int
    signed: str
    source: str

    @property
    def size_text(self) -> str:
        return _size_text(self.size)


@dataclass(frozen=True)
class GemmaOffer:
    path: Path
    size: int
    sha256: str

    @property
    def size_text(self) -> str:
        return _size_text(self.size)


@dataclass(frozen=True)
class CompanionStatus:
    arelis_version: str
    expected: ExpectedCompanion | None
    apk: ApkOffer | None
    gemma: GemmaOffer | None

    def hint(self) -> str:
        if self.apk is not None:
            bits = [
                f"Companion APK {self.apk.version_name} "
                f"({self.apk.size_text}, {self.apk.signed}) is ready on this PC."
            ]
            if self.gemma is not None:
                bits.append(f"Offline brain cached ({self.gemma.size_text}).")
            else:
                bits.append(
                    "Offline brain is not cached here. Phones will try this PC "
                    "first, then Hugging Face."
                )
            return " ".join(bits)
        want = (
            f"This checkout wants companion {self.expected.version_name}."
            if self.expected
            else "No companion version is pinned in this tree."
        )
        return (
            f"{want} No APK is sitting next to this Arelis. From a source "
            "checkout run python scripts/build_companion.py — then this page "
            "grows a download QR. The UI will not shell out to Gradle."
        )

    def snapshot(self) -> dict[str, Any]:
        """Small public summary for /inbound/health. No paths, no hashes."""
        body: dict[str, Any] = {
            "arelis": self.arelis_version,
            "apk": self.apk is not None,
        }
        if self.expected is not None:
            body["expected"] = self.expected.version_name
            body["expected_code"] = self.expected.version_code
        if self.apk is not None:
            body["version"] = self.apk.version_name
            body["version_code"] = self.apk.version_code
        body["gemma"] = self.gemma is not None
        return body

    def manifest(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "ok": True,
            "arelis": self.arelis_version,
            "apk": None,
            "gemma": None,
        }
        if self.expected is not None:
            body["expected"] = {
                "version_code": self.expected.version_code,
                "version_name": self.expected.version_name,
            }
        if self.apk is not None:
            body["apk"] = {
                "version_code": self.apk.version_code,
                "version_name": self.apk.version_name,
                "sha256": self.apk.sha256,
                "size": self.apk.size,
                "signed": self.apk.signed,
                "url": "/companion/apk",
            }
        if self.gemma is not None:
            body["gemma"] = {
                "available": True,
                "name": GEMMA_NAME,
                "sha256": self.gemma.sha256,
                "size": self.gemma.size,
                "url": "/companion/gemma",
            }
        else:
            body["gemma"] = {"available": False, "url": "/companion/gemma"}
        return body


def _size_text(size: int) -> str:
    if size >= 1_000_000_000:
        return f"{size / 1_000_000_000:.1f} GB"
    if size >= 1_000_000:
        return f"{size / 1_000_000:.0f} MB"
    if size >= 1_000:
        return f"{size / 1_000:.0f} KB"
    return f"{size} B"


def gradle_path() -> Path | None:
    if is_source_checkout():
        path = INSTALL_PARENT / GRADLE_RELATIVE
        if path.is_file():
            return path
    return None


def parse_gradle_version(text: str) -> ExpectedCompanion | None:
    code_m = _VERSION_CODE_RE.search(text)
    name_m = _VERSION_NAME_RE.search(text)
    if not code_m or not name_m:
        return None
    return ExpectedCompanion(
        version_code=int(code_m.group(1)),
        version_name=name_m.group(1),
        source="gradle",
    )


def expected_companion(gradle: Path | None = None) -> ExpectedCompanion | None:
    path = gradle if gradle is not None else gradle_path()
    if path is not None and path.is_file():
        found = parse_gradle_version(path.read_text(encoding="utf-8"))
        if found is not None:
            return found
    for apk in apk_candidates():
        meta = load_sidecar(apk)
        if meta is not None:
            return ExpectedCompanion(
                version_code=int(meta["version_code"]),
                version_name=str(meta["version_name"]),
                source="sidecar",
            )
    return None


def _sidecar_cache_path(apk: Path) -> Path:
    """Compute cache-based sidecar location for an APK."""
    cache = cache_dir() / "companion" / "sidecars"
    apk_hash = hashlib.sha256(str(apk.resolve()).encode("utf-8")).hexdigest()[:16]
    return cache / f"{apk.name}.{apk_hash}{SIDECAR_SUFFIX}"


def _sidecar_payload(offer: ApkOffer) -> str:
    """JSON payload for sidecar metadata."""
    return json.dumps(
        {
            "versionCode": offer.version_code,
            "versionName": offer.version_name,
            "sha256": offer.sha256,
            "signed": offer.signed,
            "applicationId": "app.arelis",
        },
        indent=2,
    ) + "\n"


def sidecar_path(apk: Path) -> Path:
    """Sidecars live in cache, indexed by APK location, not beside the APK."""
    return _sidecar_cache_path(apk)


def load_sidecar(apk: Path) -> dict[str, Any] | None:
    """Read sidecar from cache first, then fall back to legacy location next to APK."""
    candidates = [
        sidecar_path(apk),  # Cache location (new)
        apk.with_name(apk.name + SIDECAR_SUFFIX),  # Legacy: next to APK (installer tree)
    ]
    for path in candidates:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Could not read %s: %s", path, exc)
            continue
        if not isinstance(raw, dict):
            continue
        try:
            code = int(raw.get("versionCode") or raw.get("version_code") or 0)
            name = str(raw.get("versionName") or raw.get("version_name") or "").strip()
        except (TypeError, ValueError):
            continue
        if code <= 0 or not name:
            continue
        return {
            "version_code": code,
            "version_name": name,
            "sha256": str(raw.get("sha256") or "").strip(),
            "signed": str(raw.get("signed") or "unknown").strip() or "unknown",
        }
    return None


def write_sidecar(apk: Path, offer: ApkOffer) -> Path:
    """Write sidecar to cache, not beside APK (which may be read-only package location)."""
    dest = _sidecar_cache_path(apk)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_sidecar_payload(offer), encoding="utf-8")
    return dest


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _install_companion_dir() -> Path | None:
    try:
        from arelis.update import install_root
    except Exception as exc:
        log.warning("Could not import install_root: %s", exc)
        return None
    root = install_root()
    if root is None:
        return None
    return root / "companion"


def apk_candidates() -> list[Path]:
    """Places an APK is allowed to live, first match wins.

    User-data and the installer tree before gradle outputs, so a staged
    ``companion/arelis.apk`` beats a leftover debug build.
    """
    found: list[Path] = []
    found.append(user_data_dir() / "companion" / APK_NAME)
    installed = _install_companion_dir()
    if installed is not None:
        found.append(installed / APK_NAME)
    if is_source_checkout():
        found.append(INSTALL_PARENT / "companion" / APK_NAME)
        android = (
            INSTALL_PARENT
            / "android"
            / "arelis-notify"
            / "app"
            / "build"
            / "outputs"
            / "apk"
        )
        found.append(android / "release" / "app-release.apk")
        found.append(android / "debug" / "app-debug.apk")
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in found:
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _signed_label(apk: Path, sidecar: dict[str, Any] | None) -> str:
    if sidecar and sidecar.get("signed") not in {"", "unknown"}:
        return str(sidecar["signed"])
    name = apk.name.lower()
    parent = apk.parent.name.lower()
    if "release" in name or parent == "release":
        return "release"
    if "debug" in name or parent == "debug":
        return "debug"
    return "unknown"


def describe_apk(apk: Path) -> ApkOffer | None:
    if not apk.is_file() or apk.stat().st_size <= 0:
        return None
    sidecar = load_sidecar(apk)
    expected = expected_companion()
    if sidecar is not None:
        code = int(sidecar["version_code"])
        name = str(sidecar["version_name"])
        digest = str(sidecar.get("sha256") or "")
    elif expected is not None:
        code = expected.version_code
        name = expected.version_name
        digest = ""
    else:
        code = 0
        name = "unknown"
        digest = ""
    if not digest:
        digest = file_sha256(apk)
    return ApkOffer(
        path=apk,
        version_code=code,
        version_name=name,
        sha256=digest,
        size=apk.stat().st_size,
        signed=_signed_label(apk, sidecar),
        source=str(apk),
    )


def find_apk() -> ApkOffer | None:
    for path in apk_candidates():
        offer = describe_apk(path)
        if offer is not None:
            return offer
    return None


def gemma_dest() -> Path:
    return models_dir() / "companion" / GEMMA_NAME


def gemma_sidecar_path(dest: Path | None = None) -> Path:
    path = dest or gemma_dest()
    return path.with_name(path.name + ".sha256")


def gemma_ready(path: Path | None = None) -> bool:
    dest = path or gemma_dest()
    try:
        return dest.is_file() and dest.stat().st_size > GEMMA_MIN_BYTES
    except OSError:
        return False


def find_gemma() -> GemmaOffer | None:
    dest = gemma_dest()
    if not gemma_ready(dest):
        return None
    digest_path = gemma_sidecar_path(dest)
    digest = ""
    try:
        digest = digest_path.read_text(encoding="utf-8").strip().split()[0]
    except FileNotFoundError:
        digest = ""
    except OSError as exc:
        log.warning("Could not read %s: %s", digest_path, exc)
    if len(digest) != 64:
        digest = file_sha256(dest)
        try:
            digest_path.write_text(digest + "\n", encoding="utf-8")
        except OSError:
            pass
    return GemmaOffer(path=dest, size=dest.stat().st_size, sha256=digest)


def fetch_gemma(
    *,
    url: str = GEMMA_URL,
    dest: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    transport: Any | None = None,
) -> Path:
    """Download the LiteRT pack onto this PC so phones can take it from here."""
    import httpx

    target = dest or gemma_dest()
    if gemma_ready(target):
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    headers = {"User-Agent": f"Arelis/{__version__}"}
    client_kw: dict[str, Any] = {"follow_redirects": True, "timeout": 60.0}
    if transport is not None:
        client_kw["transport"] = transport
    with httpx.Client(**client_kw) as client:
        with client.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            digest = hashlib.sha256()
            with part.open("wb") as fh:
                for chunk in resp.iter_bytes(1024 * 64):
                    fh.write(chunk)
                    digest.update(chunk)
                    got += len(chunk)
                    if progress is not None:
                        progress(got, total)
    if target.exists():
        target.unlink()
    part.replace(target)
    gemma_sidecar_path(target).write_text(digest.hexdigest() + "\n", encoding="utf-8")
    if not gemma_ready(target):
        raise RuntimeError("Gemma download finished but the file is too small.")
    return target


def status() -> CompanionStatus:
    return CompanionStatus(
        arelis_version=__version__,
        expected=expected_companion(),
        apk=find_apk(),
        gemma=find_gemma(),
    )


def install_page_url(base: str, pair: str) -> str:
    root = base.rstrip("/")
    return f"{root}/companion?pair={quote(pair, safe='')}"


def landing_html(
    *,
    pair: str,
    ticket: str,
    apk: ApkOffer | None,
    arelis_version: str,
) -> str:
    """First-install page the phone camera opens. No JS, no third-party assets."""
    title = "Arelis"
    if apk is None:
        body = (
            "<p>This Arelis has no companion APK to hand over.</p>"
            "<p>On the PC, from a source checkout: "
            "<code>python scripts/build_companion.py</code></p>"
        )
    else:
        apk_href = f"/companion/apk?pair={quote(pair, safe='')}"
        pair_href = f"arelis://pair?ticket={quote(ticket, safe='')}"
        body = (
            f"<p>Arelis {escape(arelis_version)} · companion "
            f"{escape(apk.version_name)} · {escape(apk.size_text)}</p>"
            f'<p><a class="btn" href="{escape(apk_href)}">Download the app</a></p>'
            "<p>Android will ask once. That is the install. Then open Arelis "
            "and scan the pair code still on the PC — or tap below if the app "
            "is already on this phone.</p>"
            f'<p><a href="{escape(pair_href)}">Already installed? Pair</a></p>'
        )
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{title}</title>"
        "<style>"
        "body{font:16px/1.45 'Times New Roman',serif;background:#16110d;color:#f3e6d4;"
        "max-width:32rem;margin:0 auto;padding:2.5rem 1.25rem;}"
        "h1{font-weight:500;letter-spacing:.12em;text-transform:lowercase;"
        "font-size:1rem;color:#c47a4a;}"
        "p{color:#e8d7c0;} a{color:#e8a15a;} code{color:#f3e6d4;}"
        ".btn{display:inline-block;padding:.7rem 1.1rem;background:#c47a4a;"
        "color:#16110d;text-decoration:none;border-radius:2px;}"
        "</style></head><body>"
        f"<h1>{title}</h1>{body}</body></html>"
    )


def pair_from_query(path: str) -> str:
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(path).query)
    return str((qs.get("pair") or [""])[0] or "").strip()


def copy_apk_into(dest_dir: Path, offer: ApkOffer | None = None) -> Path | None:
    """Stage the APK and sidecar for the Windows installer tree."""
    found = offer or find_apk()
    if found is None:
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / APK_NAME
    if dest.resolve() != found.path.resolve():
        dest.write_bytes(found.path.read_bytes())
    # Write sidecar next to the staged APK (installer tree is writable).
    staged_offer = replace(found, path=dest, size=dest.stat().st_size, source=str(dest))
    sidecar = dest.with_name(dest.name + SIDECAR_SUFFIX)
    sidecar.write_text(_sidecar_payload(staged_offer), encoding="utf-8")
    return dest


def env_keystore_configured() -> bool:
    return bool(
        os.environ.get("ARELIS_ANDROID_KEYSTORE", "").strip()
        or os.environ.get("ARELIS_ANDROID_KEYSTORE_BASE64", "").strip()
    )


def companion_update_available(phone_code: int, house_code: int) -> bool:
    """True only when the house APK is a newer versionCode. Never a downgrade."""
    return house_code > 0 and phone_code > 0 and house_code > phone_code
