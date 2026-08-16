"""What only an installed copy can prove.

CI installs Arelis with ``pip install -e .``. That makes the directory above the
package the repository, so ``is_source_checkout()`` is true in every job on every
platform, and every rule that differs once installed goes untested. The gap is not
hypothetical. The window icon shipped nowhere at all for months because it lived
outside the package and went unlisted in package-data; a directory was created
inside the package on every launch of the window, which an installed copy may not be
able to write to. Both looked perfect from a checkout, and both were found by
reading rather than by a test.

So this runs against a venv that has the built *wheel* installed, from a directory
that is not the repository:

    python -m pip wheel --no-deps --wheel-dir dist .
    python -m venv ../arelis-probe
    ../arelis-probe/Scripts/python -m pip install dist/arelis-<version>-py3-none-any.whl
    cd .. ; arelis-probe/Scripts/python Arelis/scripts/installed_smoke.py

Nothing here touches the real data root. The resolution rules are read and asserted
against, and everything that would create a directory is redirected with
ARELIS_DATA_DIR first, because a check that scribbles in somebody's profile is not a
check anyone runs twice.

Exits non-zero on the first failing group so CI fails loudly, and prints every
check it made either way, because a smoke test whose output does not say what it
covered is indistinguishable from one that covered nothing.
"""

from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

# Before anything imports QtGui. There is no display in CI and Qt aborts the whole
# process rather than raising, which would look like a crash rather than a failure.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from arelis import paths

MUTABLE = (
    paths.user_data_dir,
    paths.state_dir,
    paths.logs_dir,
    paths.outputs_dir,
    paths.models_dir,
    paths.cache_dir,
)


def _release_log_file() -> None:
    """Let go of logs/arelis.log so the temporary data root can be removed.

    configure_logging() attaches a RotatingFileHandler to the root logger, and on
    Windows an open file cannot be deleted. Nothing to do with Arelis being wrong;
    it is this script asking a directory to disappear while still holding a file in
    it.
    """
    import logging

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except OSError:
            pass


def _package_contents() -> set[str]:
    """Everything inside the installed package, ignoring bytecode.

    __pycache__ appears as a side effect of importing and says nothing about
    whether Arelis wrote where it should not.
    """
    return {
        item.relative_to(paths.PACKAGE_ROOT).as_posix()
        for item in paths.PACKAGE_ROOT.rglob("*")
        if "__pycache__" not in item.parts and item.suffix != ".pyc"
    }


# --------------------------------------------------------------------- the checks


def check_this_is_really_an_install() -> None:
    """Everything below is meaningless if the repository got imported instead.

    Easy to do by accident: run this from inside the checkout and `import arelis`
    finds the source tree, every assertion passes, and the run proves nothing.
    """
    assert not paths.is_source_checkout(), (
        f"imported a checkout, not an install: {paths.PACKAGE_ROOT}. Run this from "
        "a directory that is not the repository, with the wheel installed."
    )
    parents = {part.lower() for part in paths.PACKAGE_ROOT.parts}
    assert parents & {"site-packages", "dist-packages"}, (
        f"expected the package under site-packages, found {paths.PACKAGE_ROOT}"
    )
    print(f"  installed at {paths.PACKAGE_ROOT}")


def check_every_shipped_asset_arrived() -> None:
    """The package-data contract, end to end rather than by inspecting globs.

    tests/test_packaged_assets.py checks that a non-Python file in the package is
    covered by a glob in pyproject. This checks the thing that actually matters:
    that the file is present in an installed copy. The icon's absence was invisible
    to every test for exactly this reason.
    """
    icon = paths.app_icon_path()
    assert icon.is_file(), f"the window, tray and taskbar icon is missing: {icon}"

    config = paths.PACKAGE_ROOT / "config" / "default.yaml"
    assert config.is_file(), f"the shipped default config is missing: {config}"

    personas = sorted((paths.PACKAGE_ROOT / "persona").glob("*.md"))
    assert personas, "no persona markdown shipped; she would have no character"

    fonts = [p for p in (paths.PACKAGE_ROOT / "ui" / "fonts").glob("*") if p.is_file()]
    assert fonts, "no typefaces shipped; every label falls back to a system font"

    print(
        f"  icon, config, {len(personas)} persona file(s) and {len(fonts)} font(s) present"
    )


