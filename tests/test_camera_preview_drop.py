import threading
import types

from arelis.ui.panels import camera as cam


def test_busy_preview_worker_frees_no_frame_on_gui_thread(monkeypatch):
    freed: list[int] = []

    class Held:
        def __init__(self, src) -> None:
            pass

        def __del__(self) -> None:
            freed.append(threading.get_ident())

    class Src:
        def isValid(self) -> bool:
            return True

    monkeypatch.setattr(cam, "QVideoFrame", Held)
    worker = cam.PreviewConvertWorker()
    panel = types.SimpleNamespace(
        _want_pose=False, _preview=worker, _ensure_preview_worker=lambda: None
    )
    for _ in range(5):
        cam.CameraPanel._on_video_frame(panel, Src())
    assert freed == []
    assert worker.pending
