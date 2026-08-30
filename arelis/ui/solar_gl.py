"""OpenGL space for the solar lab. Approach/orbit, not landing.

Offscreen FBO — a native GL widget aborted this AMD driver. Software
QPainter globes stay as fallback. Body spin is attitude.py (IAU W, or
GMST+obliquity for Earth) times a mesh-to-body map. Radii drawn here
may use a screen-space floor; physics does not.
"""

from __future__ import annotations

import faulthandler
import logging
import math
import os
import time
from collections.abc import MutableMapping
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QImage,
    QMatrix4x4,
    QOffscreenSurface,
    QOpenGLContext,
    QOpenGLFunctions,
    QSurfaceFormat,
    QVector3D,
)
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLFramebufferObject,
    QOpenGLFramebufferObjectFormat,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QOpenGLVertexArrayObject,
)
from shiboken6 import VoidPtr

from arelis.physics.attitude import (
    body_frame_ecliptic,
    saturn_ring_axes,
    spin_jd,
    sun_pole_ecliptic,
)
from arelis.physics.constants import (
    AU_M,
    BODY_BY_NAME,
    G_SI,
    SATURN_CASSINI_INNER_M,
    SATURN_CASSINI_OUTER_M,
    SATURN_RING_INNER_M,
    SATURN_RING_OUTER_M,
)
from arelis.physics.evolution import sample, sun_rgb
from arelis.physics.maps import describe, load_rgb
from arelis.physics.runtime import get_system
from arelis.physics.scene import BodyView

if TYPE_CHECKING:
    from arelis.ui.panels.solar import SolarPanel

log = logging.getLogger(__name__)

# Driver abort skips except and drops unflushed logging. This file is fsynced
# after every line so the last step survives. Local only; nothing leaves the machine.
_TRACE_FP = None
_FAULT_ARMED = False


def trace(step: str) -> None:
    """Breadcrumb for solar GL. Force the line to disk before the next native call."""
    line = time.strftime("solar GL %H:%M:%S ") + step
    log.info("%s", line)
    global _TRACE_FP
    try:
        if _TRACE_FP is None:
            from arelis.paths import logs_dir

            directory = logs_dir()
            directory.mkdir(parents=True, exist_ok=True)
            _TRACE_FP = open(directory / "solar_gl.log", "a", encoding="utf-8")
        _TRACE_FP.write(line + "\n")
        _TRACE_FP.flush()
        os.fsync(_TRACE_FP.fileno())
    except OSError:
        pass
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:
            pass


def _enum_name(value: object) -> str:
    """PySide6 enums are not ints. Logging must not crash realize()."""
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return str(value)


def describe_gl_format(got: object) -> str:
    """One breadcrumb line. Never raise: this used to abort GPU init."""
    try:
        return (
            f"got context {got.majorVersion()}.{got.minorVersion()} "
            f"profile={_enum_name(got.profile())} "
            f"renderable={_enum_name(got.renderableType())} "
            f"samples={got.samples()}"
        )
    except Exception:
        return "got context (could not describe format)"


def gl_offset(byte_offset: int) -> object:
    """GLvoid* for QOpenGLFunctions. A Python int is rejected (mesh-upload crash)."""
    return VoidPtr(int(byte_offset))


def uniform_is_int(value: object) -> bool:
    """True only for Python int. 4e14 as float must not take the int uniform path."""
    return type(value) is int


def arm_fault_log() -> None:
    """Dump an access violation into solar_gl.log. Python except cannot do this."""
    global _FAULT_ARMED
    if _FAULT_ARMED:
        return
    trace("arming faulthandler")
    if _TRACE_FP is None:
        trace("faulthandler skipped (no trace file)")
        return
    try:
        faulthandler.enable(file=_TRACE_FP, all_threads=True)
        _FAULT_ARMED = True
        trace("faulthandler armed")
    except Exception:
        log.exception("faulthandler failed")
        trace("faulthandler failed")

# Khronos enums. Avoid a PyOpenGL extra; Qt functions take these ints.
_GL_COLOR_BUFFER_BIT = 0x4000
_GL_DEPTH_BUFFER_BIT = 0x0100
_GL_DEPTH_TEST = 0x0B71
_GL_BLEND = 0x0BE2
_GL_SRC_ALPHA = 0x0302
_GL_ONE_MINUS_SRC_ALPHA = 0x0303
_GL_ONE = 1
_GL_TRIANGLES = 0x0004
_GL_UNSIGNED_INT = 0x1405
_GL_FLOAT = 0x1406
_GL_ARRAY_BUFFER = 0x8892
_GL_ELEMENT_ARRAY_BUFFER = 0x8893
_GL_STATIC_DRAW = 0x88E4
_GL_POINTS = 0x0000
_GL_LINES = 0x0001
_GL_LINE_LOOP = 0x0002
_GL_LEQUAL = 0x0203
_GL_CULL_FACE = 0x0B44
_GL_BACK = 0x0405
_GL_FRONT = 0x0404
_GL_PROGRAM_POINT_SIZE = 0x8642
_GL_FALSE = 0
_GL_TRUE = 1
_GL_TEXTURE0 = 0x84C0
_GL_CCW = 0x0901
_GL_CW = 0x0900
_GL_TRIANGLE_STRIP = 0x0005
_GL_TRIANGLE_FAN = 0x0006
_GL_POINT_SPRITE = 0x8861

_FOV_Y = 0.70
_FILL = 0.08
_FAR_M = 4.0e14
# Readback is a synchronous GPU->CPU transfer, so this is a bandwidth budget as
# much as a quality one. 2560 renders a 1440p plate native instead of upscaling
# a 1920 frame; inspect no longer asks for more, because 4K x 4 bytes a frame
# costs more than the sharpening is worth. Watch "frame cost" in solar_gl.log.
_FB_CAP = 2560
_FB_CLOSE = 2560
_SKIP_PX = 1.6
_TEX_PX = 8.0
_HI_PX = 28.0
_ATMO_PX = 22.0
# Rebuild osculating rings at most this often in wall seconds. The ellipse is a
# path, not a position: 1440 Kepler evaluations per frame bought nothing.
_ORBIT_REBUILD_S = 0.25
_PERF_EVERY_S = 4.0
_GL_BGRA = 0x80E1
_GL_UNSIGNED_BYTE = 0x1401
_GL_PACK_ALIGNMENT = 0x0D05

# Clip w is metres; 24-bit depth cannot span the system linearly.
_LOG_DEPTH = """
uniform float uFar;
void arelisLogDepth() {
    float w = max(gl_Position.w, 1.0);
    gl_Position.z = (2.0 * log(w) / log(max(uFar, 2.0)) - 1.0) * gl_Position.w;
}
"""

_VS_BODY = (
    "#version 330\n"
    + _LOG_DEPTH
    + """
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aN;
layout(location = 2) in vec2 aUV;
uniform mat4 uMVP;
uniform mat4 uModel;
out vec3 vWorldP;
out vec3 vWorldN;
out vec2 vUV;
void main() {
    vec4 wp = uModel * vec4(aPos, 1.0);
    vWorldP = wp.xyz;
    vWorldN = mat3(uModel) * aN;
    vUV = aUV;
    gl_Position = uMVP * vec4(aPos, 1.0);
    arelisLogDepth();
}
"""
)

_FS_BODY = """
#version 330
in vec3 vWorldP;
in vec3 vWorldN;
in vec2 vUV;
uniform sampler2D uAlbedo;
uniform vec3 uTint;
uniform vec3 uSunP;
uniform int uHasMap;
uniform int uEmissive;
uniform int uOcean;
uniform int uGap;
uniform int uRing;
uniform float uRingR0;
uniform float uRingR1;
uniform float uCas0;
uniform float uCas1;
uniform float uFill;
uniform float uWrap;
uniform float uLimb;
uniform float uAlpha;
uniform float uGran;
uniform float uClose;
uniform float uTime;
out vec4 frag;
void main() {
    vec3 n = normalize(vWorldN);
    vec3 v = normalize(-vWorldP);
    vec3 l = normalize(uSunP - vWorldP);
    float ndl = dot(n, l);
    if (uRing == 1) {
        float t = clamp(vUV.x, 0.0, 1.0);
        float rr = mix(uRingR0, uRingR1, t);
        float cassini = smoothstep(uCas0 - 0.008, uCas0, rr)
            * (1.0 - smoothstep(uCas1, uCas1 + 0.008, rr));
        float ice = 0.42 + 0.58 * abs(ndl);
        float alpha = 0.58 * ice * (1.0 - cassini);
        vec3 col = vec3(0.95, 0.90, 0.74) * ice;
        if (alpha < 0.02) discard;
        frag = vec4(col, alpha);
        return;
    }
    vec3 alb = uHasMap == 1 ? texture(uAlbedo, vUV).rgb : uTint;
    if (uGap == 1 && uHasMap == 1) {
        float lum = max(alb.r, max(alb.g, alb.b));
        float lo = min(alb.r, min(alb.g, alb.b));
        float chroma = lum - lo;
        float hole = 1.0 - smoothstep(0.02, 0.08, lum);
        float blank = smoothstep(0.97, 0.995, lum) * (1.0 - smoothstep(0.008, 0.03, chroma));
        alb = mix(alb, uTint, max(hole, blank));
    }
    if (uEmissive == 1) {
        float mu = max(dot(n, v), 0.0);
        float ld = 1.0 - 0.56 * (1.0 - mu);
        vec3 core = mix(alb * vec3(1.36, 1.12, 0.62), vec3(1.42, 1.24, 0.90), 0.34);
        vec3 limbc = alb * vec3(1.20, 0.46, 0.08);
        vec3 phot = mix(limbc, core, pow(mu, 0.32)) * ld;
        if (uGran > 0.01) {
            vec3 p = normalize(n);
            float g = sin(dot(p, vec3(17.2, 8.1, 3.4)) * 18.0 + uTime * 0.16);
            g += 0.55 * sin(dot(p, vec3(4.2, 19.0, 11.7)) * 34.0 - uTime * 0.11);
            g += 0.30 * sin(dot(p, vec3(11.4, 2.6, 23.1)) * 52.0 + uTime * 0.07);
            phot *= 1.0 + uGran * 0.10 * g;
        }
        phot *= mix(0.96, 1.06, uClose);
        frag = vec4(phot, uAlpha);
        return;
    }
    float wrap = clamp((ndl + uWrap) / max(1.0 + uWrap, 1e-4), 0.0, 1.0);
    float limb = pow(max(dot(n, v), 0.0), uLimb);
    alb *= mix(0.55, 1.0, limb);
    vec3 color = alb * (uFill + (1.0 - uFill) * wrap);
    if (uOcean == 1) {
        float water = smoothstep(0.28, 0.12, alb.r)
            * smoothstep(0.28, 0.12, alb.g)
            * smoothstep(0.12, 0.32, alb.b);
        vec3 h = normalize(l + v);
        float spec = pow(max(dot(n, h), 0.0), 120.0) * water * wrap * 0.16;
        color += vec3(0.42, 0.52, 0.68) * spec;
    }
    frag = vec4(color, uAlpha);
}
"""