def check_nothing_writable_is_inside_the_program() -> None:
    """Read the real resolution rules. Create nothing.

    Deliberately run with ARELIS_DATA_DIR unset, because the override is the easy
    case and the one the unit tests already cover. What has never been exercised is
    what these functions return on a machine where Arelis is genuinely installed.
    """
    previous = os.environ.pop(paths.DATA_DIR_ENV, None)
    try:
        for resolve in MUTABLE:
            resolved = resolve()
            assert resolved.is_absolute(), f"{resolve.__name__}() is not absolute"
            assert not resolved.is_relative_to(paths.PACKAGE_ROOT), (
                f"{resolve.__name__}() resolved inside the program at {resolved}; an "
                "update replaces that directory and a standard user cannot write to it"
            )
        root = paths.user_data_dir()
        if sys.platform == "win32":
            assert "Roaming" not in str(root), (
                f"{root} roams to a domain server at logon; model weights and a "
                "conversation database must not"
            )
        workspace = paths.default_workspace_root()
        assert not workspace.is_relative_to(paths.PACKAGE_ROOT), (
            f"the default workspace is inside the program at {workspace}, which "
            "would make the model's sandbox the application"
        )
        print(f"  data root {root}")
        print(f"  default workspace {workspace}")
    finally:
        if previous is not None:
            os.environ[paths.DATA_DIR_ENV] = previous


def check_startup_writes_nothing_into_the_package() -> None:
    """The check that would have caught both defects found so far.

    Rather than naming the directories Arelis must not create, this does the work a
    launch does and then asks whether the program directory changed. A new module
    reaching for the nearest example fails here without anybody having predicted
    what it would be called.
    """
    before = _package_contents()
    # ignore_cleanup_errors because configure_logging() attaches a rotating file
    # handler to the root logger and Windows will not delete a file that is still
    # open. The handler is closed below; this covers anything else that opened one.
    with tempfile.TemporaryDirectory(
        prefix="arelis-smoke-", ignore_cleanup_errors=True
    ) as tmp:
        os.environ[paths.DATA_DIR_ENV] = tmp

        from arelis.config import load_config
        from arelis.logging_setup import configure_logging

        configure_logging()
        config = load_config()
        assert config, "the shipped config loaded as empty"

        for resolve in MUTABLE:
            paths.ensure(resolve())

        # The two that used to land in the package, exercised on purpose.
        from arelis.browser.launch import browsers_path, pin_browsers_path
        from arelis.ui.theme import qt_font_directory

        font_dir = qt_font_directory()
        assert font_dir.is_dir() and font_dir.is_relative_to(Path(tmp))

        os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
        pin_browsers_path()
        assert browsers_path().is_relative_to(Path(tmp))

        after = _package_contents()
        _release_log_file()

    appeared = sorted(after - before)
    assert not appeared, (
        "starting Arelis created these inside the installed program:\n    "
        + "\n    ".join(appeared)
    )
    print(f"  {len(before)} files in the package before startup, and the same after")


def check_the_scheduler_can_still_name_an_interpreter() -> None:
    """Scheduled jobs are the part of this that fails where nobody is watching.

    runner_command() picks the executable a Task Scheduler action names, and its
    first candidate is a virtualenv that only exists in a checkout. The fallthrough
    is guarded, so an install gets the running interpreter's windowless twin -- but
    that has only ever been asserted against a fake install built in tmp_path.
    """
    from arelis.jobs.schedule import build_task_xml, runner_command
    from arelis.jobs.store import Job

    executable, arguments = runner_command()
    assert Path(executable).exists(), (
        f"Task Scheduler would be given {executable}, which does not exist"
    )
    assert arguments == "-m arelis", (
        f"expected an interpreter to be told what to run, got {arguments!r}"
    )

    with tempfile.TemporaryDirectory(prefix="arelis-smoke-") as tmp:
        os.environ[paths.DATA_DIR_ENV] = tmp
        job = Job(id="__smoke__", name="Smoke", prompt="never runs", times=["07:00"])
        xml = build_task_xml(job)
        assert f"<WorkingDirectory>{tmp}</WorkingDirectory>" in xml, (
            "the task would start in a directory that is not the data root"
        )
        assert str(paths.PACKAGE_ROOT) not in xml, (
            "the task names the install directory, which an update replaces"
        )
    print(f"  scheduler would run: {executable} {arguments} --run-job <id>")


