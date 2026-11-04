"""Her frames handed to the Quick surface as GPU textures, with no CPU readback.

Her scene renders on its own thread with its own QRhi (qq3d_avatar._RenderThread); the
surface is a QQuickWidget on the window's QRhi. Reading each frame back to a QImage and
uploading it again made her render thread wait for the GPU every frame and the surface
upload ~6 MB per frame: on Atria her thread ran at 13 to 14 fps and the surface took 34 to
37 ms a frame against 18 on base. Here her thread draws into a small ring of textures the
surface's QRhi can open directly:

* D3D11: textures created with D3D11_RESOURCE_MISC_SHARED on her device, opened on the
  surface's device with OpenSharedResource. An event query, polled without blocking,
  tells her thread when the GPU has finished a frame, and only then is it handed over.
* OpenGL: the two contexts share (AA_ShareOpenGLContexts), so the surface wraps the same
  texture id; her thread finishes the frame (glFinish) before handing it over.

PySide has no QRhiTexture.createFrom or nativeTexture, so both are called through the
QRhiTexture vtable (ctypes); anything unexpected falls back to the readback path.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass

_log = logging.getLogger("arelis.avatar")
RING = 4  # frames: one shown, the one before it (the surface's GPU may still sample it), two drawn

_MSVC = sys.platform == "win32"


class _NativeTexture(ctypes.Structure):
    _fields_ = [("object", ctypes.c_uint64), ("layout", ctypes.c_int)]


# QRhiTexture's virtuals after the destructor(s): resourceType, destroy, create,
# nativeTexture, createFrom. Itanium has two destructor slots, MSVC one.
_NATIVE_SLOT, _CREATE_FROM_SLOT = (4, 5) if _MSVC else (5, 6)
_FN = ctypes.WINFUNCTYPE if _MSVC else ctypes.CFUNCTYPE


def _vtable(ptr: int):
    return ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]


def _this(qt_obj) -> int:
    import shiboken6

    return shiboken6.getCppPointer(qt_obj)[0]


def native_texture(tex) -> int:
    """QRhiTexture::nativeTexture().object: the ID3D11Texture2D* or the GL texture id."""
    this = _this(tex)
    fn = _vtable(this)[_NATIVE_SLOT]
    if _MSVC:  # a struct returned by value from a member function: hidden pointer
        out = _NativeTexture()
        _FN(ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_NativeTexture))(fn)(
            this, ctypes.byref(out)
        )
        return int(out.object)
    return int(_FN(_NativeTexture, ctypes.c_void_p)(fn)(this).object)


def create_from(tex, native: int) -> bool:
    """QRhiTexture::createFrom({native, 0}), then check it took (nativeTexture reads it back)."""
    this = _this(tex)
    fn = _vtable(this)[_CREATE_FROM_SLOT]
    src = _NativeTexture(native, 0)
    if _MSVC:  # a 16-byte struct argument goes by pointer to a copy
        ok = _FN(ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(_NativeTexture))(fn)(
            this, ctypes.byref(src)
        )
    else:
        ok = _FN(ctypes.c_bool, ctypes.c_void_p, _NativeTexture)(fn)(this, src)
    return bool(ok) and native_texture(tex) == native


def kind_for(her_rhi, surface_rhi) -> str | None:
    """How her frames can reach the surface's QRhi without a readback; None if they cannot."""
    from PySide6.QtGui import QOpenGLContext, QRhi

    if her_rhi is None or surface_rhi is None:
        return None
    impl = QRhi.Implementation
    a, b = her_rhi.backend(), surface_rhi.backend()
    if a == b == impl.D3D11 and _MSVC:
        return "d3d11"
    if a == b == impl.OpenGLES2 and not _MSVC and QOpenGLContext.globalShareContext():
        return "gl"
    return None


# ---- D3D11 through COM vtables (Windows only) ----

_IID_DXGI_RESOURCE = "{035f3ab4-482e-4e50-b41f-8a7f8bd8960b}"
_IID_TEXTURE2D = "{6f15aaf2-d208-4e89-9ab4-489535d34f9c}"


class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16),
                ("d4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str) -> _GUID:
        import uuid

        u = uuid.UUID(text)
        return cls(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))


class _TexDesc(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint) for n in (
        "Width", "Height", "MipLevels", "ArraySize", "Format", "SampleCount", "SampleQuality",
        "Usage", "BindFlags", "CPUAccessFlags", "MiscFlags")]


def _com(ptr: int, index: int, restype, *argtypes):
    fn = _vtable(ptr)[index]
    proto = _FN(restype, ctypes.c_void_p, *argtypes)(fn)
    return lambda *args: proto(ptr, *args)


def _release(ptr: int) -> None:
    if ptr:
        _com(ptr, 2, ctypes.c_ulong)()


def _check(hr: int, what: str) -> None:
    if hr < 0:
        raise OSError(f"{what} failed ({hr & 0xFFFFFFFF:#x})")


def _d3d_resource(window, name: str) -> int:
    from PySide6.QtQuick import QSGRendererInterface

    ri = window.rendererInterface()
    ptr = ri.getResource(window, getattr(QSGRendererInterface.Resource, name))
    ptr = int(ptr) if ptr else 0
    if not ptr:
        raise OSError(f"no D3D11 {name}")
    return ptr


@dataclass
class Frame:
    """One finished frame, as the surface needs it (GUI thread)."""

    generation: int  # bumps when the ring is rebuilt (a resize)
    index: int
    native: int  # D3D11: the shared HANDLE; GL: the texture id
    size: tuple[int, int]
    seq: int  # the frame() call that drew it
    y_up: bool  # GL: drawn bottom-up, so the surface mirrors it


