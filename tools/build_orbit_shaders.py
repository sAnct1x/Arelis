"""Compile the Filament orbit's ShaderEffect stages (arelis/ui/persona_face/qq3d/orbit) to .qsb.

Qt Quick's ShaderEffect only takes baked shaders, so the .qsb files are committed beside their
GLSL and ship with the package (pyproject `ui/persona_face/qq3d/orbit/*`). Run this after
editing a stage: each one is common.glsl (the uniform block and the orbit's path) plus its body.

    python tools/build_orbit_shaders.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ORBIT = Path(__file__).resolve().parents[1] / "arelis" / "ui" / "persona_face" / "qq3d" / "orbit"
STAGES = (
    "strand.vert",
    "thread.vert",
    "line.frag",
    "dust.vert",
    "dust.frag",
    "overlay.frag",
    "tree.vert",
    "pulse.vert",
    "flare.vert",
    "flare.frag",
    "glow.vert",
    "glow.frag",
    "pool.vert",
    "pool.frag",
)
TARGETS = ["--glsl", "100es,120,150", "--hlsl", "50", "--msl", "12"]


def qsb_tool() -> str:
    import PySide6

    exe = Path(PySide6.__file__).parent / ("qsb.exe" if sys.platform == "win32" else "qsb")
    return str(exe) if exe.is_file() else "qsb"


def main() -> int:
    common = (ORBIT / "common.glsl").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        for name in STAGES:
            src = Path(tmp) / name
            body = (ORBIT / name).read_text(encoding="utf-8")
            src.write_text("#version 440\n" + common + "\n" + body)
            out = ORBIT / f"{name}.qsb"
            subprocess.run([qsb_tool(), *TARGETS, "-o", str(out), str(src)], check=True)
            print(f"{out.name}: {out.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