def check_the_two_ways_in_both_work() -> None:
    """`-m arelis` and the console script, in a subprocess rather than by import.

    `-m arelis` is load-bearing beyond the command line: it is what every scheduled
    task runs, and it is why the packaging ships a real interpreter rather than a
    frozen executable. Proving it works in an installed layout is the point.
    """
    module = subprocess.run(
        [sys.executable, "-m", "arelis", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert module.returncode == 0, (
        f"`-m arelis` exited {module.returncode}: "
        f"{(module.stderr or module.stdout).strip()[:400]}"
    )
    assert "arelis" in module.stdout.lower(), f"unexpected --version output: {module.stdout!r}"
    print(f"  -m arelis --version -> {module.stdout.strip()}")

    # sysconfig rather than the directory the interpreter happens to sit in. Those are
    # the same place in a virtualenv, which is why this went unnoticed, and different
    # in the tree the Windows installer ships: CPython's embeddable distribution puts
    # python.exe at the root and console scripts in Scripts\, so deriving one from the
    # other reported a missing entry point for a build that had one.
    scripts = Path(sysconfig.get_path("scripts"))
    suffix = ".exe" if sys.platform == "win32" else ""

    # Any pip launcher that is here must name an interpreter that exists, and this is the
    # check that was missing rather than a precaution. pip writes the absolute path of the
    # installing interpreter into each launcher it generates. In a virtualenv that path is
    # where the virtualenv will stay, so it is correct and these launchers are the ordinary
    # way to start the program. In a tree assembled for an installer it is the build
    # directory, so the shipped launcher pointed at a path that exists on one computer --
    # and on that computer it ran the build tree, so every check passed while testing the
    # wrong copy. Asserting only that the file exists is what let that through.
    for name in (f"arelis{suffix}", f"arelisw{suffix}"):
        launcher = scripts / name
        if not launcher.exists():
            continue
        interpreter = _interpreter_named_inside(launcher)
        assert interpreter is None or interpreter.is_file(), (
            f"{launcher} names {interpreter}, which is not on this machine. pip baked in "
            "the path of whatever interpreter installed the wheel, so this launcher works "
            "only where it was built. Point shortcuts at the interpreter directly, or ship "
            "a .cmd shim that resolves its own location."
        )
        print(f"  {name} names {interpreter or 'no interpreter'}, which is present")

    # One way to start it other than -m, whichever this install has. A virtualenv gets
    # pip's console script; the installer's tree gets a .cmd shim, because a launcher whose
    # interpreter path cannot be made relative is worse than no launcher at all.
    runnable = next(
        (p for p in (scripts / f"arelis{suffix}", scripts / "arelis.cmd") if p.exists()),
        None,
    )
    assert runnable is not None, (
        f"no way to start Arelis from {scripts} other than -m arelis. Shortcuts, the "
        "uninstall hook and scheduled tasks all need something to point at."
    )
    argv = ["cmd", "/c", str(runnable)] if runnable.suffix == ".cmd" else [str(runnable)]
    entry = subprocess.run([*argv, "--version"], capture_output=True, text=True, check=False)
    assert entry.returncode == 0, (
        f"{runnable.name} exited {entry.returncode}: "
        f"{(entry.stderr or entry.stdout).strip()[:400]}"
    )
    assert entry.stdout.strip() == module.stdout.strip(), (
        f"{runnable.name} and -m arelis disagree about the version: "
        f"{entry.stdout.strip()!r} vs {module.stdout.strip()!r}. They are running different "
        "copies of Arelis."
    )
    print(f"  {runnable.name} --version -> {entry.stdout.strip()}")

    # The interpreter a shortcut and every scheduled task actually name. Its whole purpose
    # is having no console, so it is asked to write to a file rather than to a stdout that
    # is not there.
    windowless = Path(sys.executable).with_name(f"pythonw{suffix}")
    if windowless.exists():
        with tempfile.TemporaryDirectory() as box:
            proof = Path(box) / "version.txt"
            subprocess.run(
                [
                    str(windowless),
                    "-c",
                    f"import arelis, pathlib; pathlib.Path(r'{proof}')"
                    ".write_text(arelis.__version__)",
                ],
                check=False,
                timeout=120,
            )
            assert proof.is_file(), (
                f"{windowless} could not import arelis. Every shortcut and every scheduled "
                "task starts this way, and when it fails it fails silently: an icon that "
                "does nothing when double-clicked."
            )
            print(f"  {windowless.name} imports arelis {proof.read_text()}")


def _interpreter_named_inside(launcher: Path) -> Path | None:
    """The interpreter path pip embedded in a generated launcher, if it embedded one.

    These are a small executable stub, a shebang line, then a zip of the script. Read as
    bytes because the file is mostly not text.
    """
    import re

    match = re.search(rb"#!([^\r\n]{1,400}?\.exe)\r?\n", launcher.read_bytes())
    if match is None:
        return None
    return Path(match.group(1).decode("utf-8", "replace").strip('"'))


CHECKS = (
    ("this is an install and not a checkout", check_this_is_really_an_install),
    ("every shipped asset arrived", check_every_shipped_asset_arrived),
    ("nothing writable resolves inside the program", check_nothing_writable_is_inside_the_program),
    ("startup writes nothing into the package", check_startup_writes_nothing_into_the_package),
    ("the scheduler can name an interpreter", check_the_scheduler_can_still_name_an_interpreter),
    ("both ways of starting Arelis work", check_the_two_ways_in_both_work),
)


def main() -> int:
    failures: list[str] = []
    for label, run in CHECKS:
        print(f"{label}:")
        try:
            run()
        except AssertionError as exc:
            print(f"  FAILED: {exc}")
            failures.append(label)
        except Exception as exc:  # An unexpected error is also a failed check.
            print(f"  ERROR: {type(exc).__name__}: {exc}")
            failures.append(label)
        print()

    if failures:
        print(f"FAILED {len(failures)} of {len(CHECKS)}: {', '.join(failures)}")
        return 1
    print(f"PASSED: all {len(CHECKS)} installed-copy checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
