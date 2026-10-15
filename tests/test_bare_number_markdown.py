"""Bare number-first replies must stay visible in the chat bubble.

"391. " (number, period, trailing space) was parsed as an empty ordered-list
item, so the chat view dropped the number and only showed the next paragraph.
These cases go through render_markdown, the same path _assistant_bubble_html
uses for streamed drafts and ASSISTANT_DONE.
"""
from __future__ import annotations

import re

from arelis.ui.markdown import render_markdown


def _visible(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return (
        text.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
    )


def test_trailing_space_number_stays_visible_with_followup() -> None:
    html = render_markdown(
        "391. \n\nThat's straightforward arithmetic, no need to fetch for this."
    )
    visible = _visible(html)
    assert "391" in visible
    assert "straightforward arithmetic" in visible
    assert "<li></li>" not in html


def test_real_numbered_list_still_renders_as_ol() -> None:
    html = render_markdown(
        "1. Preheat the oven\n2. Mix the flour\n3. Bake for 25 minutes"
    )
    assert "<ol" in html
    assert html.count("<li>") == 3
    visible = _visible(html)
    assert "Preheat the oven" in visible
    assert "Mix the flour" in visible
    assert "Bake for 25 minutes" in visible


def test_empty_numbered_marker_mid_reply_does_not_swallow_the_number() -> None:
    html = render_markdown("Before.\n\n7. \n\nAfter the marker.")
    visible = _visible(html)
    assert "7" in visible
    assert "Before." in visible
    assert "After the marker." in visible
    assert "<li></li>" not in html
