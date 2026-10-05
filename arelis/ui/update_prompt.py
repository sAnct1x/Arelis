"""Offer a newer Arelis at launch, and install it if the user says yes.

The rules this follows are the ones a person asked for: check quietly, at most once a day,
say nothing when there is nothing, and never download without being told to.

Everything that decides anything lives in arelis/update.py, which has no Qt in it and is
tested without a display. This file is the part that cannot be: two threads so the window
does not freeze on a network call, a question, a progress bar, and quitting at the end
because an upgrade cannot replace the interpreter that is running it.

Nothing here is allowed to be the reason Arelis fails to start. The whole entry point is
wrapped, the check happens after the window is already up, and every failure is a log line.
An update mechanism that breaks the program it updates has done more harm than the update
was worth.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication, QProgressBar, QWidget

from arelis import __version__
from arelis.backup import backup_before_upgrade
from arelis.ui.dialog import GlassDialog, confirm, notice
from arelis.update import (
    Release,
    UpdateError,
    automatic_check_enabled,
    check_is_due,
    consider_automatic_update,
    download,
    record_check,
    start_installer,
    updates_supported,
)

log = logging.getLogger(__name__)

# Long enough that the first seconds belong to the window rather than to a socket. Nobody
# is waiting for this, and an update that arrives eight seconds later arrives just as well.
_DELAY_MS = 8000

# Hung disk must not leave the upgrade waiting forever. The backup runs on a
# QThread; this timer fires on the GUI thread and stops the update if the copy
# has not finished.
_BACKUP_TIMEOUT_MS = 60_000

BACKUP_FAILED_NOTICE = (
    "Arelis couldn't save a safety copy of your memory and settings, so she "
    "didn't update. Nothing has changed. She'll offer the update again tomorrow."
)
BACKUP_FAILED_DETAIL = (
    "If this keeps happening, check that your disk has free space, or download "
    "the new version from the Arelis releases page."
)


class _CheckThread(QThread):
    """Ask GitHub, off the UI thread. Emits the release, or None for every other outcome."""

    answered = Signal(object)

    def __init__(self, parent: QObject | None = None, config: dict | None = None) -> None:
        super().__init__(parent)
        self._config = config

    def run(self) -> None:  # pragma: no cover - exercised by hand, not in CI
        self.answered.emit(consider_automatic_update(self._config))


class _BackupThread(QThread):
    """Copy allowlisted records off the GUI thread. Emits the folder, or None."""

    finished_with = Signal(object)

    def run(self) -> None:
        dest: Path | None
        try:
            dest = backup_before_upgrade(__version__)
        except Exception:
            log.warning("pre-upgrade backup failed; the update will not continue")
            dest = None
        self.finished_with.emit(dest)


class _DownloadThread(QThread):
    """Fetch and verify the installer, reporting bytes as they land."""

    progressed = Signal(int, int)
    finished_with = Signal(object)

    def __init__(self, release: Release, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._release = release

    def run(self) -> None:  # pragma: no cover - exercised by hand, not in CI
        try:
            self.finished_with.emit(download(self._release, progress=self.progressed.emit))
        except Exception as exc:
            # Emitted rather than raised. An exception escaping QThread.run crosses no
            # thread boundary and reaches no handler; it prints to stderr, which a
            # windowless launcher does not have, and the progress dialog spins forever.
            self.finished_with.emit(exc)


class _DownloadDialog(GlassDialog):
    """Progress plate for the installer download.

    Not closable by its own chrome: Cancel is the only way out, so the download
    cannot be orphaned behind a dismissed window with nothing left to report to.
    """

    cancelled = Signal()

    def __init__(self, version: str, parent: QWidget | None = None) -> None:
        super().__init__("Update Arelis", parent=parent, width=400, closable=False)
        self.label = self.add_text(f"Downloading Arelis {version}…")
        self.bar = QProgressBar()
        self.bar.setObjectName("DialogProgress")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.body.addWidget(self.bar)
        cancel = self.add_button("Cancel")
        cancel.clicked.connect(self.cancelled.emit)
        cancel.setFocus()

    def reject(self) -> None:  # type: ignore[override]
        self.cancelled.emit()


class UpdatePrompt(QObject):
    """Owns the worker threads and the dialogs, and keeps itself alive until it is done.

    A QObject with the window as its parent rather than a set of local variables, because a
    QThread that goes out of scope while running takes the process with it. Parented, so
    closing the window during a download disposes of this too.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._window = parent
        self._check: _CheckThread | None = None
        self._download: _DownloadThread | None = None
        self._progress: _DownloadDialog | None = None
        self._backup: _BackupThread | None = None
        self._backup_timer: QTimer | None = None
        self._installer: Path | None = None
        self._install_started = False

    def start(self) -> None:
        config = getattr(self._window, "config", None)
        if not automatic_check_enabled(config if isinstance(config, dict) else None):
            log.debug("not checking for updates: updates.check is false")
            return
        supported, why = updates_supported()
        if not supported:
            log.debug("not checking for updates: %s", why)
            return
        if not check_is_due():
            return
        # Written down before the answer arrives, on purpose. A check that fails must not
        # retry on every launch: offline at 9am is offline at 9:05, and the failure is
        # cheap only the first time.
        record_check()
        self._check = _CheckThread(self, config if isinstance(config, dict) else None)
        self._check.answered.connect(self._offer)
        self._check.start()

    def _offer(self, release: object) -> None:
        if not isinstance(release, Release):
            return
        log.info("update available: %s", release.tag)
        accepted = confirm(
            self._window,
            "Update Arelis",
            f"Arelis {release.version} is available. You have {__version__}.\n\n"
            f"Download {release.size_text} and install it now?",
            detail=(
                "Arelis will close, update, and reopen. Your conversations, memory, "
                "settings and scheduled jobs are not touched."
            ),
            confirm_text="Download and install",
            cancel_text="Not now",
        )
        if not accepted:
            log.info("update declined by the user")
            return
        self._begin_download(release)

    def _begin_download(self, release: Release) -> None:
        self._progress = _DownloadDialog(release.version, self._window)
        self._progress.cancelled.connect(self._cancel)
        self._progress.show()

        self._download = _DownloadThread(release, self)
        self._download.progressed.connect(self._on_progress)
        self._download.finished_with.connect(self._on_downloaded)
        self._download.start()

    def _on_progress(self, received: int, total: int) -> None:
        if self._progress is None:
            return
        if total <= 0:
            self._progress.bar.setRange(0, 0)
            return
        self._progress.bar.setValue(int(received * 100 / total))
        self._progress.label.setText(
            f"Downloading Arelis… {received / (1024 * 1024):.0f} of {total / (1024 * 1024):.0f}MB"
        )

    def _cancel(self) -> None:
        """Stop reporting and let the thread finish into nothing.

        A QThread cannot be safely killed mid-write, so cancelling detaches the UI rather
        than the download. The file is verified before it is renamed and cleaned up on the
        next successful download, so the worst case is a temporary .part nobody uses.
        """
        log.info("update download cancelled")
        if self._download is not None:
            self._download.finished_with.disconnect()
            self._download.progressed.disconnect()
        self._close_progress()

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None

    def _on_downloaded(self, result: object) -> None:
        self._close_progress()
        if isinstance(result, Exception):
            log.warning("update download failed: %s", result)
            notice(
                self._window,
                "Update Arelis",
                f"The update could not be installed.\n\n{result}",
                detail="Nothing has changed. Arelis will try again tomorrow.",
                warning=True,
            )
            return

        self._installer = result if isinstance(result, Path) else Path(result)  # type: ignore[arg-type]
        self._install_started = False
        self._backup = _BackupThread(self)
        self._backup.finished_with.connect(self._on_backup_finished)
        self._backup_timer = QTimer(self)
        self._backup_timer.setSingleShot(True)
        self._backup_timer.timeout.connect(self._on_backup_timeout)
        self._backup_timer.start(_BACKUP_TIMEOUT_MS)
        self._backup.start()

    def _on_backup_finished(self, dest: object) -> None:
        self._finish_backup_and_install(failed=dest is None)

    def _on_backup_timeout(self) -> None:
        if self._backup is not None:
            try:
                self._backup.finished_with.disconnect(self._on_backup_finished)
            except (RuntimeError, TypeError):
                pass
        log.warning("pre-upgrade backup is slow; stopping the update")
        self._finish_backup_and_install(failed=True)

    def _finish_backup_and_install(self, *, failed: bool) -> None:
        if self._install_started:
            return
        self._install_started = True
        if self._backup_timer is not None:
            self._backup_timer.stop()
            self._backup_timer = None
        if failed:
            notice(
                self._window,
                "Update Arelis",
                BACKUP_FAILED_NOTICE,
                detail=BACKUP_FAILED_DETAIL,
                warning=True,
            )
            log.warning("pre-upgrade backup failed; not starting the installer")
            return
        installer = self._installer
        if installer is None:
            return
        try:
            start_installer(installer)
        except (UpdateError, OSError) as exc:
            log.warning("could not start the installer: %s", exc)
            notice(
                self._window,
                "Update Arelis",
                f"The installer would not start.\n\n{exc}",
                warning=True,
            )
            return

        # The installer is running and is waiting for these files to be released. Quitting
        # is the last step of the update, not the end of the session: arelis.iss was given
        # /relaunch=yes and starts the new version once the files are in place.
        log.info("quitting so the installer can replace this copy")
        QApplication.quit()


def schedule_update_check(window: QWidget, delay_ms: int = _DELAY_MS) -> None:
    """Arrange the once-a-day check, some seconds after the window is up.

    Swallows everything. This is a convenience the user did not ask for at this instant,
    and there is no version of "the update check raised" that should keep Arelis closed.
    """
    try:
        config = getattr(window, "config", None)
        if not automatic_check_enabled(config if isinstance(config, dict) else None):
            return
        prompt = UpdatePrompt(window)
        QTimer.singleShot(delay_ms, prompt.start)
    except Exception as exc:
        log.debug("could not schedule the update check: %s", exc)
