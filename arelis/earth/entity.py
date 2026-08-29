"""One object on Earth. Freshness is a field, not a vibe."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EntityClass = Literal[
    "aircraft",
    "vessel",
    "satellite",
    "station",
    "camera",
    "quake",
    "fire",
    "person",
    "site",
    "rf",
    "weather",
    "traffic",
]

Freshness = Literal[
    "live",
    "delayed",
    "interpolated",
    "dead-reckoned",
    "simulated",
    "reconstructed",
    "stale",
    "unavailable",
]

PiiKind = Literal["none", "contact", "inferred"]

LAYER_IDS: tuple[str, ...] = (
    "flights",
    "drones",
    "military",
    "vessels",
    "radar",
    "satellites",
    "iss",
    "quakes",
    "fires",
    "weather",
    "radio",
    "cameras",
    "traffic",
    "sites",
    "people",
)


@dataclass(frozen=True)
class Coverage:
    """Where this sensor can know, and where it is deaf."""

    kind: str
    note: str
    volume_hint: str = ""


@dataclass
class Entity:
    id: str
    cls: EntityClass
    layer: str
    label: str
    x: float
    y: float
    z: float
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    when_unix: float = 0.0
    source: str = ""
    freshness: Freshness = "simulated"
    confidence: float = 0.5
    cite: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    pii: PiiKind = "none"
    coverage: Coverage | None = None

    def speed(self) -> float:
        return (self.vx * self.vx + self.vy * self.vy + self.vz * self.vz) ** 0.5

    def to_row(self) -> dict[str, Any]:
        meta = {k: v for k, v in self.meta.items() if k != "viewshed_ecef"}
        row: dict[str, Any] = {
            "id": self.id,
            "class": self.cls,
            "layer": self.layer,
            "label": self.label,
            "ecef_m": [self.x, self.y, self.z],
            "v_mps": [self.vx, self.vy, self.vz],
            "when_unix": self.when_unix,
            "source": self.source,
            "freshness": self.freshness,
            "confidence": self.confidence,
            "cite": self.cite,
            "pii": self.pii,
            "meta": meta,
        }
        if self.coverage is not None:
            row["coverage"] = {
                "kind": self.coverage.kind,
                "note": self.coverage.note,
                "volume_hint": self.coverage.volume_hint,
            }
        return row
