"""First-run prepare worker: download path, and plain failure sentences.

Network and process starts are mocked. These tests never talk to the real
machine's Ollama, never hit GitHub, and never launch the installer.
"""

from __future__ import annotations

import ast
import errno
import json
import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from arelis.setup.catalog import EMBED_TAG
from arelis.setup.engine import (
    download_ollama_setup,
    pull_tag,
    run_ollama_setup,
    start_ollama,
)
from arelis.ui.setup_wizard import ModelSetupDialog, _PrepareWorker, _ProbeWorker

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


class TestGroupA:
    def test_a1_happy_path_pulls_chat_then_recall(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qt_app
    ) -> None:
        pulled: list[str] = []

        def pull(tag: str, progress=None) -> None:
            pulled.append(tag)
            if progress is not None:
                progress("pulling", 1, 2)

        _patch_wizard(monkeypatch, tmp_path, pull_tag=pull)
        failed, ok, progressed = _run_worker(_PrepareWorker(_TAG))
        assert failed == []
        assert ok == [True]
        assert pulled == [_TAG, EMBED_TAG]
        assert progressed

    def test_a2_already_on_this_pc(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qt_app
    ) -> None:
        pull = MagicMock()
        _patch_wizard(
            monkeypatch,
            tmp_path,
            already_pulled=lambda tag: True,
            pull_tag=pull,
        )
        failed, ok, progressed = _run_worker(_PrepareWorker(_TAG))
        assert failed == []
        assert ok == [True]
        pull.assert_not_called()
        texts = " ".join(item[0] for item in progressed)
        assert "already on this PC" in texts

    def test_a3_installed_but_not_running_skips_download(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qt_app
    ) -> None:
        download = MagicMock()
        installer = MagicMock()
        start = MagicMock(return_value=None)
        _patch_wizard(
            monkeypatch,
            tmp_path,
            ollama_reachable=lambda: False,
            find_ollama_exe=lambda: tmp_path / "ollama.exe",
            download_ollama_setup=download,
            run_ollama_setup=installer,
            start_ollama=start,
            already_pulled=lambda tag: True,
        )
        failed, ok, _progressed = _run_worker(_PrepareWorker(_TAG))
        assert failed == []
        assert ok == [True]
        download.assert_not_called()
        installer.assert_not_called()
        start.assert_called_once()

    def test_a4_cancel(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qt_app) -> None:
        download = MagicMock()
        installer = MagicMock()
        reachable = MagicMock(return_value=False)
        _patch_wizard(
            monkeypatch,
            tmp_path,
            ollama_reachable=reachable,
            find_ollama_exe=lambda: None,
            download_ollama_setup=download,
            run_ollama_setup=installer,
        )
        worker = _PrepareWorker(_TAG)
        worker.cancel()
        failed, ok, progressed = _run_worker(worker)
        assert failed == []
        assert ok == []
        assert progressed == []
        reachable.assert_not_called()
        download.assert_not_called()
        installer.assert_not_called()

        worker = _PrepareWorker(_TAG)

        def cancel_after_download(*_args, **_kwargs) -> None:
            worker.cancel()

        download.side_effect = cancel_after_download
        _patch_wizard(
            monkeypatch,
            tmp_path,
            ollama_reachable=lambda: False,
            find_ollama_exe=lambda: None,
            download_ollama_setup=download,
            run_ollama_setup=installer,
        )
        failed, ok, _progressed = _run_worker(worker)
        assert failed == []
        assert ok == []
        download.assert_called()
        installer.assert_not_called()

    def test_a5_voice_fails_setup_still_finishes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qt_app
    ) -> None:
        _patch_wizard(monkeypatch, tmp_path, already_pulled=lambda tag: True)

        def boom(progress=None) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "arelis.voice.prepare.missing_voice_parts",
            lambda allowed_only=True: ["the ear"],
        )
        monkeypatch.setattr("arelis.voice.prepare.prepare_voice_files", boom)
        failed, ok, _progressed = _run_worker(_PrepareWorker(_TAG))
        assert failed == []
        assert ok == [True]

    def test_a6_pull_tag_stream_and_errors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[tuple[str, int, int]] = []

        def ok_handler(request: httpx.Request) -> httpx.Response:
            payload = "\n".join(
                [
                    json.dumps({"status": "pulling manifest", "completed": 1, "total": 4}),
                    json.dumps({"status": "success", "completed": 4, "total": 4}),
                ]
            )
            return httpx.Response(200, text=payload)

        _patch_client(monkeypatch, ok_handler)
        pull_tag("mistral:7b", progress=lambda status, done, total: seen.append((status, done, total)))
        assert seen

        def not_found(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="not found")

        _patch_client(monkeypatch, not_found)
        with pytest.raises(RuntimeError) as caught:
            pull_tag("missing-tag")
        assert "missing-tag" in str(caught.value)
        assert "404" in str(caught.value)

        def stream_error(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=json.dumps({"error": "blob write failed"}))

        _patch_client(monkeypatch, stream_error)
        with pytest.raises(RuntimeError) as caught:
            pull_tag("mistral:7b")
        assert "blob write failed" in str(caught.value)

        with pytest.raises(ValueError):
            pull_tag("")

    def test_a7_download_writes_then_renames(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        body = b"fake-ollama-setup"
        dest = tmp_path / "OllamaSetup.exe"
        progressed: list[tuple[str, int, int]] = []

        def ok_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=body,
                headers={"Content-Length": str(len(body))},
            )

        _patch_client(monkeypatch, ok_handler)
        result = download_ollama_setup(
            dest,
            progress=lambda status, done, total: progressed.append((status, done, total)),
        )
        assert result == dest
        assert dest.read_bytes() == body
        assert not dest.with_suffix(dest.suffix + ".part").exists()
        assert progressed

        def missing(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="missing")

        dest_404 = tmp_path / "missing" / "OllamaSetup.exe"
        _patch_client(monkeypatch, missing)
        with pytest.raises(httpx.HTTPStatusError):
            download_ollama_setup(dest_404)
        assert not dest_404.exists()

    def test_a8_run_ollama_setup_messages(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        missing = tmp_path / "nope.exe"
        assert "installer is missing" in (run_ollama_setup(missing) or "").lower()

        setup = tmp_path / "OllamaSetup.exe"
        setup.write_bytes(b"setup")

        monkeypatch.setattr(
            "arelis.setup.engine.hidden_run",
            lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
        )
        assert run_ollama_setup(setup) is None

        monkeypatch.setattr(
            "arelis.setup.engine.hidden_run",
            lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
        )
        monkeypatch.setattr("arelis.setup.engine.subprocess.Popen", MagicMock())
        opened = run_ollama_setup(setup) or ""
        assert "installer is open" in opened.lower()

        def popen_fails(*_args, **_kwargs):
            raise OSError("launch blocked")

        monkeypatch.setattr("arelis.setup.engine.subprocess.Popen", popen_fails)
        unfinished = run_ollama_setup(setup) or ""
        assert "did not finish" in unfinished.lower()

        def timed_out(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="OllamaSetup.exe", timeout=600)

        monkeypatch.setattr("arelis.setup.engine.hidden_run", timed_out)
        stalled = run_ollama_setup(setup) or ""
        assert "Could not run the Ollama installer" in stalled


# --- Group B: plain text (fail on main by assertion, pass after) ---


class TestGroupB:
    def test_b1_download_network_failures(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        qt_app,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="arelis.ui.setup_wizard")
        installer = MagicMock()
        cases = [
            httpx.ConnectError("[Errno 11001] getaddrinfo failed"),
            httpx.ReadTimeout("Read timed out"),
            _status_error(503),
        ]
        kinds = ("network", "network", "network")
        raws = (
            "getaddrinfo failed",
            "Read timed out",
            "503",
        )
        for exc, kind, raw in zip(cases, kinds, raws, strict=True):
            caplog.clear()
            installer.reset_mock()
            _patch_wizard(
                monkeypatch,
                tmp_path,
                ollama_reachable=lambda: False,
                find_ollama_exe=lambda: None,
                download_ollama_setup=MagicMock(side_effect=exc),
                run_ollama_setup=installer,
            )
            failed, ok, _progressed = _run_worker(_PrepareWorker(_TAG))
            _assert_plain(failed, ok, caplog, kind, raw)
            installer.assert_not_called()

    def test_b2_disk_full(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        qt_app,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="arelis.ui.setup_wizard")
        disk = OSError(errno.ENOSPC, "No space left on device")
        _patch_wizard(
            monkeypatch,
            tmp_path,
            ollama_reachable=lambda: False,
            find_ollama_exe=lambda: None,
            download_ollama_setup=MagicMock(side_effect=disk),
        )
        failed, ok, _progressed = _run_worker(_PrepareWorker(_TAG))
        _assert_plain(failed, ok, caplog, "disk", "No space left on device")

        caplog.clear()
        _patch_wizard(
            monkeypatch,
            tmp_path,
            ollama_reachable=lambda: True,
            pull_tag=MagicMock(
                side_effect=RuntimeError("write /x/blob: no space left on device")
            ),
        )
        failed, ok, _progressed = _run_worker(_PrepareWorker(_TAG))
        _assert_plain(failed, ok, caplog, "disk", "no space left on device")

    def test_b3_installer_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        qt_app,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="arelis.ui.setup_wizard")
        for raw in _INSTALLER_STRINGS:
            caplog.clear()
            _patch_wizard(
                monkeypatch,
                tmp_path,
                ollama_reachable=lambda: False,
                find_ollama_exe=lambda: None,
                download_ollama_setup=MagicMock(),
                run_ollama_setup=MagicMock(return_value=raw),
            )
            failed, ok, _progressed = _run_worker(_PrepareWorker(_TAG))
            _assert_plain(failed, ok, caplog, "installer", raw)

    def test_b4_engine_will_not_start(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        qt_app,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="arelis.ui.setup_wizard")
        raw = "Ollama started but is not answering yet. Wait a moment and try again."
        _patch_wizard(
            monkeypatch,
            tmp_path,
            ollama_reachable=lambda: False,
            find_ollama_exe=lambda: tmp_path / "ollama.exe",
            start_ollama=MagicMock(return_value=raw),
            already_pulled=lambda tag: True,
        )
        failed, ok, _progressed = _run_worker(_PrepareWorker(_TAG))
        _assert_plain(failed, ok, caplog, "engine_start", raw)

    def test_b5_pull_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        qt_app,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="arelis.ui.setup_wizard")
        raw = "Ollama could not pull `x` (HTTP 404). not found"
        _patch_wizard(
            monkeypatch,
            tmp_path,
            pull_tag=MagicMock(side_effect=RuntimeError(raw)),
        )
        failed, ok, _progressed = _run_worker(_PrepareWorker(_TAG))
        _assert_plain(failed, ok, caplog, "pull", raw)

        caplog.clear()

        def pull_recall(tag: str, progress=None) -> None:
            if tag == EMBED_TAG:
                raise RuntimeError(raw)

        _patch_wizard(
            monkeypatch,
            tmp_path,
            already_pulled=lambda tag: tag != EMBED_TAG,
            pull_tag=pull_recall,
        )
        failed, ok, _progressed = _run_worker(_PrepareWorker(_TAG))
        _assert_plain(failed, ok, caplog, "pull", raw)

        caplog.clear()
        mid = httpx.ReadError("peer closed")
        _patch_wizard(
            monkeypatch,
            tmp_path,
            pull_tag=MagicMock(side_effect=mid),
        )
        failed, ok, _progressed = _run_worker(_PrepareWorker(_TAG))
        _assert_plain(failed, ok, caplog, "engine_start", "peer closed")
        assert "online" not in failed[0].lower()

    def test_b6_unexpected_does_not_leak_a_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        qt_app,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="arelis.ui.setup_wizard")
        raw = r"secret C:\Users\someone\x"
        _patch_wizard(
            monkeypatch,
            tmp_path,
            ollama_reachable=MagicMock(side_effect=ValueError(raw)),
        )
        failed, ok, _progressed = _run_worker(_PrepareWorker(_TAG))
        _assert_plain(failed, ok, caplog, "unknown", raw)

    def test_b7_dialog_shows_plain_text(self, monkeypatch: pytest.MonkeyPatch, qt_app) -> None:
        monkeypatch.setattr(_ProbeWorker, "start", lambda self: None)
        text = _NETWORK_SENTENCE
        try:
            from arelis.setup.plain_errors import PLAIN

            text = PLAIN["network"]
        except ImportError:
            pass
        dialog = ModelSetupDialog()
        try:
            dialog._on_failed(text)
            assert dialog._ready_status.text() == text
            assert dialog._use.text() == "Try again"
        finally:
            dialog.deleteLater()


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


