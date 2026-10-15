"""The workspace question: asked once, recorded, and honoured afterwards.

``workspace.roots`` decides what a language model may read, create, change and
delete. Defaulting it silently would mean a user's first indication of the
arrangement was its consequences, so first run asks -- and then must actually
remember the answer, or the asking was theatre.

These cover the part that has to be right rather than the dialog: that the
question is asked exactly once, that the answer reaches the config the agent
actually loads, and that an accepted suggestion is pinned as firmly as a typed
path. The last one is the subtle one. If accepting the default merely left the
config alone, a later change to what Arelis suggests would move an existing user's
workspace without asking, which is the same class of surprise this step exists to
prevent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from arelis import onboarding, paths
from arelis.onboarding import MARKER_NAME


@pytest.fixture
def fresh_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A data root with nothing in it, and a home to suggest a folder inside.

    The local config path is a module constant resolved at import, so it is
    redirected explicitly rather than relying on the data-root override alone.
    """
    root = tmp_path / "state"
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(root))
    monkeypatch.setattr(
        "arelis.config.LOCAL_CONFIG_PATH", root / "data" / "config.local.yaml"
    )
    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True)
    monkeypatch.setattr(paths, "INSTALL_PARENT", tmp_path / "site-packages")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    # expanduser reads the environment rather than Path.home, so a tilde would
    # otherwise expand to the real profile and write outside tmp_path.
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    return home


def _local_config() -> dict:
    from arelis.config import LOCAL_CONFIG_PATH

    return yaml.safe_load(LOCAL_CONFIG_PATH.read_text(encoding="utf-8")) or {}


# ------------------------------------------------------------- asked once


# ------------------------------------------------- what the answer is worth


def test_the_suggestion_is_a_named_folder_not_all_of_documents(
    fresh_install: Path,
) -> None:
    """Blast radius. The suggestion is what most people will accept.

    Offering Documents itself would mean the common path grants delete access to
    everything a person owns.
    """
    suggested = onboarding.suggested_root()
    assert suggested == fresh_install / "Documents" / "Arelis"
    assert suggested != fresh_install / "Documents"


def test_an_accepted_suggestion_is_pinned_like_any_other_choice(
    fresh_install: Path,
) -> None:
    """The subtle one, and the reason acceptance is written down at all.

    If accepting the default left config.local.yaml untouched, the root would
    keep being recomputed on every launch -- so changing what Arelis suggests, or
    a user redirecting Documents into OneDrive, would relocate an existing
    workspace with no prompt and no explanation. Pinning the absolute path means
    the folder they agreed to is the folder they keep.
    """
    recorded = onboarding.record_choice(None)
    roots = _local_config()["workspace"]["roots"]
    assert roots == [str(recorded)]
    assert Path(roots[0]).is_absolute()


# --------------------------------------------------------------- first use


def test_the_marker_records_what_was_agreed_to(fresh_install: Path) -> None:
    """A user asking later what they granted deserves an answer on disk.

    Versioned so a future first run that needs to ask something new can tell an
    old marker from a complete one instead of re-asking everything.
    """
    recorded = onboarding.record_choice(None)
    marker = json.loads(onboarding.marker_path().read_text(encoding="utf-8"))
    assert marker["workspace_root"] == str(recorded)
    assert marker["version"] == onboarding.MARKER_VERSION
    assert marker["answered_at"]


def test_an_unwritable_marker_does_not_stop_the_workspace_being_set(
    fresh_install: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refusing to start over an unwritten marker would be absurd.

    The workspace is the part that matters and it is written first. The cost of
    losing the marker is being asked once more next launch, which this asserts
    rather than papers over; the cost of raising here would be an Arelis that
    will not open at all.
    """
    paths.ensure(paths.state_dir())
    blocked = paths.state_dir() / "blocked"
    blocked.write_text("a file, not a directory", encoding="utf-8")
    monkeypatch.setattr(onboarding, "marker_path", lambda: blocked / MARKER_NAME)

    recorded = onboarding.record_choice(None)
    assert recorded.is_dir()
    assert _local_config()["workspace"]["roots"] == [str(recorded)]
    assert onboarding.needs_prompt(), "the accepted cost: asked again next launch"
