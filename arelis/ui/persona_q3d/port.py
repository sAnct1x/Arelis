# ruff: noqa: E501  (GLSL and QML templates read best unwrapped)
"""Build the Quick 3D aether scene from a v14k export (tools/avatar_q3d_export.py).

Translation rules, three.js ShaderMaterial -> Quick 3D unshaded CustomMaterial:
  * three built-ins become Quick 3D ones through #defines (modelMatrix -> MODEL_MATRIX, ...);
  * attributes become #defines onto the Quick 3D vertex slots chosen per layer (SPECS);
  * uniforms become QML properties of the same name (arrays are split into uName0..N);
  * GPU skinning (aether.js skinPoint, three skinning chunks) uses BONE_TRANSFORMS, with the
    three bind matrix folded into each Skin's inverse bind poses;
  * blending, culling and depth flags map onto the CustomMaterial properties.
The materials that aether.js builds from MeshBasicMaterial (the interior fills, hair cut-outs,
card fills) and the PointsMaterial galaxy are written out here by hand from their aether.js
source, since three generates their shaders.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

DEFAULT_SCENE = Path("/workspace/team/avatar-qq3d/scene")

FILL_MESH = "VERTEX=position;UV0=uv;JOINTS=skinIndex;WEIGHTS=skinWeight"  # fills need no shell attributes (teeth/tongue lack aCav)
MESH = "VERTEX=position;NORMAL=normal;UV0=uv;UV1=aCav,aCavF;TANGENT=aHand,aWr,aElb;JOINTS=skinIndex;WEIGHTS=skinWeight"
ATTR_SLOT = {  # three attribute -> Quick 3D expression (vertex stage)
    "position": "VERTEX",
    "normal": "NORMAL",
    "uv": "UV0",
    "aCav": "UV1.x",
    "aCavF": "UV1.y",
    "aHand": "TANGENT.x",
    "aWr": "TANGENT.y",
    "aElb": "TANGENT.z",
    "skinIndex": "vec4(JOINTS)",
    "skinWeight": "WEIGHTS",
    "sIdx": "vec4(JOINTS)",
    "sW": "WEIGHTS",
    "seed": "UV0.x",
    "fx": "COLOR",
    "prm": "COLOR",
    "u": "UV0.x",
    "side": "UV0.y",
    "kind": "UV1",
}
SPEC_OF = {  # attribute -> spec fragment for LayerGeometry
    "sIdx": "JOINTS=sIdx",
    "sW": "WEIGHTS=sW",
    "seed": "UV0=seed",
    "fx": "COLOR=fx",
    "prm": "COLOR=prm",
    "kind": "UV1=kind",
    "normal": "NORMAL=normal",
    "uv": "UV0=uv",
}
SKIP_UNIFORMS = {"boneTex", "bindM", "bindMInv", "uModel"}
GLSL_QML = {
    "float": "real",
    "int": "int",
    "bool": "bool",
    "vec2": "vector2d",
    "vec3": "vector3d",
    "vec4": "vector4d",
    "mat4": "matrix4x4",
    "sampler2D": "TextureInput",
}

COMMON = """#define modelMatrix MODEL_MATRIX
#define viewMatrix VIEW_MATRIX
#define projectionMatrix PROJECTION_MATRIX
#define modelViewMatrix (VIEW_MATRIX * MODEL_MATRIX)
#define cameraPosition CAMERA_POSITION
#define texture2D texture
"""
VERT_PRE = (
    COMMON
    + """#define gl_Position POSITION
// aether.js skinPoint: bindM and the bone inverse live in the Skin's inverse bind poses, so the
// bone transform maps the bind-space point straight to world space (uModel * bindMInv is identity).
vec3 skinPoint(vec3 p, vec4 si, vec4 sw) { vec4 b = vec4(p, 1.0);
  vec4 s = BONE_TRANSFORMS[int(si.x)] * b * sw.x + BONE_TRANSFORMS[int(si.y)] * b * sw.y
         + BONE_TRANSFORMS[int(si.z)] * b * sw.z + BONE_TRANSFORMS[int(si.w)] * b * sw.w;
  return s.xyz; }
"""
)
# three samples glTF textures with flipY false (v = 0 is the top row of the image); Quick 3D's
# texture() has v = 0 at the bottom row, and Texture.flipV only reaches the built-in materials'
# texture transform. Unflipped, every card read its alpha upside down: hair strands broke into
# specks and the brows thinned to a few dots. aether.js only samples the card alpha maps, so
# every texture2D in a translated fragment stage becomes glTFTex.
FRAG_PRE = (
    COMMON
    + """#define gl_FragColor FRAGCOLOR
#define gl_FragCoord FRAGCOORD
#define glTFTex(s, uv) texture(s, vec2((uv).x, 1.0 - (uv).y))
"""
)

# Shell vertex stage (aether.js SHELL_VS with three's skinning chunks written out; no morphs yet).
SHELL_VERT = (
    VERT_PRE
    + """VARYING vec3 vN; VARYING vec3 vV; VARYING vec3 vW; VARYING vec3 vO; VARYING vec2 vUv2;
VARYING float vCav; VARYING float vCavF; VARYING float vHand; VARYING float vWr;
void MAIN() {
  vO = VERTEX; vUv2 = UV0; vCav = UV1.x; vCavF = UV1.y; vHand = TANGENT.x; vWr = TANGENT.y;
  mat4 S = BONE_TRANSFORMS[JOINTS.x] * WEIGHTS.x + BONE_TRANSFORMS[JOINTS.y] * WEIGHTS.y
         + BONE_TRANSFORMS[JOINTS.z] * WEIGHTS.z + BONE_TRANSFORMS[JOINTS.w] * WEIGHTS.w;
  vec4 w = S * vec4(VERTEX, 1.0);
  vec4 mv = VIEW_MATRIX * w;
  vN = normalize(mat3(VIEW_MATRIX) * (mat3(S) * NORMAL)); vV = normalize(-mv.xyz);
  vW = w.xyz;
  POSITION = PROJECTION_MATRIX * mv;
}
"""
)
# Interior fills (onModel MeshBasicMaterial + its onBeforeCompile patches).
FILL_VERT = (
    VERT_PRE
    + """VARYING vec2 vUv; VARYING vec3 vWp;
