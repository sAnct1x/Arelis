"""0.3.1 copy: welcome glass, empty folders, download line, installer console.

These lock the words a new person reads. They fail on the old copy on purpose.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel

from arelis.ui.first_run import FirstRunDialog
from arelis.workspace import RootEntry, WorkspaceRoots

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "win-installer"

FOLDER_CHOICE = (
    "When Arelis first opens, it asks you to choose the folder it may work in. "
    "Later, open Settings and add a folder there."
)
CONTINUE = (
    "Continue uses this folder. Closing this window uses it too. "
    "You are choosing the folder, not skipping the question."
)
OLLAMA_NOTE = (
    "Ollama may ask you to sign in or connect other AI services. "
    "You do not need to. Skip or close that and Arelis keeps going."
)


def _labels(dialog) -> str:
    return "\n".join(w.text() for w in dialog.findChildren(QLabel) if w.text())


def _load_build():
    spec = importlib.util.spec_from_file_location("_inst_build_say", INSTALLER / "build.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Cp1252:
    """A console that refuses anything cp1252 cannot encode."""

    encoding = "cp1252"

    def __init__(self) -> None:
        self.chunks: list[str] = []

    def write(self, text: str) -> int:
        text.encode("cp1252")
        self.chunks.append(text)
        return len(text)

    def flush(self) -> None:
        return None


def test_welcome_screen_is_plain_english(qt_app, tmp_path: Path) -> None:
    dialog = FirstRunDialog(tmp_path / "Arelis")
    try:
        text = _labels(dialog)
        copy = "\n".join(
            w.text()
            for w in dialog.findChildren(QLabel)
            if w.text() and w.objectName() != "DialogPath"
        )
    finally:
        dialog.deleteLater()
    assert "youreports" not in text
    assert "your reports" in text
    assert "screenshots" in text
    assert FOLDER_CHOICE in copy
    assert CONTINUE in copy
    assert "Settings →" not in copy
    assert "\u2014" not in copy
    assert "\u2013" not in copy
    lowered = copy.lower()
    assert "config" not in lowered
    assert ".yaml" not in lowered
    assert "\\" not in copy


def test_empty_workspace_says_this_is_setup(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as caught:
        WorkspaceRoots([])
    message = str(caught.value)
    assert "setup step, not a bug" in message
    assert FOLDER_CHOICE in message
    assert "Settings →" not in message
    assert "\u2014" not in message
    assert "\u2013" not in message
    lowered = message.lower()
    assert "yaml" not in lowered
    assert "config" not in lowered
    assert "\\" not in message

    root = tmp_path / "desk"
    root.mkdir()
    live = WorkspaceRoots([RootEntry(name="desk", path=root)])
    with pytest.raises(ValueError) as again:
        live.replace_roots([])
    assert str(again.value) == message


def test_settings_folder_tab_uses_the_same_words(qt_app) -> None:
    from arelis.ui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(
        {
            "voice": {},
            "presence": {},
            "workspace": {
                "named_roots": [{"name": "desk", "path": str(Path.cwd()), "read_only": False}]
            },
            "tools": {"sms": {"inbound": {"ingest": {}}}},
        },
        list_models=lambda: [],
    )
    try:
        labels = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
        assert "folders" in labels
        assert "roots" not in labels
        hints = [
            w.text()
            for w in dialog.findChildren(QLabel)
            if w.objectName() == "SettingsHint" and w.text()
        ]
        text = "\n".join(hints)
        assert "Add a folder below." in text
        assert "Later, open Settings and add a folder there." not in text
        assert FOLDER_CHOICE not in text
        assert "config.local" not in text
        assert "Settings →" not in text
        assert "\\" not in text
        assert "\u2014" not in text
        assert "\u2013" not in text
    finally:
        dialog.close()


def test_download_line_hides_the_blob_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qt_app
) -> None:
    from arelis.setup.catalog import EMBED_TAG
    from arelis.ui.setup_wizard import _PrepareWorker
    from tests.test_setup_worker import _block_voice_model_fetch, _patch_wizard, _run_worker

    def pull(tag: str, progress=None) -> None:
        if progress is not None and tag != EMBED_TAG:
            progress("pulling 970aa74c0a90", 10, 100)

    _patch_wizard(
        monkeypatch,
        tmp_path,
        pull_tag=pull,
        already_pulled=lambda tag: False,
    )
    # The chat-model progress line is what this test checks. Stub the
    # Sherpa download and extract so the worker never fetches that archive.
    _block_voice_model_fetch(monkeypatch)
    _failed, ok, progressed = _run_worker(_PrepareWorker("qwen3.5:9b"))
    assert ok == [True]
    texts = [item[0] for item in progressed]
    assert "Downloading the model (6.6 GB)" in texts
    assert all("970aa74" not in item for item in texts)


def test_ollama_note_shows_before_the_installer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qt_app
) -> None:
    # This test is the Windows installer flow. Off Windows the worker stops
    # before the setup program and tells the person how to install Ollama.
    monkeypatch.setattr(sys, "platform", "win32")
    import arelis.ui.setup_wizard as wizard
    from arelis.ui.setup_wizard import _PrepareWorker
    from tests.test_setup_worker import _block_voice_model_fetch, _patch_wizard

    shown: list[str] = []
    at_installer: list[str] = []

    def installer(*_args, **_kwargs) -> None:
        at_installer.append(" | ".join(shown))
        return None

    _patch_wizard(
        monkeypatch,
        tmp_path,
        ollama_reachable=lambda: False,
        find_ollama_exe=lambda: None,
        already_pulled=lambda tag: True,
        run_ollama_setup=installer,
    )
    _block_voice_model_fetch(monkeypatch)
    # Patch again so the closure sees statuses reported before the call.
    monkeypatch.setattr(wizard, "run_ollama_setup", installer)
    worker = _PrepareWorker("qwen3.5:9b")
    worker.progressed.connect(lambda status, _done, _total: shown.append(status))
    worker.run()
    assert at_installer, "installer never ran"
    assert OLLAMA_NOTE in at_installer[0]


def test_say_survives_a_cp1252_console(monkeypatch: pytest.MonkeyPatch) -> None:
    build = _load_build()
    stream = _Cp1252()
    monkeypatch.setattr(build.sys, "stdout", stream)
    build.say("Settings → Notify will say so")
    build.say("done \u2713")
    text = "".join(stream.chunks)
    assert "→" not in text
    assert "->" in text
    assert "\u2713" not in text
    assert "Notify" in text
