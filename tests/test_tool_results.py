"""Local workspace reads are not a scrape card.

Live 2026-09-21: farm/index.html was 5314 chars of markup. prepare_tool_output
turned it into title/meta bullets because workspace sat in FAT_TOOLS and
.html was not on the source-suffix allowlist. Same-call then blocked a
second read, so she reviewed the card instead of the code.
"""

from __future__ import annotations

from arelis.core.tool_results import FAT_TOOLS, prepare_tool_output


def test_workspace_is_not_a_fat_scrape_tool() -> None:
    assert "workspace" not in FAT_TOOLS
    assert "scrape" in FAT_TOOLS


def test_a_small_html_file_stays_the_body() -> None:
    """The dump file was ~5KB. A card of meta tags is not the markup."""
    html = (
        "<!doctype html>\n<html><head>"
        "<title>Farm Portraits | Springfield Illinois photography and bookings</title>"
        '<meta name="description" content="Golden hour portraits, events, and farm stands.">'
        "</head><body>\n"
        + ("<section class='hero'><p>book a shoot</p></section>\n" * 80)
        + "</body></html>\n"
    )
    assert len(html) >= 2500
    prepared = prepare_tool_output(
        "workspace",
        html,
        data={"path": r"C:\Users\you\Documents\farm\index.html"},
    )
    assert prepared.summarized is False
    assert "tool_summary" not in prepared.inject
    assert "<section class='hero'>" in prepared.inject
    assert prepared.inject == html


def test_a_fat_scrape_still_becomes_a_card(tmp_path, monkeypatch) -> None:
    import arelis.core.tool_results as tr

    monkeypatch.setattr(tr, "_CACHE_DIR", tmp_path)
    body = "Plant opened last week.\n" * 200
    prepared = prepare_tool_output(
        "scrape",
        body,
        data={"title": "example", "url": "https://example.com/long"},
    )
    assert prepared.summarized is True
    assert "tool_summary" in prepared.inject
    assert "full_ref:" in prepared.inject
