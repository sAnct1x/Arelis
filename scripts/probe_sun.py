"""Peak / crop probe for capture_sun frames."""

from pathlib import Path

import numpy as np
from PIL import Image

base = Path("outputs/physics/solar/_look")
for name in ("inspect.png", "1au.png", "40au.png"):
    im = np.asarray(Image.open(base / name).convert("RGB"))
    h, w, _ = im.shape
    lum = im.astype(np.int32).sum(axis=2)
    y, x = np.unravel_index(lum.argmax(), lum.shape)
    print(
        name,
        "peak",
        (int(x), int(y)),
        "center",
        (w // 2, h // 2),
        "rgb",
        im[y, x].tolist(),
    )
    # Center crop — the sun is placed on the look ray.
    cx, cy = w // 2, h // 2
    Image.fromarray(im[cy - 70 : cy + 71, cx - 70 : cx + 71]).save(
        base / name.replace(".png", "_center.png")
    )
    for dx, dy, label in (
        (0, 0, "c"),
        (8, 0, "+8x"),
        (0, 8, "+8y"),
        (20, 0, "+20x"),
        (0, 20, "+20y"),
        (40, 0, "+40x"),
        (0, 40, "+40y"),
    ):
        xx = min(w - 1, max(0, x + dx))
        yy = min(h - 1, max(0, y + dy))
        print(" ", label, im[yy, xx].tolist())
