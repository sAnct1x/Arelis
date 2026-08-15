from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from arelis.config import load_config
from arelis.tools.analyze import AnalyzeTool
from arelis.tools.code_workspace import CodeWorkspaceTool
from arelis.tools.safety import resolve_within_roots
from arelis.workspace import AmbiguousPathError, RootEntry, WorkspaceRoots


def _two_projects(tmp_path: Path) -> WorkspaceRoots:
    a = tmp_path / "arelis"
    b = tmp_path / "interferometer"
    a.mkdir()
    b.mkdir()
    return WorkspaceRoots(
        [
            RootEntry(name="arelis", path=a.resolve()),
            RootEntry(name="interferometer", path=b.resolve()),
        ]
    )


def test_external_read_grant_allows_absolute_read(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret-ish", encoding="utf-8")
    ws = WorkspaceRoots.from_paths([str(root)])

    with pytest.raises(PermissionError):
        ws.resolve(str(outside))
    assert ws.grant_external_read(outside) == outside.resolve()
    hit = ws.resolve_read(str(outside))
    assert hit.path == outside.resolve()
    assert hit.root_name == "external"
    # Writes still sandboxed.
    with pytest.raises(PermissionError):
        ws.resolve(str(outside), for_create=True)
    ws.clear_external_reads()
    with pytest.raises(PermissionError):
        ws.resolve_read(str(outside))


@pytest.mark.asyncio
async def test_workspace_tool_reads_granted_external(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "note.txt"
    outside.write_text("hello external", encoding="utf-8")
    ws = WorkspaceRoots.from_paths([str(root)])
    ws.grant_external_read(outside)
    tool = CodeWorkspaceTool(ws)
    result = await tool.run(action="read", path=str(outside))
    assert result.ok
    assert "hello external" in result.output
    # edit must still fail outside roots
    denied = await tool.run(
        action="edit", path=str(outside), old="hello", new="bye"
    )
    assert not denied.ok


def test_single_root_bare_path_unchanged(tmp_path: Path) -> None:
    root = tmp_path / "only"
    root.mkdir()
    (root / "notes.txt").write_text("hi", encoding="utf-8")
    ws = WorkspaceRoots.from_paths([str(root)])
    hit = ws.resolve("notes.txt")
    assert hit.path == (root / "notes.txt").resolve()
    assert hit.root_name == "only"
    assert hit.qualified(multi=False) == "notes.txt"


def test_readme_stem_resolves_to_readme_md(tmp_path: Path) -> None:
    """Operator Open typed `readme` while the file is README.md (S06)."""
    root = tmp_path / "proj"
    root.mkdir()
    target = root / "README.md"
    target.write_text("# hi", encoding="utf-8")
    ws = WorkspaceRoots.from_paths([str(root)])
    hit = ws.resolve("readme")
    assert hit.path == target.resolve()


def test_case_insensitive_filename_resolve(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    target = root / "Notes.TXT"
    target.write_text("x", encoding="utf-8")
    ws = WorkspaceRoots.from_paths([str(root)])
    hit = ws.resolve("notes.txt")
    assert hit.path == target.resolve()


def test_qualified_path_resolves_to_named_root(tmp_path: Path) -> None:
    ws = _two_projects(tmp_path)
    target = ws.roots[1].path / "data" / "notes.txt"
    target.parent.mkdir(parents=True)
    target.write_text("scope", encoding="utf-8")
    hit = ws.resolve("interferometer:data/notes.txt")
    assert hit.path == target.resolve()
    assert hit.root_name == "interferometer"
    assert hit.qualified(multi=True) == "interferometer:data/notes.txt"


def test_bare_path_unique_across_roots(tmp_path: Path) -> None:
    ws = _two_projects(tmp_path)
    only = ws.roots[1].path / "unique.txt"
    only.write_text("x", encoding="utf-8")
    hit = ws.resolve("unique.txt")
    assert hit.root_name == "interferometer"
    assert hit.path == only.resolve()


def test_bare_path_ambiguous_refuses(tmp_path: Path) -> None:
    ws = _two_projects(tmp_path)
    (ws.roots[0].path / "notes.txt").write_text("a", encoding="utf-8")
    (ws.roots[1].path / "notes.txt").write_text("b", encoding="utf-8")
    with pytest.raises(AmbiguousPathError, match="more than one project"):
        ws.resolve("notes.txt")


@pytest.mark.asyncio
async def test_bare_write_lands_in_active_not_first_root(tmp_path: Path) -> None:
    ws = _two_projects(tmp_path)
    ws.set_active("interferometer", persist=False)
    tool = CodeWorkspaceTool(ws)
    result = await tool.run(action="write", path="fresh.txt", content="new")
    assert result.ok
    assert not (ws.roots[0].path / "fresh.txt").exists()
    assert (ws.roots[1].path / "fresh.txt").read_text(encoding="utf-8") == "new"
    assert result.data["path"] == "interferometer:fresh.txt"


def test_traversal_inside_qualifier_refused(tmp_path: Path) -> None:
    ws = _two_projects(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(PermissionError, match="outside allowed workspace roots"):
        ws.resolve("arelis:../secret.txt")


def test_unknown_qualifier_refused(tmp_path: Path) -> None:
    ws = _two_projects(tmp_path)
    with pytest.raises(PermissionError, match="Unknown project"):
        ws.resolve("nope:file.txt")


def test_flat_list_config_still_loads(tmp_path: Path) -> None:
    a = tmp_path / "proj_a"
    b = tmp_path / "proj_b"
    a.mkdir()
    b.mkdir()
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(
        yaml.dump({"workspace": {"roots": [str(a), str(b)]}, "persona_file": "persona/arelis.md"}),
        encoding="utf-8",
    )
    data = load_config(cfg_path)
    names = [r["name"] for r in data["workspace"]["named_roots"]]
    assert names == ["proj_a", "proj_b"]
    assert data["workspace"]["roots"] == [str(a.resolve()), str(b.resolve())]


def test_named_config_and_duplicate_name_refused(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(
        yaml.dump(
            {
                "workspace": {
                    "roots": [
                        {"name": "same", "path": str(a)},
                        {"name": "same", "path": str(b)},
                    ]
                },
                "persona_file": "persona/arelis.md",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Duplicate workspace root name"):
        load_config(cfg_path)


def test_switch_active_changes_create_target(tmp_path: Path) -> None:
    ws = _two_projects(tmp_path)
    ws.set_active("arelis", persist=False)
    first = ws.resolve("new.txt", for_create=True)
    assert first.root_name == "arelis"
    ws.set_active("interferometer", persist=False)
    second = ws.resolve("new.txt", for_create=True)
    assert second.root_name == "interferometer"
    assert first.qualified(multi=True) == "arelis:new.txt"
    assert second.qualified(multi=True) == "interferometer:new.txt"


def test_resolve_within_roots_wrapper_returns_resolved_path(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    (root / "f.txt").write_text("x", encoding="utf-8")
    hit = resolve_within_roots("f.txt", [root.resolve()])
    assert hit.path == (root / "f.txt").resolve()
    assert hit.root_name == "r"


@pytest.mark.asyncio
async def test_list_without_path_returns_project_names(tmp_path: Path) -> None:
    ws = _two_projects(tmp_path)
    tool = CodeWorkspaceTool(ws)
    result = await tool.run(action="list")
    assert result.ok
    assert "[project] arelis (active)" in result.output
    assert "[project] interferometer" in result.output


@pytest.mark.asyncio
async def test_analyze_shares_workspace_roots(tmp_path: Path) -> None:
    ws = _two_projects(tmp_path)
    table = ws.roots[1].path / "t.csv"
    table.write_text("a,b\n1,2\n", encoding="utf-8")
    tool = AnalyzeTool(ws)
    result = await tool.run(path="interferometer:t.csv", action="summary")
    assert result.ok
    assert result.data["root_name"] == "interferometer"


def test_memory_trace_keeps_qualified_identity_after_switch(tmp_path: Path) -> None:
    from arelis.core.memory import tool_trace_entry

    ws = _two_projects(tmp_path)
    (ws.roots[0].path / "notes.txt").write_text("a", encoding="utf-8")
    hit = ws.resolve("arelis:notes.txt")
    entry = tool_trace_entry(
        "workspace",
        {"action": "read", "path": "notes.txt"},
        True,
        resolved_path=hit.qualified(multi=True),
    )
    assert "arelis:notes.txt" in entry
    ws.set_active("interferometer", persist=False)
    again = ws.resolve("arelis:notes.txt")
    assert again.path == hit.path


def test_compose_stt_prompt_includes_project_names(tmp_path: Path) -> None:
    from arelis.workspace import compose_stt_initial_prompt

    ws = _two_projects(tmp_path)
    prompt = compose_stt_initial_prompt(
        {"voice": {"stt": {"initial_prompt": "Arelis, Ollama"}}},
        ws,
    )
    assert "arelis" in prompt
    assert "interferometer" in prompt
    assert "Ollama" in prompt


def test_read_only_root_rejects_write_and_edit(tmp_path: Path) -> None:
    root = tmp_path / "papers"
    root.mkdir()
    (root / "note.txt").write_text("keep", encoding="utf-8")
    ws = WorkspaceRoots(
        [RootEntry(name="papers", path=root.resolve(), read_only=True)]
    )
    with pytest.raises(PermissionError, match="read-only"):
        ws.resolve("new.txt", for_create=True)
    with pytest.raises(PermissionError, match="read-only"):
        ws.resolve("note.txt", for_write=True)
    # Reads still work.
    hit = ws.resolve_read("note.txt")
    assert hit.path == (root / "note.txt").resolve()


@pytest.mark.asyncio
async def test_workspace_tool_honors_read_only(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    root.mkdir()
    (root / "a.txt").write_text("old", encoding="utf-8")
    ws = WorkspaceRoots(
        [RootEntry(name="archive", path=root.resolve(), read_only=True)]
    )
    tool = CodeWorkspaceTool(ws)
    denied = await tool.run(action="write", path="a.txt", content="new")
    assert not denied.ok
    assert "read-only" in denied.output.lower()
    edit = await tool.run(action="edit", path="a.txt", old="old", new="new")
    assert not edit.ok
    assert "read-only" in edit.output.lower()
    assert (root / "a.txt").read_text(encoding="utf-8") == "old"


def test_stale_active_project_falls_back_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    a = tmp_path / "arelis"
    a.mkdir()
    with caplog.at_level("WARNING", logger="arelis.workspace"):
        ws = WorkspaceRoots(
            [RootEntry(name="arelis", path=a.resolve())],
            active="interferometer",
        )
    assert ws.active == "arelis"
    assert any("interferometer" in r.message for r in caplog.records)


def test_replace_roots_keeps_preferred_active(tmp_path: Path) -> None:
    a = tmp_path / "arelis"
    b = tmp_path / "interferometer"
    a.mkdir()
    b.mkdir()
    ws = WorkspaceRoots(
        [
            RootEntry(name="arelis", path=a.resolve()),
            RootEntry(name="interferometer", path=b.resolve()),
        ],
        active="interferometer",
    )
    ws.replace_roots(
        [
            RootEntry(name="arelis", path=a.resolve()),
            RootEntry(name="interferometer", path=b.resolve(), read_only=True),
        ],
        preferred_active="interferometer",
        persist=False,
    )
    assert ws.active == "interferometer"
    with pytest.raises(PermissionError, match="read-only"):
        ws.resolve("x.txt", for_create=True)


def test_prompt_line_mentions_read_only(tmp_path: Path) -> None:
    a = tmp_path / "arelis"
    b = tmp_path / "docs"
    a.mkdir()
    b.mkdir()
    ws = WorkspaceRoots(
        [
            RootEntry(name="arelis", path=a.resolve()),
            RootEntry(name="docs", path=b.resolve(), read_only=True),
        ]
    )
    line = ws.prompt_line()
    assert line is not None
    assert "docs" in line
    assert "Read-only" in line


@pytest.mark.asyncio
async def test_project_slash_command_switches(tmp_path: Path) -> None:
    from arelis.core.bus import EventBus
    from arelis.core.events import Event, EventType
    from arelis.core.orchestrator import Orchestrator
    from arelis.tools.base import ToolRegistry

    class _StubRouter:
        default_role = "fast"
        active_model = None
        active_role = None
        models = {"fast": "mock", "research": "mock", "code": "mock"}

        def model_for(self, role=None):
            return "mock"

        async def ensure_role(self, role, *, force: bool = False):
            del force
            return "mock"

        def mark_sticky(self, role) -> None:
            return None

        async def stream(self, role, messages, **kwargs):
            if False:
                yield None

    ws = _two_projects(tmp_path)
    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    Orchestrator(
        bus,
        _StubRouter(),  # type: ignore[arg-type]
        ToolRegistry(),
        {"_persona_path": str(tmp_path / "missing.md"), "workspace": {}, "voice": {"enabled": False}},
        workspace=ws,
    )
    task = asyncio.create_task(bus.run())
    await bus.publish(Event(EventType.USER_MESSAGE, {"text": "/project interferometer"}))
    await bus.drain()
    bus.stop()
    task.cancel()
    assert ws.active == "interferometer"
    done = [e for e in events if e.type == EventType.ASSISTANT_DONE]
    assert done and "interferometer" in done[-1].payload["text"]