_VS_STAR = """
#version 330
layout(location = 0) in vec3 aDir;
layout(location = 1) in float aMag;
uniform mat4 uView;
uniform mat4 uProj;
out float vMag;
out vec3 vCol;
void main() {
    vMag = aMag;
    float t = aMag;
    vCol = mix(vec3(0.55, 0.62, 1.0), vec3(1.0, 0.92, 0.75), t);
    vec4 clip = uProj * uView * vec4(aDir, 0.0);
    gl_Position = clip.xyww;
    gl_PointSize = mix(0.9, 3.4, pow(t, 1.4));
}
"""

_FS_STAR = """
#version 330
in float vMag;
in vec3 vCol;
out vec4 frag;
void main() {
    vec2 p = gl_PointCoord * 2.0 - 1.0;
    float r = dot(p, p);
    if (r > 1.0) discard;
    float core = exp(-r * 3.2);
    frag = vec4(vCol, core * mix(0.25, 1.0, vMag));
}
"""

_VS_ATMO = (
    "#version 330\n"
    + _LOG_DEPTH
    + """
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aN;
uniform mat4 uMVP;
uniform mat4 uModel;
out vec3 vWorldP;
out vec3 vWorldN;
void main() {
    vec4 wp = uModel * vec4(aPos, 1.0);
    vWorldP = wp.xyz;
    vWorldN = mat3(uModel) * aN;
    gl_Position = uMVP * vec4(aPos, 1.0);
    arelisLogDepth();
}
"""
)

_FS_ATMO = """
#version 330
in vec3 vWorldP;
in vec3 vWorldN;
uniform vec3 uSunP;
uniform vec3 uAtmo;
uniform float uGain;
out vec4 frag;
void main() {
    vec3 n = normalize(vWorldN);
    vec3 v = normalize(-vWorldP);
    vec3 l = normalize(uSunP - vWorldP);
    float ndv = max(dot(n, v), 0.0);
    float limb = pow(1.0 - ndv, 2.2);
    float sunlit = max(dot(n, l), 0.0);
    float a = limb * (0.18 + 0.82 * sunlit) * uGain;
    frag = vec4(uAtmo, a);
}
"""

_VS_GLOW = """
#version 330
layout(location = 0) in vec2 aCorner;
uniform vec2 uSunNdc;
uniform float uExtent;
uniform float uAspect;
out vec2 vUV;
void main() {
    vUV = aCorner;
    vec2 pos = uSunNdc + vec2(aCorner.x * uExtent * uAspect, aCorner.y * uExtent);
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""

_FS_GLOW = """
#version 330
in vec2 vUV;
uniform vec3 uColor;
uniform vec2 uPole;
uniform float uDisc;
uniform float uClose;
uniform float uNeedle;
uniform float uBloom;
uniform float uCore;
uniform float uLen;
uniform float uGain;
out vec4 frag;

float needle(vec2 p, vec2 axis, float halfw, float len, float gain) {
    vec2 nrm = vec2(-axis.y, axis.x);
    float d = dot(p, nrm);
    float along = abs(dot(p, axis));
    float shaft = exp(-(d * d) / max(halfw * halfw, 1e-8));
    float fade = exp(-along / max(len, 1e-4));
    float start = max(uDisc * 0.98, 0.16 * (1.0 - uClose));
    float past = smoothstep(start, start + halfw * 8.0, along);
    return gain * shaft * fade * past;
}

void main() {
    float r = length(vUV);
    float disc = max(uDisc, 1e-4);
    // Fade to zero inside the quad so the billboard never reads as a card.
    if (r > 0.98) {
        frag = vec4(0.0);
        discard;
    }
    if (uClose > 0.55 && r < disc) {
        frag = vec4(0.0);
        discard;
    }
    float s = max(r - disc, 0.0);
    float core = (1.0 - uClose) * exp(-(r * r) / max(uCore * uCore, 1e-6));
    float bloom = exp(-s / max(uBloom, 0.002)) * mix(0.82, 0.48, uClose);
    bloom *= 1.0 - smoothstep(0.05, 0.28, s);
    float halfw = uNeedle;
    float len = max(uLen, 0.10);
    float rays = needle(vUV, vec2(1.0, 0.0), halfw, len, (0.50 + 0.85 * uClose) * uGain)
        + needle(vUV, vec2(0.0, 1.0), halfw * 0.90, len * 0.86, (0.42 + 0.70 * uClose) * uGain)
        + needle(vUV, normalize(vec2(1.0, 1.0)), halfw * 0.68, len * 0.48, 0.20 * uGain * uClose)
        + needle(vUV, normalize(vec2(1.0, -1.0)), halfw * 0.68, len * 0.48, 0.20 * uGain * uClose);
    float edge = 1.0 - smoothstep(0.62, 0.88, r);
    float a = (core * 1.25 + bloom + rays) * edge;
    if (a < 0.02) {
        frag = vec4(0.0);
        discard;
    }
    vec3 hot = mix(uColor, vec3(1.50, 1.35, 1.05), 0.72);
    vec3 col = mix(hot, vec3(1.10, 0.68, 0.28), smoothstep(0.0, 0.18, s) * 0.28);
    frag = vec4(col * min(a, 1.55), 0.0);
}
"""

_VS_LINE = (
    "#version 330\n"
    + _LOG_DEPTH
    + """
layout(location = 0) in vec3 aPos;
uniform mat4 uView;
uniform mat4 uProj;
uniform vec3 uEye;
void main() {
    vec3 p = aPos - uEye;
    gl_Position = uProj * uView * vec4(p, 1.0);
    arelisLogDepth();
}
"""
)

_FS_LINE = """
#version 330
uniform vec4 uColor;
out vec4 frag;
void main() {
    frag = uColor;
}
"""

_VS_BEAD = (
    "#version 330\n"
    + _LOG_DEPTH
    + """
