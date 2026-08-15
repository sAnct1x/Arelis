"""What Task Scheduler is actually told to run, which nothing checked.

``runner_command()`` decides the executable for every scheduled job, and
``working_directory()`` decides where it starts. Neither had a test. The two
existing scheduling tests pass ``command=`` explicitly, so the code that picks an
interpreter on a stranger's machine had never once been exercised — and it is
only ever exercised on machines the author does not have.

The function reads alarmingly at a glance: its first candidate is
``.venv/Scripts/pythonw.exe`` beneath the install directory, which does not exist
in an installed copy. I read exactly that far and reported that scheduled jobs
would silently never run once installed, which was wrong — the lookup is guarded
by ``exists()`` and falls through to the running interpreter's own windowless
twin. These tests pin the fallback chain so the next reader gets the answer from
the suite instead of from a guess.

What was genuinely wrong was quieter. The task's working directory was the
install directory, and Task Scheduler refuses to start an action whose working
directory is missing, reporting 0x8007010B without naming the path. A job that
worked for months and stopped after an update, with an error code that explains
nothing, is a worse outcome than one that never worked at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from arelis import paths
from arelis.jobs import schedule as win
from arelis.jobs.store import Job


def _job() -> Job:
    return Job(id="news", name="Morning news", prompt="brief me", times=["07:00"])


# ------------------------------------------------------- choosing an interpreter


def test_a_checkout_prefers_its_own_virtualenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A developer's dependencies are in the venv, not in the ambient Python.

    Running a job with an interpreter that cannot import PySide6 fails at 7am in
    a log nobody is watching, so when a venv is present it wins.
    """
    fake_root = tmp_path / "checkout"
    scripts = fake_root / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    venv_pythonw = scripts / "pythonw.exe"
    venv_pythonw.write_bytes(b"")
    monkeypatch.setattr(win, "INSTALL_PARENT", fake_root)

    executable, args = win.runner_command()
    assert Path(executable) == venv_pythonw
    # An interpreter needs telling what to run; the executable alone is not enough.
    assert args == "-m arelis"


def test_an_install_falls_through_to_the_running_interpreter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The case I got wrong, pinned so nobody has to re-derive it.

    There is no .venv in an installed copy. The guard means that is not fatal:
    the choice falls to the windowless twin of whatever interpreter is running,
    and scheduled jobs continue to work.
    """
    empty_install = tmp_path / "site-packages"
    empty_install.mkdir()
    monkeypatch.setattr(win, "INSTALL_PARENT", empty_install)

    interpreter = Path(sys.executable)
    windowless = interpreter.with_name("pythonw.exe")
    executable, _ = win.runner_command()

    assert not Path(executable).is_relative_to(empty_install)
    expected = windowless if windowless.exists() else interpreter
    assert Path(executable) == expected


def test_the_chosen_executable_always_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Every branch is guarded, so the result is never a path that is not there.

    This is the property that makes the alarming-looking first candidate safe,
    and the one worth asserting directly rather than inferring from the code.
    """
    empty_install = tmp_path / "site-packages"
    empty_install.mkdir()
    monkeypatch.setattr(win, "INSTALL_PARENT", empty_install)

    executable, _ = win.runner_command()
    assert Path(executable).exists(), executable


def test_a_windowless_interpreter_is_preferred_when_one_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A console window flashing on screen every morning gets a feature disabled.

    Cosmetic in the sense that the job still runs, and not cosmetic at all in the
    sense that determines whether a user leaves scheduling switched on.
    """
    empty_install = tmp_path / "site-packages"
    empty_install.mkdir()
    monkeypatch.setattr(win, "INSTALL_PARENT", empty_install)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    console = fake_bin / "python.exe"
    console.write_bytes(b"")
    (fake_bin / "pythonw.exe").write_bytes(b"")
    monkeypatch.setattr(win.sys, "executable", str(console))

    executable, _ = win.runner_command()
    assert Path(executable).name == "pythonw.exe"


def test_a_missing_windowless_twin_is_not_fatal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Some Python builds ship no pythonw at all, and a job still has to run.

    Trading a visible console window for a job that fires is the right way round.
    """
    empty_install = tmp_path / "site-packages"
    empty_install.mkdir()
    monkeypatch.setattr(win, "INSTALL_PARENT", empty_install)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    console = fake_bin / "python.exe"
    console.write_bytes(b"")
    monkeypatch.setattr(win.sys, "executable", str(console))

    executable, _ = win.runner_command()
    assert Path(executable) == console


# ------------------------------------------------------- where the job starts


def test_the_working_directory_is_not_the_install_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The actual defect here.

    An update replaces the install directory, and Task Scheduler refuses to start
    an action whose working directory has gone, reporting 0x8007010B without
    saying which path it meant.
    """
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "state"))
    resolved = win.working_directory()
    assert resolved != paths.PACKAGE_ROOT
    assert not resolved.is_relative_to(paths.PACKAGE_ROOT)


def test_the_working_directory_exists_after_being_asked_for(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Task Scheduler will not start an action into a directory that is missing.

    The first scheduled run can easily precede anything else that would have
    created it, so asking is what creates it.
    """
    root = tmp_path / "not-yet"
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(root))
    assert not root.exists()
    assert win.working_directory().is_dir()


def test_the_task_xml_names_that_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The XML is the only artefact Task Scheduler ever sees."""
    root = tmp_path / "state"
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(root))
    xml = win.build_task_xml(_job(), command=r"C:\py\pythonw.exe")
    assert f"<WorkingDirectory>{root}</WorkingDirectory>" in xml
    assert str(paths.PACKAGE_ROOT) not in xml


# ------------------------------------------------ what the arguments are made of


def test_an_interpreter_is_told_which_module_to_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`-m arelis` is not decoration: without it pythonw.exe starts a REPL."""
    monkeypatch.setattr(win, "INSTALL_PARENT", tmp_path / "site-packages")
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "state"))
    xml = win.build_task_xml(_job(), command=r"C:\py\pythonw.exe")
    assert "<Arguments>-m arelis --run-job news</Arguments>" in xml


