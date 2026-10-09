"""A source checkout says how to update in one plain line."""

from __future__ import annotations

from arelis import update

_PLAIN = "You're running from source. Update it with git."


def test_source_checkout_reason_is_plain_on_mac_and_windows(monkeypatch) -> None:
    monkeypatch.setattr(update, "is_source_checkout", lambda: True)
    for platform in ("darwin", "win32"):
        monkeypatch.setattr(update.sys, "platform", platform)
        supported, why = update.updates_supported()
        assert supported is False
        assert why == _PLAIN
        assert "--" not in why
