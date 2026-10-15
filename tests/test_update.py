"""The self-updater: what it offers, what it refuses, and what it will not install.

Nothing here touches the network. ``available_update`` takes the fetcher as an argument for
exactly that reason, and the download tests run against a local httpx transport, so the
digest check is exercised for real rather than described.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import httpx
import pytest
import yaml
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


class TestWhoMayUpdate:


    def test_updates_are_refused_off_windows(self, monkeypatch) -> None:
        monkeypatch.setattr(update.sys, "platform", "linux")
        supported, why = update.updates_supported()
        assert supported is False
        assert "Windows" in why


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


    def test_a_download_that_does_not_match_its_digest_is_deleted(
        self, monkeypatch, tmp_path
    ) -> None:
        """The whole reason the digest is published. A mismatch must leave nothing behind
        that looks like an installer, because the next thing anyone does is run it."""
        self._serve(monkeypatch, b"tampered", hashlib.sha256(b"expected").hexdigest())
        with pytest.raises(update.UpdateError, match="did not match its published digest"):
            update.download(self._release(), into=tmp_path)
        assert list(tmp_path.iterdir()) == []


def recorded_github_gets(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Count httpx.get calls. The stub answers 404, so nothing leaves the machine."""

    calls: list[str] = []

    def stub(url, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(str(url))
        request = httpx.Request("GET", str(url))
        return httpx.Response(404, request=request)

    monkeypatch.setattr(httpx, "get", stub)
    return calls


def _fallback_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "arelis.update" and "update checks stay on" in record.getMessage()
    ]


class TestHowACheckValueIsRead:
    """Empty, quoted, and numeric values, counted by the GitHub calls they cause.

    A real boolean is kept. false, no, off, and 0 (any case, surrounding spaces
    ignored) and the integer 0 turn the check off. An empty value, None, or any
    other word leaves it on and writes one log line.
    """

    @pytest.mark.parametrize(
        ("settings", "github_requests", "logs_a_fallback"),
        [pytest.param('updates:\n  check:\n', 1, True, id='empty'), pytest.param("updates:\n  check: ''\n", 1, True, id='empty-string')],
    )
    def test_github_is_asked_only_when_the_value_leaves_checks_on(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        settings: str,
        github_requests: int,
        logs_a_fallback: bool,
    ) -> None:
        calls = recorded_github_gets(monkeypatch)
        config = yaml.safe_load(settings)
        with caplog.at_level(logging.INFO, logger="arelis.update"):
            result = update.consider_automatic_update(config)
        assert result is None
        assert len(calls) == github_requests
        if github_requests:
            assert all("api.github.com" in url for url in calls)
        fallback = _fallback_lines(caplog)
        assert len(fallback) == (1 if logs_a_fallback else 0)
        for line in fallback:
            assert "\n" not in line
            assert "\\" not in line
            assert "/" not in line


def _let_the_prompt_reach_github(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The installer and the once-a-day stamp are not what this is measuring.

    On Linux the installer gate returns before any request, which would hide a
    setting that was read wrong. Open that gate, and the daily gate, so the
    request count is the setting's.
    """
    monkeypatch.setattr("arelis.ui.update_prompt.updates_supported", lambda: (True, ""))
    monkeypatch.setattr("arelis.ui.update_prompt.check_is_due", lambda now=None: True)
    monkeypatch.setattr(update, "cache_dir", lambda: tmp_path)


def _pump_qt(qt_app, milliseconds: int) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()
    qt_app.processEvents()


def _wait_out_check_threads(window) -> None:
    from arelis.ui.update_prompt import UpdatePrompt

    for prompt in window.findChildren(UpdatePrompt):
        thread = getattr(prompt, "_check", None)
        if thread is not None:
            thread.wait(5000)


