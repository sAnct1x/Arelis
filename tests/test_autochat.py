"""ARELIS_AUTOCHAT_PROMPT: a measurement-only chat turn sent with no input device."""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget


def test_autochat_is_inert_unless_a_prompt_is_set() -> None:
    from arelis.ui import autochat

    assert autochat.install(object(), env={}) is None


def test_autochat_sends_on_its_trigger_and_logs_when_the_reply_ends(tmp_path) -> None:
    QApplication.instance() or QApplication([])
    from arelis.ui import autochat

    window = QWidget()
    window._turn_busy = False
    sent: list[str] = []

    def submit() -> None:
        sent.append(conv.input.text())
        window._turn_busy = True

    conv = SimpleNamespace(input=QLineEdit(), _submit=submit)
    window.conversation = conv
    trigger, log = tmp_path / "go", tmp_path / "autochat.log"
    env = {"ARELIS_AUTOCHAT_PROMPT": "hello", "ARELIS_AUTOCHAT_TRIGGER": str(trigger),
           "ARELIS_AUTOCHAT_LOG": str(log)}
    autochat.install(window, env=env)
    QTest.qWait(600)
    assert sent == []  # waits for the trigger
    trigger.write_text("")
    QTest.qWait(600)
    assert sent == ["hello"]
    window._turn_busy = False
    QTest.qWait(600)
    events = [line.split()[0] for line in log.read_text().splitlines()]
    assert events == ["sent", "done"]
    window.deleteLater()
