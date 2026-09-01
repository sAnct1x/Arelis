"""The self-updater: what it offers, what it refuses, and what it will not install.

Nothing here touches the network. ``available_update`` takes the fetcher as an argument for
exactly that reason, and the download tests run against a local httpx transport, so the
digest check is exercised for real rather than described.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from packaging.version import Version

from arelis import update


def release_payload(
    tag: str = "v0.2.0",
    *,
    draft: bool = False,
    prerelease: bool = False,
    assets: list[dict] | None = None,
) -> dict:
    if assets is None:
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


class TestWhatCountsAsAnUpdate:
    def test_a_newer_tag_is_offered(self) -> None:
        release = update.available_update("0.1.0", fetch=lambda: update.parse_release(release_payload()))
        assert release is not None
        assert release.version == Version("0.2.0")
        assert release.setup_name.endswith("-setup.exe")

    def test_the_version_you_are_running_is_not_an_update(self) -> None:
        assert update.available_update("0.2.0", fetch=lambda: update.parse_release(release_payload())) is None

    def test_an_older_release_is_not_an_update(self) -> None:
        assert update.available_update("0.3.0", fetch=lambda: update.parse_release(release_payload())) is None

    def test_ten_is_newer_than_nine(self) -> None:
        """The reason tags are parsed rather than compared as text."""
        release = update.available_update(
            "0.9.0", fetch=lambda: update.parse_release(release_payload("v0.10.0"))
        )
        assert release is not None
        assert release.version == Version("0.10.0")

    def test_a_network_that_is_not_there_is_not_news(self) -> None:
        """A background check offline must be silent, not an error on somebody's desktop."""

        def unreachable() -> update.Release | None:
            raise httpx.ConnectError("no route to host")

        assert update.available_update("0.1.0", fetch=unreachable) is None


class TestWhatIsIgnored:
    def test_a_draft_is_not_offered(self) -> None:
        """Drafts are where releases start, and publishing is meant to be the decision."""
        assert update.parse_release(release_payload(draft=True)) is None

    def test_a_prerelease_is_not_offered(self) -> None:
        assert update.parse_release(release_payload(prerelease=True)) is None

    def test_a_release_with_no_installer_is_not_offered(self) -> None:
        """Source-only releases are ordinary. They must not become an error."""
        assert update.parse_release(release_payload(assets=[])) is None

    def test_an_installer_with_no_digest_is_not_offered(self) -> None:
        """Refusing here is what keeps download() from ever having nothing to check."""
        payload = release_payload()
        payload["assets"] = [a for a in payload["assets"] if not a["name"].endswith(".sha256")]
        assert update.parse_release(payload) is None

    def test_a_tag_that_is_not_a_version_is_ignored(self) -> None:
        assert update.parse_release(release_payload("nightly")) is None


