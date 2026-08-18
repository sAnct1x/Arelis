"""Standing profile from data/profile.yaml — short, hand-edited, every turn."""

from __future__ import annotations

from pathlib import Path

from arelis.profile import (
    load_standing_profile,
    standing_profile_prompt_line,
)


def test_load_standing_profile_reads_user_block(tmp_path: Path) -> None:
    path = tmp_path / "profile.yaml"
    path.write_text(
        "user:\n"
        "  name: Samuel Whitlock\n"
        "  prefer_called: Sam\n"
        "  work: astrophysicist at OSU\n"
        "  answer_style: direct, technical\n"
        "  units: Fahrenheit\n"
        "location:\n"
        "  city: Springfield\n",
        encoding="utf-8",
    )
    fields = load_standing_profile(path)
    assert fields["name"] == "Samuel Whitlock"
    assert fields["prefer_called"] == "Sam"
    assert fields["work"] == "astrophysicist at OSU"
    assert "city" not in fields
    assert "location" not in fields


def test_standing_profile_prompt_omits_empties_and_skips_missing_file(
    tmp_path: Path,
) -> None:
    assert standing_profile_prompt_line(path=tmp_path / "absent.yaml") == ""
    path = tmp_path / "profile.yaml"
    path.write_text(
        "user:\n  name: Sam\n  pronouns: ''\n  notes: ''\n",
        encoding="utf-8",
    )
    line = standing_profile_prompt_line(path=path)
    assert "Standing profile" in line
    assert "Name: Sam" in line
    assert "Pronouns" not in line


def test_load_profile_email_is_routing_only(tmp_path: Path) -> None:
    from arelis.profile import load_profile_email

    path = tmp_path / "profile.yaml"
    path.write_text(
        "user:\n  name: Sam\n  email: you@example.com\n",
        encoding="utf-8",
    )
    assert load_profile_email(path) == "you@example.com"
    line = standing_profile_prompt_line(path=path)
    assert "you@example.com" not in line
    assert "Name: Sam" in line
    assert load_profile_email(tmp_path / "absent.yaml") == ""


def test_standing_profile_accepts_flat_non_location_keys(tmp_path: Path) -> None:
    path = tmp_path / "profile.yaml"
    path.write_text(
        "name: Sam\nanswer_style: brief\nlocation:\n  city: X\n",
        encoding="utf-8",
    )
    fields = load_standing_profile(path)
    assert fields == {"name": "Sam", "answer_style": "brief"}
