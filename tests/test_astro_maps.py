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


def test_html_error_page_is_not_a_map(tmp_path, monkeypatch) -> None:
    from arelis.physics import maps as maps_mod

    monkeypatch.setattr(maps_mod, "maps_dir", lambda: tmp_path)
    (tmp_path / "mars.jpg").write_bytes(
        b"<!DOCTYPE html><html><body>nope</body></html>" + b"x" * 2000
    )
    assert maps_mod.map_ready(tmp_path / "mars.jpg") is False
    assert "Mars" in maps_mod.missing_maps()


def test_download_maps_skips_files_already_on_disk(tmp_path, monkeypatch) -> None:
    from arelis.physics import maps as maps_mod

    monkeypatch.setattr(maps_mod, "maps_dir", lambda: tmp_path)
    for _body, meta in maps_mod.MAPS.items():
        _jpeg(tmp_path / meta[0])

    class BoomClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("must not fetch maps that are already on disk")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(httpx, "Client", BoomClient)
    saved, errors = maps_mod.download_maps()
    assert saved == []
    assert errors == []
    assert maps_mod.missing_maps() == []


def test_store_image_rejects_html_and_accepts_jpeg(tmp_path) -> None:
    from arelis.physics.maps import _store_image

    dest = tmp_path / "out.jpg"
    assert _store_image(dest, b"<!DOCTYPE html>" + b"x" * 2000) == "not an image"
    assert not dest.exists()
    buf = BytesIO()
    Image.new("RGB", (256, 128), (180, 110, 70)).save(buf, "JPEG")
    assert _store_image(dest, buf.getvalue()) is None
    assert dest.is_file()


def test_describe_uncatalogued_body_does_not_invent_a_map() -> None:
    from arelis.physics.maps import describe

    info = describe("Bennu")
    assert info.path is None
    assert "no public map" in info.source


def test_generated_surfaces_are_real_jpegs(tmp_path, monkeypatch) -> None:
    from arelis.physics import maps as maps_mod

    monkeypatch.setattr(maps_mod, "maps_dir", lambda: tmp_path)
    for _body, meta in maps_mod.MAPS.items():
        if meta[3].startswith("http"):
            _jpeg(tmp_path / meta[0])

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


def test_fit_equirect_does_not_stretch_a_square() -> None:
    from arelis.physics.maps import fit_equirect

    square = Image.new("RGB", (256, 256), (200, 40, 40))
    wrapped = fit_equirect(square)
    assert wrapped.size[0] == wrapped.size[1] * 2
    px = wrapped.getpixel((0, wrapped.size[1] // 2))
    assert px[0] < 40
    mid = wrapped.getpixel((wrapped.size[0] // 2, wrapped.size[1] // 2))
    assert mid[0] > 150
    already = Image.new("RGB", (512, 256), (10, 20, 30))
    assert fit_equirect(already).size == (512, 256)
