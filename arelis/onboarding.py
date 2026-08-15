"""First run: which folder may Arelis work in?

Everything else about a first launch can be defaulted. This cannot, or rather it
can and shouldn't. ``workspace.roots`` is the set of paths a language model is
permitted to read, create, edit and delete within, and the honest thing is to say
so once, out loud, before it is true -- not to pick somewhere on the user's behalf
and let them discover the arrangement afterwards.

The default offered is ``Documents/Arelis``: a named folder Arelis makes for
itself, so a mistaken tool call ruins its own workspace rather than a Documents
folder holding fifteen years of someone's life. See
``arelis.paths.default_workspace_root``.

The answer is written into ``config.local.yaml`` as an absolute path even when the
user accepts the suggestion unchanged. That is deliberate: after onboarding the
root is pinned to what they agreed to, so a later change to what Arelis *would*
have suggested cannot silently move an existing user's workspace out from under
them. The ``.`` in the shipped default.yaml therefore only ever applies before
this has run.

A marker file records that the question was asked. Absence of the marker is what
"first run" means -- not an empty data directory, which would ask again after
someone cleared their history, and not a config check, which would ask again after
someone deleted their one root in Settings.

Kept free of Qt so the decision, the write and the marker can be tested without a
display, and so ``arelis --core`` can consult it. A headless core never prompts:
there is nobody to answer, so it runs on the default and leaves the marker alone,
and the desktop asks the first time a window opens.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arelis.config import merge_local_config
from arelis.paths import default_workspace_root, ensure, state_dir

log = logging.getLogger(__name__)

MARKER_NAME = "first-run.json"

# Bumped only if a future first run needs to ask something new. An older marker
# then means "asked about the workspace but not about X", which a later version
# can act on instead of re-asking everything.
MARKER_VERSION = 1


def marker_path() -> Path:
    return state_dir() / MARKER_NAME


def needs_prompt() -> bool:
    """Whether the workspace question still has to be put to the user.

    Read every call rather than cached, because the core process and the desktop
    are separate processes and either may be the one that has just written it.
    """
    return not marker_path().is_file()


def suggested_root() -> Path:
    """The folder offered on screen, and used if nobody is there to answer."""
    return default_workspace_root()


def record_choice(root: Path | str | None) -> Path:
    """Pin ``root`` as the workspace and note that the question was answered.

    ``None`` means the suggestion was accepted, which is treated as an answer
    rather than an absence of one: the path is on screen next to a sentence
    describing what it permits, so accepting it is a decision.

    The directory is created here. A root that does not exist would make every
    file tool fail on a fresh install with an error about a missing path, which
    reads as Arelis being broken rather than as a folder waiting to be made.

    The marker is written last and its failure is swallowed. Getting the workspace
    recorded is what matters; the worst case of an unwritten marker is being asked
    once more next launch, whereas refusing to start over it would be absurd.
    """
    chosen = Path(root).expanduser() if root else suggested_root()
    chosen = chosen.resolve()
    ensure(chosen)
    merge_local_config({"workspace": {"roots": [str(chosen)]}})
    _write_marker(chosen)
    return chosen


def _write_marker(root: Path) -> None:
    payload: dict[str, Any] = {
        "version": MARKER_VERSION,
        "workspace_root": str(root),
        "answered_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    try:
        ensure(state_dir())
        marker_path().write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        log.warning("Could not record the first-run marker: %s", exc)