class TestWhoMayUpdate:
    def test_a_source_checkout_is_never_offered_an_update(self, monkeypatch) -> None:
        """It would replace nothing it is running, and git pull is the real answer."""
        monkeypatch.setattr(update.sys, "platform", "win32")
        monkeypatch.setattr(update, "is_source_checkout", lambda: True)
        supported, why = update.updates_supported()
        assert supported is False
        assert "git pull" in why

    def test_a_pip_install_into_a_virtualenv_is_not_offered_an_update(self, monkeypatch) -> None:
        """No uninstaller means our setup .exe did not put this here, and running one over
        somebody's virtualenv is not a repair."""
        monkeypatch.setattr(update.sys, "platform", "win32")
        monkeypatch.setattr(update, "is_source_checkout", lambda: False)
        monkeypatch.setattr(update, "install_root", lambda: None)
        supported, why = update.updates_supported()
        assert supported is False
        assert "installer" in why

    def test_an_installed_copy_may_update(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(update.sys, "platform", "win32")
        monkeypatch.setattr(update, "is_source_checkout", lambda: False)
        monkeypatch.setattr(update, "install_root", lambda: tmp_path)
        assert update.updates_supported() == (True, "")

    def test_the_installer_is_recognised_by_its_uninstaller(self, monkeypatch, tmp_path) -> None:
        """The non-vacuity half of the check above: it is looking at something real."""
        package = tmp_path / "Lib" / "site-packages" / "arelis"
        package.mkdir(parents=True)
        monkeypatch.setattr(update, "PACKAGE_ROOT", package)
        assert update.install_root() is None

        (tmp_path / "unins000.exe").write_bytes(b"MZ")
        assert update.install_root() == tmp_path

    def test_updates_are_refused_off_windows(self, monkeypatch) -> None:
        monkeypatch.setattr(update.sys, "platform", "linux")
        supported, why = update.updates_supported()
        assert supported is False
        assert "Windows" in why


class TestHowOftenItAsks:
    def test_the_first_launch_checks(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(update, "cache_dir", lambda: tmp_path)
        assert update.check_is_due() is True

    def test_a_second_launch_the_same_hour_does_not(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(update, "cache_dir", lambda: tmp_path)
        update.record_check()
        assert update.check_is_due() is False

    def test_a_day_later_it_checks_again(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(update, "cache_dir", lambda: tmp_path)
        update.record_check(datetime.now(UTC) - timedelta(days=1, minutes=1))
        assert update.check_is_due() is True

    def test_a_stamp_from_the_future_does_not_wedge_it_shut(self, monkeypatch, tmp_path) -> None:
        """A clock that was wrong and got fixed must not stop updates for a day."""
        monkeypatch.setattr(update, "cache_dir", lambda: tmp_path)
        update.record_check(datetime.now(UTC) + timedelta(days=400))
        assert update.check_is_due() is True

    def test_an_unreadable_stamp_means_check(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(update, "cache_dir", lambda: tmp_path)
        (tmp_path / "update-check.json").write_text("{not json", encoding="utf-8")
        assert update.check_is_due() is True


class TestTheDigest:
    def test_a_sha256sum_line_is_understood(self) -> None:
        digest = "a" * 64
        assert update.expected_digest(f"{digest}  Arelis-0.2.0-win64-setup.exe\n") == digest

    def test_an_uppercase_digest_is_normalised(self) -> None:
        assert update.expected_digest(f"{'AB' * 32}  setup.exe") == "ab" * 32

    def test_a_file_with_no_digest_is_an_error(self) -> None:
        with pytest.raises(update.UpdateError):
            update.expected_digest("404: Not Found")

    def test_something_that_is_not_hexadecimal_is_not_a_digest(self) -> None:
        with pytest.raises(update.UpdateError):
            update.expected_digest(f"{'z' * 64}  setup.exe")


class TestDownloading:
    """Runs against a local transport, so verification is exercised rather than described."""

    @staticmethod
    def _release() -> update.Release:
        return update.Release(
            version=Version("0.2.0"),
            tag="v0.2.0",
            setup_name="Arelis-0.2.0-win64-setup.exe",
            setup_url="https://example.invalid/setup.exe",
            digest_url="https://example.invalid/setup.exe.sha256",
            size=9,
            page_url="https://example.invalid/releases",
        )

    @staticmethod
    def _serve(monkeypatch, body: bytes, digest: str) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith(".sha256"):
                return httpx.Response(200, text=f"{digest}  Arelis-0.2.0-win64-setup.exe\n")
            return httpx.Response(200, content=body)

        transport = httpx.MockTransport(handler)
        original = httpx.Client

        def client(*args, **kwargs):
            kwargs["transport"] = transport
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", client)

    def test_a_good_download_lands_under_its_real_name(self, monkeypatch, tmp_path) -> None:
        body = b"installer"
        self._serve(monkeypatch, body, hashlib.sha256(body).hexdigest())
        path = update.download(self._release(), into=tmp_path)
        assert path.name == "Arelis-0.2.0-win64-setup.exe"
        assert path.read_bytes() == body
        assert not list(tmp_path.glob("*.part")), "the partial file should have been renamed"

    def test_a_download_that_does_not_match_its_digest_is_deleted(self, monkeypatch, tmp_path) -> None:
        """The whole reason the digest is published. A mismatch must leave nothing behind
        that looks like an installer, because the next thing anyone does is run it."""
        self._serve(monkeypatch, b"tampered", hashlib.sha256(b"expected").hexdigest())
        with pytest.raises(update.UpdateError, match="did not match its published digest"):
            update.download(self._release(), into=tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_progress_is_reported(self, monkeypatch, tmp_path) -> None:
        body = b"installer"
        self._serve(monkeypatch, body, hashlib.sha256(body).hexdigest())
        seen: list[tuple[int, int]] = []
        update.download(self._release(), into=tmp_path, progress=lambda got, total: seen.append((got, total)))
        assert seen
        assert seen[-1][0] == len(body)

    def test_an_older_download_is_cleaned_up(self, monkeypatch, tmp_path) -> None:
        stale = tmp_path / "Arelis-0.1.0-win64-setup.exe"
        stale.write_bytes(b"old")
        body = b"installer"
        self._serve(monkeypatch, body, hashlib.sha256(body).hexdigest())
        update.download(self._release(), into=tmp_path)
        assert not stale.exists()


def test_the_api_url_follows_the_source_url() -> None:
    """A fork must not offer its users the upstream's releases."""
    assert update.api_url() == "https://api.github.com/repos/sAnct1x/arelis/releases/latest"


def test_the_installer_is_told_to_relaunch(monkeypatch, tmp_path) -> None:
    """Without /relaunch=yes a self-update ends with Arelis closed and no explanation,
    because the [Run] entry a user clicks is skipped in a silent install."""
    monkeypatch.setattr(update.sys, "platform", "win32")
    recorded: dict[str, object] = {}

    def fake_popen(argv, **kwargs):
        recorded["argv"] = argv
        recorded["kwargs"] = kwargs
        return None

    monkeypatch.setattr(update.subprocess, "Popen", fake_popen)
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"MZ")
    update.start_installer(installer)

    argv = recorded["argv"]
    assert argv[0] == str(installer)
    assert "/SILENT" in argv
    assert "/relaunch=yes" in argv
    assert recorded["kwargs"]["creationflags"] & 0x00000008, "must be detached to survive our exit"


def test_nothing_the_installer_runs_goes_through_a_pip_launcher() -> None:
    """The defect that would have shipped, pinned so it cannot come back.

    pip writes the absolute path of the installing interpreter into every .exe launcher it
    generates, which during a build is the build directory. A shortcut pointing at one does
    nothing on any other machine; on the build machine it runs the build tree, so it looks
    like it works. The only relocatable shebang those launchers accept is a bare name,
    resolved against PATH -- measured on the machine this was found on, that started an
    unrelated Python 3.11 and imported arelis out of a source checkout, which is worse than
    failing.

    So every entry point the installer names has to be the interpreter itself. That covers
    both shortcuts, the "start now" checkbox, the update relaunch and the uninstall hook
    that removes scheduled tasks -- the last one being the entry whose silent failure leaves
    Windows waking on a timer forever.
    """
    script = (Path(__file__).resolve().parent.parent / "win-installer" / "arelis.iss").read_text(
        encoding="utf-8"
    )

    # By section, rather than by matching every line that mentions a path. [InstallDelete]
    # names those launchers on purpose, to clear them off machines that installed 0.1.0
    # before they were removed, so a check that read the file as a flat list of lines would
    # have to be right about which mention is the cleanup -- and would be wrong the day the
    # directives are written in the other order.
    sections: dict[str, list[str]] = {}
    current = ""
    pending = ""
    for raw in script.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            current, pending = line, ""
        elif not line or line.startswith(";"):
            continue
        elif line.endswith("\\"):
            # An Inno directive may be split across lines with a trailing backslash, and a
            # check that read half of one would pass on the half without the Filename.
            pending += line[:-1].strip() + " "
        else:
            sections.setdefault(current, []).append(pending + line)
            pending = ""

    for section in ("[Icons]", "[Run]", "[UninstallRun]"):
        assert section in sections, f"{section} is gone from the installer script"
        started = [d for d in sections[section] if "Filename:" in d]
        assert started, f"{section} starts nothing at all, which cannot be right"
        for directive in started:
            assert "Scripts\\arelis" not in directive, (
                f"{section} starts a pip-generated launcher, which carries the build "
                f"machine's interpreter path: {directive[:160]}"
            )
            assert (
                "{app}\\python.exe" in directive
                or "{app}\\pythonw.exe" in directive
                or "{uninstallexe}" in directive
            ), f"{section} does not start the bundled interpreter directly: {directive[:160]}"


def test_the_installer_script_reads_the_relaunch_flag() -> None:
    """The Pascal half of the pair above, and the ordering rule that is easy to break:
    everything after [Code] is source, so a section below it stops being a section."""
    script = (Path(__file__).resolve().parent.parent / "win-installer" / "arelis.iss").read_text(
        encoding="utf-8"
    )
    assert "Check: RelaunchRequested" in script
    assert "function RelaunchRequested" in script
    assert "{param:relaunch|no}" in script
    assert script.index("[Code]") > script.index("[UninstallDelete]"), (
        "[Code] must be the last section: Inno reads everything after it as Pascal."
    )
    assert "Check: ShouldWipeData" in script
    assert "function ShouldWipeData" in script
    assert "function InitializeUninstall" in script
    assert "{param:wipe|no}" in script
    assert "MB_DEFBUTTON2" in script
    assert "{localappdata}\\Arelis" in script
    assert "{localappdata}\\Arelis-runtime" in script
    assert "{localappdata}\\Arelis-dev" in script
    assert "{userdocs}\\Arelis" not in script, (
        "Inno cannot tell a workspace from a git clone; Documents\\Arelis "
        "is only removed by --purge-user-data after a checkout check."
    )
    assert "--purge-user-data" in script
