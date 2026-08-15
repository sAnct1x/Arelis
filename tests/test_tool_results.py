"""Fat-tool summary cards (Wave 1)."""

from __future__ import annotations

from arelis.core.tool_results import FAT_TOOLS, prepare_tool_output


def test_small_body_passes_through(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("arelis.core.tool_results._CACHE_DIR", tmp_path)
    out = prepare_tool_output("scrape", "short body", force=False)
    assert not out.summarized
    assert out.inject == "short body"
    assert out.full_ref is None


def test_fat_scrape_builds_card(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("arelis.core.tool_results._CACHE_DIR", tmp_path)
    body = "Title line\n\n" + ("Important point about batteries. " * 80)
    out = prepare_tool_output(
        "scrape",
        body,
        data={"title": "Battery note", "url": "https://example.com/a"},
        force=True,
    )
    assert out.summarized
    assert out.full_ref
    assert "tool_summary" in out.inject
    assert "untrusted" in out.inject.lower() or "not instructions" in out.inject
    assert "Battery note" in out.inject
    assert "full_ref:" in out.inject
    assert "https://example.com/a" in out.inject
    assert tmp_path.exists()


def test_non_fat_tool_never_summarized(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("arelis.core.tool_results._CACHE_DIR", tmp_path)
    body = "x" * 5000
    out = prepare_tool_output("calculator", body, force=True)
    assert not out.summarized
    assert "scrape" in FAT_TOOLS
    assert "web_fetch" in FAT_TOOLS