class TestGroupC:
    def test_c1_single_failed_emit_inside_fail(self) -> None:
        tree = ast.parse(_WIZARD.read_text(encoding="utf-8"))
        emits = _failed_emits(tree)
        assert len(emits) == 1
        assert emits[0][0] == "_fail"

    def test_c2_stage_names(self) -> None:
        from arelis.setup.plain_errors import STAGES

        tree = ast.parse(_WIZARD.read_text(encoding="utf-8"))
        assigned: set[str] = set()
        for value in _stage_assignments(tree):
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                assigned.add(value.value)
            elif isinstance(value, ast.Name):
                from arelis.setup import plain_errors

                assigned.add(getattr(plain_errors, value.id))
            else:
                raise AssertionError(f"unrecognised self._stage assignment: {ast.dump(value)}")
        assert assigned <= set(STAGES)
        required = set(STAGES) - {"unexpected"}
        assert required <= assigned

    def test_c3_no_raw_leak(self) -> None:
        from arelis.setup.plain_errors import PLAIN, STAGES, plain_failure

        request = httpx.Request("GET", "https://example.invalid/")
        response = httpx.Response(500, request=request)
        problems: list[BaseException | str] = [
            ValueError("secret-value-error-token"),
            KeyError("secret-key-error-token"),
            OSError("plain os error token"),
            OSError(errno.ENOSPC, "No space left on device"),
            httpx.ConnectError("connect-error-token"),
            httpx.HTTPStatusError("status-error-token", request=request, response=response),
            RuntimeError("HTTP 500 boom-token"),
            "",
            "x" * 4000,
            r"C:\Users\someone\secret-path",
        ]
        allowed = set(PLAIN.values())
        for stage in STAGES:
            for problem in problems:
                result = plain_failure(stage, problem)
                assert result in allowed
                text = str(problem)
                if text:
                    assert text not in result

    def test_c4_message_hygiene(self) -> None:
        from arelis.setup.plain_errors import PLAIN, SUFFIX

        kinds = {
            "network",
            "disk",
            "installer",
            "engine_start",
            "engine_missing",
            "pull",
            "unknown",
        }
        assert set(PLAIN) == kinds
        banned = ("Traceback", "Errno", "httpx", "HTTP", "Exception", "\\", "\u2014")
        for text in PLAIN.values():
            assert text.endswith(SUFFIX)
            sentences = [part for part in text.replace("?", ".").replace("!", ".").split(".") if part.strip()]
            assert len(sentences) <= 4
            for word in banned:
                assert word not in text


