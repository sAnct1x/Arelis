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
import subprocess
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


def _samples(explicit: str) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("ARELIS_IMAGE_SAMPLES", "")
    if env:
        candidates.append(Path(env))
    candidates.append(Path("/tmp/image-tools-data"))
    for path in candidates:
        if (path / "cat.jpg").is_file() and (path / "pillars.jpg").is_file():
            return path
    raise SystemExit("cat.jpg and pillars.jpg were not found")


def _available_mb() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except OSError:
        return 0
    return 0


def _rss_mb() -> int:
    import resource

    # Linux reports kilobytes. macOS reports bytes.
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return int(raw / (1024 * 1024))
    return int(raw / 1024)


def _proof_root() -> Path:
    return _REPO / "docs" / "image-proof" / "2"


def _run_job(kind: str, samples: Path, out: Path) -> dict[str, object]:
    """One model, in this process, so the RSS number is only this job."""
    from PIL import Image

    from arelis.tools.image_matting import cutout
    from arelis.tools.image_models import ensure_model
    from arelis.tools.image_upscale import upscale_image

    out.mkdir(parents=True, exist_ok=True)
    if kind in {"isnet", "birefnet"}:
        model = "isnet-general-use" if kind == "isnet" else "birefnet-general-lite"
        image = Image.open(samples / "cat.jpg")
        started = time.perf_counter()
        ensure_model(model)
        downloaded = time.perf_counter() - started
        cutout(image, model)
        warm_started = time.perf_counter()
        result = cutout(image, model)
        warm = time.perf_counter() - warm_started
        dest = out / f"cat-nobg-{kind}.png"
        result.save(dest)
        return {
            "kind": kind,
            "model": model,
            "download_s": round(downloaded, 2),
            "warm_s": round(warm, 2),
            "peak_rss_mb": _rss_mb(),
            "file": dest.name,
            "size": list(result.size),
        }

    image = Image.open(samples / "pillars.jpg").convert("RGB")
    started = time.perf_counter()
    ensure_model("realesrgan-x4v3")
    downloaded = time.perf_counter() - started
    upscale_image(image, 4)
    warm_started = time.perf_counter()
    result = upscale_image(image, 4)
    warm = time.perf_counter() - warm_started
    dest = out / "pillars-x4.png"
    result.save(dest)
    lanczos = image.resize((image.width * 4, image.height * 4), Image.Resampling.LANCZOS)
    box = (image.width * 2 - 80, image.height * 2 - 80, image.width * 2 + 80, image.height * 2 + 80)
    left = result.crop(box)
    right = lanczos.crop(box)
    compare = Image.new("RGB", (left.width + right.width + 8, left.height), (0, 0, 0))
    compare.paste(left, (0, 0))
    compare.paste(right, (left.width + 8, 0))
    compare.save(out / "pillars-crop-compare.jpg", quality=90)
    return {
        "kind": "upscale",
        "model": "realesrgan-x4v3",
        "download_s": round(downloaded, 2),
        "warm_s": round(warm, 2),
        "peak_rss_mb": _rss_mb(),
        "file": dest.name,
        "size": list(result.size),
        "lanczos_crop": "pillars-crop-compare.jpg",
    }


def _magenta(out: Path) -> str | None:
    from PIL import Image

    names = ["cat-nobg-isnet.png", "cat-nobg-birefnet.png"]
    frames = []
    for name in names:
        path = out / name
        if not path.is_file():
            continue
        rgba = Image.open(path).convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 0, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        frames.append(bg)
    if not frames:
        return None
    gap = 8
    width = sum(frame.width for frame in frames) + gap * (len(frames) - 1)
    height = max(frame.height for frame in frames)
    sheet = Image.new("RGB", (width, height), (255, 0, 255))
    x = 0
    for frame in frames:
        sheet.paste(frame, (x, 0))
        x += frame.width + gap
    sheet.save(out / "cat-magenta-compare.jpg", quality=90)
    return "cat-magenta-compare.jpg"


def phase_2(data: str, job: str) -> int:
    os.environ.setdefault("ARELIS_DATA_DIR", "/tmp/arelis-image-proof")
    samples = _samples(data)
    out = _proof_root()
    if job:
        report = _run_job(job, samples, out)
        print(json.dumps(report))
        return 0

    out.mkdir(parents=True, exist_ok=True)
    jobs = ["isnet", "upscale"]
    available = _available_mb()
    skipped = ""
    if available >= 8000:
        jobs.insert(1, "birefnet")
    else:
        skipped = (
            f"BiRefNet needs 8 GB free and this machine had {available} MB, so it was skipped."
        )
    rows = []
    for name in jobs:
        proc = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--phase",
                "2",
                "--job",
                name,
                "--data",
                str(samples),
            ],
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "ARELIS_DATA_DIR": os.environ.get(
                    "ARELIS_DATA_DIR", "/tmp/arelis-image-proof"
                ),
            },
        )
        if proc.returncode != 0:
            sys.stderr.write(proc.stdout)
            sys.stderr.write(proc.stderr)
            return proc.returncode
        line = proc.stdout.strip().splitlines()[-1]
        rows.append(json.loads(line))
    magenta = _magenta(out)
    report = {
        "phase": "2",
        "jobs": rows,
        "magenta": magenta,
        "skipped": skipped,
        "targets_s": {"isnet": 2.5, "birefnet": 15.0, "upscale": 4.0},
        "files": sorted(
            path.name
            for path in out.iterdir()
            if path.is_file() and path.name not in {"timings.json", "commands.txt"}
        ),
    }
    (out / "timings.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "commands.txt").write_text(
        "python scripts/prove_images.py --phase 2\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    slow = [
        str(row["kind"])
        for row in rows
        if float(row["warm_s"]) > float(report["targets_s"][str(row["kind"])])
    ]
    if slow:
        print("over target:", ", ".join(slow))
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draw image samples and time them.")
    parser.add_argument("--phase", default="1", choices=("1", "1a", "2"))
    parser.add_argument("--job", default="", choices=("", "isnet", "birefnet", "upscale"))
    parser.add_argument("--data", default="")
    args = parser.parse_args(argv)
    if args.phase in {"1", "1a"}:
        return phase_1()
    if args.phase == "2":
        return phase_2(args.data, args.job)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