void MAIN() {
  mat4 S = BONE_TRANSFORMS[JOINTS.x] * WEIGHTS.x + BONE_TRANSFORMS[JOINTS.y] * WEIGHTS.y
         + BONE_TRANSFORMS[JOINTS.z] * WEIGHTS.z + BONE_TRANSFORMS[JOINTS.w] * WEIGHTS.w;
  vec4 w = S * vec4(VERTEX, 1.0); vUv = UV0; vWp = w.xyz;
  w.xyz += normalize(w.xyz - CAMERA_POSITION) * uPush;   // occluders sit behind the shells
  // same expression as SHELL_VERT: the shells draw over these fills at the same depth (three's
  // LessEqual), and VIEWPROJECTION * w rounds differently, so the shells z-fought them in specks
  vec4 mv = VIEW_MATRIX * w;
  POSITION = PROJECTION_MATRIX * mv;
}
"""
)
FILL_FRAG = {
    # see-through body: interior only from the neck up, wide fade down the neck (pass 8).
    # three blends this fade over what is behind; Quick 3D has no depth-writing blended
    # material, so the fade is premultiplied onto black and drawn opaque.
    "neck": FRAG_PRE
    + """VARYING vec2 vUv; VARYING vec3 vWp;
void MAIN() {
  float nA = smoothstep(uNeckY - 0.03, uNeckY + 0.05, vWp.y) * (1.0 - smoothstep(0.055, 0.085, abs(vWp.x - uFace.x)) * (1.0 - smoothstep(uNeckY - 0.02, uNeckY + 0.06, vWp.y)));
  if (nA < 0.03) discard;
  FRAGCOLOR = vec4(uColor * nA, 1.0);
}
""",
    "solid": FRAG_PRE
    + """VARYING vec2 vUv; VARYING vec3 vWp;
void MAIN() { FRAGCOLOR = vec4(uColor, 1.0); }
""",
    # skin opacity pass (see SKIN_OPACITY): her interior colour laid over what is behind her body
    "skin": FRAG_PRE
    + """VARYING vec2 vUv; VARYING vec3 vWp;
void MAIN() {
  // only where the neck fill above leaves her see-through: the head is already solid, and laying
  // the colour over it would only veil the eyes and brows drawn before this pass
  float nA = smoothstep(uNeckY - 0.03, uNeckY + 0.05, vWp.y) * (1.0 - smoothstep(0.055, 0.085, abs(vWp.x - uFace.x)) * (1.0 - smoothstep(uNeckY - 0.02, uNeckY + 0.06, vWp.y)));
  float a = uSkinOpacity * (1.0 - nA);
  if (a < 0.003) discard;
  FRAGCOLOR = vec4(uColor, a);
}
""",
    # alphaMap cut-out (hair volume: alphaTest 0.45, opaque; cards: alphaTest 0.3, opacity 0.6)
    "card": FRAG_PRE
    + """VARYING vec2 vUv; VARYING vec3 vWp;
void MAIN() { float a = uOpacity * glTFTex(uAlphaMap, vUv).a; if (a < uAlphaTest) discard;
  FRAGCOLOR = vec4(uColor, a); }
""",
}


# Point layers. gl_PointSize (Quick 3D POINT_SIZE) is honoured on OpenGL and Vulkan only; D3D11
# and Metal draw every point at 1 px. So LayerGeometry(points: true) turns each point into a quad
# whose 4 vertices carry the corner in UV1 (-0.5..0.5), and the vertex stage moves each corner by
# the same size in framebuffer pixels that aether.js gives gl_PointSize. vPc replaces
# gl_PointCoord (0..1 across the sprite; y runs up rather than down, and every aether sprite
# fragment shader is radially symmetric).
def sprite_size(size: str) -> str:
    return f"vPc = UV1 + 0.5; POSITION.xy += UV1 * ({size}) * 2.0 / uVp * POSITION.w;"


def point_sprites(src: str, stage: str) -> str:
    """Rewrite a point layer's gl_PointSize / gl_PointCoord onto the quad expansion."""
    if stage == "vert":
        out, n = re.subn(r"gl_PointSize\s*=\s*([^;]+);", lambda m: sprite_size(m.group(1)), src)
        if n != 1:
            raise ValueError(f"expected one gl_PointSize write, found {n}")
    else:
        out = src.replace("gl_PointCoord", "vPc")
    i = out.index("\nvoid MAIN")
    return out[:i] + "\nVARYING vec2 vPc;\n" + out[i:]


GALAXY_VERT = point_sprites(
    VERT_PRE
    + """VARYING vec3 vC;
void MAIN() { vC = COLOR.rgb; vec4 mv = VIEW_MATRIX * MODEL_MATRIX * vec4(VERTEX, 1.0);
  POSITION = PROJECTION_MATRIX * mv; gl_PointSize = uSize * (uScale / -mv.z); }
""",
    "vert",
)
GALAXY_FRAG = point_sprites(
    FRAG_PRE
    + """VARYING vec3 vC;
void MAIN() { float dq = length(gl_PointCoord - 0.5); if (dq > 0.5) discard;
  FRAGCOLOR = vec4(vC * smoothstep(0.5, 0.0, dq), 1.0); }
""",
    "frag",
)


