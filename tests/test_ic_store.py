"""Cached Horizons VECTORS are the real fetch, labeled, or they are unused."""

from __future__ import annotations

from arelis.physics.horizons import VectorState
from arelis.physics.ic_store import load_cached, nearest_cached, save_cached


def _sun() -> VectorState:
    return VectorState(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, units="SI", epoch_jd=2451545.0)


def test_vector_cache_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    states = {"Sun": _sun(), "Earth": _sun()}
    save_cached("2000-01-01", states)
    loaded = load_cached("2000-01-01")
    assert loaded is not None
    assert loaded["Earth"].x == 1.0
    assert loaded["Sun"].epoch_jd == 2451545.0
    assert load_cached("2000-01-02") is None


def test_corrupt_vector_cache_is_ignored(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    from arelis.physics.ic_store import cache_path, vectors_dir

    vectors_dir().mkdir(parents=True)
    cache_path("2000-01-01").write_text("{not json", encoding="utf-8")
    assert load_cached("2000-01-01") is None
    cache_path("2000-01-01").write_text(
        '{"schema": 1, "source": "made up", "date": "2000-01-01", "bodies": {}}',
        encoding="utf-8",
    )
    assert load_cached("2000-01-01") is None


def test_nearest_cached_picks_the_closest_day(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    states = {"Sun": _sun()}
    save_cached("2000-01-01", states)
    save_cached("2000-01-10", states)
    found = nearest_cached("2000-01-08")
    assert found is not None
    day, loaded = found
    assert day == "2000-01-10"
    assert "Sun" in loaded
    hit = nearest_cached("2000-01-01")
    assert hit is not None
    assert hit[0] == "2000-01-01"
