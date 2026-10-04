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
    def _notes(self) -> str:
        return (REPO / "docs" / "releases" / "v0.3.0.md").read_text(encoding="utf-8")

    def _section(self, heading: str) -> str:
        text = self._notes()
        body = text.split(heading, 1)[1]
        return body.split("\n## ", 1)[0]

    def test_v030_notes_exist(self) -> None:
        assert (REPO / "docs" / "releases" / "v0.3.0.md").is_file()

    def test_no_em_or_en_dash(self) -> None:
        text = self._notes()
        assert "\u2014" not in text
        assert "\u2013" not in text

    def test_required_sections(self) -> None:
        text = self._notes()
        for heading in ("## Fixed", "## New", "## Privacy and safety", "## Still true"):
            assert heading in text
        # The fresh-profile line is not a "Changed" item: relative to 0.2.9
        # nothing changes, only a new setting exists.
        assert "## Changed" not in text

    def test_still_true_mentions(self) -> None:
        still = self._section("## Still true")
        assert "unsigned" in still or "not signed" in still
        assert ".sha256" in still
        assert "first run" in still
        assert "source checkout" in still

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

    def test_fresh_profile_line_is_accurate_for_a_092_user(self) -> None:
        text = " ".join(self._notes().split())
        assert "keeps your sign-ins between runs (a new setting" in text
        assert "tools.browser.fresh_profile" in text
        assert "between runs again" not in text

    def test_says_it_is_large_and_not_complete(self) -> None:
        text = " ".join(self._notes().split())
        assert "large release" in text
        assert "not complete" in text
        assert "mostly fixes and safety" not in text.lower()

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

    def test_toast_is_not_claimed_as_seen(self) -> None:
        text = " ".join(self._notes().split())
        assert "notification should say so" in text
        assert "not yet seen" in text

    def test_removed_or_corrected_claims(self) -> None:
        text = " ".join(self._notes().split())
        assert "Per the docs" not in text
        assert "newer phone app" not in text
        assert "device names" not in text
        assert "device paths" in text
        assert "stay out of what the model" not in text
        assert "only when a question needs them" in text

    def test_rc1_block_is_marked_for_removal(self) -> None:
        text = self._notes()
        assert "<!-- rc1-only: delete this block on the final release page -->" in text
        assert "<!-- end rc1-only -->" in text
        block = text.split("<!-- rc1-only", 1)[1].split("<!-- end rc1-only -->", 1)[0]
        assert "Release candidate" in block
        assert "pre-release" in block
        assert "Release candidate" not in text.split("<!-- end rc1-only -->", 1)[1]

    def test_night_line_is_not_under_privacy_and_safety(self) -> None:
        assert "Night" not in self._section("## Privacy and safety")
        assert "Night" in self._section("## New")

    def test_new_items_are_in_the_code(self) -> None:
        # Each user-facing item added in review exists in the tree.
        from arelis.tools.run_task import RunTaskTool

        assert RunTaskTool.name == "run_task"
        assert (REPO / "arelis" / "tools" / "confirm_preview.py").is_file()
        assert (REPO / "arelis" / "core" / "reliance" / "conflicts.py").is_file()
        assert (REPO / "arelis" / "core" / "reliance" / "mail_reply.py").is_file()
        assert (REPO / "arelis" / "core" / "search_loop.py").is_file()
        assert (REPO / "arelis" / "ui" / "caption_fade.py").is_file()
        settings = (REPO / "arelis" / "ui" / "settings_dialog.py").read_text(encoding="utf-8")
        assert "language_combo.addItem(" in settings and '"zh"' in settings

    def test_no_hype_words(self) -> None:
        text = self._notes().lower()
        for word in ("faster", "more reliable", "quicker"):
            assert word not in text

    def test_no_local_paths(self) -> None:
        text = self._notes()
        assert not re.search(r"[A-Za-z]:\\", text)
        assert "Users" not in text

    def test_whats_new_has_030_above_this_checkout(self) -> None:
        text = (REPO / "docs" / "whats-new.md").read_text(encoding="utf-8")
        idx_030 = text.index("## 0.3.0")
        idx_checkout = text.index("## This checkout")
        assert idx_030 < idx_checkout

    def test_whats_new_030_section_names_the_filament_exemption(self) -> None:
        text = " ".join((REPO / "docs" / "whats-new.md").read_text(encoding="utf-8").split())
        section = text.split("## 0.3.0", 1)[1].split("## This checkout", 1)[0]
        assert "Filament" in section
        assert "not complete" in section
        assert "between runs again" not in section

    def test_old_allow_paragraph_no_longer_contradicts_the_send_floor(self) -> None:
        text = " ".join((REPO / "docs" / "whats-new.md").read_text(encoding="utf-8").split())
        assert "Don't ask again turns that class off." not in text
        assert "except mail, texts and deletes, which always show the card" in text

    def test_backups_doc_says_the_backup_starts_with_030(self) -> None:
        text = " ".join((REPO / "docs" / "backups.md").read_text(encoding="utf-8").split())
        assert "This starts with 0.3.0." in text
        assert "The 0.2.9 to 0.3.0 upgrade is made by 0.2.9" in text
        assert "copy the data folder by hand first" in text

    def test_second_review_wording(self) -> None:
        text = " ".join(self._notes().split())
        # run_task: the Settings box turns the card off, voice always asks.
        assert "asks every time" not in text
        assert 'allow box "programs in the project" is on by default' in text
        assert "by voice it always asks" in text
        # Fonts: PDFs embed Zen Kaku only; Word and mail only name the fonts.
        assert "Documents and mail she writes" not in text
        assert "PDFs she writes use Zen Kaku Gothic New" in text
        assert "Word files and mail ask for them by name" in text
        # Inbox reply: an instruction to the model, not a forced handoff.
        assert "is handed to the send card" in text
        assert "told not to ask again in chat" in text
        assert "goes to the same send card" not in text
        # Calendar: the event is still added.
        assert "still adds it" in text
        # Routing: the open-page fix stopped the turn ending early.
        assert "no longer stops after the page opens" in text
        assert "were sent to the wrong tool" not in text

    def test_whats_new_chrome_line_says_still_keeps(self) -> None:
        text = " ".join((REPO / "docs" / "whats-new.md").read_text(encoding="utf-8").split())
        section = text.split("## 0.3.0", 1)[1].split("## This checkout", 1)[0]
        assert "Her Chrome still keeps your sign-ins between runs" in section


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
            "Since 0.3.0, before an in-app upgrade she copies your memory and a "
            "few settings files into `data/backups/pre-<version>/` (never "
            "passwords or tokens) and keeps the newest two. Upgrading from "
            "0.2.9 to 0.3.0 itself is not covered, so copy your data folder by "
            "hand first. Daily dated memory copies stay off. See "
            "[backups.md](docs/backups.md)."
        ) in text
        assert "allowlisted" not in text
        assert "for two weeks" not in text
        assert (REPO / "docs" / "backups.md").is_file()