layout(location = 0) in vec3 aPos;
layout(location = 1) in float aPulse;
uniform mat4 uView;
uniform mat4 uProj;
uniform vec3 uEye;
out float vPulse;
void main() {
    vPulse = aPulse;
    vec3 p = aPos - uEye;
    gl_Position = uProj * uView * vec4(p, 1.0);
    gl_PointSize = mix(6.0, 14.0, clamp(aPulse, 0.0, 1.0));
    arelisLogDepth();
}
"""
)

_FS_BEAD = """
#version 330
in float vPulse;
uniform vec4 uColor;
out vec4 frag;
void main() {
    vec2 p = gl_PointCoord * 2.0 - 1.0;
    float r = dot(p, p);
    if (r > 1.0) discard;
    float core = exp(-r * 2.8);
    float a = core * mix(0.40, 1.0, vPulse);
    frag = vec4(uColor.rgb * (0.70 + 0.50 * vPulse), a * uColor.a);
}
"""


def framebuffer_size(
    width: int, height: int, *, cap: int = _FB_CAP
) -> tuple[int, int]:
    """Readback size. Full window toImage at 4K is the 5 Hz path."""
    w, h = max(int(width), 1), max(int(height), 1)
    long_edge = max(w, h)
    if long_edge <= cap:
        return w, h
    scale = cap / long_edge
    return max(1, int(w * scale)), max(1, int(h * scale))


def projection(fb_w: int, fb_h: int, *, fov_y: float | None = None) -> QMatrix4x4:
    """Perspective with clip Y negated.

    glReadPixels hands back rows bottom-up, so rendering upside down is what
    makes the readback come out the right way round without copying the whole
    frame through QImage.mirrored() every paint. The reflection also reverses
    triangle winding, which is why realize() sets FRONT_FACE.
    """
    fov = float(fov_y) if fov_y is not None else _FOV_Y
    proj = QMatrix4x4()
    proj.perspective(
        math.degrees(fov), fb_w / max(fb_h, 1), 1.0e3, _FAR_M
    )
    proj.scale(1.0, -1.0, 1.0)
    return proj


# view_from_basis has determinant -1 and projection() adds another reflection,
# so front faces come back round to counter-clockwise.
FRONT_FACE = _GL_CCW


def glow_extent_px(sun_px: float, fb_h: int) -> float:
    """Pixel radius of the flare quad. See arelis.physics.star_look."""
    from arelis.physics.star_look import star_flare

    return star_flare(sun_px, fb_h).extent_px


def view_from_basis(
    fx: tuple[float, float, float],
    fy: tuple[float, float, float],
    fz: tuple[float, float, float],
) -> QMatrix4x4:
    """Eye-space matching Camera.project.

    Rows fx, fy, -fz have det -1, so winding is reversed here and again by the
    clip-Y flip in projection(). FRONT_FACE carries the net result. Qt lookAt
    would keep winding and mirror X against the overlay.
    """
    return QMatrix4x4(
        fx[0],
        fx[1],
        fx[2],
        0.0,
        fy[0],
        fy[1],
        fy[2],
        0.0,
        -fz[0],
        -fz[1],
        -fz[2],
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )


def gl_wanted() -> bool:
    """GPU space is opt-in. Three driver aborts; software globes stay the default."""
    raw = os.environ.get("ARELIS_SOLAR_GL", "0").strip().lower()
    if raw in {"", "0", "false", "no", "off"}:
        return False
    plat = os.environ.get("QT_QPA_PLATFORM", "").lower()
    if plat in {"offscreen", "minimal", "minimalegl"}:
        return False
    return raw in {"1", "true", "yes", "on"}


def prepare_desktop_gl(env: MutableMapping[str, str]) -> None:
    """Ask for the vendor ICD before QApplication. AMD is fine; D3D+GL mix is not."""
    raw = env.get("ARELIS_SOLAR_GL", "0").strip().lower()
    if raw not in {"1", "true", "yes", "on"}:
        return
    env["QT_OPENGL"] = "desktop"
    trace(f"prepare_desktop_gl QT_OPENGL={env.get('QT_OPENGL')}")


_ATMO: dict[str, tuple[tuple[float, float, float], float, float]] = {
    # color, radius scale, gain. Thin scattering shell, not a climate model.
    "Earth": ((0.32, 0.55, 1.0), 1.016, 0.40),
    "Venus": ((0.92, 0.80, 0.52), 1.020, 0.26),
    "Mars": ((0.78, 0.44, 0.28), 1.022, 0.32),
    "Titan": ((0.82, 0.60, 0.32), 1.03, 0.55),
}
_GAS = {"Jupiter", "Saturn", "Uranus", "Neptune"}


def earth_mesh_to_ecef() -> QMatrix4x4:
    """Mesh UV → ECEF so NASA plate-carrée lines up with overlays.

    make_sphere: u=0 is +Z, u=0.5 is −Z, +Y is the north pole. NASA
    Blue Marble has u=0 at the antimeridian and u=0.5 at Greenwich, so
    mesh −Z must be ECEF +X and mesh +Y must be ECEF +Z.
    """
    return QMatrix4x4(
        0.0,
        0.0,
        -1.0,
        0.0,
        -1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )


def earth_spin_matrix(jd: float) -> QMatrix4x4:
    """ECLIPJ2000 from a unit mesh point. Same axes as ecef_to_ecliptic."""
    frame = body_frame_ecliptic("Earth", jd)
    assert frame is not None
    return _frame_matrix(frame) * earth_mesh_to_ecef()


def _frame_matrix(frame) -> QMatrix4x4:
    xx, yx, zx = frame
    return QMatrix4x4(
        xx[0],
        yx[0],
        zx[0],
        0.0,
        xx[1],
        yx[1],
        zx[1],
        0.0,
        xx[2],
        yx[2],
        zx[2],
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )


def make_sphere(slices: int = 96, stacks: int = 64) -> tuple[np.ndarray, np.ndarray]:
    """Unit sphere, +Y pole. Interleaved pos, normal, uv. Clockwise? CCW with +Y."""
    verts: list[float] = []
    for i in range(stacks + 1):
        v = i / stacks
        phi = v * math.pi
        sp, cp = math.sin(phi), math.cos(phi)
        for j in range(slices + 1):
            u = j / slices
            th = u * 2.0 * math.pi
            st, ct = math.sin(th), math.cos(th)
            x, y, z = st * sp, cp, ct * sp
            verts.extend((x, y, z, x, y, z, u, 1.0 - v))
    idx: list[int] = []
    row = slices + 1
    for i in range(stacks):
        for j in range(slices):
            a = i * row + j
            b = a + row
            idx.extend((a, b, a + 1, a + 1, b, b + 1))
    return (
        np.asarray(verts, dtype=np.float32),
        np.asarray(idx, dtype=np.uint32),
    )


def make_stars(count: int = 9000, seed: int = 20260824) -> np.ndarray:
    """Unit directions + 0..1 brightness. Denser along a tilted band (illustration)."""
    rng = np.random.default_rng(seed)
    n = int(count)
    field = rng.normal(size=(n, 3))
    field /= np.linalg.norm(field, axis=1, keepdims=True).clip(1e-9)
    pole = np.array([0.18, 0.48, 0.86], dtype=np.float64)
    pole /= np.linalg.norm(pole)
    extra = int(n * 0.35)
    band = rng.normal(size=(extra, 3))
    band -= (band @ pole)[:, None] * pole
    band += pole * rng.normal(scale=0.12, size=(extra, 1))
    band /= np.linalg.norm(band, axis=1, keepdims=True).clip(1e-9)
    dirs = np.vstack((field, band))
    mag = rng.random(len(dirs)) ** 2.4
    mag[:80] = np.linspace(0.75, 1.0, 80)
    out = np.zeros((len(dirs), 4), dtype=np.float32)
    out[:, :3] = dirs.astype(np.float32)
    out[:, 3] = mag.astype(np.float32)
    return out


def make_ring(inner: float, outer: float, steps: int = 96) -> np.ndarray:
    """XY annulus triangle strip. Ecliptic plane; +Z north."""
    verts: list[float] = []
    for i in range(steps + 1):
        ang = 2.0 * math.pi * i / steps
        c, s = math.cos(ang), math.sin(ang)
        verts.extend((inner * c, inner * s, 0.0, 0.0, 0.0, 1.0, 0.0, 0.5))
        verts.extend((outer * c, outer * s, 0.0, 0.0, 0.0, 1.0, 1.0, 0.5))
    return np.asarray(verts, dtype=np.float32)


class SolarSpaceView(QOpenGLFunctions):
    """Offscreen GL. The plate stays a normal widget so Qt 6 can keep using D3D."""

    def __init__(self, panel: SolarPanel) -> None:
        super().__init__()
        self._panel = panel
        self.gl_ok = False
        self.version_label = "software"
        self._logged_paint = False
        self._fb_w = 1
        self._fb_h = 1
        self._surface: QOffscreenSurface | None = None
        self._ctx: QOpenGLContext | None = None
        self._fbo: QOpenGLFramebufferObject | None = None
        self._prog_body: QOpenGLShaderProgram | None = None
        self._prog_star: QOpenGLShaderProgram | None = None
        self._prog_atmo: QOpenGLShaderProgram | None = None
        self._prog_glow: QOpenGLShaderProgram | None = None
        self._prog_line: QOpenGLShaderProgram | None = None
        self._prog_bead: QOpenGLShaderProgram | None = None
        self._sphere_vao: QOpenGLVertexArrayObject | None = None
        self._sphere_n = 0
        self._lod_vao: QOpenGLVertexArrayObject | None = None
        self._lod_n = 0
        self._star_vao: QOpenGLVertexArrayObject | None = None
        self._star_n = 0
        self._glow_vao: QOpenGLVertexArrayObject | None = None
        self._ring_vao: QOpenGLVertexArrayObject | None = None
        self._ring_n = 0
        self._textures: dict[str, QOpenGLTexture] = {}
        self._white: QOpenGLTexture | None = None
        self._orbit_buf: QOpenGLBuffer | None = None
        self._orbit_vao: QOpenGLVertexArrayObject | None = None
        self._orbit_n = 0
        self._orbit_key: object = None
        self._orbit_local: np.ndarray | None = None
        self._orbit_groups: list[tuple[str, str | None, int, int]] = []
        self._orbit_scratch: np.ndarray | None = None
        self._orbit_built = -1.0e9
        self._orbit_t = -1.0e9
        self._orbit_cap = 0
        self._bead_buf: QOpenGLBuffer | None = None
        self._bead_vao: QOpenGLVertexArrayObject | None = None
        self._bead_cap = 0
        self._fill_buf: QOpenGLBuffer | None = None
        self._fill_vao: QOpenGLVertexArrayObject | None = None
        self._fill_cap = 0
        self._mag_buf: QOpenGLBuffer | None = None
        self._mag_vao: QOpenGLVertexArrayObject | None = None
        self._mag_ibo: QOpenGLBuffer | None = None
        self._mag_local: np.ndarray | None = None
        self._mag_idx: np.ndarray | None = None
        self._mag_n = 0
        self._mag_cap = 0
        self._mag_key: object = None
        self._dip_buf: QOpenGLBuffer | None = None
        self._dip_vao: QOpenGLVertexArrayObject | None = None
        self._dip_local: np.ndarray | None = None
        self._dip_cap = 0
        self._shue_n = 0
        self._well_buf: QOpenGLBuffer | None = None
        self._well_vao: QOpenGLVertexArrayObject | None = None
        self._well_ibo: QOpenGLBuffer | None = None
        self._well_local: np.ndarray | None = None
        self._well_idx: np.ndarray | None = None
        self._well_n = 0
        self._well_cap = 0
        self._well_key: object = None
        self._tracer_buf: QOpenGLBuffer | None = None
        self._tracer_vao: QOpenGLVertexArrayObject | None = None
        self._tracer_cap = 0
        self._loop_buf: QOpenGLBuffer | None = None
        self._loop_vao: QOpenGLVertexArrayObject | None = None
        self._loop_cap = 0
        self._frame: QImage | None = None
        self._frame_key: object = None
        self._readback: QImage | None = None
        self._perf = [0.0, 0.0, 0.0, 0.0]  # frames, render s, readback s, since
        self._keep: list[object] = []

    def realize(self) -> None:
        try:
            trace("realize: QOffscreenSurface")
            fmt = QSurfaceFormat()
            fmt.setVersion(3, 3)
            fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
            fmt.setDepthBufferSize(24)
            fmt.setSamples(0)
            fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
            self._surface = QOffscreenSurface()
            self._surface.setFormat(fmt)
            self._surface.create()
            if not self._surface.isValid():
                raise RuntimeError("offscreen surface invalid")
            trace("realize: QOpenGLContext.create")
            self._ctx = QOpenGLContext()
            self._ctx.setFormat(fmt)
            if not self._ctx.create():
                raise RuntimeError("OpenGL context create failed")
            got = self._ctx.format()
            trace(describe_gl_format(got))
            self.version_label = f"OpenGL {got.majorVersion()}.{got.minorVersion()}"
            trace("realize: makeCurrent")
            if not self._ctx.makeCurrent(self._surface):
                raise RuntimeError("makeCurrent failed")
            trace("initializeOpenGLFunctions")
            self.initializeOpenGLFunctions()
            trace("glClearColor")
            self.glClearColor(0.004, 0.006, 0.014, 1.0)
            trace("glEnable DEPTH_TEST")
            self.glEnable(_GL_DEPTH_TEST)
            trace("glEnable PROGRAM_POINT_SIZE")
            self.glEnable(_GL_PROGRAM_POINT_SIZE)
            trace("glEnable POINT_SPRITE")
            self.glEnable(_GL_POINT_SPRITE)
            trace("glEnable CULL_FACE")
            self.glEnable(_GL_CULL_FACE)
            self.glCullFace(_GL_BACK)
            self.glFrontFace(FRONT_FACE)
            self._prog_body = self._compile(_VS_BODY, _FS_BODY, "body")
            self._prog_star = self._compile(_VS_STAR, _FS_STAR, "star")
            self._prog_atmo = self._compile(_VS_ATMO, _FS_ATMO, "atmo")
            self._prog_glow = self._compile(_VS_GLOW, _FS_GLOW, "glow")
            self._prog_line = self._compile(_VS_LINE, _FS_LINE, "line")
            self._prog_bead = self._compile(_VS_BEAD, _FS_BEAD, "bead")
            trace("make_sphere")
            v, i = make_sphere()
            trace("upload sphere mesh")
            self._sphere_vao, self._sphere_n = self._mesh(v, i)
            lod_v, lod_i = make_sphere(24, 16)
            self._lod_vao, self._lod_n = self._mesh(lod_v, lod_i)
            trace("make_stars")
            stars = make_stars()
            trace("upload stars")
            self._star_vao, self._star_n = self._points(stars)
            glow = np.array(
                [-1.0, -1.0, 1.0, -1.0, -1.0, 1.0, 1.0, 1.0], dtype=np.float32
            )
            trace("upload glow quad")
            self._glow_vao = self._vec2(glow)
            trace("make_ring")
            rs = BODY_BY_NAME["Saturn"].radius
            ring = make_ring(SATURN_RING_INNER_M / rs, SATURN_RING_OUTER_M / rs)
            trace("upload ring")
            self._ring_vao, self._ring_n = self._strip(ring)
            trace("white texture")
            img = QImage(4, 4, QImage.Format.Format_RGBA8888)
            img.fill(Qt.GlobalColor.white)
            self._white = QOpenGLTexture(img)
            self._white.setMinMagFilters(
                QOpenGLTexture.Filter.Linear, QOpenGLTexture.Filter.Linear
            )
            self.gl_ok = True
            trace("realize ok")
        except Exception:
            log.exception("solar OpenGL init failed")
            trace("realize python exception (see arelis.log)")
            self.gl_ok = False

    def _compile(self, vs: str, fs: str, name: str) -> QOpenGLShaderProgram:
        trace(f"compile {name} vertex")
        prog = QOpenGLShaderProgram()
        self._keep.append(prog)
        if not prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, vs):
            raise RuntimeError(f"{name} vs: {prog.log()}")
        trace(f"compile {name} fragment")
        if not prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, fs):
            raise RuntimeError(f"{name} fs: {prog.log()}")
        trace(f"link {name}")
        if not prog.link():
            raise RuntimeError(f"{name} link: {prog.log()}")
        trace(f"linked {name}")
        return prog

    def _mesh(
        self, verts: np.ndarray, idx: np.ndarray
    ) -> tuple[QOpenGLVertexArrayObject, int]:
        vao = QOpenGLVertexArrayObject()
        if not vao.create():
            raise RuntimeError("sphere VAO")
        vao.bind()
        vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        if not vbo.create():
            raise RuntimeError("sphere VBO")
        vbo.bind()
        vbo.allocate(verts.tobytes(), verts.nbytes)
        ibo = QOpenGLBuffer(QOpenGLBuffer.Type.IndexBuffer)
        if not ibo.create():
            raise RuntimeError("sphere IBO")
        ibo.bind()
        ibo.allocate(idx.tobytes(), idx.nbytes)
        stride = 8 * 4
        self._attrib(0, 3, stride, 0)
        self._attrib(1, 3, stride, 12)
        self._attrib(2, 2, stride, 24)
        vao.release()
        self._keep.extend((vbo, ibo))
        return vao, int(idx.size)

    def _points(self, stars: np.ndarray) -> tuple[QOpenGLVertexArrayObject, int]:
        vao = QOpenGLVertexArrayObject()
        if not vao.create():
            raise RuntimeError("star VAO")
        vao.bind()
        vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        if not vbo.create():
            raise RuntimeError("star VBO")
        vbo.bind()
        vbo.allocate(stars.tobytes(), stars.nbytes)
        self._attrib(0, 3, 16, 0)
        self._attrib(1, 1, 16, 12)
        vao.release()
        self._keep.append(vbo)
        return vao, int(stars.shape[0])

    def _vec2(self, data: np.ndarray) -> QOpenGLVertexArrayObject:
        vao = QOpenGLVertexArrayObject()
        if not vao.create():
            raise RuntimeError("glow VAO")
        vao.bind()
        vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        if not vbo.create():
            raise RuntimeError("glow VBO")
        vbo.bind()
        vbo.allocate(data.tobytes(), data.nbytes)
        self._attrib(0, 2, 8, 0)
        vao.release()
        self._keep.append(vbo)
        return vao

    def _strip(self, verts: np.ndarray) -> tuple[QOpenGLVertexArrayObject, int]:
        vao = QOpenGLVertexArrayObject()
        if not vao.create():
            raise RuntimeError("ring VAO")
        vao.bind()
        vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        if not vbo.create():
            raise RuntimeError("ring VBO")
        vbo.bind()
        vbo.allocate(verts.tobytes(), verts.nbytes)
        stride = 8 * 4
        self._attrib(0, 3, stride, 0)
        self._attrib(1, 3, stride, 12)
        self._attrib(2, 2, stride, 24)
        vao.release()
        self._keep.append(vbo)
        return vao, int(verts.size // 8)

    def _attrib(self, index: int, size: int, stride: int, offset: int) -> None:
        self.glEnableVertexAttribArray(int(index))
        self.glVertexAttribPointer(
            int(index),
            int(size),
            int(_GL_FLOAT),
            int(_GL_FALSE),
            int(stride),
            gl_offset(offset),
        )

    def _draw_sphere(self, *, hi: bool = True) -> None:
        vao = self._sphere_vao if hi else self._lod_vao
        count = self._sphere_n if hi else self._lod_n
        if vao is None or count <= 0:
            return
        vao.bind()
        self.glDrawElements(
            int(_GL_TRIANGLES),
            int(count),
            int(_GL_UNSIGNED_INT),
            gl_offset(0),
        )
        vao.release()

    def invalidate_maps(self) -> None:
        if self._ctx is not None and self._surface is not None:
            self._ctx.makeCurrent(self._surface)
        for tex in self._textures.values():
            tex.destroy()
        self._textures.clear()
        self._frame = None
        self._frame_key = None

    def _tex(self, name: str) -> tuple[QOpenGLTexture, int]:
        hit = self._textures.get(name)
        if hit is not None:
            return hit, 1
        info = describe(name)
        if info.path is None:
            assert self._white is not None
            return self._white, 0
        rgb = load_rgb(info.path)
        if rgb is None:
            trace(f"tex decode failed {name}")
            assert self._white is not None
            return self._white, 0
        width, height, pixels = rgb
        image = QImage(pixels, width, height, width * 3, QImage.Format.Format_RGB888)
        image = image.copy().convertToFormat(QImage.Format.Format_RGBA8888).mirrored(
            False, True
        )
        tex = QOpenGLTexture(image)
        if not tex.isCreated() or tex.textureId() == 0:
            trace(f"tex create failed {name}")
            assert self._white is not None
            return self._white, 0
        # A 2048-wide mosaic on a 40 px disc without mipmaps is a shimmering
        # mess. QOpenGLTexture(QImage) already built the levels; use them.
        tex.setMinificationFilter(QOpenGLTexture.Filter.LinearMipMapLinear)
        tex.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
        tex.setWrapMode(QOpenGLTexture.WrapMode.Repeat)
        try:
            tex.setMaximumAnisotropy(8.0)
        except (AttributeError, RuntimeError):
            pass
        self._textures[name] = tex
        self._keep.append(tex)
        self._keep.append(image)
        trace(f"tex {name} {image.width()}x{image.height()} id={tex.textureId()}")
        return tex, 1

    def _ensure_fbo(self, width: int, height: int) -> QOpenGLFramebufferObject:
        w, h = max(int(width), 1), max(int(height), 1)
        if (
            self._fbo is not None
            and self._fbo.width() == w
            and self._fbo.height() == h
        ):
            return self._fbo
        trace(f"fbo resize {w}x{h}")
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(
            QOpenGLFramebufferObject.Attachment.CombinedDepthStencil
        )
        self._fbo = QOpenGLFramebufferObject(w, h, fmt)
        if not self._fbo.isValid():
            raise RuntimeError("FBO invalid")
        return self._fbo

    def _fb_size(self, width: int, height: int) -> tuple[int, int]:
        cap = _FB_CLOSE if self._panel._inspect else _FB_CAP
        return framebuffer_size(width, height, cap=cap)

    def _view_key(self, width: int, height: int) -> tuple:
        panel = self._panel
        system = get_system()
        cam = panel.cam
        t = 0.0 if system is None or system.paused else round(float(system.t), 2)
        osc = bool(system is not None and system.show_osculating)
        if system is None:
            live = 0
        elif osc:
            live = int(time.perf_counter() * 6)
        elif system.paused:
            live = int(time.perf_counter() * 3)
        else:
            live = 0
        gyr = 0.0 if system is None else round(float(system.future_gyr), 3)
        grav = bool(system is not None and system.overlay.show_gravity)
        mag = bool(system is not None and system.overlay.show_magnetic)
        return (
            int(width),
            int(height),
            round(cam.x),
            round(cam.y),
            round(cam.z),
            round(cam.yaw, 4),
            round(cam.pitch, 4),
            round(cam.up[0], 4),
            round(cam.up[1], 4),
            round(cam.up[2], 4),
            t,
            live,
            gyr,
            osc,
            grav,
            mag,
            panel._inspect or "",
            round(panel._fov_y(), 4),
        )

    def _read_fbo(self, fbo: QOpenGLFramebufferObject) -> QImage:
        w, h = fbo.width(), fbo.height()
        image = self._readback
        if image is None or image.width() != w or image.height() != h:
            image = QImage(w, h, QImage.Format.Format_ARGB32)
            self._readback = image
        try:
            self.glPixelStorei(_GL_PACK_ALIGNMENT, 4)
            self.glReadPixels(
                0,
                0,
                w,
                h,
                _GL_BGRA,
                _GL_UNSIGNED_BYTE,
                VoidPtr(image.bits()),
            )
            return image
        except Exception:
            # Qt flips for us here, and the scene is already rendered flipped.
            return fbo.toImage().mirrored(False, True)

    def render(
        self, width: int, height: int, *, stars_only: bool = False
    ) -> QImage | None:
        if not self.gl_ok or self._ctx is None or self._surface is None:
            return None
        key = (*self._view_key(width, height), stars_only)
        if key == self._frame_key and self._frame is not None and not self._frame.isNull():
            return self._frame
        first = not self._logged_paint
        started = time.perf_counter()
        try:
            if first:
                trace("render first frame start")
            if not self._ctx.makeCurrent(self._surface):
                raise RuntimeError("makeCurrent failed")
            self._fb_w, self._fb_h = self._fb_size(width, height)
            fbo = self._ensure_fbo(self._fb_w, self._fb_h)
            fbo.bind()
            self.glViewport(0, 0, self._fb_w, self._fb_h)
            self.glClear(_GL_COLOR_BUFFER_BIT | _GL_DEPTH_BUFFER_BIT)
            panel = self._panel
            eye = (panel.cam.x, panel.cam.y, panel.cam.z)
            fx, fy, fz = panel.cam.basis()
            view = view_from_basis(fx, fy, fz)
            proj = projection(self._fb_w, self._fb_h, fov_y=panel._fov_y())
            self._draw_stars(view, proj)
            system = get_system()
            if system is not None and not stars_only:
                views = system.views()
                sun = system.nbody.find("Sun")
                sun_p = (
                    QVector3D(sun.x - eye[0], sun.y - eye[1], sun.z - eye[2])
                    if sun is not None
                    else QVector3D(0, 0, 0)
                )
                self.glEnable(_GL_DEPTH_TEST)
                bodies = [
                    b
                    for b in views
                    if not b.tracer and b.kind not in {"probe", "lagrange"}
                ]
                bodies.sort(key=lambda b: -self._cam_z(b, eye, fz))
                for body in bodies:
                    self._draw_body(panel, body, system, eye, sun_p, view, proj, fz)
                self._draw_glow(system, eye, sun_p, view, proj, fy, fx)
                self._draw_loops(system, eye, sun_p, view, proj)
                if system.show_osculating:
                    self._draw_orbits(system, views, eye, fz, view, proj)
                if system.overlay.show_gravity:
                    self._draw_wells(system, views, eye, fz, sun_p, view, proj)
                if system.overlay.show_magnetic:
                    self._draw_magnetosphere(system, eye, fz, sun_p, view, proj)
                tracers = [b for b in views if b.tracer]
                if tracers:
                    self._draw_tracers(tracers, eye, view, proj)
            self._unbind()
            drawn = time.perf_counter()
            image = self._read_fbo(fbo)
            fbo.release()
            if first:
                trace("render first frame ok")
                self._logged_paint = True
            self._frame = image
            self._frame_key = key
            self._log_cost(started, drawn, time.perf_counter())
            return image
        except Exception:
            log.exception("solar OpenGL paint failed")
            trace("render python exception (see arelis.log)")
            self._logged_paint = True
            self.gl_ok = False
            return None

    def _log_cost(self, started: float, drawn: float, done: float) -> None:
        """Mean GPU-frame cost every few seconds. Local file, nothing leaves."""
        perf = self._perf
        perf[0] += 1.0
        perf[1] += drawn - started
        perf[2] += done - drawn
        if perf[3] <= 0.0:
            perf[3] = done
            return
        window = done - perf[3]
        if window < _PERF_EVERY_S:
            return
        n = max(perf[0], 1.0)
        trace(
            f"frame cost {self._fb_w}x{self._fb_h} "
            f"draw {perf[1] / n * 1e3:.1f} ms  readback {perf[2] / n * 1e3:.1f} ms  "
            f"{n / window:.0f} gl fps"
        )
        perf[0] = perf[1] = perf[2] = 0.0
        perf[3] = done

    def _unbind(self) -> None:
        for vao in (
            self._sphere_vao,
            self._lod_vao,
            self._star_vao,
            self._glow_vao,
            self._ring_vao,
            self._orbit_vao,
            self._bead_vao,
            self._mag_vao,
            self._well_vao,
        ):
            if vao is not None:
                vao.release()
        if self._white is not None:
            self._white.release()

    def _set_far(self, prog: QOpenGLShaderProgram) -> None:
        self._uni(prog, "uFar", float(_FAR_M))

    def _uni(self, prog: QOpenGLShaderProgram, name: str, *values: object) -> None:
        """Scalars via glUniform*. setUniformValue(loc, 4e14) overflows a C int."""
        loc = int(prog.uniformLocation(name))
        if loc < 0:
            return
        if len(values) == 1:
            v = values[0]
            if isinstance(v, (QMatrix4x4, QVector3D)):
                prog.setUniformValue(loc, v)
                return
            if uniform_is_int(v):
                self.glUniform1i(loc, int(v))
                return
            self.glUniform1f(loc, float(v))
            return
        if len(values) == 2:
            self.glUniform2f(loc, float(values[0]), float(values[1]))
            return
        if len(values) == 4:
            self.glUniform4f(
                loc,
                float(values[0]),
                float(values[1]),
                float(values[2]),
                float(values[3]),
            )
            return
        raise TypeError(f"uniform {name} arity {len(values)}")

    def _cam_z(self, body: BodyView, eye: tuple[float, float, float], fz) -> float:
        return (
            (body.x - eye[0]) * fz[0]
            + (body.y - eye[1]) * fz[1]
            + (body.z - eye[2]) * fz[2]
        )

    def _draw_stars(self, view: QMatrix4x4, proj: QMatrix4x4) -> None:
        if self._prog_star is None or self._star_vao is None:
            return
        self.glDisable(_GL_DEPTH_TEST)
        self.glEnable(_GL_BLEND)
        self.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE)
        self._prog_star.bind()
        self._uni(self._prog_star, "uView", view)
        self._uni(self._prog_star, "uProj", proj)
        self._star_vao.bind()
        self.glDrawArrays(_GL_POINTS, 0, self._star_n)
        self._star_vao.release()
        self._prog_star.release()
        self.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE_MINUS_SRC_ALPHA)
        self.glDisable(_GL_BLEND)

    def _draw_body(
        self,
        panel: SolarPanel,
        body: BodyView,
        system,
        eye: tuple[float, float, float],
        sun_p: QVector3D,
        view: QMatrix4x4,
        proj: QMatrix4x4,
        fz,
    ) -> None:
        if self._prog_body is None or self._sphere_vao is None:
            return
        depth = max(self._cam_z(body, eye, fz), 1.0)
        true_px = panel._true_px(body.radius, depth)
        inspect = body.name == panel._inspect
        if body.name != "Sun" and not inspect and true_px < _SKIP_PX:
            return
        r = body.radius
        rel = QVector3D(body.x - eye[0], body.y - eye[1], body.z - eye[2])
        model = self._body_model(body, system, rel, r)
        mvp = proj * view * model
        hi = inspect or body.name == "Sun" or true_px >= _HI_PX
        want_tex = inspect or true_px >= _TEX_PX
        tex, has_map = self._tex(body.name) if want_tex else (self._white, 0)
        if tex is None:
            return
        tint = panel._tint_for(body.name, system)
        emissive = 1 if body.name == "Sun" else 0
        if body.kind == "asteroid":
            fill, wrap, limb = 0.38, 0.0, 1.45
        elif body.name in _GAS:
            fill, wrap, limb = 0.12, 0.22, 0.52
        else:
            fill, wrap, limb = _FILL, 0.12, 0.88
        if body.name == "Earth":
            try:
                from arelis.earth.runtime import get_earth

                zone = get_earth()
                if zone is not None and zone.active:
                    fill = 0.78
            except Exception:
                pass
        self._prog_body.bind()
        self._set_far(self._prog_body)
        self._uni(self._prog_body, "uMVP", mvp)
        self._uni(self._prog_body, "uModel", model)
        self._uni(self._prog_body, "uSunP", sun_p)
        self._uni(
            self._prog_body,
            "uTint",
            QVector3D(tint[0] / 255.0, tint[1] / 255.0, tint[2] / 255.0),
        )
        self._uni(self._prog_body, "uHasMap", int(has_map))
        self._uni(self._prog_body, "uEmissive", int(emissive))
        self._uni(self._prog_body, "uOcean", 1 if body.name == "Earth" else 0)
        self._uni(self._prog_body, "uGap", 1 if body.name != "Sun" else 0)
        self._uni(self._prog_body, "uRing", 0)
        self._uni(self._prog_body, "uRingR0", 0.0)
        self._uni(self._prog_body, "uRingR1", 1.0)
        self._uni(self._prog_body, "uCas0", 0.0)
        self._uni(self._prog_body, "uCas1", 0.0)
        self._uni(self._prog_body, "uFill", float(fill))
        self._uni(self._prog_body, "uWrap", float(wrap))
        self._uni(self._prog_body, "uLimb", float(limb))
        self._uni(self._prog_body, "uAlpha", 1.0)
        gran = 0.0
        tick = 0.0
        if body.name == "Sun":
            gran = min(1.0, max(0.0, (true_px - 200.0) / 140.0))
            tick = time.perf_counter() * 0.08
        self._uni(self._prog_body, "uGran", float(gran))
        close = 0.0
        if body.name == "Sun":
            from arelis.physics.star_look import star_flare

            close = 1.0 - star_flare(true_px, self._fb_h).unresolved
        self._uni(self._prog_body, "uClose", float(close))
        self._uni(self._prog_body, "uTime", float(tick))
        self.glActiveTexture(_GL_TEXTURE0)
        tex.bind()
        self._uni(self._prog_body, "uAlbedo", 0)
        self._draw_sphere(hi=hi)
        tex.release()
        self._prog_body.release()
        atmo = _ATMO.get(body.name)
        if atmo is not None and true_px >= _ATMO_PX:
            rgb, scale, gain = atmo
            shell = self._body_model(body, system, rel, r * scale)
            self._draw_atmo(shell, sun_p, view, proj, rgb, gain)
        if body.name == "Saturn" and true_px >= 3.0:
            self._draw_rings(rel, r, sun_p, view, proj)

    def _body_model(self, body, system, rel: QVector3D, r: float) -> QMatrix4x4:
        model = QMatrix4x4()
        model.translate(rel)
        model = model * self._body_spin(body, system)
        model.scale(r)
        return model

    def _body_spin(self, body, system) -> QMatrix4x4:
        geo = QMatrix4x4(
            0.0,
            0.0,
            1.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
        )
        jd = spin_jd(system.epoch_jd, system.t)
        if body.name == "Earth":
            # Same GMST+obliquity as software globes and Earth-zone overlays.
            # Do not use the generic mesh map — that parks Greenwich at u=0.
            return earth_spin_matrix(jd)
        moon = system.nbody.find("Moon")
        earth = system.nbody.find("Earth")
        frame = body_frame_ecliptic(
            body.name,
            jd,
            moon=(moon.x, moon.y, moon.z) if moon is not None else None,
            earth=(earth.x, earth.y, earth.z) if earth is not None else None,
        )
        if frame is not None:
            return _frame_matrix(frame) * geo
        pole = QMatrix4x4()
        pole.rotate(90.0, 1.0, 0.0, 0.0)
        return pole

    def _draw_atmo(
        self,
        model: QMatrix4x4,
        sun_p: QVector3D,
        view: QMatrix4x4,
        proj: QMatrix4x4,
        rgb: tuple[float, float, float],
        gain: float,
    ) -> None:
        if self._prog_atmo is None or self._sphere_vao is None:
            return
        mvp = proj * view * model
        self.glEnable(_GL_BLEND)
        self.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE)
        self.glDepthMask(_GL_FALSE)
        self.glCullFace(_GL_FRONT)
        self._prog_atmo.bind()
        self._set_far(self._prog_atmo)
        self._uni(self._prog_atmo, "uMVP", mvp)
        self._uni(self._prog_atmo, "uModel", model)
        self._uni(self._prog_atmo, "uSunP", sun_p)
        self._uni(self._prog_atmo, "uAtmo", QVector3D(*rgb))
        self._uni(self._prog_atmo, "uGain", float(gain))
        self._draw_sphere(hi=True)
        self._prog_atmo.release()
        self.glCullFace(_GL_BACK)
        self.glDepthMask(_GL_TRUE)
        self.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE_MINUS_SRC_ALPHA)
        self.glDisable(_GL_BLEND)

    def _draw_rings(
        self,
        rel: QVector3D,
        r: float,
        sun_p: QVector3D,
        view: QMatrix4x4,
        proj: QMatrix4x4,
    ) -> None:
        if self._prog_body is None or self._ring_vao is None or self._white is None:
            return
        model = QMatrix4x4()
        model.translate(rel)
        xx, yx, zx = saturn_ring_axes()
        model *= QMatrix4x4(
            xx[0],
            yx[0],
            zx[0],
            0.0,
            xx[1],
            yx[1],
            zx[1],
            0.0,
            xx[2],
            yx[2],
            zx[2],
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
        )
        model.scale(r)
        mvp = proj * view * model
        self.glDisable(_GL_CULL_FACE)
        self.glEnable(_GL_DEPTH_TEST)
        self.glEnable(_GL_BLEND)
        self.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE_MINUS_SRC_ALPHA)
        self.glDepthMask(_GL_FALSE)
        self._prog_body.bind()
        self._set_far(self._prog_body)
        self._uni(self._prog_body, "uMVP", mvp)
        self._uni(self._prog_body, "uModel", model)
        self._uni(self._prog_body, "uSunP", sun_p)
        self._uni(self._prog_body, "uTint", QVector3D(0.85, 0.78, 0.62))
        self._uni(self._prog_body, "uHasMap", 0)
        self._uni(self._prog_body, "uEmissive", 0)
        self._uni(self._prog_body, "uOcean", 0)
        self._uni(self._prog_body, "uGap", 0)
        self._uni(self._prog_body, "uRing", 1)
        rs = max(r, 1.0)
        self._uni(self._prog_body, "uRingR0", SATURN_RING_INNER_M / rs)
        self._uni(self._prog_body, "uRingR1", SATURN_RING_OUTER_M / rs)
        self._uni(self._prog_body, "uCas0", SATURN_CASSINI_INNER_M / rs)
        self._uni(self._prog_body, "uCas1", SATURN_CASSINI_OUTER_M / rs)
        self._uni(self._prog_body, "uFill", 0.18)
        self._uni(self._prog_body, "uWrap", 0.2)
        self._uni(self._prog_body, "uLimb", 1.0)
        self._uni(self._prog_body, "uAlpha", 0.62)
        self._uni(self._prog_body, "uGran", 0.0)
        self._uni(self._prog_body, "uClose", 0.0)
        self._uni(self._prog_body, "uTime", 0.0)
        self._white.bind()
        self._ring_vao.bind()
        self.glDrawArrays(_GL_TRIANGLE_STRIP, 0, self._ring_n)
        self._ring_vao.release()
        self._white.release()
        self._prog_body.release()
        self.glDepthMask(_GL_TRUE)
        self.glDisable(_GL_BLEND)
        self.glEnable(_GL_CULL_FACE)

    def _draw_glow(
        self,
        system,
        eye: tuple[float, float, float],
        sun_p: QVector3D,
        view: QMatrix4x4,
        proj: QMatrix4x4,
        fy,
        fx,
    ) -> None:
        """Lens diffraction + K-corona. Sized in pixels, not a viewport fill."""
        if self._prog_glow is None or self._glow_vao is None:
            return
        sun = system.nbody.find("Sun")
        if sun is None:
            return
        depth = float(sun_p.length())
        if depth < 1.0:
            return
        rgb = (255, 236, 210)
        if abs(system.future_gyr) > 1e-6:
            rgb = sun_rgb(sample(system.future_gyr))
        from arelis.physics.star_look import angular_px, star_flare

        sun_px = angular_px(sun.radius, depth, self._fb_h, self._panel._fov_y())
        look = star_flare(sun_px, self._fb_h)
        extent_px = look.extent_px
        extent = 2.0 * extent_px / max(float(self._fb_h), 1.0)
        if look.unresolved > 0.45:
            extent = min(extent, 0.055)
        else:
            extent = min(extent, 0.96)
        aspect = float(self._fb_h) / max(float(self._fb_w), 1.0)
        clip = proj * view
        ndc = clip.map(sun_p)
        self.glDisable(_GL_CULL_FACE)
        self.glDisable(_GL_DEPTH_TEST)
        self.glDepthMask(_GL_FALSE)
        self.glEnable(_GL_BLEND)
        self.glBlendFunc(_GL_ONE, _GL_ONE)
        self._prog_glow.bind()
        self._uni(self._prog_glow, "uSunNdc", float(ndc.x()), float(ndc.y()))
        self._uni(self._prog_glow, "uExtent", float(extent))
        self._uni(self._prog_glow, "uAspect", float(aspect))
        self._uni(
            self._prog_glow,
            "uColor",
            QVector3D(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0),
        )
        pole = sun_pole_ecliptic()
        self._uni(
            self._prog_glow,
            "uPole",
            pole[0] * fx[0] + pole[1] * fx[1] + pole[2] * fx[2],
            pole[0] * fy[0] + pole[1] * fy[1] + pole[2] * fy[2],
        )
        self._uni(self._prog_glow, "uDisc", float(look.disc_px / max(extent_px, 1e-3)))
        self._uni(self._prog_glow, "uClose", float(1.0 - look.unresolved))
        self._uni(self._prog_glow, "uNeedle", float(0.48 / max(extent_px, 1.0)))
        sigma_px = max(look.bloom_px - look.disc_px, 2.8)
        self._uni(self._prog_glow, "uBloom", float(sigma_px / max(extent_px, 1.0)))
        self._uni(self._prog_glow, "uCore", float(1.55 / max(extent_px, 1.0)))
        self._uni(self._prog_glow, "uLen", float(look.spike_px / max(extent_px, 1.0)))
        self._uni(self._prog_glow, "uGain", float(look.spike_gain))
        self._glow_vao.bind()
        self.glDrawArrays(_GL_TRIANGLE_STRIP, 0, 4)
        self._glow_vao.release()
        self._prog_glow.release()
        self.glDepthMask(_GL_TRUE)
        self.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE_MINUS_SRC_ALPHA)
        self.glDisable(_GL_BLEND)
        self.glEnable(_GL_DEPTH_TEST)
        self.glEnable(_GL_CULL_FACE)
        self.glCullFace(_GL_BACK)

    def _draw_loops(
        self,
        system,
        eye: tuple[float, float, float],
        sun_p: QVector3D,
        view: QMatrix4x4,
        proj: QMatrix4x4,
    ) -> None:
        """Off-limb prominences. Magnetic overlay brightens the dipole sketch."""
        from arelis.physics.corona import LOOP_MIN_PX, loops, off_limb_segments

        mag = bool(system.overlay.show_magnetic)
        if self._prog_line is None or not mag:
            return
        sun = system.nbody.find("Sun")
        if sun is None:
            return
        depth = max(float(sun_p.length()), 1.0)
        if self._panel._true_px(sun.radius, depth) < LOOP_MIN_PX:
            return
        jd = spin_jd(system.epoch_jd, system.t)
        ox = sun.x - eye[0]
        oy = sun.y - eye[1]
        oz = sun.z - eye[2]
        quiet: list[np.ndarray] = []
        hot: list[np.ndarray] = []
        sun_eye = np.array((ox, oy, oz), dtype=np.float64)
        for loop in loops(sun.radius, jd, time.perf_counter()):
            segs = off_limb_segments(loop, sun.radius, sun_eye=sun_eye)
            if segs.shape[0] < 2:
                continue
            segs = segs + np.array((ox, oy, oz), dtype=np.float64)
            if loop.flare > 0.22:
                hot.append(segs)
            else:
                quiet.append(segs)
        self.glEnable(_GL_DEPTH_TEST)
        self.glDepthMask(_GL_FALSE)
        self.glEnable(_GL_BLEND)
        self.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE)
        if quiet:
            a = 0.55 if mag else 0.28
            self._stroke_loops(np.vstack(quiet), view, proj, (1.0, 0.42, 0.08, a))
        if hot:
            a = 0.95 if mag else 0.55
            self._stroke_loops(np.vstack(hot), view, proj, (1.0, 0.78, 0.22, a))
        self.glDepthMask(_GL_TRUE)
        self.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE_MINUS_SRC_ALPHA)
        self.glDisable(_GL_BLEND)

    def _stroke_loops(
        self,
        pts: np.ndarray,
        view: QMatrix4x4,
        proj: QMatrix4x4,
        color: tuple[float, float, float, float],
    ) -> None:
        arr = np.asarray(pts, dtype=np.float32)
        if arr.shape[0] < 2:
            return
        if self._loop_vao is None or self._loop_buf is None:
            self._loop_vao, self._loop_buf = self._lines(arr.nbytes)
            self._loop_cap = max(int(arr.nbytes), 12)
        self._loop_cap = self._upload(self._loop_buf, arr, self._loop_cap)
        self._prog_line.bind()
        self._set_far(self._prog_line)
        self._uni(self._prog_line, "uView", view)
        self._uni(self._prog_line, "uProj", proj)
        self._uni(self._prog_line, "uEye", QVector3D(0.0, 0.0, 0.0))
        self._uni(self._prog_line, "uColor", *color)
        self._loop_vao.bind()
        self.glDrawArrays(_GL_LINES, 0, int(arr.shape[0]))
        self._loop_vao.release()
        self._prog_line.release()

    def _orbit_drawn(self, views, eye, fz):
        inspect = self._panel._inspect
        close = False
        if inspect:
            host = next((b for b in views if b.name == inspect), None)
            if host is not None:
                depth = max(self._cam_z(host, eye, fz), 1.0)
                close = self._panel._true_px(host.radius, depth) >= 48.0
        return [
            b
            for b in views
            if not b.tracer
            and b.name != "Sun"
            and b.kind in {"planet", "asteroid", "moon"}
            and (b.kind != "moon" or b.name == inspect or (close and b.parent == inspect))
            and not (close and b.parent != inspect)
        ]

    def _rebuild_orbits(self, system, drawn) -> None:
        """Rings in parent-relative metres, so a stale rebuild still tracks its host."""
        from arelis.physics.elements import osculating, position_at_true_anomaly

        pts: list[float] = []
        groups: list[tuple[str, str | None, int, int]] = []
        for body in drawn:
            r, v, mu, about, _origin = system.about(body)
            el = osculating(r, v, mu)
            if el is None or el.e >= 0.95:
                continue
            steps = 96 if body.kind == "asteroid" else 160
            start = len(pts) // 3
            for i in range(steps):
                pts.extend(position_at_true_anomaly(el, 2.0 * math.pi * i / steps))
            groups.append((body.name, about, start, steps))
        self._orbit_local = (
            np.asarray(pts, dtype=np.float64).reshape(-1, 3) if pts else None
        )
        self._orbit_groups = groups
        self._orbit_n = 0 if self._orbit_local is None else int(
            self._orbit_local.shape[0]
        )
        self._orbit_scratch = (
            np.empty((self._orbit_n, 3), dtype=np.float32) if self._orbit_n else None
        )

    def _draw_orbits(
        self, system, views, eye, fz, view: QMatrix4x4, proj: QMatrix4x4
    ) -> None:
        if self._prog_line is None:
            return
        inspect = self._panel._inspect
        drawn = self._orbit_drawn(views, eye, fz)
        key = (inspect or "", tuple(b.name for b in drawn))
        now = time.perf_counter()
        moved = float(system.t) != self._orbit_t
        if key != self._orbit_key or (
            moved and now - self._orbit_built >= _ORBIT_REBUILD_S
        ):
            self._rebuild_orbits(system, drawn)
            self._orbit_key = key
            self._orbit_t = float(system.t)
            self._orbit_built = now
        local = self._orbit_local
        scratch = self._orbit_scratch
        if local is None or scratch is None or self._orbit_n < 2:
            return
        # World float32 at Neptune loses moon rings, so the eye comes off in
        # float64 here. Each host's offset is constant across its own ring.
        offsets: dict[str | None, np.ndarray] = {}
        for _name, about, start, count in self._orbit_groups:
            if about not in offsets:
                host = system.nbody.find(about) if about else None
                offsets[about] = (
                    np.array(
                        (host.x - eye[0], host.y - eye[1], host.z - eye[2]),
                        dtype=np.float64,
                    )
                    if host is not None
                    else -np.asarray(eye, dtype=np.float64)
                )
            scratch[start : start + count] = local[start : start + count] + offsets[about]
        if self._orbit_vao is None or self._orbit_buf is None:
            self._orbit_vao, self._orbit_buf = self._lines(scratch.nbytes)
            self._orbit_cap = max(int(scratch.nbytes), 12)
        self._orbit_cap = self._upload(self._orbit_buf, scratch, self._orbit_cap)
        self.glEnable(_GL_DEPTH_TEST)
        self.glDepthMask(_GL_FALSE)
        self.glEnable(_GL_BLEND)
        self.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE)
        self.glDisable(_GL_CULL_FACE)
        try:
            self.glLineWidth(2.0)
        except Exception:
            pass
        self._prog_line.bind()
        self._set_far(self._prog_line)
        self._uni(self._prog_line, "uView", view)
        self._uni(self._prog_line, "uProj", proj)
        self._uni(self._prog_line, "uEye", QVector3D(0.0, 0.0, 0.0))
        self._orbit_vao.bind()
        self._uni(self._prog_line, "uColor", 0.78, 0.86, 1.0, 0.42)
        for _name, _about, start, count in self._orbit_groups:
            self.glDrawArrays(_GL_LINE_LOOP, start, count)
        self._orbit_vao.release()
        if inspect:
            self._draw_orbit_fill(inspect, offsets, view, proj)
        self._prog_line.release()
        try:
            self.glLineWidth(1.0)
        except Exception:
            pass
        self._draw_orbit_beads(system, drawn, eye, view, proj)
        self.glEnable(_GL_CULL_FACE)
        self.glCullFace(_GL_BACK)
        self.glDepthMask(_GL_TRUE)
        self.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE_MINUS_SRC_ALPHA)
        self.glDisable(_GL_BLEND)

    def _draw_orbit_fill(
        self,
        inspect: str,
        offsets: dict[str | None, np.ndarray],
        view: QMatrix4x4,
        proj: QMatrix4x4,
    ) -> None:
        """Faint Kepler pie in the orbital plane. Skip when the ellipse fills the view."""
        local = self._orbit_local
        if local is None or self._prog_line is None:
            return
        hit = next((g for g in self._orbit_groups if g[0] == inspect), None)
        if hit is None:
            return
        _name, about, start, count = hit
        ring = local[start : start + count]
        origin = offsets.get(about)
        if origin is None or ring.shape[0] < 3:
            return
        span = float(np.linalg.norm(ring[0]))
        depth = max(float(np.linalg.norm(origin)), 1.0)
        if self._panel._true_px(span, depth) > 0.72 * max(self._fb_h, 1):
            return
        fan = np.empty((count + 2, 3), dtype=np.float32)
        fan[0] = origin
        fan[1 : count + 1] = ring + origin
        fan[-1] = fan[1]
        if self._fill_vao is None or self._fill_buf is None:
            self._fill_vao, self._fill_buf = self._lines(fan.nbytes)
            self._fill_cap = max(int(fan.nbytes), 12)
        self._fill_cap = self._upload(self._fill_buf, fan, self._fill_cap)
        self._uni(self._prog_line, "uColor", 0.45, 0.70, 1.0, 0.045)
        self._fill_vao.bind()
        self.glDrawArrays(_GL_TRIANGLE_FAN, 0, int(fan.shape[0]))
        self._fill_vao.release()

    def _draw_orbit_beads(self, system, drawn, eye, view: QMatrix4x4, proj: QMatrix4x4) -> None:
        if self._prog_bead is None:
            return
        from arelis.physics.elements import (
            BEAD_LAP_S,
            bead_true_anomalies,
            osculating,
            position_at_true_anomaly,
        )

        packed: list[float] = []
        phase = (time.perf_counter() / BEAD_LAP_S) * 2.0 * math.pi
        for body in drawn:
            r, v, mu, _about, origin = system.about(body)
            el = osculating(r, v, mu)
            if el is None or el.e >= 0.95:
                continue
            for k, nu in enumerate(
                bead_true_anomalies(el.true_anomaly, phase=phase)
            ):
                px, py, pz = position_at_true_anomaly(el, nu)
                packed.extend(
                    (
                        origin[0] + px - eye[0],
                        origin[1] + py - eye[1],
                        origin[2] + pz - eye[2],
                        1.0 if k == 0 else 0.42,
                    )
                )
        if not packed:
            return
        arr = np.asarray(packed, dtype=np.float32)
        if self._bead_vao is None or self._bead_buf is None:
            self._bead_vao, self._bead_buf = self._points4(arr.nbytes)
            self._bead_cap = max(int(arr.nbytes), 16)
        self._bead_cap = self._upload(self._bead_buf, arr, self._bead_cap)
        self._prog_bead.bind()
        self._set_far(self._prog_bead)
        self._uni(self._prog_bead, "uView", view)
        self._uni(self._prog_bead, "uProj", proj)
        self._uni(self._prog_bead, "uEye", QVector3D(0.0, 0.0, 0.0))
        self._uni(self._prog_bead, "uColor", 0.85, 0.95, 1.0, 0.95)
        self._bead_vao.bind()
        self.glDrawArrays(_GL_POINTS, 0, len(packed) // 4)
        self._bead_vao.release()
        self._prog_bead.release()

    def _draw_bubble(
        self,
        rel: QVector3D,
        radius: float,
        view: QMatrix4x4,
        proj: QMatrix4x4,
        sun_p: QVector3D,
        rgb: tuple[float, float, float],
        gain: float,
        *,
        hi: bool,
    ) -> None:
        if self._prog_atmo is None:
            return
        model = QMatrix4x4()
        model.translate(rel)
        model.scale(float(radius))
        mvp = proj * view * model
        self._prog_atmo.bind()
        self._set_far(self._prog_atmo)
        self._uni(self._prog_atmo, "uMVP", mvp)
        self._uni(self._prog_atmo, "uModel", model)
        self._uni(self._prog_atmo, "uSunP", sun_p)
        self._uni(self._prog_atmo, "uAtmo", QVector3D(*rgb))
        self._uni(self._prog_atmo, "uGain", float(gain))
        self._draw_sphere(hi=hi)
        self._prog_atmo.release()

    def _draw_wells(
        self, system, views, eye, fz, sun_p: QVector3D, view: QMatrix4x4, proj: QMatrix4x4
    ) -> None:
        from arelis.physics.elements import ISO_G_FACTORS, hill_radius, osculating

        inspect = self._panel._inspect
        inspect_body = system.nbody.find(inspect) if inspect else None
        self.glEnable(_GL_DEPTH_TEST)
        self.glDepthMask(_GL_FALSE)
        self.glEnable(_GL_BLEND)
        self.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE)
        self.glDisable(_GL_CULL_FACE)
        gains = (0.28, 0.16, 0.09)
        for body in views:
            if body.tracer or body.kind in {"probe", "lagrange"}:
                continue
            wanted = body.kind in {"star", "planet"} or (
                inspect_body is not None and body.name == inspect_body.name
            )
            if not wanted:
                continue
            depth = max(self._cam_z(body, eye, fz), 1.0)
            rel = QVector3D(body.x - eye[0], body.y - eye[1], body.z - eye[2])
            for k, gain in zip(ISO_G_FACTORS, gains, strict=True):
                rad = k * body.radius
                px = self._panel._true_px(rad, depth)
                if px < 3.0 or px > 80.0:
                    continue
                self._draw_bubble(
                    rel, rad, view, proj, sun_p, (1.0, 0.72, 0.28), gain, hi=px >= 28.0
                )
            r, v, mu, _about, _origin = system.about(body)
            el = osculating(r, v, mu)
            if el is None or body.mass <= 0.0 or mu <= 0.0:
                continue
            hill = hill_radius(float(el.a), body.mass, mu / G_SI)
            if hill <= 8.0 * body.radius:
                continue
            px = self._panel._true_px(hill, depth)
            if px < 4.0 or px > 72.0:
                continue
            self._draw_bubble(
                rel, hill, view, proj, sun_p, (1.0, 0.52, 0.16), 0.20, hi=px >= 22.0
            )
        if inspect_body is not None:
            self._draw_well_mesh(system, inspect_body, eye, view, proj)
        self.glEnable(_GL_CULL_FACE)
        self.glCullFace(_GL_BACK)
        self.glDepthMask(_GL_TRUE)
        self.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE_MINUS_SRC_ALPHA)
        self.glDisable(_GL_BLEND)

    def _draw_well_mesh(self, system, body, eye, view: QMatrix4x4, proj: QMatrix4x4) -> None:
        from arelis.physics.elements import well_grid, well_line_indices

        _r, _v, mu, _about, _origin = system.about(body)
        key = (body.name, round(float(mu), 3), round(body.radius, 1))
        if key != self._well_key:
            pts = well_grid(mu, body.radius, n=20)
            self._well_local = np.asarray(pts, dtype=np.float64)
            self._well_idx = np.asarray(well_line_indices(20), dtype=np.uint32)
            self._well_n = int(self._well_idx.size)
            self._well_key = key
        local = self._well_local
        idx = self._well_idx
        if local is None or idx is None or self._well_n < 2 or self._prog_line is None:
            return
        offset = np.array(
            (body.x - eye[0], body.y - eye[1], body.z - eye[2]), dtype=np.float64
        )
        world = (local + offset).astype(np.float32)
        self._well_vao, self._well_buf, self._well_ibo, self._well_cap = self._indexed(
            world,
            idx,
            self._well_vao,
            self._well_buf,
            self._well_ibo,
            self._well_cap,
        )
        self._prog_line.bind()
        self._set_far(self._prog_line)
        self._uni(self._prog_line, "uView", view)
        self._uni(self._prog_line, "uProj", proj)
        self._uni(self._prog_line, "uEye", QVector3D(0.0, 0.0, 0.0))
        self._uni(self._prog_line, "uColor", 1.0, 0.70, 0.22, 0.22)
        self._well_vao.bind()
        self.glDrawElements(
            int(_GL_LINES), self._well_n, int(_GL_UNSIGNED_INT), gl_offset(0)
        )
        self._well_vao.release()
        self._prog_line.release()

    def _draw_magnetosphere(
        self, system, eye, fz, _sun_p: QVector3D, view: QMatrix4x4, proj: QMatrix4x4
    ) -> None:
        inspect = self._panel._inspect
        if inspect and inspect != "Earth":
            return
        earth = system.nbody.find("Earth")
        sun = system.nbody.find("Sun")
        if earth is None or self._prog_line is None:
            return
        depth = max(self._cam_z(earth, eye, fz), 1.0)
        if self._panel._true_px(earth.radius * 15.0, depth) < 6.0:
            return
        from arelis.physics.magnetosphere import (
            dipole_L_polylines,
            dipole_segments,
            earth_standoff_m,
            shue_meridians,
            shue_surface,
            sunward_basis,
        )
        from arelis.physics.parker import dynamic_pressure_npa

        if sun is not None:
            sl = math.hypot(sun.x - earth.x, sun.y - earth.y, sun.z - earth.z) or AU_M
            p_npa = dynamic_pressure_npa(sl)
            ux, uy, uz = sunward_basis(
                (earth.x, earth.y, earth.z), (sun.x, sun.y, sun.z)
            )
        else:
            p_npa = dynamic_pressure_npa(AU_M)
            ux, uy, uz = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
        r0_m, _r0_re, alpha = earth_standoff_m(p_npa, earth.radius)
        key = (
            round(r0_m, -4),
            round(alpha, 3),
            round(ux[0], 3),
            round(ux[1], 3),
            round(ux[2], 3),
        )
        if key != self._mag_key:
            verts, idx = shue_surface(r0_m, alpha, ux, uy, uz)
            self._mag_local = verts
            self._mag_idx = idx
            self._mag_n = int(idx.size)
            mer = dipole_segments(
                [
                    np.asarray(line, dtype=np.float64)
                    for line in shue_meridians(r0_m, alpha, ux, uy, uz, n_theta=48, n_phi=12)
                ]
            )
            dip = dipole_segments(dipole_L_polylines(earth.radius, ux, uy, uz))
            if mer is not None and dip is not None:
                self._shue_n = int(mer.shape[0])
                self._dip_local = np.vstack((mer, dip))
            elif mer is not None:
                self._shue_n = int(mer.shape[0])
                self._dip_local = mer
            else:
                self._shue_n = 0
                self._dip_local = dip
            self._mag_key = key
        local = self._mag_local
        idx = self._mag_idx
        offset = np.array(
            (earth.x - eye[0], earth.y - eye[1], earth.z - eye[2]), dtype=np.float64
        )
        pulse = 0.72 + 0.28 * (0.5 + 0.5 * math.sin(time.perf_counter() * 0.11))
        r0_px = self._panel._true_px(r0_m, depth)
        fill = (
            local is not None
            and idx is not None
            and self._mag_n >= 3
            and 12.0 <= r0_px <= 96.0
        )
        dip = self._dip_local
        if self._prog_line is None:
            return
        if not fill and (dip is None or dip.shape[0] < 2):
            return
        self.glEnable(_GL_DEPTH_TEST)
        self.glDepthMask(_GL_FALSE)
        self.glEnable(_GL_BLEND)
        self.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE)
        self.glDisable(_GL_CULL_FACE)
        self._prog_line.bind()
        self._set_far(self._prog_line)
        self._uni(self._prog_line, "uView", view)
        self._uni(self._prog_line, "uProj", proj)
        self._uni(self._prog_line, "uEye", QVector3D(0.0, 0.0, 0.0))
        if fill:
            world = (local + offset).astype(np.float32)
            self._mag_vao, self._mag_buf, self._mag_ibo, self._mag_cap = self._indexed(
                world,
                idx,
                self._mag_vao,
                self._mag_buf,
                self._mag_ibo,
                self._mag_cap,
            )
            self._uni(self._prog_line, "uColor", 0.35, 0.78, 1.0, 0.08 * pulse)
            self._mag_vao.bind()
            self.glDrawElements(
                int(_GL_TRIANGLES), self._mag_n, int(_GL_UNSIGNED_INT), gl_offset(0)
            )
            self._mag_vao.release()
        if dip is not None and dip.shape[0] >= 2:
            dworld = (dip + offset).astype(np.float32)
            if self._dip_vao is None or self._dip_buf is None:
                self._dip_vao, self._dip_buf = self._lines(dworld.nbytes)
                self._dip_cap = max(int(dworld.nbytes), 12)
            self._dip_cap = self._upload(self._dip_buf, dworld, self._dip_cap)
            try:
                self.glLineWidth(1.5)
            except Exception:
                pass
            self._dip_vao.bind()
            shue_n = min(int(self._shue_n), int(dworld.shape[0]))
            if shue_n >= 2:
                self._uni(self._prog_line, "uColor", 0.35, 0.78, 1.0, 0.55 * pulse)
                self.glDrawArrays(_GL_LINES, 0, shue_n)
            rest = int(dworld.shape[0]) - shue_n
            if rest >= 2:
                self._uni(self._prog_line, "uColor", 0.45, 0.88, 1.0, 0.42 * pulse)
                self.glDrawArrays(_GL_LINES, shue_n, rest)
            self._dip_vao.release()
            try:
                self.glLineWidth(1.0)
            except Exception:
                pass
        self._prog_line.release()
        self.glEnable(_GL_CULL_FACE)
        self.glCullFace(_GL_BACK)
        self.glDepthMask(_GL_TRUE)
        self.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE_MINUS_SRC_ALPHA)
        self.glDisable(_GL_BLEND)

    def _lines(self, capacity: int) -> tuple[QOpenGLVertexArrayObject, QOpenGLBuffer]:
        vao = QOpenGLVertexArrayObject()
        vao.create()
        vao.bind()
        buf = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        buf.create()
        buf.bind()
        room = max(int(capacity), 12)
        buf.allocate(bytes(room), room)
        self._attrib(0, 3, 12, 0)
        vao.release()
        buf.release()
        self._keep.append(vao)
        self._keep.append(buf)
        return vao, buf

    def _points4(self, capacity: int) -> tuple[QOpenGLVertexArrayObject, QOpenGLBuffer]:
        vao = QOpenGLVertexArrayObject()
        vao.create()
        vao.bind()
        buf = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        buf.create()
        buf.bind()
        room = max(int(capacity), 16)
        buf.allocate(bytes(room), room)
        self._attrib(0, 3, 16, 0)
        self._attrib(1, 1, 16, 12)
        vao.release()
        buf.release()
        self._keep.append(vao)
        self._keep.append(buf)
        return vao, buf

    def _indexed(
        self,
        verts: np.ndarray,
        idx: np.ndarray,
        vao: QOpenGLVertexArrayObject | None,
        vbo: QOpenGLBuffer | None,
        ibo: QOpenGLBuffer | None,
        cap: int,
    ) -> tuple[QOpenGLVertexArrayObject, QOpenGLBuffer, QOpenGLBuffer, int]:
        if vao is None or vbo is None or ibo is None:
            vao = QOpenGLVertexArrayObject()
            vao.create()
            vao.bind()
            vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            vbo.create()
            vbo.bind()
            room = max(int(verts.nbytes), 12)
            vbo.allocate(verts.tobytes(), room)
            ibo = QOpenGLBuffer(QOpenGLBuffer.Type.IndexBuffer)
            ibo.create()
            ibo.bind()
            ibo.allocate(idx.tobytes(), int(idx.nbytes))
            self._attrib(0, 3, 12, 0)
            vao.release()
            vbo.release()
            self._keep.extend((vao, vbo, ibo))
            return vao, vbo, ibo, room
        cap = self._upload(vbo, verts, cap)
        return vao, vbo, ibo, cap

    def _upload(self, buf: QOpenGLBuffer, arr: np.ndarray, cap: int) -> int:
        """Stream into a live VBO. allocate() every frame is a driver realloc."""
        data = arr.tobytes()
        size = len(data)
        buf.bind()
        if size > cap:
            buf.allocate(data, size)
            cap = size
        else:
            try:
                buf.write(0, data, size)
            except (AttributeError, TypeError):
                # Losing the substream is a stall, not a broken frame. Do not
                # let a binding surprise drop the whole GPU path to software.
                buf.allocate(data, size)
                cap = size
        buf.release()
        return cap

    def _draw_tracers(self, tracers, eye, view: QMatrix4x4, proj: QMatrix4x4) -> None:
        if self._prog_line is None:
            return
        pts = []
        for t in tracers[:2000]:
            pts.extend((t.x - eye[0], t.y - eye[1], t.z - eye[2]))
        if not pts:
            return
        arr = np.asarray(pts, dtype=np.float32)
        if self._tracer_vao is None or self._tracer_buf is None:
            self._tracer_vao, self._tracer_buf = self._lines(arr.nbytes)
            self._tracer_cap = max(int(arr.nbytes), 12)
        self._tracer_cap = self._upload(self._tracer_buf, arr, self._tracer_cap)
        self.glDisable(_GL_DEPTH_TEST)
        self.glEnable(_GL_BLEND)
        self.glBlendFunc(_GL_SRC_ALPHA, _GL_ONE)
        self._prog_line.bind()
        self._set_far(self._prog_line)
        self._uni(self._prog_line, "uView", view)
        self._uni(self._prog_line, "uProj", proj)
        self._uni(self._prog_line, "uEye", QVector3D(0.0, 0.0, 0.0))
        self._uni(self._prog_line, "uColor", 0.7, 0.72, 0.8, 0.35)
        self._tracer_vao.bind()
        self.glDrawArrays(_GL_POINTS, 0, len(pts) // 3)
        self._tracer_vao.release()
        self._prog_line.release()
        self.glDisable(_GL_BLEND)
        self.glEnable(_GL_DEPTH_TEST)
