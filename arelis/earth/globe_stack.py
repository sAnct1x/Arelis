"""Which Earth pictures this copy is allowed to show.

NASA GIBS + OSM cover the whole planet with no key. Google Photorealistic
3D Tiles need earth.google_maps_key (Photorealistic cities, covered areas only).
Cesium ion is optional countryside hills. Fail closed to GIBS.

Hosts are string literals so tests/test_egress.py can pin them.
"""

from __future__ import annotations

from dataclasses import dataclass

from arelis.earth.secrets import earth_secret

CESIUM_JS = (
    "https://cesium.com/downloads/cesiumjs/releases/1.128/Build/Cesium/Cesium.js"
)
CESIUM_CSS = (
    "https://cesium.com/downloads/cesiumjs/releases/1.128/Build/Cesium/"
    "Widgets/widgets.css"
)
CESIUM_ION = "https://ion.cesium.com"
CESIUM_API = "https://api.cesium.com"
GIBS_XYZ = (
    "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
    "BlueMarble_NextGeneration/default/GoogleMapsCompatible_Level8/"
    "{z}/{y}/{x}.jpeg"
)
OSM_XYZ = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
GOOGLE_3D = "https://tile.googleapis.com/v1/3dtiles/root.json"


@dataclass(frozen=True)
class GlobeStack:
    kind: str
    google_key: str = ""
    ion_token: str = ""

    def label(self) -> str:
        return {
            "photoreal": "photoreal",
            "ion": "ion-terrain",
            "gibs": "gibs+osm",
        }.get(self.kind, self.kind)

    def credits(self) -> tuple[str, ...]:
        bits = ["NASA GIBS Blue Marble", "© OpenStreetMap"]
        if self.kind == "photoreal":
            bits = ["Google", "Cesium", *bits]
        elif self.kind == "ion":
            bits = ["Cesium ion", "Bing", *bits]
        return tuple(bits)

    def to_payload(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "label": self.label(),
            "googleKey": self.google_key,
            "ionToken": self.ion_token,
            "cesiumJs": CESIUM_JS,
            "cesiumCss": CESIUM_CSS,
            "cesiumBase": CESIUM_JS[: CESIUM_JS.rfind("/") + 1],
            "gibs": GIBS_XYZ,
            "osm": OSM_XYZ,
            "google3d": GOOGLE_3D,
            "photorealAltM": "80000",
            "credits": " · ".join(self.credits()),
        }


def choose_stack(*, google_key: str | None = None, ion_token: str | None = None) -> GlobeStack:
    """Photoreal when keyed, else ion hills, else the free mosaic."""
    google = (
        google_key
        if google_key is not None
        else earth_secret("google_maps_key", "ARELIS_GOOGLE_MAPS_KEY")
    )
    ion = (
        ion_token
        if ion_token is not None
        else earth_secret("cesium_ion_token", "ARELIS_CESIUM_ION_TOKEN")
    )
    if google:
        return GlobeStack("photoreal", google_key=google, ion_token=ion)
    if ion:
        return GlobeStack("ion", ion_token=ion)
    return GlobeStack("gibs")
