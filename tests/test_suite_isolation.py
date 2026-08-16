"""The suite must not be able to touch a real Arelis profile.

Written after finding out it could. A test run appended a fixture email address and a
pytest temp path to data/action_ledger.jsonl -- the real one, next to the real profile --
and had been writing to the live memory.db and tool_cache for as long as those tests had
existed. Nothing failed, which is why it went unnoticed: writing to the wrong database
looks exactly like working.

tests/conftest.py fixes it by pointing ARELIS_DATA_DIR at a temporary directory when it is
imported. These tests are here because that fix has a failure mode that is invisible --
move it a few lines later, into an autouse fixture, and it still looks right, still sets the
variable, and no longer works, because the module-level constants it needs to influence were
computed during collection.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from arelis import paths

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_the_suite_is_not_pointed_at_a_real_profile() -> None:
    root = paths.user_data_dir()
    assert root != REPO_ROOT, (
        "the suite is running against the checkout's own data root, which is somebody's "
        "live profile: data/profile.yaml, data/secrets.yaml and data/memory.db are the "
        "real ones. tests/conftest.py is supposed to have overridden ARELIS_DATA_DIR."
    )
    assert root.is_relative_to(Path(tempfile.gettempdir()).resolve()), (
        f"the data root is {root}, which is not under the system temp directory. Tests "
        "may only write somewhere it costs nothing to delete."
    )


def test_the_override_happened_before_modules_cached_their_paths() -> None:
    """The ordering check, and the only one that catches the real regression.

    jobs.store and memory.store each resolve a path once, at import. Those imports happen
    while pytest collects the test modules, so an override installed by a fixture arrives
    too late to reach them: user_data_dir() would report the sandbox while every write went
    to the profile. Reaching into a private for the memory default is deliberate -- it is
    the constant whose timing is at issue, and asserting on a public wrapper would pass
    while the constant stayed wrong.
    """
    from arelis.jobs.store import JOBS_PATH
    from arelis.memory.store import _DEFAULT_PATH

    root = paths.user_data_dir()
    for name, path in (("jobs.yaml", JOBS_PATH), ("memory.db", _DEFAULT_PATH)):
        assert path.is_relative_to(root), (
            f"{name} resolves to {path}, outside the sandbox at {root}. The environment "
            "override must be in place before the test modules are imported, which means "
            "at conftest import time and not in a fixture."
        )