class Producer:
    """Her thread's side: the ring, and when the GPU has finished a frame in it."""

    def __init__(self, kind: str, rhi, window) -> None:
        self.kind, self._rhi, self._window = kind, rhi, window
        self._dev = self._ctx = 0
        if kind == "d3d11":
            self._dev = _d3d_resource(window, "DeviceResource")
            self._ctx = _d3d_resource(window, "DeviceContextResource")

    def texture(self, size: tuple[int, int]):
        """(QRhiTexture to render into, native handle for the surface, release callable)."""
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QRhiTexture

        fmt, flag = QRhiTexture.Format.RGBA8, QRhiTexture.Flag.RenderTarget
        tex = self._rhi.newTexture(fmt, QSize(*size), 1, flag)
        if self.kind == "gl":
            if not tex.create():
                raise OSError("texture create failed")
            return tex, native_texture(tex), tex.destroy
        desc = _TexDesc(size[0], size[1], 1, 1, 28, 1, 0, 0, 0x28, 0, 0x2)  # RGBA8, SHARED
        out = ctypes.c_void_p()
        create = _com(self._dev, 5, ctypes.c_long, ctypes.POINTER(_TexDesc), ctypes.c_void_p,
                      ctypes.POINTER(ctypes.c_void_p))
        _check(create(ctypes.byref(desc), None, ctypes.byref(out)), "CreateTexture2D")
        d3d = out.value
        try:
            res = ctypes.c_void_p()
            qi = _com(d3d, 0, ctypes.c_long, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))
            _check(qi(ctypes.byref(_GUID.parse(_IID_DXGI_RESOURCE)), ctypes.byref(res)),
                   "IDXGIResource")
            handle = ctypes.c_void_p()
            get = _com(res.value, 8, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))
            hr = get(ctypes.byref(handle))
            _release(res.value)
            _check(hr, "GetSharedHandle")
            if not create_from(tex, d3d):
                raise OSError("QRhiTexture.createFrom failed")
        except Exception:
            _release(d3d)
            raise

        def release() -> None:
            tex.destroy()
            _release(d3d)

        return tex, int(handle.value), release

    def fence(self):
        """After endFrame: a token for done(). OpenGL finishes the frame here."""
        if self.kind == "gl":
            self._rhi.finish()
            return None
        q = ctypes.c_void_p()
        desc = (ctypes.c_uint * 2)(0, 0)  # D3D11_QUERY_EVENT
        create = _com(self._dev, 24, ctypes.c_long, ctypes.c_void_p,
                      ctypes.POINTER(ctypes.c_void_p))
        _check(create(desc, ctypes.byref(q)), "CreateQuery")
        _com(self._ctx, 28, None, ctypes.c_void_p)(q.value)  # End
        _com(self._ctx, 111, None)()  # Flush: the surface's device waits on nothing of ours
        return q.value

    def done(self, token) -> bool:
        """True once the GPU has finished the frame (never blocks); frees the token then."""
        if token is None:
            return True
        data = ctypes.c_int(0)
        get = _com(self._ctx, 29, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_uint, ctypes.c_uint)
        hr = get(token, ctypes.byref(data), 4, 1)  # D3D11_ASYNC_GETDATA_DONOTFLUSH
        if hr == 0:
            _release(token)
            return True
        _check(hr, "GetData")
        return False

    def drop(self, token) -> None:
        if token is not None and self.kind == "d3d11":
            _release(token)


class Consumer:
    """The surface's side (GUI thread): her ring opened on the surface's QRhi."""

    def __init__(self, kind: str, window) -> None:
        self.kind, self._window = kind, window
        self._dev = _d3d_resource(window, "DeviceResource") if kind == "d3d11" else 0
        self._open: dict[tuple[int, int], tuple] = {}

    def texture(self, frame: Frame):
        """The QSGTexture for a frame, opened once per ring slot."""
        key = (frame.generation, frame.index)
        have = self._open.get(key)
        if have is not None:
            return have[0]
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QRhiTexture
        from PySide6.QtQuick import QQuickWindow

        rhi = self._window.rhi()
        tex = rhi.newTexture(QRhiTexture.Format.RGBA8, QSize(*frame.size), 1, QRhiTexture.Flag(0))
        native, com = frame.native, 0
        if self.kind == "d3d11":
            out = ctypes.c_void_p()
            open_ = _com(self._dev, 28, ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_GUID),
                         ctypes.POINTER(ctypes.c_void_p))
            _check(open_(ctypes.c_void_p(frame.native), ctypes.byref(_GUID.parse(_IID_TEXTURE2D)),
                         ctypes.byref(out)), "OpenSharedResource")
            native = com = out.value
        if not create_from(tex, native):
            _release(com)
            raise OSError("QRhiTexture.createFrom failed on the surface")
        opt = QQuickWindow.CreateTextureOption.TextureHasAlphaChannel
        sg = self._window.createTextureFromRhiTexture(tex, opt)
        self._open[key] = (sg, tex, com)
        return sg

    def forget_before(self, generation: int) -> None:
        """Free slots of rings older than ``generation`` (her thread rebuilt it)."""
        for key in [k for k in self._open if k[0] < generation]:
            self.free(key)

    def free(self, key) -> None:
        import shiboken6

        sg, tex, com = self._open.pop(key)
        if shiboken6.isValid(sg):
            tex.destroy()  # while the surface's QRhi is alive
            # sg owns tex (createTextureFromRhiTexture) and deletes it. Through Qt, so PySide
            # hears of it: shiboken6.delete left a dangling wrapper that crashed at exit.
            sg.deleteLater()
        _release(com)

    def close(self) -> None:
        for key in list(self._open):
            self.free(key)