# --- Group D: pinned wording and real-engine scenarios ---


class TestGroupD:
    def test_d1_pinned_sentences(self) -> None:
        from arelis.setup.plain_errors import PLAIN, SUFFIX

        assert SUFFIX == _SUFFIX
        assert PLAIN["engine_start"] == _ENGINE_START_SENTENCE
        assert PLAIN["pull"] == _PULL_SENTENCE
        assert PLAIN["network"] == _NETWORK_SENTENCE
        assert PLAIN["disk"].endswith("Free some space, then try again. " + SUFFIX)
        assert PLAIN["installer"].endswith(
            "finish it there, then try again. " + SUFFIX
        )
        assert PLAIN["unknown"] == (
            "Setup hit a problem it did not expect. Try again. " + SUFFIX
        )
        assert "moment" not in PLAIN["engine_missing"].lower()
        assert PLAIN["engine_missing"].endswith(SUFFIX)

    def test_d2_enospace_errno_without_disk_words(self) -> None:
        from arelis.setup.plain_errors import PLAIN, plain_failure

        bare = OSError(errno.ENOSPC, "resource exhausted")
        text = str(bare).lower()
        assert "no space left" not in text
        assert "not enough space" not in text
        assert "disk full" not in text
        assert plain_failure("download_engine", bare) == PLAIN["disk"]
        assert plain_failure("pull_model", bare) == PLAIN["disk"]

        win = OSError("write failed")
        win.winerror = 112
        win_text = str(win).lower()
        assert "no space left" not in win_text
        assert "not enough space" not in win_text
        assert "disk full" not in win_text
        assert plain_failure("download_engine", win) == PLAIN["disk"]
        assert plain_failure("pull_model", win) == PLAIN["disk"]

    def test_d3_pull_internet_down_and_registry_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from arelis.setup.plain_errors import PLAIN, plain_failure

        # Phrases from reviewer memory, not a live Ollama capture.
        host = (
            'pull model manifest: Get "https://registry.ollama.ai/v2/library/'
            'qwen3.5/manifests/9b": dial tcp: lookup registry.ollama.ai: no such host'
        )
        timeout = (
            'pull model manifest: Get "https://registry.ollama.ai/v2/library/'
            "qwen3.5/manifests/9b\": dial tcp 104.21.1.1:443: i/o timeout"
        )

        def host_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=json.dumps({"error": host}))

        def timeout_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=json.dumps({"error": timeout}))

        _patch_client(monkeypatch, host_handler)
        with pytest.raises(RuntimeError) as caught:
            pull_tag("qwen3.5:9b")
        assert plain_failure("pull_model", caught.value) == PLAIN["network"]

        _patch_client(monkeypatch, timeout_handler)
        with pytest.raises(RuntimeError) as caught:
            pull_tag("qwen3.5:9b")
        assert plain_failure("pull_model", caught.value) == PLAIN["network"]

    def test_d4_pull_tag_not_found_and_disk(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from arelis.setup.plain_errors import PLAIN, plain_failure

        def missing(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                text=json.dumps({"error": "pull model manifest: file does not exist"}),
            )

        _patch_client(monkeypatch, missing)
        with pytest.raises(RuntimeError) as caught:
            pull_tag("missing-tag")
        assert plain_failure("pull_model", caught.value) == PLAIN["pull"]

        def disk_linux(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                text=json.dumps({"error": "write /x/blob: no space left on device"}),
            )

        def disk_win(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                text=json.dumps(
                    {"error": "write C:\\x\\blob: There is not enough space on the disk."}
                ),
            )

        _patch_client(monkeypatch, disk_linux)
        with pytest.raises(RuntimeError) as caught:
            pull_tag("qwen3.5:9b")
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

    def test_d6_start_ollama_exe_missing_and_not_answering(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from arelis.setup.plain_errors import PLAIN, plain_failure

        monkeypatch.setattr(
            "arelis.setup.engine.ollama_reachable",
            lambda *_args, **_kwargs: False,
        )
        monkeypatch.setattr("arelis.setup.engine.find_ollama_exe", lambda: None)
        raw = start_ollama()
        assert raw == _ENGINE_MISSING_TEXT
        message = plain_failure("start_engine", raw)
        assert message == PLAIN["engine_missing"]
        assert "moment" not in message.lower()

        monkeypatch.setattr(
            "arelis.setup.engine.subprocess.Popen",
            MagicMock(),
        )
        monkeypatch.setattr("arelis.setup.engine.time.sleep", lambda *_args: None)
        raw = start_ollama(Path("/x/ollama"))
        assert raw is not None
        assert "not answering" in raw.lower()
        assert plain_failure("start_engine", raw) == PLAIN["engine_start"]

    def test_d7_installer_and_download_failures(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from arelis.setup.plain_errors import PLAIN, plain_failure

        setup = tmp_path / "OllamaSetup.exe"
        setup.write_bytes(b"setup")

        monkeypatch.setattr(
            "arelis.setup.engine.hidden_run",
            lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
        )
        monkeypatch.setattr("arelis.setup.engine.subprocess.Popen", MagicMock())
        opened = run_ollama_setup(setup)
        assert opened is not None
        assert plain_failure("install_engine", opened) == PLAIN["installer"]

        monkeypatch.setattr(
            "arelis.setup.engine.hidden_run",
            MagicMock(side_effect=OSError("blocked by policy")),
        )
        blocked = run_ollama_setup(setup)
        assert blocked is not None
        assert plain_failure("install_engine", blocked) == PLAIN["installer"]

        def dns_fail(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("getaddrinfo failed", request=request)

        def forbidden(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="forbidden")

        dest = tmp_path / "dl" / "OllamaSetup.exe"
        _patch_client(monkeypatch, dns_fail)
        with pytest.raises(httpx.ConnectError) as caught:
            download_ollama_setup(dest)
        assert plain_failure("download_engine", caught.value) == PLAIN["network"]

        _patch_client(monkeypatch, forbidden)
        with pytest.raises(httpx.HTTPStatusError) as caught:
            download_ollama_setup(tmp_path / "dl2" / "OllamaSetup.exe")
        assert plain_failure("download_engine", caught.value) == PLAIN["network"]

        def ok_body(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * 10)

        _patch_client(monkeypatch, ok_body)
        monkeypatch.setattr(
            Path,
            "open",
            MagicMock(side_effect=OSError(errno.ENOSPC, "No space left on device")),
        )
        with pytest.raises(OSError) as caught:
            download_ollama_setup(tmp_path / "dl3" / "OllamaSetup.exe")
        assert plain_failure("download_engine", caught.value) == PLAIN["disk"]

    def test_d8_worker_engine_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        qt_app,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="arelis.ui.setup_wizard")
        _patch_wizard(
            monkeypatch,
            tmp_path,
            ollama_reachable=lambda: False,
            find_ollama_exe=lambda: tmp_path / "ollama.exe",
            start_ollama=MagicMock(return_value=_ENGINE_MISSING_TEXT),
            already_pulled=lambda tag: True,
        )
        failed, ok, _progressed = _run_worker(_PrepareWorker(_TAG))
        _assert_plain(failed, ok, caplog, "engine_missing", _ENGINE_MISSING_TEXT)
        assert "moment" not in failed[0].lower()