# Look gains on top of the aether shell (iter5, by eye against v14k): rim peaks sat near 222 where
# v14k reaches 255, and the glow over the head read weaker. Hair cards keep their own rim, so
# the body rim stays brighter than the hair.
RIM_GAIN = 1.25
HEAD_GLOW = 2.0
# Skin opacity (root skinOpacity; 0 = v14k, where the body below the neck is see-through and only
# the additive shell glow draws it). Above 0, each body fill is drawn a second time in the
# blended pass, just before the shells, as its interior colour at that alpha wherever the neck
# fill leaves her see-through (below the neck): what is behind her body dims toward it and her
# shell glow reads over a surface.
# Hidden at 0, so the default frame is v14k's exactly.
SKIN_OPACITY = 0.0
RIM_SRC = "float rim = pow(1.0 - ndv, 2.4);"
GLOW_SRC = re.compile(r"float glow = uGlow[^;]*;")


def look_gains(frag: str) -> str:
    """Scale the shell rim by uRimGain and the glow above the neck by uHeadGlow."""
    if frag.count(RIM_SRC) != 1 or len(GLOW_SRC.findall(frag)) != 1:
        raise ValueError("shell fragment shader no longer has one rim and one glow term")
    frag = frag.replace(RIM_SRC, RIM_SRC + " rim *= uRimGain;")
    return GLOW_SRC.sub(
        lambda m: (
            m.group(0)
            + " glow *= mix(1.0, uHeadGlow, smoothstep(uNeckY - 0.02, uNeckY + 0.06, vW.y));"
        ),
        frag,
    )


# Face morphs. aether.js draws the shells and fills on three's skinned meshes, so the face's morph
# weights (visemes, jaw, blinks) move them. The export carries no morph data; it comes from the GLB,
# whose primitives hold the exported vertices in the same order. Only the names face.js writes are
# kept, as absolute target positions (Quick 3D blends base + w * (target - base)).
# QQuick3DGeometry::addTargetAttribute ignores attributes past 32 per geometry
# (QQuick3DGeometryPrivate::MAX_TARGET_ATTRIBUTE_COUNT, Qt 6.11); each face morph is one Position.
MAX_MORPHS = 32
FACE_JS = Path(__file__).with_name("face.js")
DEFAULT_GLB = Path("/workspace/team/avatar-proto/threejs-prep/models/ellah.glb")


def _glb(path: Path):
    import struct

    import numpy as np

    raw = path.read_bytes()
    n = struct.unpack("<I", raw[12:16])[0]
    doc = json.loads(raw[20 : 20 + n])
    o = 20 + n
    blob = raw[o + 8 : o + 8 + struct.unpack("<I", raw[o : o + 4])[0]]

    def acc(i: int):
        a = doc["accessors"][i]
        width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
        out = np.zeros((a["count"], width), np.float32)
        if "bufferView" in a:
            bv = doc["bufferViews"][a["bufferView"]]
            stride = bv.get("byteStride", 4 * width)
            off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
            rows = np.frombuffer(blob, np.uint8, count=a["count"] * stride, offset=off)
            out[:] = rows.reshape(a["count"], stride)[:, : 4 * width].copy().view(np.float32)
        if "sparse" in a:
            sp = a["sparse"]
            ib, vb = (
                doc["bufferViews"][sp["indices"]["bufferView"]],
                doc["bufferViews"][sp["values"]["bufferView"]],
            )
            it = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32}[sp["indices"]["componentType"]]
            idx = np.frombuffer(
                blob,
                it,
                count=sp["count"],
                offset=ib.get("byteOffset", 0) + sp["indices"].get("byteOffset", 0),
            )
            vals = np.frombuffer(
                blob,
                np.float32,
                count=sp["count"] * width,
                offset=vb.get("byteOffset", 0) + sp["values"].get("byteOffset", 0),
            )
            out[idx] = vals.reshape(-1, width)
        return out

    return doc, acc


def export_morphs(glb: Path, scene: Path, layers: list[dict], out: Path) -> dict[str, list[str]]:
    """Write out/<geom>_<name>.bin (absolute positions) for every face morph that moves a layer's mesh."""
    import numpy as np

    order = list(
        dict.fromkeys(re.findall(r"'([A-Z][A-Za-z]+(?:_[A-Za-z0-9]+)+)'", FACE_JS.read_text()))
    )
    wanted = set(order)
    doc, acc = _glb(glb)
    prims = []
    for mesh in doc["meshes"]:
        names = (mesh.get("extras") or {}).get("targetNames", [])
        for prim in mesh["primitives"]:
            if prim.get("targets"):
                prims.append((acc(prim["attributes"]["POSITION"]), names, prim["targets"]))
    out.mkdir(parents=True, exist_ok=True)
    found: dict[str, list[str]] = {}
    for gid in sorted({lay["geom"]["id"] for lay in layers if lay["type"] == "SkinnedMesh"}):
        pos = np.fromfile(scene / f"{gid}_position.bin", np.float32).reshape(-1, 3)
        for base, names, targets in prims:
            if base.shape != pos.shape or not np.array_equal(base, pos):
                continue
            keep = []
            for name, t in zip(names, targets, strict=True):
                d = acc(t["POSITION"]) if name in wanted and "POSITION" in t else None
                if d is not None and np.abs(d).max() > 1e-6:
                    (pos + d).astype(np.float32).tofile(out / f"{gid}_{name}.bin")
                    keep.append(name)
            if len(keep) > MAX_MORPHS:
                # face.js lists the mouth first; past the cap the rarest expressions drop
                keep.sort(key=order.index)
                import warnings

                warnings.warn(
                    f"{gid}: {len(keep)} face morphs, Quick 3D keeps {MAX_MORPHS}; dropped {keep[MAX_MORPHS:]}",
                    stacklevel=2,
                )
                keep = keep[:MAX_MORPHS]
            if keep:
                found[gid] = keep
            break
    return found


