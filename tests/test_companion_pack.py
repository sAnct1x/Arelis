"""House-served companion APK and Gemma: find, refuse, and hand over."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx

from arelis import companion_pack
from arelis.companion_pack import (
    ApkOffer,
    fetch_gemma,
    file_sha256,
    find_apk,
    install_page_url,
    write_sidecar,
)

GRADLE = """
android {
    defaultConfig {
        applicationId = "app.arelis"
        versionCode = 6
        versionName = "0.3.3"
    }
}
"""


def test_find_apk_prefers_staged_file(tmp_path: Path, monkeypatch) -> None:
    staged = tmp_path / "companion" / "arelis.apk"
    staged.parent.mkdir()
    staged.write_bytes(b"apk-bytes-here")
    offer = ApkOffer(
        path=staged,
        version_code=6,
        version_name="0.3.3",
        sha256=file_sha256(staged),
        size=staged.stat().st_size,
        signed="debug",
        source=str(staged),
    )
    write_sidecar(staged, offer)
    monkeypatch.setattr(companion_pack, "apk_candidates", lambda: [staged, tmp_path / "missing.apk"])
    monkeypatch.setattr(companion_pack, "expected_companion", lambda gradle=None: None)
    found = find_apk()
    assert found is not None
    assert found.version_name == "0.3.3"
    assert found.version_code == 6
    assert found.sha256 == file_sha256(staged)


def test_install_page_url_quotes_the_secret() -> None:
    assert install_page_url("http://10.0.0.2:8765", "a+b") == (
        "http://10.0.0.2:8765/companion?pair=a%2Bb"
    )


def test_fetch_gemma_writes_digest(tmp_path: Path) -> None:
    payload = b"g" * (companion_pack.GEMMA_MIN_BYTES + 8)
    dest = tmp_path / "gemma-4-E2B-it.litertlm"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, headers={"Content-Length": str(len(payload))})

    transport = httpx.MockTransport(handler)
    seen: list[tuple[int, int]] = []
    got = fetch_gemma(
        url="https://example.invalid/gemma",
        dest=dest,
        progress=lambda n, t: seen.append((n, t)),
        transport=transport,
    )
    assert got == dest
    assert dest.stat().st_size == len(payload)
    digest = dest.with_name(dest.name + ".sha256").read_text(encoding="utf-8").strip()
    assert digest == hashlib.sha256(payload).hexdigest()
    assert seen
    assert seen[-1][0] == len(payload)