def test_a_frozen_build_is_not_asked_to_run_a_module(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The breakage that made this seam worth building, pinned before it can bite.

    Under PyInstaller or Nuitka, sys.executable is Arelis itself and `-m arelis`
    means nothing to it, so every scheduled job would fail — at 7am, with nobody
    watching. The arguments used to be a hardcoded string in the XML template,
    which made this impossible to express as anything but a comment.

    The chosen packaging ships a real interpreter and never takes this branch. The
    test exists so that changing that decision is a decision rather than a
    discovery.
    """
    monkeypatch.setattr(win, "INSTALL_PARENT", tmp_path / "site-packages")
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "state"))
    frozen_exe = tmp_path / "Arelis.exe"
    frozen_exe.write_bytes(b"")
    monkeypatch.setattr(win.sys, "frozen", True, raising=False)
    monkeypatch.setattr(win.sys, "executable", str(frozen_exe))

    executable, args = win.runner_command()
    assert Path(executable) == frozen_exe
    assert args == ""

    xml = win.build_task_xml(_job())
    assert "<Arguments>--run-job news</Arguments>" in xml
    assert "-m arelis" not in xml


def test_a_frozen_build_does_not_go_looking_for_a_virtualenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A checkout venv beside a frozen build would be the wrong interpreter.

    The frozen check comes first for this reason: a developer who freezes inside
    their own checkout has a .venv sitting right there, and preferring it would
    hand the task an interpreter with no relationship to the build under test.
    """
    fake_root = tmp_path / "checkout"
    scripts = fake_root / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "pythonw.exe").write_bytes(b"")
    monkeypatch.setattr(win, "INSTALL_PARENT", fake_root)

    frozen_exe = tmp_path / "Arelis.exe"
    frozen_exe.write_bytes(b"")
    monkeypatch.setattr(win.sys, "frozen", True, raising=False)
    monkeypatch.setattr(win.sys, "executable", str(frozen_exe))

    executable, _ = win.runner_command()
    assert Path(executable) == frozen_exe


# --------------------------------------------- when the interpreter has moved


def test_a_task_registered_against_another_install_is_repointed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The migration this exists for: checkout today, installed build tomorrow.

    A scheduled task stores the absolute path it was created with. Installing a
    packaged build leaves every existing task naming the checkout's virtualenv,
    which may be gone, or may still be there and quietly run a copy of Arelis the
    user has stopped using. Nobody is watching at 7am either way.
    """
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "state"))
    monkeypatch.setattr(win, "supported", lambda: True)
    win.runner_record_path().parent.mkdir(parents=True, exist_ok=True)
    win.runner_record_path().write_text(
        '{"command": "C:\\\\old-checkout\\\\.venv\\\\Scripts\\\\pythonw.exe", '
        '"arguments": "-m arelis"}',
        encoding="utf-8",
    )
    registered: list[str] = []
    monkeypatch.setattr(win, "register", lambda job: registered.append(job.id))

    assert win.repoint_tasks_if_runner_moved([_job()]) == ["news"]
    assert registered == ["news"]


def test_nothing_is_touched_when_the_command_has_not_changed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """This runs at every launch, so the common case must cost nothing.

    A repair that re-registers every task on every start would write to Task
    Scheduler thousands of times for no reason, and each write is a subprocess.
    """
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "state"))
    monkeypatch.setattr(win, "supported", lambda: True)
    registered: list[str] = []
    monkeypatch.setattr(win, "register", lambda job: registered.append(job.id))

    first = win.repoint_tasks_if_runner_moved([_job()])
    assert first == ["news"], "no record yet means the tasks are of unknown origin"
    second = win.repoint_tasks_if_runner_moved([_job()])
    assert second == [], "the second launch has a record and must do nothing"
    assert registered == ["news"]


def test_a_failed_repoint_is_retried_on_the_next_launch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Recording success we did not have would strand the job permanently."""
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "state"))
    monkeypatch.setattr(win, "supported", lambda: True)

    def refuse(job: object) -> None:
        raise win.ScheduleError("schtasks said no")

    monkeypatch.setattr(win, "register", refuse)
    assert win.repoint_tasks_if_runner_moved([_job()]) == []
    assert not win.runner_record_path().exists()


def test_a_disabled_job_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A job the user switched off must not be quietly reinstated."""
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "state"))
    monkeypatch.setattr(win, "supported", lambda: True)
    registered: list[str] = []
    monkeypatch.setattr(win, "register", lambda job: registered.append(job.id))

    off = Job(id="news", name="Morning news", prompt="brief me", times=["07:00"], enabled=False)
    assert win.repoint_tasks_if_runner_moved([off]) == []
    assert registered == []


def test_the_record_lives_with_the_user_data_and_not_the_program(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """And so a move to a different data root reads as no record, which is right.

    That is the migration case exactly: the checkout kept its record in the
    repository, the installed build looks in %LOCALAPPDATA% and finds nothing, and
    finding nothing is what triggers the repair.
    """
    root = tmp_path / "state"
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(root))
    record = win.runner_record_path()
    assert record.is_relative_to(root)
    assert not record.is_relative_to(paths.PACKAGE_ROOT)


def test_repointing_is_a_no_op_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """There is no Task Scheduler to disagree with, so there is nothing to repair."""
    monkeypatch.setattr(win, "supported", lambda: False)
    assert win.repoint_tasks_if_runner_moved([_job()]) == []