class NoFaceMorphs(UserWarning):
    """The port built without face morphs: her mouth and eyes will not move."""


def face_morphs(
    glb: Path | None, scene: Path, layers: list[dict], out: Path
) -> dict[str, list[str]]:
    """export_morphs, but a missing GLB (or one with no face morphs) is a loud warning, not a quiet
    build where face.js runs and nothing on her face moves."""
    import sys
    import warnings

    found = export_morphs(glb, scene, layers, out) if glb and glb.exists() else {}
    if not found:
        why = (
            f"{glb} not found" if not (glb and glb.exists()) else f"no face morphs matched in {glb}"
        )
        msg = f"WARNING: building without face morphs ({why}); her mouth and eyes will not move. Pass --glb."
        print("\n" + "!" * len(msg) + "\n" + msg + "\n" + "!" * len(msg), file=sys.stderr)
        warnings.warn(msg, NoFaceMorphs, stacklevel=2)
    return found


def with_morphs(vert: str, n: int) -> str:
    """Read the morphed position wherever the vertex stage reads VERTEX. Quick 3D only morphs it
    itself when the shader leaves POSITION alone, and every aether vertex stage writes POSITION."""
    i = vert.index("void MAIN() {") + len("void MAIN() {")
    body = vert[i:].replace("VERTEX", "MORPHED_VERTEX")
    blend = (
        " vec3 MORPHED_VERTEX = VERTEX;"
        f" for (int k = 0; k < {n}; k++) MORPHED_VERTEX += MORPH_WEIGHTS[k] * (MORPH_POSITION(k) - VERTEX);"
    )
    return vert[:i] + blend + body


# Uniforms that follow the render target instead of the export: aether.js feeds them from the
# renderer (uPx = pixel ratio; the galaxy's size attenuation scale is half the drawing-buffer height).
SCREEN = {"uVp": "viewportSize", "uPx": "devicePixelRatio", "uScale": "viewportSize.y / 2"}


