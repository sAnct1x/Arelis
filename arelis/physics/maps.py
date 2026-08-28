"""Public NASA / USGS albedo maps for approach/orbit. No invented crater noise.

A planet 'model' here is an IAU sphere with a cited equirectangular mosaic.
Landing-scale height is out of scope. A file that is not a real image is treated
as missing so a bad Photojournal HTML page cannot masquerade as Mars.
"""

from __future__ import annotations

import math
import stat
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import numpy as np
from PIL import Image

from arelis.paths import models_dir

_NASA3D = (
    "https://raw.githubusercontent.com/nasa/NASA-3D-Resources/master/"
    "Images%20and%20Textures"
)
_MAX_EDGE = 2048
_MIN_W, _MIN_H = 256, 128


def _n3d(folder: str) -> str:
    """NASA 3D Resources texture JPEG. Public domain US government work."""
    name = f"{folder}.jpg"
    return f"{_NASA3D}/{quote(folder)}/{quote(name)}"


# name: (filename, source, approx km/pixel at equator, url)
MAPS: dict[str, tuple[str, str, float, str]] = {
    "Earth": (
        "earth.jpg",
        "NASA Visible Earth Blue Marble (land_shallow_topo_2048)",
        20.0,
        "https://eoimages.gsfc.nasa.gov/images/imagerecords/57000/"
        "57752/land_shallow_topo_2048.jpg",
    ),
    "Moon": (
        "moon.jpg",
        "NASA SVS LRO color mosaic ~1k",
        11.0,
        "https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/"
        "lroc_color_poles_1k.jpg",
    ),
    "Mercury": (
        "mercury.jpg",
        "NASA SVS MESSENGER MDIS global mosaic (enhanced color)",
        12.0,
        "https://svs.gsfc.nasa.gov/vis/a010000/a011100/a011197/Image1_rawpng.png",
    ),
    "Venus": (
        "venus.jpg",
        "NASA 3D Resources / Magellan radar, not optical",
        26.0,
        _n3d("Venus"),
    ),
    "Mars": (
        "mars.jpg",
        "NASA 3D Resources Viking mosaic processed at USGS",
        15.0,
        _n3d("Mars"),
    ),
    "Jupiter": (
        "jupiter.jpg",
        "NASA SVS Hubble WFC3 global map 2015 (cloud tops)",
        430.0,
        "https://svs.gsfc.nasa.gov/vis/a010000/a012000/a012021/"
        "Hubble_Jupiter_color_global_map_2015a_print.jpg",
    ),
    "Neptune": (
        "neptune.jpg",
        "NASA 3D Resources Voyager ISS cloud-top map",
        80.0,
        f"{_NASA3D}/{quote('Neptune')}/{quote('Neptune.tif')}",
    ),
    "Saturn": (
        "saturn.jpg",
        "NASA 3D Resources JPL planetary map (compiled cloud tops)",
        510.0,
        _n3d("Saturn"),
    ),
    "Uranus": (
        "uranus.jpg",
        "Voyager true-color: pale methane cyan, faint belts, not a mosaic",
        220.0,
        "",
    ),
    "Ceres": (
        "ceres.jpg",
        "Tholen C-type + p_v=0.09, large-scale albedo only (no Dawn mosaic)",
        0.9,
        "",
    ),
    "Vesta": (
        "vesta.jpg",
        "Tholen V-type + p_v=0.38, large-scale albedo only (no Dawn mosaic)",
        0.5,
        "",
    ),
    "Pallas": (
        "pallas.jpg",
        "Tholen B-type + p_v=0.16, large-scale albedo only",
        0.5,
        "",
    ),
    "Hygiea": (
        "hygiea.jpg",
        "Tholen C-type + p_v=0.07, large-scale albedo only",
        0.4,
        "",
    ),
    "Io": (
        "io.jpg",
        "NASA 3D Resources USGS/Voyager mosaic (polar gaps)",
        8.0,
        _n3d("Jupiter - Io (A)"),
    ),
    "Europa": (
        "europa.jpg",
        "NASA 3D Resources USGS/Voyager mosaic",
        7.0,
        _n3d("Jupiter - Europa"),
    ),
    "Ganymede": (
        "ganymede.jpg",
        "NASA 3D Resources USGS/Voyager mosaic",
        11.0,
        _n3d("Jupiter - Ganymede"),
    ),
    "Callisto": (
        "callisto.jpg",
        "NASA 3D Resources USGS/Voyager mosaic",
        10.0,
        _n3d("Jupiter - Callisto"),
    ),
    "Phobos": (
        "phobos.jpg",
        "NASA 3D Resources Phobos map",
        0.05,
        _n3d("Mars - Phobos"),
    ),
    "Deimos": (
        "deimos.jpg",
        "NASA 3D Resources Deimos map",
        0.03,
        _n3d("Mars - Deimos"),
    ),
    "Titan": (
        "titan.jpg",
        "NASA 3D Resources Titan (IR/radar composite, not optical)",
        22.0,
        _n3d("Saturn - Titan"),
    ),
    "Enceladus": (
        "enceladus.jpg",
        "NASA 3D Resources Cassini mosaic",
        1.1,
        _n3d("Saturn - Enceladus"),
    ),
    "Mimas": (
        "mimas.jpg",
        "NASA 3D Resources Cassini mosaic",
        0.9,
        _n3d("Saturn - Mimas"),
    ),
    "Tethys": (
        "tethys.jpg",
        "NASA 3D Resources Cassini mosaic",
        2.3,
        _n3d("Saturn - Tethys"),
    ),
    "Dione": (
        "dione.jpg",
        "NASA 3D Resources Cassini mosaic",
        2.5,
        _n3d("Saturn - Dione"),
    ),
    "Rhea": (
        "rhea.jpg",
        "NASA 3D Resources Cassini mosaic",
        3.3,
        _n3d("Saturn - Rhea"),
    ),
    "Iapetus": (
        "iapetus.jpg",
        "NASA 3D Resources Cassini mosaic",
        3.2,
        _n3d("Saturn - Iapetus"),
    ),
    "Triton": (
        "triton.jpg",
        "NASA 3D Resources Voyager mosaic",
        12.0,
        _n3d("Neptune - Triton"),
    ),
    "Miranda": (
        "miranda.jpg",
        "NASA 3D Resources Voyager mosaic",
        2.1,
        _n3d("Uranus - Miranda"),
    ),
    "Ariel": (
        "ariel.jpg",
        "NASA 3D Resources Voyager mosaic",
        5.0,
        _n3d("Uranus - Ariel"),
    ),
    "Umbriel": (
        "umbriel.jpg",
        "NASA 3D Resources Voyager mosaic",
        5.1,
        _n3d("Uranus - Umbriel"),
    ),
    "Titania": (
        "titania.jpg",
        "NASA 3D Resources Voyager mosaic",
        6.9,
        _n3d("Uranus - Titania"),
    ),
    "Oberon": (
        "oberon.jpg",
        "NASA 3D Resources Voyager mosaic",
        6.6,
        _n3d("Uranus - Oberon"),
    ),
}


