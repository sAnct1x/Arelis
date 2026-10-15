"""NASA albedo cache: catalogued files or an honest gap. No invented detail."""

from __future__ import annotations

from io import BytesIO

import httpx
from PIL import Image


def _jpeg(path, size=(256, 128)) -> None:
    Image.new("RGB", size, (40, 50, 60)).save(path, "JPEG")


def test_missing_maps_treats_tiny_files_as_absent(tmp_path, monkeypatch) -> None:
    from arelis.physics import maps as maps_mod

    monkeypatch.setattr(maps_mod, "maps_dir", lambda: tmp_path)
    missing = maps_mod.missing_maps()
    assert "Earth" in missing
    assert "Mars" in missing
    (tmp_path / "earth.jpg").write_bytes(b"no")
    assert "Earth" in maps_mod.missing_maps()
    (tmp_path / "earth.jpg").write_bytes(b"x" * 2000)
    assert "Earth" in maps_mod.missing_maps()
    _jpeg(tmp_path / "earth.jpg")
    assert "Earth" not in maps_mod.missing_maps()
    assert "Moon" in maps_mod.missing_maps()


def test_map_ready_decodes_once_per_file_version(tmp_path, monkeypatch) -> None:
    """describe() runs per body per frame. A mosaic decode there costs the frame."""
    from arelis.physics import maps as maps_mod

    monkeypatch.setattr(maps_mod, "maps_dir", lambda: tmp_path)
    maps_mod.forget_ready()
    decodes: list[str] = []
    real = maps_mod.load_rgb

    def counted(path):
        decodes.append(str(path))
        return real(path)

    monkeypatch.setattr(maps_mod, "load_rgb", counted)
    _jpeg(tmp_path / "earth.jpg")
    for _ in range(30):
        assert maps_mod.describe("Earth").path is not None
    assert len(decodes) == 1
    _jpeg(tmp_path / "earth.jpg", size=(512, 256))
    assert maps_mod.describe("Earth").path is not None
    assert len(decodes) == 2


def test_store_image_rejects_html_and_accepts_jpeg(tmp_path) -> None:
    from arelis.physics.maps import _store_image

    dest = tmp_path / "out.jpg"
    assert _store_image(dest, b"<!DOCTYPE html>" + b"x" * 2000) == "not an image"
    assert not dest.exists()
    buf = BytesIO()
    Image.new("RGB", (256, 128), (180, 110, 70)).save(buf, "JPEG")
    assert _store_image(dest, buf.getvalue()) is None
    assert dest.is_file()


def test_describe_prefers_earth_8192(tmp_path, monkeypatch) -> None:
    from arelis.physics import maps as maps_mod

    monkeypatch.setattr(maps_mod, "maps_dir", lambda: tmp_path)
    maps_mod.forget_ready()
    _jpeg(tmp_path / "earth.jpg")
    coarse = maps_mod.describe("Earth")
    assert coarse.path is not None
    assert coarse.path.name == "earth.jpg"
    _jpeg(tmp_path / maps_mod.EARTH_HI_FILE, size=(512, 256))
    maps_mod.forget_ready()
    hi = maps_mod.describe("Earth")
    assert hi.path is not None
    assert hi.path.name == maps_mod.EARTH_HI_FILE
    assert hi.km_per_px == maps_mod.EARTH_HI_KM


def test_generated_surfaces_are_real_jpegs(tmp_path, monkeypatch) -> None:
    from arelis.physics import maps as maps_mod

    monkeypatch.setattr(maps_mod, "maps_dir", lambda: tmp_path)
    for _body, meta in maps_mod.MAPS.items():
        if meta[3].startswith("http"):
            _jpeg(tmp_path / meta[0])
    _jpeg(tmp_path / maps_mod.EARTH_HI_FILE)

    class BoomClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("taxonomy surfaces must not hit the network")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(httpx, "Client", BoomClient)
    saved, errors = maps_mod.download_maps()
    assert errors == []
    assert set(saved) >= {"Ceres", "Vesta", "Pallas", "Hygiea", "Uranus"}
    assert maps_mod.map_ready(tmp_path / "ceres.jpg")
    info = maps_mod.describe("Ceres")
    assert info.path is not None
    assert "Dawn" not in info.source or "no Dawn" in info.source


def _pole_lon_std(path) -> float:
    import numpy as np

    arr = np.array(Image.open(path), dtype=np.float32)
    return float(arr[0].mean(axis=1).std())


