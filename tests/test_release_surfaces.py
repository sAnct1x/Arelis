"""Release surfaces for a plain MAJOR.MINOR.PATCH tag.

win-installer/arelis.iss builds VersionInfoVersion as "<AppVersion>.0", which
must be numeric, so an rc suffix in __version__ would break the installer
compile.
"""

from __future__ import annotations

import re
from pathlib import Path

from packaging.version import Version

import arelis
from arelis import update

REPO = Path(__file__).resolve().parents[1]


def release_payload(
    tag: str,
    *,
    draft: bool = False,
    prerelease: bool = False,
) -> dict:
    assets = [
        {
            "name": f"Arelis-{tag.lstrip('v')}-win64-setup.exe",
            "browser_download_url": f"https://example.invalid/{tag}/setup.exe",
            "size": 158_000_000,
        },
        {
            "name": f"Arelis-{tag.lstrip('v')}-win64-setup.exe.sha256",
            "browser_download_url": f"https://example.invalid/{tag}/setup.exe.sha256",
            "size": 90,
        },
    ]
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "html_url": f"https://github.com/sAnct1x/arelis/releases/tag/{tag}",
        "assets": assets,
    }


def test_version_is_plain_major_minor_patch() -> None:
    """win-installer/arelis.iss builds VersionInfoVersion as "<AppVersion>.0", which must be numeric, so an rc suffix in __version__ would break the installer compile."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", arelis.__version__), (
        f"{arelis.__version__!r} is not plain MAJOR.MINOR.PATCH"
    )


class TestUpdaterFacts:
    def test_prerelease_rc1_parses_to_none(self) -> None:
        assert update.parse_release(release_payload("v0.3.0-rc1", prerelease=True)) is None

    def test_draft_parses_to_none(self) -> None:
        assert update.parse_release(release_payload("v0.3.0-rc1", draft=True)) is None

    def test_packaging_rc_is_older_than_plain(self) -> None:
        assert Version("0.3.0rc1") < Version("0.3.0")

    def test_installed_plain_030_is_not_offered_published_030(self) -> None:
        # rc1 testers on the plain-0.3.0 build must reinstall by hand.
        release = update.available_update(
            "0.3.0",
            fetch=lambda: update.parse_release(release_payload("v0.3.0")),
        )
        assert release is None

    def test_installed_029_is_offered_published_030(self) -> None:
        release = update.available_update(
            "0.2.9",
            fetch=lambda: update.parse_release(release_payload("v0.3.0")),
        )
        assert release is not None
        assert release.version == Version("0.3.0")


class TestVersionSurfacesAgree:
    def test_readme_installer_name_and_label(self) -> None:
        v = arelis.__version__
        text = (REPO / "README.md").read_text(encoding="utf-8")
        assert f"Arelis-{v}-win64-setup.exe" in text
        assert f"[v{v}]" in text

    def test_win_installer_readme_and_github_templates(self) -> None:
        v = arelis.__version__
        paths = [
            REPO / "win-installer" / "README.md",
            REPO / ".github" / "ISSUE_TEMPLATE" / "bug.yml",
            REPO / ".github" / "ISSUE_TEMPLATE" / "first-run.yml",
            REPO / ".github" / "DISCUSSION_TEMPLATE" / "q-a.yml",
        ]
        for path in paths:
            assert v in path.read_text(encoding="utf-8"), path

    def test_whats_new_checkout_line(self) -> None:
        v = arelis.__version__
        lines = (REPO / "docs" / "whats-new.md").read_text(encoding="utf-8").splitlines()
        assert f"**{v}**" in lines[2]

    def test_release_notes_file_exists(self) -> None:
        v = arelis.__version__
        assert (REPO / "docs" / "releases" / f"v{v}.md").is_file()


class TestReleaseNotesContent:
    def test_v030_notes_exist(self) -> None:
        assert (REPO / "docs" / "releases" / "v0.3.0.md").is_file()

    def test_no_em_or_en_dash(self) -> None:
        text = (REPO / "docs" / "releases" / "v0.3.0.md").read_text(encoding="utf-8")
        assert "\u2014" not in text
        assert "\u2013" not in text

    def test_required_sections(self) -> None:
        text = (REPO / "docs" / "releases" / "v0.3.0.md").read_text(encoding="utf-8")
        for heading in (
            "## Fixed",
            "## Privacy and safety",
            "## Changed, and you may notice",
            "## Still true",
        ):
            assert heading in text

    def test_still_true_mentions(self) -> None:
        text = (REPO / "docs" / "releases" / "v0.3.0.md").read_text(encoding="utf-8")
        still = text.split("## Still true", 1)[1]
        assert "unsigned" in still or "not signed" in still
        assert ".sha256" in still
        assert "first run" in still
        assert "source checkout" in still

    def test_notes_mention_key_behaviors(self) -> None:
        text = (REPO / "docs" / "releases" / "v0.3.0.md").read_text(encoding="utf-8")
        assert "updates.check" in text
        assert "confirm" in text.lower() or "pauses for your OK" in text
        assert "backups" in text
        assert "prove you are human" in text or "wall" in text
        assert "keeps your sign-ins between runs again" in text
        assert "persistent" in text and "profile" in text

    def test_no_hype_words(self) -> None:
        text = (REPO / "docs" / "releases" / "v0.3.0.md").read_text(encoding="utf-8").lower()
        for word in ("faster", "more reliable", "quicker"):
            assert word not in text

    def test_no_local_paths(self) -> None:
        text = (REPO / "docs" / "releases" / "v0.3.0.md").read_text(encoding="utf-8")
        assert not re.search(r"[A-Za-z]:\\", text)
        assert "Users" not in text

    def test_whats_new_has_030_above_this_checkout(self) -> None:
        text = (REPO / "docs" / "whats-new.md").read_text(encoding="utf-8")
        idx_030 = text.index("## 0.3.0")
        idx_checkout = text.index("## This checkout")
        assert idx_030 < idx_checkout


class TestReadmeStatements:
    """README lines that were stale against the 0.3.0 behavior."""

    def _readme(self) -> str:
        text = (REPO / "README.md").read_text(encoding="utf-8")
        return " ".join(text.split())

    def test_mail_setup_sentence(self) -> None:
        text = self._readme()
        assert "Mail has no Settings tab of its own." in text
        assert (
            "Mail has no Settings tab of its own. Put the address and app password "
            "under Settings, Notify, or in the `email:` block of `secrets.yaml`."
        ) in text
        assert "There's no Mail tab in Settings" not in text

    def test_backup_sentence_matches_pre_upgrade_backup(self) -> None:
        text = self._readme()
        assert (
            "Before an in-app upgrade she copies allowlisted records into "
            "`data/backups/pre-<version>/` and keeps the newest two. "
            "Daily dated memory copies stay off. See [backups.md](docs/backups.md)."
        ) in text
        assert "for two weeks" not in text
        assert (REPO / "docs" / "backups.md").is_file()
