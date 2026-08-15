"""Confirm-card safety: reject placeholder / empty write args (U7 / Phase K)."""

from __future__ import annotations

from arelis.tools.base import confirm_args_blocked


def test_blocks_placeholder_phone() -> None:
    reason = confirm_args_blocked(
        "contacts",
        {"action": "add", "name": "Wife", "phone": "<user_phone_number>"},
    )
    assert reason is not None
    assert "placeholder" in reason.lower() or "user_phone" in reason.lower()


def test_blocks_empty_workspace_write() -> None:
    reason = confirm_args_blocked(
        "workspace",
        {"action": "write", "path": "tmp.txt", "content": ""},
    )
    assert reason is not None
    assert "empty" in reason.lower()


def test_allows_normal_write() -> None:
    assert (
        confirm_args_blocked(
            "workspace",
            {"action": "write", "path": "tmp.txt", "content": "hello"},
        )
        is None
    )


def test_allows_read() -> None:
    assert (
        confirm_args_blocked("workspace", {"action": "read", "path": "README.md"})
        is None
    )
