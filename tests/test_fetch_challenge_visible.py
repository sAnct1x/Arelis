"""Visible-text challenge detection: scripts do not pad a wall into an article.

No network. Monkeypatch guarded_get / guarded_request. Nothing here solves a wall.
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.evidence import looks_like_challenge_page
from tests._wall_fixtures import WALL_FIXTURES

_CF_URL = "https://example.test/gated"
_WORDING = "Just a moment. Checking your browser. Verify you are human."

_SHORT_DOCS = "SHORT docs page, reCAPTCHA integration (~600 chars)"
_SHORT_BLOG = "short blog post about captchas (~700 chars)"


def _visible_len(html: str) -> int:
    from arelis.core.evidence import _visible_text

    return len(_visible_text(html))


def _wall_html(target_visible: int, *, script: str = "") -> str:
    seed = _WORDING + " "
    extra = f"<script>{script}</script>" if script else ""
    pad = "x" * (target_visible + 80)
    html = (
        f"<html><head><title>Gate</title>{extra}</head>"
        f"<body><p>{seed}{pad}</p></body></html>"
    )
    vis_n = _visible_len(html)
    over = vis_n - target_visible
    assert over >= 0
    pad = pad[:-over] if over else pad
    html = (
        f"<html><head><title>Gate</title>{extra}</head>"
        f"<body><p>{seed}{pad}</p></body></html>"
    )
    assert _visible_len(html) == target_visible
    return html


def _fixture_params() -> list[Any]:
    return [
        pytest.param(name, is_wall, status, body, id=name)
        for name, is_wall, status, body in WALL_FIXTURES
    ]


def _fixture_body(name: str) -> str:
    for label, _is_wall, _status, body in WALL_FIXTURES:
        if label == name:
            return body
    raise AssertionError("labelled page is missing")


def test_short_gate_inside_main_is_still_a_wall() -> None:
    html = "<html><body><main><p>Please verify you are human.</p></main></body></html>"
    assert looks_like_challenge_page(html, 200) is True


def test_style_and_comment_blocks_do_not_pad_a_gate() -> None:
    gate = "<html><body><p>Verify you are human.</p></body></html>"
    style = (
        "<html><body><style>" + ("z" * 5000) + "</style><p>Verify you are human.</p></body></html>"
    )
    comment = "<html><body><!--" + ("z" * 5000) + "--><p>Verify you are human.</p></body></html>"
    assert looks_like_challenge_page(gate, 200) is True
    assert looks_like_challenge_page(style, 200) is True
    assert looks_like_challenge_page(comment, 200) is True
    assert _visible_len(style) == _visible_len(gate)
    assert _visible_len(comment) == _visible_len(gate)


def test_unterminated_script_does_not_hide_a_gate_behind_padding() -> None:
    html = "<html><body><p>Verify you are human.</p><script>" + ("var secret = 1;" * 400)
    assert looks_like_challenge_page(html, 200) is True
    assert _visible_len(html) < 2000


