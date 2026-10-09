"""Start the background core when a Mac user logs in.

Windows keeps scripts/install_core_startup.ps1. This module is the Mac
LaunchAgent with the same idea: the current interpreter, -m arelis --core,
RunAtLoad. The app offers it through --install-login-start and
--remove-login-start.
"""

from __future__ import annotations

import sys

CORE_LABEL = "app.arelis.core"


def install_login_start() -> str:
    if sys.platform != "darwin":
        return "Starting at login from this command is for Mac."
    from arelis.jobs.launchd import install_agent

    install_agent(
        CORE_LABEL,
        [sys.executable, "-m", "arelis", "--core"],
        run_at_load=True,
    )
    return "Arelis will start in the background when you log in."


def remove_login_start() -> str:
    if sys.platform != "darwin":
        return "Starting at login from this command is for Mac."
    from arelis.jobs.launchd import remove_agent

    if not remove_agent(CORE_LABEL):
        return "Login start was already off."
    return "Arelis will no longer start when you log in."