@dataclass(frozen=True)
class MapInfo:
    body: str
    path: Path | None
    source: str
    km_per_px: float | None


def maps_dir() -> Path:
    return models_dir() / "astro" / "maps"


def write_surface_map(
    dest: Path,
    *,
    rgb: tuple[int, int, int],
    albedo: float,
    seed: int,
    belts: bool = False,
) -> None:
    """Large-scale albedo only. Not craters, not a spacecraft mosaic."""
    width, height = 1024, 512
    yy, xx = np.mgrid[0:height, 0:width]
    lon = xx / max(width, 1) * (2.0 * math.pi)
    lat = (0.5 - yy / max(height - 1, 1)) * math.pi
    field = np.zeros((height, width), dtype=np.float32)
    for freq, amp, phase in (
        (2.0, 0.28, seed * 0.17),
        (5.0, 0.16, seed * 0.31),
        (9.0, 0.08, seed * 0.47),
    ):
        field += amp * np.sin(freq * lon + phase) * np.cos((freq * 0.45) * lat + phase)
    field = 0.62 + 0.38 * np.tanh(field)
    if belts:
        field *= 0.88 + 0.12 * np.cos(lat * 6.0)
    scale = max(float(albedo), 0.04) / 0.18
    color = np.clip(
        np.array(rgb, dtype=np.float32) * field[..., None] * scale, 0, 255
    ).astype(np.uint8)
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(color, mode="RGB").save(dest, "JPEG", quality=86)


_SURFACES: dict[str, tuple[tuple[int, int, int], float, int, bool]] = {
    "Uranus": ((168, 214, 220), 0.51, 7, True),
    "Ceres": ((150, 145, 138), 0.090, 1, False),
    "Vesta": ((196, 168, 132), 0.38, 4, False),
    "Pallas": ((164, 156, 142), 0.16, 2, False),
    "Hygiea": ((142, 138, 132), 0.072, 10, False),
}


def write_generated_maps() -> list[str]:
    saved: list[str] = []
    for body, (rgb, albedo, seed, belts) in _SURFACES.items():
        dest = map_path(body)
        if map_ready(dest):
            continue
        write_surface_map(dest, rgb=rgb, albedo=albedo, seed=seed, belts=belts)
        saved.append(body)
    return saved


def map_path(body: str) -> Path:
    meta = MAPS.get(body)
    name = meta[0] if meta else f"{body.lower()}.jpg"
    return maps_dir() / name


