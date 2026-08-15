"""Every location Arelis is allowed to write to, resolved in one place.

Until this module existed, all mutable state was derived from the directory above
the package. In a checkout that directory is the repository, so it worked, and it
worked so well that nothing revealed what it would mean once installed: the
directory above the package becomes ``site-packages``, which on Windows sits
inside Program Files. A standard user cannot write there. An installer replaces
it wholesale on update. Every account on the machine shares it. The first real
install would therefore have failed to save a contact, or saved one and lost it
at the next version, or shown one user another user's records — three quite
different disasters from a single wrong parent directory.

So mutable state moves out, read-only shipped assets stay beside the code, and
the two are reached through different functions here. Conflating them again
requires ignoring the names.

``%LOCALAPPDATA%`` rather than ``%APPDATA%``, deliberately. APPDATA roams: on a
domain account it is copied to a server at logon and back at logoff, and a
conversation database next to several gigabytes of model weights is exactly the
payload that turns roaming profiles into a support ticket. None of this is meant
to follow someone between machines. It is meant to stay on the one that made it.

The layout under the root mirrors the repository — ``data``, ``logs``,
``outputs``, ``models`` — which is not cosmetic. It means a checkout can point
the root at itself and every path lands where it always did, so this migration
could be done a few modules at a time with the suite green in between instead of
in one leap.

Windows gives each account its own ``%LOCALAPPDATA%``, and that fact is the whole
of Arelis's multi-user story: two people sharing a PC get two unrelated sets of
contacts, profile and memory without Arelis having any notion of an account.
``tests/test_user_data_dir.py`` pins the part that is ours. The part that is the
operating system's — that one user cannot read another's directory — is stated
there as the assumption it is, rather than dressed up as something we enforce.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Arelis"

# Read-only, shipped, installed alongside the code: persona, default config,
# fonts, icons. Never written to.
PACKAGE_ROOT = Path(__file__).resolve().parent

# The directory above the package. The repository in a checkout, site-packages in
# an install. Used to answer which of those we are in, and for resolving a
# relative path a user typed, and for nothing else -- if you are reaching for
# this to build a path to write to, you want user_data_dir() instead.
INSTALL_PARENT = PACKAGE_ROOT.parent

# An explicit override, honoured before anything else. Tests use it so they never
# touch a real profile, and it lets someone keep their data on another drive
# without editing code.
DATA_DIR_ENV = "ARELIS_DATA_DIR"


def is_source_checkout() -> bool:
    """True when Arelis is running from its own repository rather than installed.

    Two markers and both are required. ``pyproject.toml`` alone would be
    satisfied by an unrelated project that happened to have Arelis installed into
    a virtualenv beneath it, which would send that user's contacts into someone
    else's source tree. ``tests/`` is not packaged into a wheel, so an installed
    copy cannot have both no matter where it was installed.
    """
    return (INSTALL_PARENT / "pyproject.toml").is_file() and (
        INSTALL_PARENT / "tests"
    ).is_dir()


def user_data_dir() -> Path:
    """The root of everything this user's copy of Arelis may write.

    Resolved on every call rather than cached at import. The cost is a few
    string operations; the benefit is that a test can set the environment
    variable and be believed, which a module-level constant computed at import
    time would silently ignore.
    """
    override = os.environ.get(DATA_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()

    if is_source_checkout():
        return INSTALL_PARENT

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "").strip()
        if base:
            return Path(base) / APP_NAME
        # A service or stripped environment can be missing it. Spelling out the
        # same location beats failing to start over an unset variable.
        return Path.home() / "AppData" / "Local" / APP_NAME

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME

    # Linux and the CI runners. Lowercase to match the convention of everything
    # else that lands in a dotted share directory.
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    base_dir = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base_dir / APP_NAME.lower()


def state_dir() -> Path:
    """User records and durable state: contacts, profile, secrets, memory."""
    return user_data_dir() / "data"


def logs_dir() -> Path:
    return user_data_dir() / "logs"


def outputs_dir() -> Path:
    """Things Arelis produced for the user: reports, images, voice clips."""
    return user_data_dir() / "outputs"


def models_dir() -> Path:
    """Weights downloaded after install. Large, replaceable, never roamed."""
    return user_data_dir() / "models"


def default_workspace_root() -> Path:
    """The directory the agent may read and write when nothing is configured.

    A subfolder of Documents rather than Documents itself, and the reason is
    blast radius. The workspace is the set of paths a language model can write
    to and delete within, and defaulting that to everything a person owns means
    the first bad tool call is unrecoverable and entirely our fault. A folder
    that is obviously ours is discoverable, explicable, and survivable.

    Not expressible in default.yaml, because
    ``test_no_shipped_config_value_is_an_absolute_path`` forbids absolute paths
    in the shipped config -- rightly, since a path naming one machine is wrong on
    every other one. So it is computed here and ``workspace.roots`` ships empty.
    """
    if is_source_checkout():
        return INSTALL_PARENT
    # Documents can be redirected, most often into OneDrive, in which case the
    # literal path under the profile does not exist. Falling back to the profile
    # root keeps a working default instead of creating a folder nobody can find.
    documents = Path.home() / "Documents"
    base = documents if documents.is_dir() else Path.home()
    return base / APP_NAME


def ensure(path: Path) -> Path:
    """Create a directory and return it, so callers can inline the call.

    Directories are made on demand rather than at startup. A first run must not
    depend on an installer having prepared anything, both because the installer
    does not exist yet and because a user who deletes a folder to reclaim space
    should get it back rather than a stack trace.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path