def _remove_func(src: str, sig: str) -> str:
    i = src.find(sig)
    if i < 0:
        return src
    j = src.index("{", i)
    depth = 0
    for k in range(j, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[:i] + src[k + 1 :]
    raise ValueError(sig)


def _split_arrays(src: str, arrays: dict[str, int], vec: str) -> str:
    for name, n in arrays.items():
        helper = (
            f"{vec} {name}At(int k) {{ "
            + " ".join(f"if (k == {i}) return {name}{i};" for i in range(n))
            + f" return {name}0; }}\n"
        )
        out, i = [], 0
        while (j := src.find(name + "[", i)) >= 0:
            out.append(src[i:j] + name + "At(")
            depth, k = 0, j + len(name)
            while True:
                depth += {"[": 1, "]": -1}.get(src[k], 0)
                if depth == 0:
                    break
                k += 1
            out.append(src[j + len(name) + 1 : k] + ")")
            i = k + 1
        out.append(src[i:])
        src = helper + "".join(out)
    return src


def translate(src: str, stage: str, uniforms: dict[str, tuple[str, int]]) -> str:
    """three.js GLSL (ShaderMaterial source) -> Quick 3D CustomMaterial snippet."""
    src = re.sub(r"^\s*#extension[^\n]*\n", "", src, flags=re.M)
    src = re.sub(r"precision\s+\w+\s+\w+\s*;", "", src)
    arrays: dict[str, int] = {}
    vec_of: dict[str, str] = {}

    def uni(m: re.Match) -> str:
        typ = m.group(2)
        for part in m.group(3).split(","):
            part = part.strip()
            am = re.match(r"(\w+)\s*\[\s*(\d+)\s*\]", part)
            if am:
                arrays[am.group(1)] = int(am.group(2))
                vec_of[am.group(1)] = typ
                for i in range(int(am.group(2))):
                    uniforms[f"{am.group(1)}{i}"] = (typ, 0)
            elif part not in SKIP_UNIFORMS:
                uniforms[part] = (typ, 0)
        return ""

    src = re.sub(r"uniform\s+(highp\s+|mediump\s+|lowp\s+)?(\w+)\s+([^;]+);", uni, src)
    defines = []
    if stage == "vert":
        src = _remove_func(src, "mat4 boneM(")
        src = _remove_func(src, "vec3 skinPoint(")

        loads = []

        def attr(m: re.Match) -> str:
            # a global copied from the slot in MAIN, so locals of the same name (noise's u) still shadow it
            defines.append(f"{m.group(1)} {m.group(2)};")
            loads.append(f"{m.group(2)} = {ATTR_SLOT[m.group(2)]};")
            return ""

        src = re.sub(r"attribute\s+(\w+)\s+(\w+)\s*;", attr, src)
        defines.append("vec3 position;")
        loads.append("position = VERTEX;")
        src = re.sub(r"void\s+main\s*\(\s*\)\s*\{", "void main() { " + " ".join(loads), src)
    if stage == "frag":
        src = re.sub(r"\btexture2D\s*\(", "glTFTex(", src)  # see FRAG_PRE
    src = re.sub(r"\bvarying\b", "VARYING", src)
    src = re.sub(r"void\s+main\s*\(\s*\)", "\nvoid MAIN()", src)
    src = re.sub(
        r"(VARYING[^;]*;)", r"\n\1\n", src
    )  # Quick 3D wants VARYING and MAIN on their own lines
    for name in arrays:
        src = _split_arrays(src, {name: arrays[name]}, vec_of[name])
    if stage == "frag":
        # pow() of a slightly negative base (thin strips, interpolation error) is NaN on Mesa and
        # some GPUs and 0 on ANGLE; one NaN pixel blooms into a white square, so drop such fragments.
        src = src.replace("void MAIN()", "void aether_main()") + (
            "\nvoid MAIN() { aether_main(); if (any(isnan(FRAGCOLOR)) || any(isinf(FRAGCOLOR))) discard; }\n"
        )
    pre = VERT_PRE if stage == "vert" else FRAG_PRE
    if "skinPoint(" not in src:
        pre = (
            pre.replace(
                pre[pre.index("// aether.js skinPoint") :],
                "#define gl_Position POSITION\n",
            )
            if stage == "vert"
            else pre
        )
    return pre + "\n".join(defines) + "\n" + src


# aether.js anim loop at a steady voice level L (lvl.med = lvl.slow = L, uFX.x eased to L):
# uAnim = (glow * (1 + 0.16 L) * (1 + 0.1 L), rim + 0.12 L, shimmer, 0)


# ---- the look clock: aether.js frameBody() per-frame uniforms, driven from the look itself ----
# Each entry is the QML expression a material uniform binds to. The review tool sets material
# properties directly for its frozen poses, which replaces these bindings (and it stops the clock).
DRIVEN = {
    "uAnim": "lookAnim",  # anim.js light terms: breath/voice glow, state rim, thinking shimmer
    "uFX": "Qt.vector4d(fxLevel, 0, 0, 0)",  # x voice level (smoothed), y walk weight (no walk)
    "uPh": "floorPhase",  # FLO.ph: the floor rings' drift
    "uNeckS": "neckScreenY",  # the neck line's height on screen (0 bottom, 1 top)
    "uRes": "viewportSize",  # renderer.getDrawingBufferSize
}
ARM_BONES = ["L_Upperarm", "L_Forearm", "L_Hand", "R_Upperarm", "R_Forearm", "R_Hand"]
# anim.js P: per-state flow clock rate, rim gain, shimmer and breaths per second
LOOK_STATES = {
    "idle": (1.0, 1.0, 0, 0.23),
    "listening": (1.1, 1.38, 0, 0.22),
    "thinking": (2.3, 1.08, 1, 0.21),
    "speaking": (1.25, 1.12, 0, 0.26),
    "done": (0.8, 1.0, 0, 0.2),
}


def driven(name: str, real_clock: bool, ids: dict[str, str]) -> str | None:
    """The look-clock expression for uniform `name`, or None when it stays a constant.
    real_clock: the layer reads aether.js's uTime (floor rings) rather than uFlow (the rest)."""
    if name == "uTime":
        return "aetherTime" if real_clock else "aetherFlow"
    arm = re.fullmatch(r"uArm(\d)", name)
    if arm:
        return f"{ids['CC_Base_' + ARM_BONES[int(arm.group(1))]]}.scenePosition"
    return DRIVEN.get(name)


def look_clock(unis: list[dict]) -> str:
    """Root properties and the FrameAnimation that advance them (aether.js frameBody + anim.js light)."""
    t0 = next(u["uTime"] for u in unis if "uAnim" in u)
    ph0 = next((u["uPh"] for u in unis if "uPh" in u), 0.0)
    ring = next((u["uRing"] for u in unis if "uRing" in u), [0, 0, 0])
    neck = next(u["uNeckY"] for u in unis if "uNeckY" in u)
    ns0 = next((u["uNeckS"] for u in unis if "uNeckS" in u), 0.8)
    states = ", ".join(f"{k}: [{', '.join(str(x) for x in v)}]" for k, v in LOOK_STATES.items())
    return f"""    // ---- look clock (arelis/ui/persona_q3d/port.py look_clock): what aether.js frameBody() animates ----
    // Any host gets it: set aetherState and speakingLevel, and camera for the neck line. The review
    // tool sets clockRunning false and writes the frozen pose's uniforms itself.
    property bool clockRunning: true
    property string aetherState: "idle"
    property var camera: null
    property real aetherTime: {t0!r}
    property real aetherFlow: {t0!r}
    property real fxLevel: 0
    property real slowLevel: 0
    property real floorPhase: {ph0!r}
    property real neckScreenY: {ns0!r}
    property vector4d lookAnim: Qt.vector4d(1, 1, 0, 0)
    readonly property var lookStates: ({{ {states} }})
    property var lookW: ({{ idle: 1 }})
    property var lookW1: ({{ idle: 1 }})
    FrameAnimation {{ running: clockRunning; onTriggered: lookTick(Math.min(frameTime, 0.1)) }}
    function lookTick(dt) {{
        var k = 1 - Math.exp(-dt / 0.11), p = [0, 0, 0, 0]
        for (var m in lookStates) {{
            var w1 = (lookW1[m] || 0) + ((m === aetherState ? 1 : 0) - (lookW1[m] || 0)) * k
            var w = (lookW[m] || 0) + (w1 - (lookW[m] || 0)) * k
            lookW1[m] = w1; lookW[m] = w
            for (var j = 0; j < 4; j++) p[j] += w * lookStates[m][j]
        }}
        aetherTime += dt
        aetherFlow += dt * p[0]
        fxLevel += (speakingLevel - fxLevel) * Math.min(1, dt * 3)
        slowLevel += (speakingLevel - slowLevel) * (1 - Math.exp(-dt / 0.6))
        floorPhase += dt * 0.35
        var b = 0.5 + 0.5 * Math.sin(2 * Math.PI * p[3] * aetherTime)
        lookAnim = Qt.vector4d((1 + 0.04 * (b - 0.5)) * (1 + 0.16 * speakingLevel + 0.1 * slowLevel),
                               p[1] + 0.12 * speakingLevel, p[2] * (0.875 + 0.125 * Math.sin(aetherTime * 0.9 * 6.2832)), 0)
        if (camera) {{
            var v = camera.mapToViewport(Qt.vector3d({ring[0]!r}, {neck!r}, {ring[2]!r}))
            neckScreenY = Math.min(1, Math.max(0.05, 1 - v.y))
        }}
    }}
"""


def _qml_value(typ: str, v) -> str:
    if typ in ("float", "int"):
        return repr(float(v)) if typ == "float" else str(int(v))
    if typ == "bool":
        return "true" if v else "false"
    if typ in ("vec2", "vec3", "vec4"):
        n = int(typ[-1])
        return f"Qt.vector{n}d({', '.join(repr(float(x)) for x in list(v)[:n])})"
    return "undefined"


def _mat(m16: list[float]) -> str:  # three column-major -> Qt.matrix4x4 row-major args
    rows = [m16[c * 4 + r] for r in range(4) for c in range(4)]
    return "Qt.matrix4x4(" + ", ".join(f"{x:.9g}" for x in rows) + ")"


def _mul(a: list[float], b: list[float]) -> list[float]:  # column-major a*b
    return [sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4)) for c in range(4) for r in range(4)]


