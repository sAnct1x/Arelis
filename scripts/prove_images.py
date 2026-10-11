"""Draw the phase 1 diagram samples and record how long they took.

    python scripts/prove_images.py --phase 1

Phase 1 here is the diagram tool only. Poster charts and picture notes are a
later change. Files land in docs/image-proof/1a/.
"""

from __future__ import annotations

import argparse
import json
import math
import os
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draw diagram samples and time them.")
    parser.add_argument("--phase", default="1", choices=("1", "1a"))
    args = parser.parse_args(argv)
    if args.phase in {"1", "1a"}:
        return phase_1()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
