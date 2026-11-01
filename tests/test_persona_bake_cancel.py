"""Quit during the face bake must stop it, or the exit drain gives up (#393)."""

from __future__ import annotations

import threading


def test_cancel_during_face_phase_stops_the_bake(monkeypatch) -> None:
    from arelis.ui.persona_face import plate

    cancel = threading.Event()
    calls: list[int] = []
    real = plate._feature_patch

    def patch_then_quit(*args, **kwargs):
        calls.append(1)
        cancel.set()
        return real(*args, **kwargs)

    monkeypatch.setattr(plate, "_feature_patch", patch_then_quit)
    published: list[int] = []

    result = plate.bake_layers(120, cancel=cancel, publish=lambda _l, p: published.append(p))

    assert calls == [1]
    assert result == {}
    assert published == []
