"""Draw a diagram from text and save a picture plus the text that made it.

A room with a folder gets the files in that project's results folder. Orbit
lands under outputs/diagrams/. Same decision as a chart: a room whose folder
is gone, or a room with no folder, uses the shared folder and says so.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any

from arelis.paths import display_path, ensure, outputs_dir
from arelis.rooms import RoomStore
from arelis.tools.base import ToolResult
from arelis.tools.diagram_render import (
    render_mermaid,
    render_svg,
    render_typst,
    render_vegalite,
)
from arelis.workspace import WorkspaceRoots

_KINDS = ("mermaid", "vegalite", "typst", "svg")
_SOURCE_SUFFIX = {
    "mermaid": ".mmd",
    "vegalite": ".json",
    "typst": ".typ",
    "svg": ".svg",
}
_RENDER = {
    "mermaid": render_mermaid,
    "vegalite": render_vegalite,
    "typst": render_typst,
    "svg": render_svg,
}
_MAX_SOURCE = 200_000
_SAFE_STEM = re.compile(r"[^a-zA-Z0-9._-]+")


def _contained(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except (ValueError, OSError):
        return False


def _free_stem(folder: Path, stem: str, suffixes: tuple[str, ...]) -> str:
    number = 1
    while number < 1000:
        candidate = stem if number == 1 else f"{stem}-{number}"
        if all(not (folder / f"{candidate}{suffix}").exists() for suffix in suffixes):
            return candidate
        number += 1
    raise ValueError("I could not find a free name for that diagram.")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class DiagramTool:
    name = "diagram"
    description = (
        "Draw a diagram from text. "
        "kind is mermaid (a flowchart), vegalite (a chart), typst (a slide or "
        "an equation), or svg (a drawing). source is the text. out is an "
        "optional file name. A room with a folder saves in that room's results "
        "folder, otherwise your diagrams folder. Not image and not plot. Then "
        "look once with vision. Allow is required."
    )
    risk = "write"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": list(_KINDS),
                "description": "mermaid, vegalite, typst, or svg",
            },
            "source": {
                "type": "string",
                "description": "The diagram text to draw",
            },
            "out": {
                "type": "string",
                "description": "File name only. Lands beside the picture.",
            },
        },
        "required": ["kind", "source"],
    }

    def __init__(
        self,
        workspace: WorkspaceRoots | None = None,
        rooms: RoomStore | None = None,
    ) -> None:
        self.workspace = workspace
        self.rooms = rooms

    def drop_dir(self) -> Path:
        return ensure(outputs_dir() / "diagrams")

    def room_results_dir(self) -> Path | None:
        """Project/results when a room with a live folder is open."""
        room = None if self.rooms is None else self.rooms.active
        if room is None or not room.root or self.workspace is None:
            return None
        entry = self.workspace.root_named(room.root)
        if entry is None:
            return None
        return ensure(entry.path / "results")

    def out_dir(self) -> tuple[Path, str]:
        """(folder, short where-it-landed note)."""
        room_dir = self.room_results_dir()
        if room_dir is not None:
            return room_dir, "this room's results folder"
        room = None if self.rooms is None else self.rooms.active
        if room is not None and room.root:
            return (
                self.drop_dir(),
                "your diagrams folder, this room's folder is not a project any more",
            )
        if room is not None:
            return (
                self.drop_dir(),
                "your diagrams folder, this room has no folder",
            )
        return self.drop_dir(), "your diagrams folder"

    def preview_path(self, args: dict[str, Any] | None = None) -> Path:
        """Where the picture will land, without writing it."""
        args = args or {}
        kind = str(args.get("kind") or "mermaid").strip().lower()
        if kind not in _RENDER:
            kind = "mermaid"
        folder, _where = self.out_dir()
        _svg, png, _source = self._dests(args, kind, folder)
        return png

    async def run(self, **kwargs: Any) -> ToolResult:
        kind = str(kwargs.get("kind") or "").strip().lower()
        # A drawing is painted on the window thread. Moving that work to a
        # worker and waiting for the window deadlocks when the window thread
        # is the one running this call (tests, and a headless proof).
        if kind == "svg":
            return self._run(kwargs)
        return await asyncio.to_thread(self._run, kwargs)

    def _run(self, kwargs: dict[str, Any]) -> ToolResult:
        kind = str(kwargs.get("kind") or "").strip().lower()
        if kind not in _RENDER:
            return ToolResult(
                ok=False,
                output=(
                    "I do not know that kind of diagram. "
                    "Use mermaid, vegalite, typst, or svg."
                ),
                data={"fail_class": "fail:kind"},
            )
        source = kwargs.get("source")
        text = source if isinstance(source, str) else "" if source is None else str(source)
        if not text.strip():
            return ToolResult(
                ok=False,
                output="Tell me what to draw.",
                data={"fail_class": "fail:args"},
            )
        if len(text) > _MAX_SOURCE:
            return ToolResult(
                ok=False,
                output="That diagram text is too long. Shorten it and try again.",
                data={"fail_class": "fail:args"},
            )
        folder, where = self.out_dir()
        try:
            svg_path, png_path, source_path = self._dests(kwargs, kind, folder)
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc), data={"fail_class": "fail:args"})
        error = _RENDER[kind](text, svg_path, png_path)
        if error:
            self._drop(svg_path, png_path, source_path)
            return ToolResult(
                ok=False,
                output=error,
                data={"fail_class": "fail:render"},
            )
        if kind != "svg":
            try:
                _write_text(source_path, text)
            except OSError:
                self._drop(svg_path, png_path, source_path)
                return ToolResult(
                    ok=False,
                    output="I could not save that diagram. Try again.",
                    data={"fail_class": "fail:write"},
                )
        shown = display_path(png_path)
        return ToolResult(
            ok=True,
            output=(
                f"Saved {shown} in {where}. "
                "Take one look at the picture with vision to check it."
            ),
            data={
                "kind": kind,
                "path": shown,
                "abs_path": str(png_path.resolve()),
                "svg": display_path(svg_path),
                "source_path": display_path(svg_path if kind == "svg" else source_path),
                "format": "png",
                "title": png_path.stem,
                "where": where,
            },
        )

    def _dests(
        self, kwargs: dict[str, Any], kind: str, folder: Path
    ) -> tuple[Path, Path, Path]:
        raw = str(kwargs.get("out") or "").strip().replace("\\", "/")
        leaf = Path(raw).name if raw else "diagram"
        stem = _SAFE_STEM.sub("-", Path(leaf).stem).strip(".-") or "diagram"
        suffix = _SOURCE_SUFFIX[kind]
        suffixes = (".svg", ".png") if kind == "svg" else (suffix, ".svg", ".png")
        stem = _free_stem(folder, stem, suffixes)
        svg_path = folder / f"{stem}.svg"
        png_path = folder / f"{stem}.png"
        source_path = svg_path if kind == "svg" else folder / f"{stem}{suffix}"
        if not all(_contained(path, folder) for path in (svg_path, png_path, source_path)):
            stem = _free_stem(folder, "diagram", suffixes)
            svg_path = folder / f"{stem}.svg"
            png_path = folder / f"{stem}.png"
            source_path = svg_path if kind == "svg" else folder / f"{stem}{suffix}"
        return svg_path, png_path, source_path

    @staticmethod
    def _drop(*paths: Path) -> None:
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue
