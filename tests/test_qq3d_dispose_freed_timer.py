"""Quit on Atria (534pr2, Q10) raised "QTimer already deleted" from her render thread's
dispose: Qt had freed her incubation controller's timer first. Dispose skips a freed one."""

from __future__ import annotations

import pytest
from PySide6.QtTest import QTest


# Serial: a native crash here took down an xdist worker (macOS gw0); the serial step
# keeps it from killing unrelated tests and gives its render thread an uncontended CPU.
@pytest.mark.serial
def test_dispose_after_qt_freed_the_incubation_timer(qt_app) -> None:
    import shiboken6
    from PySide6.QtWidgets import QWidget

    from arelis.ui.persona_face import qq3d_avatar

    if qq3d_avatar.unavailable_reason():
        pytest.skip(qq3d_avatar.unavailable_reason())
    host = QWidget()
    av = qq3d_avatar.QQ3DAvatar(host)
    render = av._render
    if render.incubator is None:
        pytest.skip("her scene did not start here")
    shiboken6.delete(render.incubator.timer)
    render.cancel()
    for _ in range(100):
        if not render.isRunning():
            break
        QTest.qWait(20)
    render.dispose()  # raised RuntimeError before
    assert render not in qq3d_avatar._LIVE
    host.deleteLater()
