"""First-run prepare worker: download path, and plain failure sentences.

Network and process starts are mocked. These tests never talk to the real
machine's Ollama, never hit GitHub, and never launch the installer.
"""

from __future__ import annotations

import ast
import json
import logging
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
import yaml

from arelis.setup.engine import (
    pull_tag,
)
from arelis.ui.setup_wizard import _PrepareWorker

_REAL_HTTPX_CLIENT = httpx.Client
_REAL_POPEN = subprocess.Popen
_WIZARD = Path(__file__).resolve().parents[1] / "arelis" / "ui" / "setup_wizard.py"
_SUFFIX = "Nothing was lost."
_TAG = "qwen3.5:4b"
_INSTALLER_STRINGS = (
    "The Ollama installer is missing.",
    "Could not run the Ollama installer: timed out",
    "Ollama setup did not finish (code 1): Access denied",
    "The Ollama installer is open. Finish it, then come back and continue.",
)
_ENGINE_START_SENTENCE = (
    "The local engine would not start. Wait a few seconds and try again. "
    "If it keeps happening, restart your PC. Nothing was lost."
)
_PULL_SENTENCE = (
    "The model download stopped. Check your internet connection and that "
    "the disk has enough free space, then try again. Nothing was lost."
)
_NETWORK_SENTENCE = (
    "Arelis could not download the setup files. Check that this PC is online, "
    "then try again. Nothing was lost."
)
_ENGINE_MISSING_TEXT = "Ollama is not installed on this PC yet."
_ENGINE_OLD_SENTENCE = "Your local engine is out of date. Update it, then try again. " + _SUFFIX
_OLLAMA = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "ollama_pull_errors.json").read_text(
        encoding="utf-8"
    )
)["errors"]
_PULL_NETWORK_PHRASES = (
    "tls handshake timeout",
    "temporary failure in name resolution",
    "network is unreachable",
)


def _no_client(*_args, **_kwargs):
    raise AssertionError("no network in tests")


def _no_popen(*_args, **_kwargs):
    raise AssertionError("no network in tests")


@pytest.fixture(autouse=True)
def _no_real_network_or_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "Client", _no_client)
    monkeypatch.setattr(subprocess, "Popen", _no_popen)


def _patch_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return _REAL_HTTPX_CLIENT(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.invalid/OllamaSetup.exe")
    response = httpx.Response(code, request=request, text="unavailable")
    return httpx.HTTPStatusError(
        f"{code} unavailable",
        request=request,
        response=response,
    )


def _block_voice_model_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """The prepare worker calls prepare_voice_files, which downloads Sherpa.

    Stub the retrieve and the bz2 extract so a missing local model never
    hits the network or unpacks an archive. The other voice weights call
    urllib.request.urlretrieve from inside the function, so that name is
    stubbed too.
    """
    import urllib.request

    import arelis.voice.sherpa_stt as sherpa

    def _no_download(*_args: object, **_kwargs: object) -> None:
        raise OSError("voice model download is stubbed")

    def _no_extract(*_args: object, **_kwargs: object) -> None:
        raise OSError("voice model extract is stubbed")

    monkeypatch.setattr(sherpa, "urlretrieve", _no_download)
    monkeypatch.setattr(sherpa, "_extract_archive", _no_extract)
    monkeypatch.setattr(urllib.request, "urlretrieve", _no_download)


def _patch_wizard(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **overrides):
    names = {
        "ollama_reachable": lambda: True,
        "find_ollama_exe": lambda: None,
        "download_ollama_setup": MagicMock(),
        "run_ollama_setup": MagicMock(return_value=None),
        "start_ollama": MagicMock(return_value=None),
        "already_pulled": lambda tag: False,
        "pull_tag": MagicMock(),
        "runtime_dir": lambda: tmp_path,
    }
    names.update(overrides)
    import arelis.ui.setup_wizard as wizard

    for name, value in names.items():
        monkeypatch.setattr(wizard, name, value)
    _block_voice_model_fetch(monkeypatch)
    return names


def _run_worker(worker: _PrepareWorker):
    failed: list[str] = []
    ok: list[bool] = []
    progressed: list[tuple[str, int, int]] = []
    worker.failed.connect(failed.append)
    worker.finished_ok.connect(lambda: ok.append(True))
    worker.progressed.connect(lambda status, done, total: progressed.append((status, done, total)))
    worker.run()
    return failed, ok, progressed


def _assert_plain(
    failed: list[str],
    ok: list[bool],
    caplog: pytest.LogCaptureFixture,
    kind: str,
    raw: str,
) -> None:
    assert ok == []
    assert len(failed) == 1
    message = failed[0]
    assert message.endswith(_SUFFIX)
    assert raw not in message
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert raw in logged
    from arelis.setup.plain_errors import PLAIN

    assert message == PLAIN[kind]


# --- Group A: pin current behavior (pass on main and after) ---


# --- Group B: plain text (fail on main by assertion, pass after) ---


# --- Group C: drift guards ---


def _failed_emits(tree: ast.AST) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.func = ""

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            previous = self.func
            self.func = node.name
            self.generic_visit(node)
            self.func = previous

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "emit"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "failed"
            ):
                found.append((self.func, node.lineno))
            self.generic_visit(node)

    Visitor().visit(tree)
    return found


