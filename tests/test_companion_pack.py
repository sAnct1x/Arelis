"""House-served companion APK and Gemma: find, refuse, and hand over."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from arelis import companion_pack
from arelis.companion_pack import (
    ApkOffer,
    ExpectedCompanion,
    companion_update_available,
    copy_apk_into,
    describe_apk,
    expected_companion,
    fetch_gemma,
    file_sha256,
    find_apk,
    gemma_ready,
    install_page_url,
    landing_html,
    pair_from_query,
    parse_gradle_version,
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


def test_parse_gradle_version() -> None:
    got = parse_gradle_version(GRADLE)
    assert got == ExpectedCompanion(6, "0.3.3", "gradle")


def test_parse_gradle_version_ignores_noise() -> None:
    assert parse_gradle_version("android { }") is None


def test_expected_companion_reads_gradle(tmp_path: Path) -> None:
    gradle = tmp_path / "app.gradle.kts"
    gradle.write_text(GRADLE, encoding="utf-8")
    got = expected_companion(gradle)
    assert got is not None
    assert got.version_code == 6
    assert got.version_name == "0.3.3"


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


def test_find_apk_none_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(companion_pack, "apk_candidates", lambda: [])
    assert find_apk() is None


def test_describe_apk_without_sidecar_uses_expected(tmp_path: Path, monkeypatch) -> None:
    apk = tmp_path / "app-debug.apk"
    apk.write_bytes(b"debug-apk")
    monkeypatch.setattr(
        companion_pack,
        "expected_companion",
        lambda gradle=None: ExpectedCompanion(6, "0.3.3", "gradle"),
    )
    got = describe_apk(apk)
    assert got is not None
    assert got.version_code == 6
    assert got.signed == "debug"


def test_status_hint_says_how_to_build_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(companion_pack, "find_apk", lambda: None)
    monkeypatch.setattr(companion_pack, "find_gemma", lambda: None)
    monkeypatch.setattr(
        companion_pack,
        "expected_companion",
        lambda gradle=None: ExpectedCompanion(6, "0.3.3", "gradle"),
    )
    hint = companion_pack.status().hint()
    assert "0.3.3" in hint
    assert "build_companion.py" in hint
    assert "will not shell out" in hint


def test_manifest_omits_apk_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(companion_pack, "find_apk", lambda: None)
    monkeypatch.setattr(companion_pack, "find_gemma", lambda: None)
    monkeypatch.setattr(companion_pack, "expected_companion", lambda gradle=None: None)
    body = companion_pack.status().manifest()
    assert body["ok"] is True
    assert body["apk"] is None
    assert body["gemma"]["available"] is False


def test_manifest_includes_hashes(tmp_path: Path, monkeypatch) -> None:
    apk = tmp_path / "arelis.apk"
    apk.write_bytes(b"signed-apk")
    offer = describe_apk(apk)
    assert offer is not None
    monkeypatch.setattr(companion_pack, "find_apk", lambda: offer)
    monkeypatch.setattr(companion_pack, "find_gemma", lambda: None)
    monkeypatch.setattr(
        companion_pack,
        "expected_companion",
        lambda gradle=None: ExpectedCompanion(6, "0.3.3", "gradle"),
    )
    body = companion_pack.status().manifest()
    assert body["apk"]["sha256"] == file_sha256(apk)
    assert body["apk"]["size"] == apk.stat().st_size
    assert body["apk"]["url"] == "/companion/apk"


def test_landing_html_has_download_and_pair_links() -> None:
    offer = ApkOffer(
        path=Path("x.apk"),
        version_code=6,
        version_name="0.3.3",
        sha256="ab",
        size=12_000_000,
        signed="debug",
        source="x",
    )
    html = landing_html(
        pair="secret",
        ticket="A1|inst|tok|secret|http://10.0.0.2:8765",
        apk=offer,
        arelis_version="0.2.9",
    )
    assert "Download the app" in html
    assert "/companion/apk?pair=secret" in html
    assert "arelis://pair?ticket=" in html
    assert "0.3.3" in html


def test_landing_html_without_apk_tells_the_truth() -> None:
    html = landing_html(pair="x", ticket="A1|x", apk=None, arelis_version="0.2.9")
    assert "no companion APK" in html
    assert "build_companion.py" in html
    assert "Download the app" not in html


def test_install_page_url_quotes_the_secret() -> None:
    assert install_page_url("http://10.0.0.2:8765", "a+b") == (
        "http://10.0.0.2:8765/companion?pair=a%2Bb"
    )


def test_pair_from_query() -> None:
    assert pair_from_query("/companion?pair=abc") == "abc"
    assert pair_from_query("/companion/apk?pair=zz&x=1") == "zz"
    assert pair_from_query("/companion") == ""


def test_copy_apk_into_writes_sidecar(tmp_path: Path) -> None:
    src = tmp_path / "app-debug.apk"
    src.write_bytes(b"payload")
    offer = ApkOffer(
        path=src,
        version_code=6,
        version_name="0.3.3",
        sha256=file_sha256(src),
        size=src.stat().st_size,
        signed="debug",
        source=str(src),
    )
    dest_dir = tmp_path / "tree" / "companion"
    dest = copy_apk_into(dest_dir, offer)
    assert dest is not None
    assert dest.is_file()
    meta = json.loads(dest.with_name("arelis.apk.json").read_text(encoding="utf-8"))
    assert meta["versionCode"] == 6
    assert meta["sha256"] == file_sha256(src)


def test_gemma_ready_floor(tmp_path: Path) -> None:
    tiny = tmp_path / "g.litertlm"
    tiny.write_bytes(b"nope")
    assert gemma_ready(tiny) is False
    huge = tmp_path / "h.litertlm"
    huge.write_bytes(b"x" * (companion_pack.GEMMA_MIN_BYTES + 1))
    assert gemma_ready(huge) is True


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


def test_fetch_gemma_skips_when_ready(tmp_path: Path) -> None:
    dest = tmp_path / "gemma-4-E2B-it.litertlm"
    dest.write_bytes(b"x" * (companion_pack.GEMMA_MIN_BYTES + 1))

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not hit the network")

    assert fetch_gemma(dest=dest, transport=httpx.MockTransport(handler)) == dest


@pytest.mark.parametrize(
    ("phone_code", "house_code", "want"),
    [
        (5, 6, True),
        (6, 6, False),
        (7, 6, False),
        (6, 0, False),
    ],
)
def test_newer_house_apk_is_an_update(phone_code: int, house_code: int, want: bool) -> None:
    assert companion_update_available(phone_code, house_code) is want
