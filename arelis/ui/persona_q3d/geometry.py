"""QQuick3DGeometry that loads one exported three.js BufferGeometry from raw .bin buffers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Property, QByteArray, Signal
from PySide6.QtGui import QVector3D
from PySide6.QtQml import QmlElement
from PySide6.QtQuick3D import QQuick3DGeometry

QML_IMPORT_NAME = "Arelis.PersonaQ3D"
QML_IMPORT_MAJOR_VERSION = 1

_A = QQuick3DGeometry.Attribute
# Quick 3D slot -> (semantic, float count). JOINTS is the one integer slot.
SLOTS = {
    "VERTEX": (_A.Semantic.PositionSemantic, 3),
    "NORMAL": (_A.Semantic.NormalSemantic, 3),
    "UV0": (_A.Semantic.TexCoord0Semantic, 2),
    "UV1": (_A.Semantic.TexCoord1Semantic, 2),
    "TANGENT": (_A.Semantic.TangentSemantic, 3),
    "BINORMAL": (_A.Semantic.BinormalSemantic, 3),
    "COLOR": (_A.Semantic.ColorSemantic, 4),
    "JOINTS": (_A.Semantic.JointSemantic, 4),
    "WEIGHTS": (_A.Semantic.WeightSemantic, 4),
}


def pack(arrays: dict[str, np.ndarray], spec: str, count: int) -> tuple[bytes, list[tuple]]:
    """Interleave exported attributes into Quick 3D slots.

    spec is "SLOT=attr[.c],attr...;SLOT=..." e.g. "UV1=aCav,aCavF;JOINTS=skinIndex". Each
    slot is filled component by component from the listed attributes, zero padded.
    """
    cols: list[np.ndarray] = []
    layout: list[tuple] = []
    off = 0
    for part in filter(None, spec.split(";")):
        slot, srcs = part.split("=")
        sem, n = SLOTS[slot]
        comp: list[np.ndarray] = []
        for src in srcs.split(","):
            a = arrays[src].reshape(count, -1)
            comp.extend(a[:, k] for k in range(a.shape[1]))
        comp = (comp + [np.zeros(count, np.float32)] * n)[:n]
        if slot == "JOINTS":
            comp = [c.astype(np.int32).view(np.float32) for c in comp]
        cols.extend(comp)
        layout.append((sem, off, slot == "JOINTS"))
        off += 4 * n
    data = np.stack(cols, axis=1).astype(np.float32, copy=False)
    return data.tobytes(), [*layout, ("stride", off)]


SPRITE_SLOT = "UV1"  # corner of the sprite quad, read by port.SPRITE_VERT_PRE
_CORNERS = np.array([[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]], np.float32)


def sprite_arrays(arrays: dict[str, np.ndarray], spec: str) -> tuple[dict[str, np.ndarray], str]:
    """Point layers as camera-facing quads: every point becomes 4 vertices sharing its attributes.

    Point size (gl_PointSize) only exists on OpenGL and Vulkan; D3D11 and Metal draw every point
    at 1 px. The vertex shader moves each corner by the point size in pixels instead.
    """
    n = len(arrays["position"]) // 3
    out = {k: np.repeat(v.reshape(n, -1), 4, axis=0).ravel() for k, v in arrays.items()}
    if any(part.startswith(SPRITE_SLOT + "=") for part in spec.split(";")):
        raise ValueError(f"point layer spec already uses {SPRITE_SLOT}: {spec}")
    out["_corner"] = np.tile(_CORNERS, (n, 1)).ravel()
    return out, f"{spec};{SPRITE_SLOT}=_corner"


def sprite_index(n: int) -> np.ndarray:
    q = np.arange(n, dtype=np.uint32)[:, None] * 4
    return (q + np.array([0, 1, 2, 0, 2, 3], np.uint32)).ravel()


@QmlElement
class LayerGeometry(QQuick3DGeometry):
    """source: export dir + geometry id (".../scene/g3"); spec: see pack(); points: sprite quads."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = ""
        self._spec = ""
        self._points = False

    def _get_source(self):
        return self._source

    def _set_source(self, v):
        self._source = v
        self._rebuild()

    def _get_spec(self):
        return self._spec

    def _set_spec(self, v):
        self._spec = v
        self._rebuild()

    def _get_points(self):
        return self._points

    def _set_points(self, v):
        self._points = bool(v)
        self._rebuild()

    source = Property(str, _get_source, _set_source, notify=changed)
    spec = Property(str, _get_spec, _set_spec, notify=changed)
    points = Property(bool, _get_points, _set_points, notify=changed)

    def _rebuild(self):
        if not (self._source and self._spec):
            return
        base = Path(self._source)
        arrays = {
            f.stem[len(base.name) + 1 :]: np.fromfile(f, np.float32)
            for f in base.parent.glob(base.name + "_*.bin")
            if not f.stem.endswith("_index")
        }
        pos = arrays["position"].reshape(-1, 3)
        spec = self._spec
        if self._points:
            arrays, spec = sprite_arrays(arrays, spec)
        count = len(arrays["position"]) // 3
        data, layout = pack(arrays, spec, count)
        self.clear()
        self.setVertexData(QByteArray(data))
        self.setStride(layout[-1][1])
        for sem, off, is_int in layout[:-1]:
            ct = _A.ComponentType.I32Type if is_int else _A.ComponentType.F32Type
            self.addAttribute(sem, off, ct)
        idx = base.parent / (base.name + "_index.bin")
        if self._points:
            self.setIndexData(QByteArray(sprite_index(len(pos)).tobytes()))
            self.addAttribute(_A.Semantic.IndexSemantic, 0, _A.ComponentType.U32Type)
        elif idx.exists():
            self.setIndexData(QByteArray(idx.read_bytes()))
            self.addAttribute(_A.Semantic.IndexSemantic, 0, _A.ComponentType.U32Type)
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        lo, hi = pos.min(0), pos.max(0)
        pad = 10.0  # skinned and animated layers move far from their bind pose; never cull them
        self.setBounds(QVector3D(*(lo - pad)), QVector3D(*(hi + pad)))
        self.update()