def _stage_assignments(tree: ast.AST) -> list[ast.AST]:
    values: list[ast.AST] = []

    class Visitor(ast.NodeVisitor):
        def visit_Assign(self, node: ast.Assign) -> None:
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "_stage"
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    values.append(node.value)
            self.generic_visit(node)

    Visitor().visit(tree)
    return values


# --- Group D: pinned wording and real-engine scenarios ---


class TestGroupD:


    def test_d3_real_offline_pull_and_network_phrases(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        qt_app,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from arelis.setup.plain_errors import PLAIN, plain_failure

        caplog.set_level(logging.WARNING, logger="arelis.ui.setup_wizard")
        offline = _OLLAMA["offline_pull"]

        def offline_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=json.dumps({"error": offline}))

        _patch_client(monkeypatch, offline_handler)
        with pytest.raises(RuntimeError) as caught:
            pull_tag("qwen3.5:4b")
        assert str(caught.value) == offline
        assert plain_failure("pull_model", caught.value) == PLAIN["network"]
        assert plain_failure("pull_recall", caught.value) == PLAIN["network"]

        for phrase in _PULL_NETWORK_PHRASES:
            caplog.clear()

            def handler(request: httpx.Request, phrase: str = phrase) -> httpx.Response:
                return httpx.Response(200, text=json.dumps({"error": phrase}))

            _patch_client(monkeypatch, handler)
            with pytest.raises(RuntimeError) as caught:
                pull_tag("qwen3.5:9b")
            assert str(caught.value) == phrase
            assert plain_failure("pull_model", caught.value) == PLAIN["network"]
            assert plain_failure("pull_recall", caught.value) == PLAIN["network"]

            _patch_wizard(
                monkeypatch,
                tmp_path,
                pull_tag=MagicMock(side_effect=RuntimeError(phrase)),
            )
            failed, ok, _progressed = _run_worker(_PrepareWorker(_TAG))
            _assert_plain(failed, ok, caplog, "network", phrase)

        # These two were already matched. The old full sentences around them
        # were memory, so the test keeps the phrase itself.
        for phrase in ("no such host", "i/o timeout"):
            assert plain_failure("pull_model", phrase) == PLAIN["network"]

    def test_d4_pull_tag_not_found_and_disk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from arelis.setup.plain_errors import PLAIN, plain_failure

        missing_text = _OLLAMA["bad_tag"]

        def missing(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=json.dumps({"error": missing_text}))

        _patch_client(monkeypatch, missing)
        with pytest.raises(RuntimeError) as caught:
            pull_tag("arelis-no-such-model:missingtag")
        assert str(caught.value) == missing_text
        assert plain_failure("pull_model", caught.value) == PLAIN["pull"]

        disk_text = _OLLAMA["disk_full"]

        def disk_linux(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=json.dumps({"error": disk_text}))

        # English Windows write error. Not recaptured here (this machine is Linux).
        def disk_win(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                text=json.dumps(
                    {"error": "write C:\\x\\blob: There is not enough space on the disk."}
                ),
            )

        _patch_client(monkeypatch, disk_linux)
        with pytest.raises(RuntimeError) as caught:
            pull_tag("all-minilm")
        assert str(caught.value) == disk_text
        assert plain_failure("pull_model", caught.value) == PLAIN["disk"]

        _patch_client(monkeypatch, disk_win)
        with pytest.raises(RuntimeError) as caught:
            pull_tag("qwen3.5:9b")
        assert plain_failure("pull_model", caught.value) == PLAIN["disk"]

    def test_d5_local_engine_refused_or_dropped_mid_pull(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from arelis.setup.plain_errors import PLAIN, plain_failure

        def refused(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(
                "[WinError 10061] connection refused",
                request=request,
            )

        def dropped(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadError("peer closed", request=request)

        _patch_client(monkeypatch, refused)
        with pytest.raises(httpx.ConnectError) as caught:
            pull_tag("qwen3.5:9b")
        message = plain_failure("pull_model", caught.value)
        assert message == PLAIN["engine_start"]
        assert "online" not in message.lower()

        _patch_client(monkeypatch, dropped)
        with pytest.raises(httpx.ReadError) as caught:
            pull_tag("qwen3.5:9b")
        message = plain_failure("pull_model", caught.value)
        assert message == PLAIN["engine_start"]
        assert "online" not in message.lower()

        message = plain_failure("pull_recall", httpx.RemoteProtocolError("broken"))
        assert message == PLAIN["engine_start"]
        assert "online" not in message.lower()


def test_setup_readiness_and_pull_use_configured_ollama_port(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    qt_app,
) -> None:
    """First-run readiness and pull follow ollama.base_url.

    A copy of Ollama on a non-default port has to be the server setup asks
    and downloads from. The shipped default is 11434. This pins 11436.
    """
    local = tmp_path / "config.local.yaml"
    local.write_text(
        yaml.safe_dump(
            {"ollama": {"base_url": "http://127.0.0.1:11436"}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("arelis.config.LOCAL_CONFIG_PATH", local)
    monkeypatch.setattr(
        "arelis.voice.prepare.missing_voice_parts",
        lambda *args, **kwargs: [],
    )

    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        if request.url.path == "/api/pull":
            return httpx.Response(200, text=json.dumps({"status": "success"}) + "\n")
        return httpx.Response(404, text="unexpected")

    _patch_client(monkeypatch, handler)
    failed, ok, _progressed = _run_worker(_PrepareWorker(_TAG))
    assert failed == [], failed
    assert ok == [True]
    assert seen, "setup made no Ollama request"
    ports = sorted({url.port for url in seen})
    paths = sorted({url.path for url in seen})
    assert ports == [11436], ports
    assert "/api/tags" in paths
    assert "/api/pull" in paths


def test_pull_progress_zero_and_huge_total(qt_app, monkeypatch: pytest.MonkeyPatch) -> None:
    """A model pull's byte counts must not blow up the progress bar.

    Ollama's /api/pull stream leaves total out, or sends 0, then reports
    completed and total in bytes. qwen3.5:9b is about 6.6e9, past a 32-bit
    Qt int. Zero means the bar is still working out the size.
    """
    import sys

    from arelis.setup.engine import parse_pull_status
    from arelis.ui.setup_wizard import ModelSetupDialog, _PrepareWorker, _ProbeWorker

    monkeypatch.setattr(_ProbeWorker, "start", lambda *args, **kwargs: None)
    crashes: list[BaseException] = []

    def _record(exc_type, exc, _tb) -> None:
        crashes.append(exc)

    monkeypatch.setattr(sys, "excepthook", _record)

    dialog = ModelSetupDialog()
    try:
        worker = _PrepareWorker("qwen3.5:9b", dialog)
        worker.progressed.connect(dialog._on_progress)

        def feed(data: dict) -> None:
            status, done, total = parse_pull_status(data)
            worker._report(status, done, total)

        feed({"status": "pulling manifest"})
        assert dialog._bar.minimum() == 0
        assert dialog._bar.maximum() == 0

        feed(
            {
                "status": "pulling 970aa74c0a90",
                "digest": "sha256:970aa74c0a90",
                "total": 0,
                "completed": 0,
            }
        )
        assert dialog._bar.minimum() == 0
        assert dialog._bar.maximum() == 0

        total = 6_600_000_000
        assert total > 2**31
        feed(
            {
                "status": "pulling 970aa74c0a90",
                "digest": "sha256:970aa74c0a90",
                "total": total,
                "completed": total // 2,
            }
        )
        assert crashes == []
        assert dialog._bar.minimum() == 0
        assert dialog._bar.maximum() == 100
        assert dialog._bar.value() == 50
    finally:
        dialog.close()

