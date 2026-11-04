"""ARELIS_SURFACE=quick on D3D11: the orbit's shaders reach the surface with DXBC in them,
compiled on a worker thread. The .qsb files carry only HLSL, so Qt compiled all 15 with
D3DCompile on the GUI thread on the surface's first full-size frames (the QQuickWidget
renders there): Atria's GUI thread stalled 1.1 to 1.2 s two to three seconds into her load."""

from __future__ import annotations

import threading

from PySide6.QtCore import QByteArray, QUrl
from PySide6.QtTest import QTest


def test_the_surface_gets_orbit_bytecode_built_off_the_gui_thread(
    qt_app, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("ARELIS_SURFACE", "quick")
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    from PySide6.QtGui import QShader, QShaderKey, QShaderVersion
    from PySide6.QtWidgets import QWidget

    from arelis.ui.persona_face import orbit_shaders, quick_surface

    threads = []

    def fake_compile(hlsl: bytes, entry: bytes, target: str) -> bytes:
        threads.append(threading.get_ident())
        return b"DXBC" + target.encode() + hlsl[:16]

    monkeypatch.setattr(orbit_shaders, "wants_bytecode", lambda: True)
    monkeypatch.setattr(orbit_shaders, "d3d_compile", fake_compile)
    surface = quick_surface.surface_for(QWidget())
    root = surface.rootObject()
    assert root.property("orbitShaders") == ""  # nothing drawn while the worker compiles
    # Bounded by when the worker is done, not by a guess at its speed: 2 s ran out on the
    # Windows runner with 12 of 15 built, and the test read the unfinished count.
    for _ in range(1500):
        if root.property("orbitShaders"):
            break
        QTest.qWait(20)
    assert root.property("orbitShaders") not in ("", orbit_shaders.PACKAGE), "no bytecode folder"
    folder = QUrl(root.property("orbitShaders")).toLocalFile()
    names = sorted(p.name for p in orbit_shaders._sources())
    assert len(threads) == len(names) == 15
    assert threading.main_thread().ident not in threads
    dxbc = QShaderKey(QShader.Source.DxbcShader, QShaderVersion(50))
    for name in names:
        with open(f"{folder}/{name}", "rb") as f:
            shader = QShader.fromSerialized(QByteArray(f.read()))
        assert bytes(shader.shader(dxbc).shader()).startswith(b"DXBC"), name
    # The next start finds the cache: served at once, nothing compiled.
    assert orbit_shaders.shader_root(lambda _f: None) == root.property("orbitShaders")
    assert len(threads) == 15
    import shiboken6

    shiboken6.delete(surface)


def test_the_bytecode_shaders_bind_their_resources_as_the_hlsl_they_came_from(tmp_path) -> None:
    """Qt's D3D11 backend binds by the loaded variant's map: an empty one samples nothing."""
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QShader, QShaderKey, QShaderVersion

    from arelis.ui.persona_face import orbit_shaders

    folder = tmp_path / "dxbc"
    orbit_shaders.build(folder, lambda hlsl, entry, target: b"DXBC")
    source = QShaderKey(QShader.Source.HlslShader, QShaderVersion(50))
    dxbc = QShaderKey(QShader.Source.DxbcShader, QShaderVersion(50))
    wrong = {}
    for path in orbit_shaders._sources():
        built = QShader.fromSerialized(QByteArray((folder / path.name).read_bytes()))
        if built.nativeResourceBindingMap(dxbc) != built.nativeResourceBindingMap(source):
            wrong[path.name] = built.nativeResourceBindingMap(dxbc)
    assert not wrong


def test_copies_an_older_build_wrote_are_not_served_again(monkeypatch) -> None:
    """The fixed copies live in a new folder: the black ones on disk are left behind."""
    from arelis.ui.persona_face import orbit_shaders

    before = orbit_shaders.cache_dir()
    monkeypatch.setattr(orbit_shaders, "BUILD_FORMAT", b"1")
    assert orbit_shaders.cache_dir() != before
