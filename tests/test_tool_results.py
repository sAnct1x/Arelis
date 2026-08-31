"""Fat-tool summary cards (Wave 1)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from arelis.core.tool_results import FAT_TOOLS, prepare_tool_output, prune_tool_cache


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
    assert "doc_extract" in FAT_TOOLS
    assert "research_report" in FAT_TOOLS
    assert "workspace" in FAT_TOOLS


def test_fat_workspace_source_py_not_summarized(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("arelis.core.tool_results._CACHE_DIR", tmp_path)
    body = "def action_is_destructive():\n    return True\n" + ("x" * 2800)
    out = prepare_tool_output(
        "workspace",
        body,
        data={"path": "arelis/core/policy.py"},
        force=True,
    )
    assert not out.summarized
    assert out.inject == body
    assert out.full_ref is None
    assert "tool_summary" not in out.inject


def test_fat_workspace_arelis_path_not_summarized(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("arelis.core.tool_results._CACHE_DIR", tmp_path)
    body = "# architecture notes\n" + ("gate keep " * 400)
    out = prepare_tool_output(
        "workspace",
        body,
        data={
            "path": "arelis/core/tool_subset.py",
            "abs_path": r"C:\Users\you\Documents\Arelis\arelis\core\tool_subset.py",
        },
        force=True,
    )
    assert not out.summarized
    assert out.inject == body


def test_fat_workspace_docs_md_not_summarized(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("arelis.core.tool_results._CACHE_DIR", tmp_path)
    body = "# Earth zone\n" + ("room id is physics. " * 200)
    out = prepare_tool_output(
        "workspace",
        body,
        data={"path": "docs/architecture.md"},
        force=True,
    )
    assert not out.summarized
    assert out.inject == body


def test_fat_workspace_nonsource_still_summarized(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("arelis.core.tool_results._CACHE_DIR", tmp_path)
    body = "2026-08-31 00:00:00 INFO started\n" + ("LOG LINE about runtime. " * 200)
    out = prepare_tool_output(
        "workspace",
        body,
        data={"path": "data/runtime.log"},
        force=True,
    )
    assert out.summarized
    assert "tool_summary" in out.inject
    assert out.inject != body
    assert out.full_ref


def test_prune_tool_cache_drops_old_files(tmp_path) -> None:
    old = tmp_path / "old.txt"
    fresh = tmp_path / "fresh.txt"
    old.write_text("gone", encoding="utf-8")
    fresh.write_text("keep", encoding="utf-8")
    age = (datetime.now(UTC) - timedelta(hours=60)).timestamp()
    os.utime(old, (age, age))
    assert prune_tool_cache(max_age_hours=48, cache_dir=tmp_path) == 1
    assert not old.exists()
    assert fresh.exists()


def test_prune_tool_cache_zero_clears_all(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "b.txt").write_text("y", encoding="utf-8")
    assert prune_tool_cache(max_age_hours=0, cache_dir=tmp_path) == 2
    assert list(tmp_path.iterdir()) == []
