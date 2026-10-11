"""Environment for a program the user asked to run.

The parent process keeps its own environment. A child gets the names a
script needs to start, and nothing that looks like a credential.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

# A script can start, find its interpreter, and speak the user's language
# with these. Everything else stays in this process.
_ALLOW = (
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "LANG",
    "LC_ALL",
    "VIRTUAL_ENV",
    "PYTHONUNBUFFERED",
    "PYTHONIOENCODING",
)

_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASS|AUTH|COOKIE|SESSION")


def _dropped(name: str) -> bool:
    key = name.upper()
    if key.startswith("ARELIS_"):
        return True
    return _SECRET_NAME.search(key) is not None


def child_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Copy the allowlist, then extra names that are not credentials.

    `extra` cannot smuggle `ARELIS_*` or a name like `GITHUB_TOKEN`. A
    control flag the child must see is set on the dict this returns.
    """
    env: dict[str, str] = {}
    for name in _ALLOW:
        if _dropped(name) or name not in os.environ:
            continue
        env[name] = os.environ[name]
    for name, value in (extra or {}).items():
        if _dropped(name):
            continue
        env[str(name)] = str(value)
    return env
