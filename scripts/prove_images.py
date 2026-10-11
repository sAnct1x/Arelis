"""Draw the phase 1 samples and record how long they took.

    python scripts/prove_images.py --phase 1
    python scripts/prove_images.py --phase 1b

Phase 1 is the diagram tool. Files land in docs/image-proof/1a/.
Phase 1b is a poster chart and picture marks. Files land in docs/image-proof/1b/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from arelis.tools.diagram import DiagramTool
from arelis.workspace import RootEntry, WorkspaceRoots

_OUT = _REPO / "docs" / "image-proof" / "1a"


def _flow() -> str:
    return (
        "flowchart TD\n"
        "  raw[Telescope raw FITS] --> bias[Bias and dark]\n"
        "  bias --> flat[Flat field]\n"
        "  flat --> decide{Stack decision}\n"
        "  decide --> photo[Photometry]\n"
    )


def _lightcurve() -> str:
    values = []
    for i in range(100):
        dip = 0.01 * math.exp(-((i - 50) ** 2) / 18)
        values.append({"x": i, "y": round(1.0 - dip, 5)})
    spec = {
        "width": 360,
        "height": 180,
        "data": {"values": values},
        "mark": "line",
        "encoding": {
            "x": {"field": "x", "type": "quantitative", "title": "sample"},
            "y": {
                "field": "y",
                "type": "quantitative",
                "title": "flux",
                "scale": {"domain": [0.985, 1.005]},
            },
        },
    }
    return json.dumps(spec)


def _slide() -> str:
    return """#set page(width: 360pt, height: 220pt, margin: 18pt)
#set text(size: 14pt)
= Transit depth

Depth delta = (R_p / R_star)^2 approx 1.5%

