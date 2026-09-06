"""Desk image rail: recent outputs, square thumbs, sidecar copy.

Workspace imports these so the panel does not grow another 200 lines of
listing and decode. Thumbs load through QImageReader at the display size
so a 4K output is not decoded 16 times at full resolution.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader, QPixmap

from arelis.desk import infer_kind, is_image_kind
from arelis.tools.image_meta import read_sidecar

IMAGE_STRIP_CAP = 16
THUMB_LONG = 72
CAPTION_LIMIT = 72

WELL_NAME = "WorkspaceImageWell"
STRIP_NAME = "WorkspaceImageStrip"
THUMB_NAME = "WorkspaceImageThumb"
CAPTION_NAME = "WorkspaceImageCaption"

DESK_EMPTY_PICTURES = "Pictures she makes open in this dock."


def recent_output_images(folder: Path | str) -> list[Path]:
    """Newest image files in a folder. Sidecars and junk stay off the rail."""
    root = Path(folder)
    if not root.is_dir():
        return []
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    found: list[Path] = []
    for path in entries:
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        if path.suffix.lower() == ".json":
            continue
        if not is_image_kind(infer_kind(str(path)), str(path)):
            continue
        found.append(path)

    def _stamp(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    found.sort(key=_stamp, reverse=True)
    return found[:IMAGE_STRIP_CAP]


def sidecar_tooltip(path: Path | str) -> str:
    """Filename, plus prompt and seed when a sibling ``{stem}.json`` is there."""
    target = Path(path)
    lines = [target.name]
    data = read_sidecar(target)
    prompt = data.get("prompt")
    if prompt is not None and str(prompt).strip():
        lines.append(str(prompt).strip())
    seed = data.get("seed")
    if seed is not None and str(seed).strip() != "":
        lines.append(f"seed {seed}")
    return "\n".join(lines)


def sidecar_caption(path: Path | str, *, limit: int = CAPTION_LIMIT) -> str:
    """One line under the hero: filename, then a short prompt."""
    target = Path(path)
    name = target.name
    prompt = str(read_sidecar(target).get("prompt") or "").strip()
    if not prompt:
        return name
    one = prompt.splitlines()[0].strip()
    cap = max(8, int(limit))
    if len(one) > cap:
        one = one[: cap - 1].rstrip() + "…"
    return f"{name} · {one}"


def load_fail_line(path: Path | str) -> str:
    """What the well says when the file will not decode."""
    return f"Could not load {Path(path).name}."


def load_fitted_pixmap(path: Path | str, width: int, height: int) -> QPixmap:
    """Decode only as large as the well, keeping aspect."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    src = reader.size()
    wide = max(1, int(width))
    high = max(1, int(height))
    if src.isValid() and src.width() > 0 and src.height() > 0:
        fitted = src.scaled(wide, high, Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(fitted)
    image = reader.read()
    if image.isNull():
        pix = QPixmap(str(path))
        if pix.isNull():
            return QPixmap()
        return pix.scaled(
            wide,
            high,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return QPixmap.fromImage(image)


def load_square_thumb(path: Path | str, size: int = THUMB_LONG) -> QPixmap:
    """Center-crop a square thumb. Decode near ``size``, not at source pixels."""
    side = max(1, int(size))
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    src = reader.size()
    if src.isValid() and src.width() > 0 and src.height() > 0:
        scale = max(side / float(src.width()), side / float(src.height()))
        reader.setScaledSize(
            QSize(
                max(1, round(src.width() * scale)),
                max(1, round(src.height() * scale)),
            )
        )
    image = reader.read()
    if image.isNull():
        pix = QPixmap(str(path))
        if pix.isNull():
            return QPixmap()
        image = pix.toImage()
    crop = min(image.width(), image.height())
    x = max(0, (image.width() - crop) // 2)
    y = max(0, (image.height() - crop) // 2)
    image = image.copy(x, y, crop, crop)
    if image.width() != side or image.height() != side:
        image = image.scaled(
            side,
            side,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return QPixmap.fromImage(image)
