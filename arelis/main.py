from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from arelis import __license__, __source_url__, __version__
from arelis.config import load_config
from arelis.logging_setup import configure_logging, install_unhandled_hook


def main(argv: list[str] | None = None) -> int:
    # Before any subsystem that might log.exception into the void. --run-job
    # replaces this with its own jobs.log sink once runner.configure_logging runs.
    configure_logging()
    install_unhandled_hook()
    from arelis.hidden_proc import install_hidden_subprocess

    install_hidden_subprocess()

    parser = argparse.ArgumentParser(
        prog="arelis",
        description="Arelis personal research assistant",
    )
    # Names the licence and the source alongside the number. Someone asking a
    # program its version is usually about to file a bug or check what they are
    # running, and both go better with somewhere to go next.
    #
    # One line, and deliberately so: argparse runs this through the help
    # formatter, which collapses newlines, so a multi-line string here would be
    # reflowed into a paragraph rather than printed as written.
    parser.add_argument(
        "--version",
        action="version",
        version=f"arelis {__version__} ({__license__}) {__source_url__}",
        help="Print the version, licence and source location, then exit.",
    )
    parser.add_argument("--cli", action="store_true", help="Run terminal interface")
    parser.add_argument(
        "--allow-write",
        action="store_true",
        help=(
            "With --cli when stdin is not a terminal: auto-allow write/image/"
            "browser confirms. Default is deny (absence of a human is not consent)."
        ),
    )
    parser.add_argument(
        "--core",
        action="store_true",
        help=(
            "Run the always-on core (inbound SMS/RCS ingest, no glass UI). "
            "Keeps port 8765 alive after the desktop window is closed."
        ),
    )
    parser.add_argument(
        "--run-job",
        type=str,
        default=None,
        metavar="ID",
        help="Run one saved job, email the answer, and exit. Used by the scheduler.",
    )
    parser.add_argument(
        "--remove-scheduled-tasks",
        action="store_true",
        help=(
            "Delete every Windows scheduled task Arelis registered, then exit. Run by "
            "the uninstaller: a task holds an absolute path to the program, so removing "
            "the program without this leaves Windows waking on a timer to run nothing."
        ),
    )
    parser.add_argument(
        "--purge-user-data",
        action="store_true",
        help=(
            "Uninstall wipe: scheduled tasks plus published data "
            "(%%LOCALAPPDATA%%\\Arelis, Arelis-runtime, Documents\\Arelis). "
            "Refuses a source checkout. Does not touch a system Ollama install."
        ),
    )
    parser.add_argument(
        "--check-update",
        action="store_true",
        help=(
            "Ask GitHub whether a newer Arelis has been published, report, and exit. "
            "Downloads and installs nothing. The same check the app makes once a day, "
            "runnable where the answer is visible."
        ),
    )
    parser.add_argument("--config", type=str, default=None, help="Optional YAML config path")
    parser.add_argument(
        "--solar-gl",
        action="store_true",
        help=(
            "GPU solar viewport (offscreen OpenGL, then the plate paints the frame). "
            "The Arelis (dev) shortcut passes this; the installed shortcut does not."
        ),
    )
    parser.add_argument(
        "--auth-calendar",
        type=str,
        default=None,
        metavar="PROVIDER",
        help=(
            "One-shot browser OAuth for calendar: google or outlook. "
            "Writes refresh_token into data/secrets.yaml. See docs/calendar-oauth.md."
        ),
    )
    # Before parse_args: --version exits inside argparse, and the GPU flag has to
    # be visible to prepare_desktop_gl before QApplication is constructed.
    if argv is None:
        argv = sys.argv[1:]
    if "--solar-gl" in argv:
        os.environ["ARELIS_SOLAR_GL"] = "1"
    args = parser.parse_args(argv)

    # Before load_config, and deliberately. This runs from an uninstaller, by which time
    # the configuration may be edited, moved or already deleted, and failing to read it
    # is no reason to leave scheduled tasks behind.
    if args.purge_user_data:
        from arelis.uninstall import purge_user_state

        removed = purge_user_state()
        print(f"Purged {len(removed)} leftover(s): {', '.join(removed) or 'none'}")
        return 0
    if args.remove_scheduled_tasks:
        from arelis.jobs.schedule import remove_all_tasks

        removed = remove_all_tasks()
        print(f"Removed {len(removed)} scheduled task(s): {', '.join(removed) or 'none'}")
        return 0

    # Also before load_config: this reports on the program rather than acting on the
    # user's settings, and it is the thing you reach for when something about updating is
    # already not working.
    if args.check_update:
        import sys as _sys

        from arelis.paths import PACKAGE_ROOT
        from arelis.update import available_update, install_root, updates_supported

        supported, why = updates_supported()
        print(f"This copy   : arelis {__version__}")
        # Printed always, not only on failure. Every question about updating turns out to
        # be a question about which copy is asking, and the answer is these three lines.
        print(f"Launched by : {_sys.executable}")
        print(f"Package     : {PACKAGE_ROOT}")
        print(f"Install root: {install_root() or 'not an installed copy'}")
        if not supported:
            print(f"Not updated here: {why}")
            return 0
        release = available_update()
        if release is None:
            print("Latest      : nothing newer published (drafts are not offered)")
            return 0
        print(f"Available   : {release.tag} ({release.setup_name}, {release.size_text})")
        print(f"Notes       : {release.page_url}")
        return 0

    config = load_config(Path(args.config)) if args.config else load_config()

    if args.auth_calendar:
        from arelis.calendar.auth import run_auth_calendar

        return run_auth_calendar(args.auth_calendar, config)

    # Imported lazily so `arelis --cli` does not pay for loading PySide6, and so
    # a machine without a working Qt platform plugin can still use the CLI.
    if args.run_job:
        from arelis.jobs.runner import run_job

        return run_job(args.run_job, config)

    if args.core:
        from arelis.presence.core import run_core

        return run_core(config)

    if args.cli:
        from arelis.cli import run_cli

        return run_cli(config, allow_write=bool(args.allow_write))

    from arelis.ui.app import run_ui

    return run_ui(config)


if __name__ == "__main__":
    sys.exit(main())
