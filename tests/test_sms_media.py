"""SMS link policy and inbound picture adapters."""

from __future__ import annotations

from pathlib import Path

from arelis.sms_media import (
    allowed_open_url,
    already_published_recent,
    body_needs_rich_text,
    inbound_fingerprint,
    inbox_media_url,
    looks_like_photo_body,
    remember_published,
    save_image_b64,
    save_image_bytes,
    sms_body_html,
)

# 1x1 PNG. Fixture image — not a personal photo.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000100ffff03000006000557bf0000000049454e44ae426082"
)


def test_https_becomes_an_anchor_and_file_does_not() -> None:
    html = sms_body_html("see https://example.com/x and file:///C:/Users/you/x.png")
    assert '<a href="https://example.com/x">' in html
    assert "file://" in html
    assert '<a href="file:' not in html
    assert not allowed_open_url("file:///tmp/x")
    assert not allowed_open_url("javascript:alert(1)")
    assert allowed_open_url("https://example.com/x")
    assert body_needs_rich_text("https://example.com/x")
    assert not body_needs_rich_text("hello")


def test_photo_label_is_a_chip_not_a_blank() -> None:
    assert looks_like_photo_body("Photo")
    assert looks_like_photo_body("")
    assert not looks_like_photo_body("on my way")


def test_inbox_row_exposes_a_media_url() -> None:
    assert (
        inbox_media_url({"mediaUrl": "https://example.com/p.jpg"})
        == "https://example.com/p.jpg"
    )
    assert (
        inbox_media_url({"parts": [{"url": "https://example.com/p.png"}]})
        == "https://example.com/p.png"
    )
    assert inbox_media_url({"contentPreview": "hi"}) == ""


def test_jpeg_bytes_land_on_disk(tmp_path: Path) -> None:
    path = save_image_bytes(_PNG, message_id="n1", dest_dir=tmp_path)
    assert path is not None
    assert path.read_bytes()[:8] == _PNG[:8]
    import base64

    b64 = base64.b64encode(_PNG).decode("ascii")
    again = save_image_b64(b64, message_id="n2", dest_dir=tmp_path)
    assert again is not None
    assert save_image_bytes(b"not-an-image", message_id="n3", dest_dir=tmp_path) is None


def test_same_sender_and_body_is_recent_duplicate() -> None:
    fp = inbound_fingerprint(sender="+15550100", body="dedupe-fixture-media")
    assert not already_published_recent(fp)
    remember_published(fp)
    assert already_published_recent(fp)
    other = inbound_fingerprint(sender="+15550100", body="later")
    assert not already_published_recent(other)
