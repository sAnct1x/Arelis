"""Catalog radii and GM stay published IAU / DE440. No physics radius multipliers."""

from __future__ import annotations

import pytest

from arelis.physics.constants import AU_M, BODY_BY_NAME, GM_EARTH, GM_SUN


# IAU 2015 / WGCCRE typical mean radii, metres. The catalog must match these
# exactly — a silent scale factor here is a product lie.
_IAU_MEAN_RADIUS_M = {
    "Sun": 695_700_000.0,
    "Mercury": 2_439_700.0,
    "Venus": 6_051_800.0,
    "Earth": 6_371_000.0,
    "Moon": 1_737_400.0,
    "Mars": 3_389_500.0,
    "Jupiter": 69_911_000.0,
    "Saturn": 58_232_000.0,
    "Uranus": 25_362_000.0,
    "Neptune": 24_622_000.0,
}


def test_au_is_the_iau_2012_exact_metre() -> None:
    assert AU_M == 149_597_870_700.0


def test_catalog_radii_are_iau_mean() -> None:
    for name, radius in _IAU_MEAN_RADIUS_M.items():
        assert BODY_BY_NAME[name].radius == radius, name


def test_earth_and_sun_gm_match_the_pins() -> None:
    assert BODY_BY_NAME["Sun"].gm == GM_SUN
    assert BODY_BY_NAME["Earth"].gm == GM_EARTH


def test_true_px_is_angular_size_with_no_radius_scale(qt_app) -> None:
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import BodyView
    from arelis.ui.panels.solar import SolarPanel

    set_system(None)
    panel = SolarPanel()
    panel.resize(960, 720)
    earth = BODY_BY_NAME["Earth"]
    depth = 10.0 * earth.radius
    true = panel._true_px(earth.radius, depth)
    assert true == pytest.approx(earth.radius / depth * (720 / 1.4))
    far = 1.0e12
    assert panel._true_px(earth.radius, far) < 1.0
    view = BodyView(
        name="Earth",
        kind="planet",
        tracer=False,
        x=0.0,
        y=0.0,
        z=0.0,
        vx=0.0,
        vy=0.0,
        vz=0.0,
        radius=earth.radius,
        mass=0.0,
        parent=None,
    )
    floor = panel._screen_radius(view, far)
    assert floor >= panel._true_px(earth.radius, far)
    panel.hide()
