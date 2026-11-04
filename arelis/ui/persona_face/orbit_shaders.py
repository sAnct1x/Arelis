"""The orbit's ShaderEffect shaders with D3D11 bytecode, built once and off the GUI thread.

tools/build_orbit_shaders.py bakes HLSL source into the .qsb files, not DXBC (qsb needs
fxc.exe for that, and the build runs anywhere). With no DXBC in a .qsb, Qt's D3D11 backend
runs D3DCompile on the HLSL when it first builds the pipeline. The Quick surface is a
QQuickWidget, which renders on the GUI thread with the window's QRhi (no pipeline cache),
so on Windows the orbit's first full-size frames compiled 15 shaders there: the GUI thread
stalled 0.3 to 0.8 s and then 1.1 to 1.2 s two to three seconds into her load (Atria,
534pr2), and a right-click got no menu.

Here a worker thread compiles the same HLSL with the same D3DCompile call Qt makes (flags
0, vs_5_0 or ps_5_0, entry point from the .qsb), adds it to each .qsb as DXBC 50, and
writes the copies to a cache folder keyed by the files' contents. Qt then loads that
bytecode and never compiles on the GUI thread. The orbit is not drawn until the folder is
ready (QuickOrbit.shaders is ""); the next start finds it on disk and draws at once.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QUrl

from arelis.paths import user_data_dir

ORBIT_DIR = Path(__file__).resolve().parent / "qq3d" / "orbit"
PACKAGE = "orbit/"  # QuickOrbit.qml's default: the .qsb files next to it

_log = logging.getLogger("arelis.avatar")

Compiler = Callable[[bytes, bytes, str], bytes]  # (hlsl, entry point, target) -> DXBC


def wants_bytecode() -> bool:
    """True where the surface renders with D3D11: Windows unless QSG_RHI_BACKEND says other."""
    if sys.platform != "win32":
        return False
    return os.environ.get("QSG_RHI_BACKEND", "").strip().lower() in ("", "d3d11")


def _sources() -> list[Path]:
    return sorted(ORBIT_DIR.glob("*.qsb"))


def cache_dir() -> Path:
    """The bytecode copies, keyed by every .qsb's bytes and the Qt version that reads them."""
    from PySide6.QtCore import qVersion

    h = hashlib.sha1(qVersion().encode())
    for path in _sources():
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return user_data_dir() / "avatar" / "orbit-dxbc" / h.hexdigest()[:16]


def _url(folder: Path) -> str:
    return QUrl.fromLocalFile(str(folder) + "/").toString()


def _complete(folder: Path) -> bool:
    return all((folder / p.name).is_file() for p in _sources())


def d3d_compile(hlsl: bytes, entry: bytes, target: str) -> bytes:  # pragma: no cover - Windows
    """D3DCompile from d3dcompiler_47.dll, called as Qt's D3D11 backend calls it."""
    import ctypes

    lib = ctypes.WinDLL("d3dcompiler_47.dll")
    fn = lib.D3DCompile
    fn.restype = ctypes.c_long
    vp = ctypes.c_void_p
    fn.argtypes = [
        ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, vp, vp, ctypes.c_char_p,
        ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(vp), ctypes.POINTER(vp),
    ]
    code, errors = vp(), vp()
    hr = fn(hlsl, len(hlsl), None, None, None, entry, target.encode(), 0, 0,
            ctypes.byref(code), ctypes.byref(errors))

    def blob(ptr: vp) -> bytes:  # ID3DBlob: GetBufferPointer 3, GetBufferSize 4, Release 2
        vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(vp)))[0]
        data = ctypes.WINFUNCTYPE(vp, vp)(vtbl[3])(ptr)
        size = ctypes.WINFUNCTYPE(ctypes.c_size_t, vp)(vtbl[4])(ptr)
        out = ctypes.string_at(data, size)
        ctypes.WINFUNCTYPE(ctypes.c_ulong, vp)(vtbl[2])(ptr)
        return out

    msg = blob(errors).decode(errors="replace") if errors.value else ""
    if hr < 0 or not code.value:
        raise RuntimeError(f"D3DCompile {target} failed ({hr & 0xFFFFFFFF:#x}): {msg}")
    return blob(code)


def build(folder: Path, compile_fn: Compiler) -> None:
    """Write every orbit .qsb with DXBC 50 added to ``folder`` (atomically, as a whole)."""
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QShader, QShaderCode, QShaderKey, QShaderVersion

    tmp = folder.with_name(f"{folder.name}.tmp{os.getpid()}.{threading.get_ident()}")
    tmp.mkdir(parents=True, exist_ok=True)
    failed = []
    for path in _sources():
        shader = QShader.fromSerialized(QByteArray(path.read_bytes()))
        code = shader.shader(QShaderKey(QShader.Source.HlslShader, QShaderVersion(50)))
        vertex = shader.stage() == QShader.Stage.VertexStage
        target = "vs_5_0" if vertex else "ps_5_0"
        entry = bytes(code.entryPoint()) or b"main"
        try:
            if not shader.isValid() or not bytes(code.shader()):
                raise ValueError("no HLSL 50 source in the .qsb")
            dxbc = compile_fn(bytes(code.shader()), entry, target)
        except Exception as exc:  # one bad shader: say which, then fail the folder
            _log.warning(
                "[avatar] orbit shader %s (%s, entry %s) got no bytecode: %s",
                path.name, target, entry.decode(errors="replace"), exc,
            )
            failed.append(path.name)
            continue
        shader.setShader(
            QShaderKey(QShader.Source.DxbcShader, QShaderVersion(50)),
            QShaderCode(QByteArray(dxbc), QByteArray(entry)),
        )
        (tmp / path.name).write_bytes(bytes(shader.serialized()))
    if failed:
        raise RuntimeError(f"{len(failed)} of {len(_sources())} failed: {', '.join(failed)}")
    try:
        os.replace(tmp, folder)
    except OSError:  # another start built it first
        if not _complete(folder):
            raise


def shader_root(on_ready: Callable[[str], None], compile_fn: Compiler | None = None) -> str:
    """The folder QuickOrbit.shaders should use now ("" while bytecode is being built).

    Without D3D11 this is the package folder. With it, the cached bytecode copies if they
    are on disk; otherwise a worker thread builds them and ``on_ready`` gets the folder (or
    the package one, if the build failed) from that thread: queue it to the GUI thread.
    """
    if not wants_bytecode() and compile_fn is None:
        return PACKAGE
    folder = cache_dir()
    if _complete(folder):
        return _url(folder)
    compile_fn = compile_fn or d3d_compile

    def work() -> None:
        t0 = time.perf_counter()
        try:
            build(folder, compile_fn)
        except Exception as exc:  # no d3dcompiler, a driver fault: Qt compiles, as before
            _log.warning("[avatar] orbit shaders: no bytecode (%s); compiled on first draw", exc)
            on_ready(PACKAGE)
            return
        _log.info(
            "[avatar] orbit shaders: %d built off the GUI thread in %.0f ms",
            len(_sources()), (time.perf_counter() - t0) * 1e3,
        )
        on_ready(_url(folder))

    threading.Thread(target=work, name="orbit-dxbc", daemon=True).start()
    return ""
