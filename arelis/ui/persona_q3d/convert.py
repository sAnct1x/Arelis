"""Convert ellah-anim.glb with balsam and fix up the result for the aether port.

  * balsam generates every Timeline enabled and running; they are switched off so the
    caller drives one clip at a time.
  * glTF clips that hold a bone at its rest pose (the thumbs' Thumb2/Thumb3 rotations in
    every clip but Talking) come out of balsam with that track dropped, so a bone keeps
    the last value another clip gave it. fill_missing_tracks() gives every Timeline a
    constant rest-pose track for each node+property some other Timeline animates.

The output is derived from the private model: keep it outside the repo.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

BALSAM = "balsam"


def _blocks(qml: str, head: str) -> list[tuple[int, int]]:
    """(start, end) spans of every `head {` ... matching `}` block."""
    spans = []
    for m in re.finditer(r"\b" + re.escape(head) + r"\s*\{", qml):
        depth = 0
        for k in range(m.end() - 1, len(qml)):
            depth += {"{": 1, "}": -1}.get(qml[k], 0)
            if depth == 0:
                spans.append((m.start(), k + 1))
                break
    return spans


def _rest_values(qml: str) -> dict[tuple[str, str], str]:
    rest = {}
    for m in re.finditer(r"id:\s*(\w+)\s*\n((?:\s*\w+:\s*[^\n]+\n)+)", qml):
        for p in re.finditer(r"(position|rotation|scale):\s*([^\n]+)", m.group(2)):
            rest[(m.group(1), p.group(1))] = p.group(2).strip()
    return rest


def fill_missing_tracks(qml: str) -> tuple[str, int]:
    """Add a constant rest-pose KeyframeGroup to each Timeline for every track it lacks."""
    timelines = _blocks(qml, "Timeline")
    tracks = [
        set(re.findall(r'target:\s*(\w+)\s*\n\s*property:\s*"(\w+)"', qml[a:b]))
        for a, b in timelines
    ]
    union = set().union(*tracks) if tracks else set()
    rest = _rest_values(qml)
    out, last, added = [], 0, 0
    for (a, b), have in zip(timelines, tracks, strict=True):
        missing = sorted(t for t in union - have if t in rest)
        add = "".join(
            f"        KeyframeGroup {{\n            target: {node}\n"
            f'            property: "{prop}"\n'
            f"            Keyframe {{ frame: 0; value: {rest[(node, prop)]} }}\n        }}\n"
            for node, prop in missing
        )
        added += len(missing)
        close = qml.rindex("}", a, b)
        out.append(qml[last:close] + add)
        last = close
    out.append(qml[last:])
    return "".join(out), added


def disable_timelines(qml: str) -> str:
    return re.sub(r"^(\s*)(enabled|running): true$", r"\1\2: false", qml, flags=re.M)


def convert(glb: Path, out: Path, balsam: str = BALSAM) -> int:
    if out.exists():
        shutil.rmtree(out)
    subprocess.run([balsam, "-o", str(out), str(glb)], check=True)
    qml = out / (glb.stem.replace("-", "_").capitalize() + ".qml")
    text, added = fill_missing_tracks(disable_timelines(qml.read_text()))
    qml.write_text(text)
    return added


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--glb", type=Path, default=Path("/workspace/team/avatar-proto/threejs-prep/ellah-anim.glb")
    )
    ap.add_argument("--out", type=Path, default=Path("/workspace/team/avatar-qq3d/converted"))
    ap.add_argument("--balsam", default=BALSAM)
    a = ap.parse_args(argv)
    print(f"{a.out}: added {convert(a.glb, a.out, a.balsam)} rest-pose tracks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
