"""Release surfaces for a plain MAJOR.MINOR.PATCH tag.

win-installer/arelis.iss builds VersionInfoVersion as "<AppVersion>.0", which
must be numeric, so an rc suffix in __version__ would break the installer
compile.
"""

from __future__ import annotations

from pathlib import Path

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


class TestReleaseNotesContent:
    def _notes(self) -> str:
        return (REPO / "docs" / "releases" / "v0.3.0.md").read_text(encoding="utf-8")

    def _section(self, heading: str) -> str:
        text = self._notes()
        body = text.split(heading, 1)[1]
        return body.split("\n## ", 1)[0]


    def test_notes_mention_key_behaviors(self) -> None:
        text = self._notes()
        assert "updates.check" in text
        assert "pauses for your OK" in " ".join(text.split())
        assert "backups" in text
        assert "prove you are human" in text
        assert "persistent" in text and "profile" in text
        assert "Simplified Chinese" in text
        assert "`run_task`" in text
        assert "preview" in text


    def test_backup_claim_does_not_cover_the_092_upgrade(self) -> None:
        text = " ".join(self._notes().split())
        assert "From this version on, before an in-app upgrade" in text
        assert "Upgrading from 0.2.9 to 0.3.0 itself is not covered" in text
        assert "pre-<version>" in text
        assert "dated folder" not in text
        assert "Before an upgrade she copies" not in text
        whats_new = " ".join((REPO / "docs" / "whats-new.md").read_text(encoding="utf-8").split())
        section = whats_new.split("## 0.3.0", 1)[1].split("## This checkout", 1)[0]
        assert "not made when upgrading from 0.2.9" in section


    def test_night_line_is_not_under_privacy_and_safety(self) -> None:
        assert "Night" not in self._section("## Privacy and safety")
        assert "Night" in self._section("## New")


class TestReadmeStatements:
    """README lines that were stale against the 0.3.0 behavior."""

    def _readme(self) -> str:
        text = (REPO / "README.md").read_text(encoding="utf-8")
        return " ".join(text.split())


