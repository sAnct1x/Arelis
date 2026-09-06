"""Inbound SMS links and pictures — no Qt."""

from arelis.sms_media import (
    allowed_open_url,
    body_is_only_image_url,
    body_needs_rich_text,
    href_for_url,
    iter_http_urls,
    looks_like_image_url,
    sms_body_html,
)


def test_https_and_www_are_openable() -> None:
    assert allowed_open_url("https://example.com/notes")
    assert allowed_open_url("www.example.com/notes")
    assert href_for_url("www.example.com/notes") == "https://www.example.com/notes"
    assert not allowed_open_url("file:///C:/secret.txt")
    assert not allowed_open_url("javascript:alert(1)")


def test_sms_body_html_wraps_www_and_https() -> None:
    html = sms_body_html("see www.example.com/notes please")
    assert 'href="https://www.example.com/notes"' in html
    assert ">www.example.com/notes<" in html
    rich = sms_body_html("https://maps.app.goo.gl/abc")
    assert 'href="https://maps.app.goo.gl/abc"' in rich
    assert body_needs_rich_text("park at www.example.com/lot")
    assert not body_needs_rich_text("nope file:///C:/secret.txt")


def test_angle_brackets_do_not_join_the_href() -> None:
    html = sms_body_html("go <https://example.com/x>")
    assert 'href="https://example.com/x"' in html
    assert "example.com/x>" not in html


def test_image_url_body_is_detected() -> None:
    assert looks_like_image_url("https://cdn.example.com/pic.jpg")
    assert body_is_only_image_url("https://cdn.example.com/pic.jpg")
    assert body_is_only_image_url("www.cdn.example.com/pic.png")
    assert not body_is_only_image_url("look https://cdn.example.com/pic.jpg")
    assert iter_http_urls("a https://x.test/y and www.z.test/w") == [
        "https://x.test/y",
        "www.z.test/w",
    ]
