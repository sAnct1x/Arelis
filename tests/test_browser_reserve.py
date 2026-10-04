"""normalize_party / resolve_party / reserve_url party size."""

from __future__ import annotations

import pytest

from arelis.browser.reserve import normalize_party, reserve_url, resolve_party


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, 1),
        ("0", 1),
        (0.0, 1),
        (None, 2),
        ("", 2),
        ("  ", 2),
        ("abc", 2),
        (1, 1),
        (3, 3),
        ("party of 4", 4),
        (20, 20),
        (21, 20),
        (99, 20),
    ],
)
def test_normalize_party_table(raw: object, expected: int) -> None:
    assert normalize_party(raw) == expected


def test_normalize_party_zero_int_matches_zero_string() -> None:
    assert normalize_party(0) == normalize_party("0") == 1


def test_reserve_url_party_zero_opentable() -> None:
    url = reserve_url("Some Place", site="opentable", party=0)
    assert "covers=1" in url


def test_reserve_url_party_zero_resy() -> None:
    url = reserve_url("Some Place", site="resy", party=0)
    assert "seats=1" in url


def test_reserve_url_party_zero_google() -> None:
    url = reserve_url("Some Place", site="google", party=0)
    assert "party+of+1" in url


@pytest.mark.parametrize(
    ("candidates", "expected"),
    [
        ((0, 5), 1),
        ((None, 5), 5),
        (("", None), 2),
        ((None, None), 2),
        ((3, None), 3),
        (("0", 4), 1),
    ],
)
def test_resolve_party(candidates: tuple[object, ...], expected: int) -> None:
    assert resolve_party(*candidates) == expected