def _decompose(m16: list[float]):
    sx = math.dist(m16[0:3], (0, 0, 0))
    sy = math.dist(m16[4:7], (0, 0, 0))
    sz = math.dist(m16[8:11], (0, 0, 0))
    r = [[m16[c * 4 + rr] / s for c, s in enumerate((sx, sy, sz))] for rr in range(3)]
    tr = r[0][0] + r[1][1] + r[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = (0.25 * s, (r[2][1] - r[1][2]) / s, (r[0][2] - r[2][0]) / s, (r[1][0] - r[0][1]) / s)
    elif r[0][0] > r[1][1] and r[0][0] > r[2][2]:
        s = math.sqrt(1.0 + r[0][0] - r[1][1] - r[2][2]) * 2
        q = ((r[2][1] - r[1][2]) / s, 0.25 * s, (r[0][1] + r[1][0]) / s, (r[0][2] + r[2][0]) / s)
    elif r[1][1] > r[2][2]:
        s = math.sqrt(1.0 + r[1][1] - r[0][0] - r[2][2]) * 2
        q = ((r[0][2] - r[2][0]) / s, (r[0][1] + r[1][0]) / s, 0.25 * s, (r[1][2] + r[2][1]) / s)
    else:
        s = math.sqrt(1.0 + r[2][2] - r[0][0] - r[1][1]) * 2
        q = ((r[1][0] - r[0][1]) / s, (r[0][2] + r[2][0]) / s, (r[1][2] + r[2][1]) / s, 0.25 * s)
    return m16[12:15], q, (sx, sy, sz)


def transform_props(m16: list[float]) -> dict[str, str]:
    p, q, s = _decompose(m16)
    return {
        "position": "Qt.vector3d({:.9g}, {:.9g}, {:.9g})".format(*p),
        "rotation": "Qt.quaternion({:.9g}, {:.9g}, {:.9g}, {:.9g})".format(*q),
        "scale": "Qt.vector3d({:.9g}, {:.9g}, {:.9g})".format(*s),
    }


def balsam_ids(qml: str) -> dict[str, str]:
    return {
        m.group(2): m.group(1)
        for m in re.finditer(r"id:\s*(\w+)\s*\n\s*objectName:\s*\"([^\"]+)\"", qml)
    }


def no_depth_test(vert: str) -> str:
    """three's depthTest:false. Put the vertex at the near plane so the layer passes the depth test.

    Inserted at the end of MAIN rather than wrapping it: Quick 3D only declares the
    attributes MAIN itself uses.
    """
    i = vert.index("void MAIN")
    i = vert.index("{", i)
    depth = 0
    for k in range(i, len(vert)):
        depth += {"{": 1, "}": -1}.get(vert[k], 0)
        if depth == 0:
            z = " POSITION.z = mix(NEAR_CLIP_VALUE, 1.0, 1e-3) * POSITION.w; "
            return vert[:k] + z + vert[k:]
    raise ValueError("no MAIN")


def layer_plan(layers: list[dict]) -> list[dict]:
    """Decide, per exported object, what Quick 3D draws (or that it is skipped, and why)."""
    plan = []
    for lay in layers:
        m, g = lay["mat"], lay["geom"]
        at = set(g["at"])
        p = {"i": lay["i"], "geom": g["id"], "points": lay["type"] == "Points", "skin": lay["skin"]}
        if m["type"] == "ShaderMaterial" and lay["skin"] and lay["skin"]["ref"] is None:
            p.update(kind="shell", spec=MESH)
        elif m["type"] == "ShaderMaterial":
            spec = ["VERTEX=position"] + [SPEC_OF[a] for a in sorted(at) if a in SPEC_OF]
            if "u" in at:
                spec = [s for s in spec if not s.startswith("UV0=")] + ["UV0=u,side"]
            p.update(kind="shader", spec=";".join(spec))
        elif m["type"] == "PointsMaterial":
            p.update(kind="galaxy", spec="VERTEX=position;COLOR=color")
        elif not m["cw"]:
            # Depth only. Opaque black is the same thing here: Quick 3D draws opaque Models
            # first, over the black clear, so only the depth is left for the additive layers.
            p.update(kind="fill", frag="solid", spec=FILL_MESH, occluder=True)
        elif m["alphaMap"] is not None:
            p.update(kind="fill", frag="card", spec=FILL_MESH)
        elif lay["parent"] == "CC_Base_Body":
            p.update(kind="fill", frag="neck", spec=FILL_MESH)
        else:
            p.update(kind="fill", frag="solid", spec=FILL_MESH)
        plan.append(p)
    return plan


def build(
    scene: Path, converted: Path, out_name: str = "Ellah_aether.qml", glb: Path | None = DEFAULT_GLB
) -> Path:
    layers = json.loads((scene / "layers.json").read_text())
    morph_dir = converted / "morphs"
    morphs = face_morphs(glb, scene, layers, morph_dir)
    unis = json.loads((scene / "uniforms.json").read_text())["idle"]
    base = (converted / "Ellah_anim.qml").read_text()
    ids = balsam_ids(base)
    shaders = converted / "aether_shaders"
    shaders.mkdir(exist_ok=True)
    body: list[str] = []
    # three draws transparent objects by renderOrder, then scene order. Quick 3D sorts them
    # back to front by camera distance plus Model.depthBias, so a large bias per rank keeps
    # three's order. Depth-only passes that three draws after the shells (the body
    # occluders, renderOrder 6) go in that ordered pass too, or they would hide shells
    # behind other body parts that v14k shows (the torso edge under the arm).
    first_colour = min(x["ro"] for x in layers if x["mat"]["tr"] and x["mat"]["cw"])
    late_depth = {
        x["i"] for x in layers if x["mat"]["tr"] and not x["mat"]["cw"] and x["ro"] > first_colour
    }
    order = sorted((x["ro"], x["i"]) for x in layers if x["mat"]["tr"])
    rank = {i: n for n, (_, i) in enumerate(order)}
    for p in layer_plan(layers):
        lay, i = layers[p["i"]], p["i"]
        m = lay["mat"]
        if p["kind"] == "skip":
            continue
        uniforms: dict[str, tuple[str, int]] = {}
        if p["kind"] == "shell":
            vert = SHELL_VERT
            frag = look_gains(translate(m["fs"], "frag", uniforms))
            uniforms.update(uRimGain=("float", 0), uHeadGlow=("float", 0))
        elif p["kind"] == "shader":
            vert = translate(m["vs"], "vert", uniforms)
            frag = translate(m["fs"], "frag", uniforms)
            if p["points"]:
                vert, frag = point_sprites(vert, "vert"), point_sprites(frag, "frag")
            if not m["dt"]:
                vert = no_depth_test(vert)
        elif p["kind"] == "galaxy":
            vert, frag = GALAXY_VERT, GALAXY_FRAG
            uniforms = {"uSize": ("float", 0), "uScale": ("float", 0)}
        else:
            vert, frag = FILL_VERT, FILL_FRAG[p["frag"]]
            uniforms = {
                "uColor": ("vec3", 0),
                "uNeckY": ("float", 0),
                "uFace": ("vec4", 0),
                "uOpacity": ("float", 0),
                "uPush": ("float", 0),
                "uAlphaTest": ("float", 0),
                "uAlphaMap": ("sampler2D", 0),
            }
        if p["points"]:
            uniforms["uVp"] = ("vec2", 0)
        names = morphs.get(p["geom"], []) if p["kind"] in ("shell", "fill") else []
        if names:
            vert = with_morphs(vert, len(names))
        (shaders / f"L{i}.vert").write_text(vert)
        (shaders / f"L{i}.frag").write_text(frag)
        vals = dict(unis[i])
        if p["kind"] == "fill":
            shell = next(u for u in unis if "uNeckY" in u)
            vals.update(
                uColor=[0, 0, 0] if p.get("occluder") else m["color"],
                uNeckY=shell["uNeckY"],
                uFace=shell["uFace"],
                uOpacity=m["opacity"],
                uPush=0.004 if p.get("occluder") else 0.0,
                uAlphaTest=m["alphaTest"],
            )
        if p["kind"] == "shell":
            vals.update(uRimGain=1.0 if lay["parent"] == "Hair" else RIM_GAIN, uHeadGlow=HEAD_GLOW)
        if p["kind"] == "galaxy":
            vals.update(uSize=m["size"], uScale=480.0)
        props = []
        for name, (typ, _) in sorted(uniforms.items()):
            if typ == "sampler2D":
                tex = m["utex"].get(name, m["alphaMap"])
                if tex is None:
                    props.append(f"property TextureInput {name}: TextureInput {{ enabled: false }}")
                else:
                    props.append(
                        f'property TextureInput {name}: TextureInput {{ texture: Texture {{ source: "{(scene / f"tex_{tex}.png").as_uri()}"; generateMipmaps: true; mipFilter: Texture.Linear }} }}'
                    )
            else:
                arr = re.match(r"(\w+?)(\d+)$", name)
                v = vals.get(name)
                if v is None and arr and isinstance(vals.get(arr.group(1)), list):
                    v = vals[arr.group(1)][int(arr.group(2))]
                val = (
                    SCREEN.get(name)
                    or driven(name, "uPh" in unis[i], ids)
                    or _qml_value(typ, v if v is not None else 0)
                )
                props.append(f"property {GLSL_QML[typ]} {name}: {val}")
        if i in late_depth:
            blend = (
                "sourceBlend: CustomMaterial.Zero; destinationBlend: CustomMaterial.One; "
                "depthDrawMode: Material.AlwaysDepthDraw"
            )
        elif m["blend"] == 2:
            blend = "sourceBlend: CustomMaterial.SrcAlpha; destinationBlend: CustomMaterial.One"
        elif (m["tr"] and p["kind"] in ("shader", "shell")) or (
            p.get("frag") == "card" and m["alphaTest"] < 0.4
        ):
            blend = "sourceBlend: CustomMaterial.SrcAlpha; destinationBlend: CustomMaterial.OneMinusSrcAlpha"
        else:
            blend = ""
        cull = (
            "cullMode: Material.NoCulling"
            if m["side"] == 2
            else "cullMode: Material.BackFaceCulling"
        )
        skin = ""
        if p["skin"]:
            sk = p["skin"]
            joints = ", ".join(ids[b] for b in sk["bones"])
            ibp = ", ".join(_mat(_mul(inv, sk["bind"])) for inv in sk["inv"])
            body.append(
                f"    Skin {{ id: skinL{i}; joints: [{joints}]\n        inverseBindPoses: [{ibp}] }}"
            )
            skin = f"skin: skinL{i}; "
        tf = (
            ""
            if p["skin"] and p["skin"]["ref"] is None
            else "; ".join(f"{k}: {v}" for k, v in transform_props(lay["world"]).items())
        )
        if p["kind"] == "galaxy":
            # aether.js: galaxy.rotation.z = uTime * 0.03, on top of its fixed tilt
            _, q, _ = _decompose(lay["world"])
            a = -0.03 * next(u["uTime"] for u in unis if "uPh" in u) / 2
            ca, sa = math.cos(a), math.sin(a)
            w_, x_, y_, z_ = q
            q0 = (w_ * ca - z_ * sa, x_ * ca + y_ * sa, y_ * ca - x_ * sa, z_ * ca + w_ * sa)
            tf = tf.replace(
                transform_props(lay["world"])["rotation"],
                "Qt.quaternion({:.9g}, {:.9g}, {:.9g}, {:.9g})".format(*q0)
                + ".times(Quaternion.fromAxisAndAngle(0, 0, 1, aetherTime * 0.03 * 57.2957795))",
            )
        if blend and i in rank:
            tf = (tf + "; " if tf else "") + f"depthBias: {(len(order) - rank[i]) * 1000}"
        morph_src = f'; morphs: "{morph_dir / p["geom"]}:{",".join(names)}"' if names else ""
        morph_targets = (
            "        morphTargets: ["
            + ", ".join(
                f'MorphTarget {{ objectName: "{n}"; attributes: MorphTarget.Position }}'
                for n in names
            )
            + "]\n"
            if names
            else ""
        )
        if p.get("frag") == "neck":
            shell_bias = (len(order) - min(rank[x["i"]] for x in layers if x["ro"] == 2)) * 1000
            (shaders / f"S{i}.frag").write_text(FILL_FRAG["skin"])
            body.append(
                f'    Model {{ objectName: "S{i}"; visible: skinOpacity > 0; {skin}{tf}{"; " if tf else ""}depthBias: {shell_bias + 500}\n'
                f'        geometry: LayerGeometry {{ source: "{scene / p["geom"]}"; spec: "{p["spec"]}"; points: false{morph_src} }}\n'
                f"{morph_targets}"
                f'        materials: CustomMaterial {{ objectName: "SM{i}"; shadingMode: CustomMaterial.Unshaded; sourceBlend: CustomMaterial.SrcAlpha; destinationBlend: CustomMaterial.OneMinusSrcAlpha; {cull}\n'
                f'            vertexShader: "aether_shaders/L{i}.vert"; fragmentShader: "aether_shaders/S{i}.frag"\n'
                + "".join(f"            {pr}\n" for pr in props)
                + "            property real uSkinOpacity: skinOpacity\n"
                + "        } }"
            )
        body.append(
            f'    Model {{ objectName: "L{i}"; {skin}{tf}\n'
            f'        geometry: LayerGeometry {{ source: "{scene / p["geom"]}"; spec: "{p["spec"]}"; points: {"true" if p["points"] else "false"}{morph_src} }}\n'
            f"{morph_targets}"
            f'        materials: CustomMaterial {{ objectName: "M{i}"; shadingMode: CustomMaterial.Unshaded; {blend + "; " if blend else ""}{cull}\n'
            f'            vertexShader: "aether_shaders/L{i}.vert"; fragmentShader: "aether_shaders/L{i}.frag"\n'
            + "".join(f"            {pr}\n" for pr in props)
            + "        } }"
        )
    # hide balsam's own Models; the skeleton, skins and timelines stay
    src = re.sub(r"(\n(\s*)Model \{\n)", r"\1\2    visible: false\n", base)
    src = src.replace("import QtQuick3D\n", "import QtQuick3D\nimport Arelis.PersonaQ3D\n", 1)
    k = src.rstrip().rindex("}")
    src = (
        src[:k]
        + "\n    // ---- aether layers (arelis/ui/persona_q3d/port.py) ----\n"
        + "    // voice level 0..1 from the host/face track; drives uAnim (glow, rim) and uFX.x (motes, strands)\n"
        + "    property real speakingLevel: 0\n"
        + "    // render target size in framebuffer pixels; point sprites are sized in it (see point_sprites)\n"
        + "    property vector2d viewportSize: Qt.vector2d(720, 960)\n"
        + "    property real devicePixelRatio: 1\n"
        + "    // how much her skin hides what is behind it (0 = v14k; see SKIN_OPACITY)\n"
        + f"    property real skinOpacity: {SKIN_OPACITY!r}\n"
        + look_clock(unis)
        + "\n".join(body)
        + "\n}\n"
    )
    out = converted / out_name
    out.write_text(src)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scene", type=Path, default=DEFAULT_SCENE)
    ap.add_argument("--converted", type=Path, required=True)
    ap.add_argument("--glb", type=Path, default=DEFAULT_GLB, help="source of the face morphs")
    a = ap.parse_args(argv)
    print(build(a.scene, a.converted, glb=a.glb))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
