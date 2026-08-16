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

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QWidget

from arelis import __version__
from arelis.update import (
    Release,
    UpdateError,
    available_update,
    check_is_due,
    download,
    record_check,
    start_installer,
    updates_supported,
)

log = logging.getLogger(__name__)

# Long enough that the first seconds belong to the window rather than to a socket. Nobody
# is waiting for this, and an update that arrives eight seconds later arrives just as well.
_DELAY_MS = 8000


class _CheckThread(QThread):
    """Ask GitHub, off the UI thread. Emits the release, or None for every other outcome."""

    answered = Signal(object)

    def run(self) -> None:  # pragma: no cover - exercised by hand, not in CI
        self.answered.emit(available_update())


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


class UpdatePrompt(QObject):
    """Owns the two threads and the dialogs, and keeps itself alive until it is done.

    A QObject with the window as its parent rather than a set of local variables, because a
    QThread that goes out of scope while running takes the process with it. Parented, so
    closing the window during a download disposes of this too.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._window = parent
        self._check: _CheckThread | None = None
        self._download: _DownloadThread | None = None
        self._progress: QProgressDialog | None = None

    def start(self) -> None:
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
        self._check = _CheckThread(self)
        self._check.answered.connect(self._offer)
        self._check.start()

    def _offer(self, release: object) -> None:
        if not isinstance(release, Release):
            return
        log.info("update available: %s", release.tag)
        answer = QMessageBox.question(
            self._window,
            "Update Arelis",
            f"Arelis {release.version} is available. You have {__version__}.\n\n"
            f"Download {release.size_text} and install it now?\n\n"
            "Arelis will close, update, and reopen. Your conversations, memory, "
            "settings and scheduled jobs are not touched.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            log.info("update declined by the user")
            return
        self._begin_download(release)

    def _begin_download(self, release: Release) -> None:
        self._progress = QProgressDialog(
            f"Downloading Arelis {release.version}...", "Cancel", 0, 100, self._window
        )
        self._progress.setWindowTitle("Update Arelis")
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        # Otherwise Qt shows it only after four seconds, which for a 150MB download looks
        # like the button did nothing.
        self._progress.setMinimumDuration(0)
        self._progress.canceled.connect(self._cancel)
        self._progress.show()

        self._download = _DownloadThread(release, self)
        self._download.progressed.connect(self._on_progress)
        self._download.finished_with.connect(self._on_downloaded)
        self._download.start()

    def _on_progress(self, received: int, total: int) -> None:
        if self._progress is None:
            return
        if total <= 0:
            self._progress.setRange(0, 0)
            return
        self._progress.setValue(int(received * 100 / total))
        self._progress.setLabelText(
            f"Downloading Arelis... {received / (1024 * 1024):.0f} of "
            f"{total / (1024 * 1024):.0f}MB"
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
            QMessageBox.warning(
                self._window,
                "Update Arelis",
                f"The update could not be installed.\n\n{result}\n\n"
                "Nothing has changed. Arelis will try again tomorrow.",
            )
            return

        try:
            start_installer(result)  # type: ignore[arg-type]
        except (UpdateError, OSError) as exc:
            log.warning("could not start the installer: %s", exc)
            QMessageBox.warning(
                self._window, "Update Arelis", f"The installer would not start.\n\n{exc}"
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
        prompt = UpdatePrompt(window)
        QTimer.singleShot(delay_ms, prompt.start)
    except Exception as exc:
        log.debug("could not schedule the update check: %s", exc)