def load_rgb(path: Path) -> tuple[int, int, bytes] | None:
    """RGB bytes for a decoded mosaic. None if the file is HTML, truncated, or tiny."""
    try:
        with Image.open(path) as image:
            image.load()
            rgb = fit_equirect(image.convert("RGB"))
            width, height = rgb.size
            if width < _MIN_W or height < _MIN_H:
                return None
            return width, height, rgb.tobytes()
    except (OSError, ValueError, SyntaxError):
        return None


def fit_equirect(rgb: Image.Image) -> Image.Image:
    """Center a non-wrap photo on a 2:1 canvas. Do not stretch a hemisphere around the globe."""
    width, height = rgb.size
    if width < 2 or height < 1:
        return rgb
    aspect = width / height
    if 1.8 <= aspect <= 2.2:
        return rgb
    dest_w = max(width, height * 2)
    dest_w = min(dest_w, _MAX_EDGE)
    dest_h = max(1, dest_w // 2)
    canvas = Image.new("RGB", (dest_w, dest_h), (6, 6, 7))
    scale = min(dest_w / width, dest_h / height)
    nw = max(1, round(width * scale))
    nh = max(1, round(height * scale))
    fitted = rgb.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas.paste(fitted, ((dest_w - nw) // 2, (dest_h - nh) // 2))
    return canvas


_READY: dict[tuple[str, int, int], bool] = {}


def forget_ready() -> None:
    """Drop validation verdicts after a fetch rewrites the cache directory."""
    _READY.clear()


def map_ready(path: Path) -> bool:
    """True if the file decodes as a wrap map.

    The decode verdict is kept per (path, mtime, size): describe() runs per body
    per frame, and a full mosaic decode there costs more than the whole frame.
    A rewritten file gets a new key, so a bad download still re-validates.
    """
    try:
        info = path.stat()
    except OSError:
        return False
    if not stat.S_ISREG(info.st_mode):
        return False
    if info.st_size < 1000:
        return False
    key = (str(path), info.st_mtime_ns, info.st_size)
    hit = _READY.get(key)
    if hit is None:
        hit = load_rgb(path) is not None
        if len(_READY) > 512:
            _READY.clear()
        _READY[key] = hit
    return hit


def describe(body: str) -> MapInfo:
    meta = MAPS.get(body)
    path = map_path(body)
    exists = map_ready(path)
    if meta is None:
        return MapInfo(body, path if exists else None, "no public map catalogued", None)
    _fn, source, gsd, _url = meta
    if not exists:
        return MapInfo(body, None, source, gsd)
    return MapInfo(body, path, source, gsd)


def missing_maps() -> list[str]:
    return [name for name in MAPS if not map_ready(map_path(name))]


def _store_image(dest: Path, content: bytes) -> str | None:
    """Write a JPEG mosaic. Returns an error string, or None on success."""
    if len(content) < 1000:
        return "too small"
    if content.lstrip()[:1] in (b"<", b"{") or content[:5] == b"<?xml":
        return "not an image"
    try:
        with Image.open(BytesIO(content)) as image:
            image.load()
            rgb = image.convert("RGB")
    except (OSError, ValueError, SyntaxError) as exc:
        return str(exc)
    rgb = fit_equirect(rgb)
    width, height = rgb.size
    if width < _MIN_W or height < _MIN_H:
        return f"{width}x{height} too small for a wrap map"
    if width > _MAX_EDGE:
        height = max(1, round(height * _MAX_EDGE / width))
        rgb = rgb.resize((_MAX_EDGE, height), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    rgb.save(dest, "JPEG", quality=88)
    return None


def download_maps() -> tuple[list[str], list[str]]:
    """Fetch missing NASA/USGS mosaics and write cited taxonomy surfaces."""
    maps_dir().mkdir(parents=True, exist_ok=True)
    saved = write_generated_maps()
    errors: list[str] = []
    todo = [
        (body, meta[3])
        for body, meta in MAPS.items()
        if meta[3].startswith("http") and not map_ready(map_path(body))
    ]
    if not todo:
        return saved, errors
    import httpx

    headers = {
        "User-Agent": "Arelis/research (NASA public-domain albedo; personal lab)"
    }
    with httpx.Client(timeout=120.0, follow_redirects=True, headers=headers) as client:
        for body, url in todo:
            dest = map_path(body)
            try:
                response = client.get(url)
                if response.status_code >= 400:
                    alt = _n3d("Neptune") if body == "Neptune" and url != _n3d("Neptune") else ""
                    if alt:
                        response = client.get(alt)
                    if response.status_code >= 400:
                        errors.append(f"{body}: HTTP {response.status_code}")
                        continue
                err = _store_image(dest, response.content)
                if err and body == "Neptune" and url != _n3d("Neptune"):
                    response = client.get(_n3d("Neptune"))
                    if response.status_code < 400:
                        err = _store_image(dest, response.content)
                if err:
                    errors.append(f"{body}: {err}")
                    continue
                saved.append(body)
            except httpx.HTTPError as exc:
                errors.append(f"{body}: {exc}")
    return saved, errors