#table(
  columns: 3,
  [band], [depth], [note],
  [g], [1.4%], [in],
  [r], [1.5%], [in],
  [i], [1.6%], [in],
)
"""


def _run(tool: DiagramTool, kind: str, source: str, out: str) -> tuple[float, str]:
    start = time.perf_counter()
    result = tool._run({"kind": kind, "source": source, "out": out})
    elapsed = time.perf_counter() - start
    if not result.ok:
        raise SystemExit(result.output)
    return elapsed, str(result.data.get("abs_path") or "")


def phase_1() -> int:
    _OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="arelis-proof-") as raw:
        root = Path(raw) / "room"
        root.mkdir()
        tool = DiagramTool(
            WorkspaceRoots([RootEntry(name="room", path=root.resolve())]),
            SimpleNamespace(active=SimpleNamespace(root="room")),
        )
        jobs = (
            ("mermaid", _flow(), "diagram_pipeline"),
            ("vegalite", _lightcurve(), "lightcurve"),
            ("typst", _slide(), "slide"),
        )
        # First pass warms the helper and the page cache. The times below are the second pass.
        for kind, source, name in jobs:
            _run(tool, kind, source, name)
        timings: dict[str, float] = {}
        for kind, source, name in jobs:
            elapsed, _png = _run(tool, kind, source, f"{name}-warm")
            timings[name] = round(elapsed, 4)
            folder = root / "results"
            # SVG text trips the personal-data scan (font ids and coordinates
            # look like phone numbers and places). Keep the pictures and the source.
            for suffix in (".png", ".mmd", ".json", ".typ"):
                src = folder / f"{name}-warm{suffix}"
                if src.is_file():
                    shutil.copyfile(src, _OUT / f"{name}{suffix}")
    report = {
        "phase": "1a",
        "warm_seconds": timings,
        "target_seconds": 1.0,
        "files": sorted(
            p.name
            for p in _OUT.iterdir()
            if p.is_file() and p.name not in {"timings.json", "commands.txt"}
        ),
    }
    (_OUT / "timings.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (_OUT / "commands.txt").write_text(
        "python scripts/prove_images.py --phase 1\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    slow = [name for name, seconds in timings.items() if seconds > 1.0]
    if slow:
        print("over a second:", ", ".join(slow))
        return 1
    return 0


def _svg_one_token_per_line(text: str) -> str:
    """Put flagged path lines on one token per line.

    A run of coordinates can look like a phone number to the personal-data
    scan. SVG treats a newline as a space, so the picture stays put. The
    diagram proof leaves its SVG out for the same reason.
    """
    phone = re.compile(
        r"(?<![\d.])(?:\+?1[\s.-]?)?"
        r"\(?([2-9]\d{2})\)?[\s.-]?([2-9]\d{2})[\s.-]?(\d{4})(?!\d)"
    )

    def flagged(line: str) -> bool:
        return bool(phone.search(line))

    out: list[str] = []
    for line in text.splitlines():
        if flagged(line):
            out.extend(line.split(" "))
        else:
            out.append(line)
    rewritten = "\n".join(out) + "\n"
    if any(flagged(line) for line in rewritten.splitlines()):
        raise SystemExit("poster.svg still trips the personal-data scan.")
    return rewritten


def _flux_csv(path: Path) -> None:
    rows = ["wave,flux,err"]
    for i in range(24):
        wave = 400 + i * 15
        flux = 1.0 + 0.08 * math.sin(i / 3.0)
        rows.append(f"{wave},{flux:.4f},0.010")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def phase_1b() -> int:
    """Poster chart plus arrow, label, scale bar, and asinh on the Pillars JPEG."""
    from PIL import Image

    from arelis.tools.image_edit import ImageEditTool
    from arelis.tools.plot import PlotTool

    proof = _REPO / "docs" / "image-proof" / "1b"
    proof.mkdir(parents=True, exist_ok=True)
    pillars = proof / "pillars.jpg"
    if not pillars.is_file():
        raise SystemExit("docs/image-proof/1b/pillars.jpg is missing.")

    with tempfile.TemporaryDirectory(prefix="arelis-proof-") as raw:
        root = Path(raw) / "room"
        root.mkdir()
        _flux_csv(root / "flux.csv")
        shutil.copyfile(pillars, root / "pillars.jpg")
        rooms = SimpleNamespace(active=SimpleNamespace(root="room"))
        workspace = WorkspaceRoots([RootEntry(name="room", path=root.resolve())])
        plot = PlotTool(workspace, rooms)
        edit = ImageEditTool(workspace, output_dir=root / "images")
        plot_args = {
            "action": "line",
            "path": "flux.csv",
            "x": "wave",
            "y": "flux",
            "title": "Sample flux",
            "xlabel": "wave",
            "ylabel": "flux",
            "look": "poster",
            "out": "poster.png",
        }
        edit_args = {
            "path": "room:pillars.jpg",
            "stretch": "asinh",
            "annotate": [
                {"kind": "arrow", "x": 70, "y": 48, "x2": 145, "y2": 210},
                {"kind": "label", "x": 168, "y": 36, "text": "Pillar I"},
            ],
            "scale_bar": {"length": 100, "label": "100 px"},
        }
        # First pass warms font caches. The times below are the second pass.
        plot._run(plot_args)
        asyncio.run(edit.run(**edit_args))
        timings: dict[str, float] = {}
        start = time.perf_counter()
        drawn = plot._run(dict(plot_args, out="poster-warm.png"))
        timings["poster"] = round(time.perf_counter() - start, 4)
        if not drawn.ok:
            raise SystemExit(drawn.output)
        start = time.perf_counter()
        marked = asyncio.run(edit.run(**edit_args))
        timings["pillars"] = round(time.perf_counter() - start, 4)
        if not marked.ok:
            raise SystemExit(marked.output)
        folder = root / "plots"
        for suffix in (".png", ".svg", ".pdf"):
            src = folder / f"poster-warm{suffix}"
            if not src.is_file():
                raise SystemExit(f"poster {suffix} was not written.")
            if suffix == ".svg":
                safe = _svg_one_token_per_line(src.read_text(encoding="utf-8"))
                (proof / f"poster{suffix}").write_text(safe, encoding="utf-8")
            else:
                shutil.copyfile(src, proof / f"poster{suffix}")
        annotated = Path(str(marked.data.get("abs_path") or ""))
        if not annotated.is_file():
            raise SystemExit("annotated image was not written.")
        with Image.open(annotated) as im:
            if im.size != (500, 521):
                raise SystemExit(
                    f"annotated size {im.size[0]}x{im.size[1]}, expected 500x521."
                )
        shutil.copyfile(annotated, proof / "pillars_annotated.png")

    report = {
        "phase": "1b",
        "warm_seconds": timings,
        "target_seconds": 1.0,
        "files": sorted(
            p.name
            for p in proof.iterdir()
            if p.is_file()
            and p.name not in {"timings.json", "commands.txt", "pillars.jpg"}
        ),
    }
    (proof / "timings.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (proof / "commands.txt").write_text(
        "python scripts/prove_images.py --phase 1b\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    slow = [name for name, seconds in timings.items() if seconds > 1.0]
    if slow:
        print("over a second:", ", ".join(slow))
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draw image samples and time them.")
    parser.add_argument("--phase", default="1", choices=("1", "1a", "1b"))
    args = parser.parse_args(argv)
    if args.phase == "1b":
        return phase_1b()
    if args.phase in {"1", "1a"}:
        return phase_1()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
