"""A source ask arms a workspace read before the model.

``redirect_inspect_wander`` is gone. ``_prepare_inspect_first_move`` sets
``workspace_preinject`` to ``{action: read, path}``. ``try_inspect`` stays
the no-call floor.
"""

from __future__ import annotations

from arelis.core.call_redirects import REDIRECT_STEPS, redirect_agenda
from arelis.core.intent_catalog import inspect_read_path
from arelis.core.turn_prepare import _prepare_inspect_first_move
from tests.test_no_call_path import _ctx

_DRIVE_ASK = "where is the Drive strip?"


def test_it_is_reached_through_the_real_table() -> None:
    """The prepare helper arms the read. A web_search redirect does not."""
    ctx = _ctx(text=_DRIVE_ASK)
    ctx.tool_names = {"workspace", "web_search"}
    _prepare_inspect_first_move(ctx, _DRIVE_ASK)
    path = inspect_read_path(_DRIVE_ASK)
    assert path
    assert ctx.workspace_preinject == {"action": "read", "path": path}


def test_it_runs_last() -> None:
    """Last remaining entry once ``redirect_inspect_wander`` is dropped.

    The earlier steps stay in the order they already had.
    """
    assert REDIRECT_STEPS[-1] is redirect_agenda
