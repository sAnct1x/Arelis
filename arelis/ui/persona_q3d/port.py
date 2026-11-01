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
#define gl_PointSize POINT_SIZE
// aether.js skinPoint: bindM and the bone inverse live in the Skin's inverse bind poses, so the
// bone transform maps the bind-space point straight to world space (uModel * bindMInv is identity).
vec3 skinPoint(vec3 p, vec4 si, vec4 sw) { vec4 b = vec4(p, 1.0);
  vec4 s = BONE_TRANSFORMS[int(si.x)] * b * sw.x + BONE_TRANSFORMS[int(si.y)] * b * sw.y
         + BONE_TRANSFORMS[int(si.z)] * b * sw.z + BONE_TRANSFORMS[int(si.w)] * b * sw.w;
  return s.xyz; }
"""
)
FRAG_PRE = (
    COMMON
    + """#define gl_FragColor FRAGCOLOR
#define gl_FragCoord FRAGCOORD
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
  POSITION = VIEWPROJECTION_MATRIX * w;
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
    # alphaMap cut-out (hair volume: alphaTest 0.45, opaque; cards: alphaTest 0.3, opacity 0.6)
    "card": FRAG_PRE
    + """VARYING vec2 vUv; VARYING vec3 vWp;
void MAIN() { float a = uOpacity * texture(uAlphaMap, vUv).a; if (a < uAlphaTest) discard;
  FRAGCOLOR = vec4(uColor, a); }
""",
}
GALAXY_VERT = (
    VERT_PRE
    + """VARYING vec3 vC;
void MAIN() { vC = COLOR.rgb; vec4 mv = VIEW_MATRIX * MODEL_MATRIX * vec4(VERTEX, 1.0);
  POSITION = PROJECTION_MATRIX * mv; POINT_SIZE = uSize * (uScale / -mv.z); }
"""
)
GALAXY_FRAG = (
    FRAG_PRE
    + """VARYING vec3 vC;
void MAIN() { float dq = length(gl_PointCoord - 0.5); if (dq > 0.5) discard;
  FRAGCOLOR = vec4(vC * smoothstep(0.5, 0.0, dq), 1.0); }
"""
)


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
                "#define gl_Position POSITION\n#define gl_PointSize POINT_SIZE\n",
            )
            if stage == "vert"
            else pre
        )
    return pre + "\n".join(defines) + "\n" + src


# aether.js anim loop at a steady voice level L (lvl.med = lvl.slow = L, uFX.x eased to L):
# uAnim = (glow * (1 + 0.16 L) * (1 + 0.1 L), rim + 0.12 L, shimmer, 0)
SPEAK = {
    "uAnim": "Qt.vector4d({0} * (1 + 0.16 * speakingLevel) * (1 + 0.1 * speakingLevel), {1} + 0.12 * speakingLevel, {2}, {3})",
    "uFX": "Qt.vector4d(speakingLevel, {1}, {2}, {3})",
}


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


def build(scene: Path, converted: Path, out_name: str = "Ellah_aether.qml") -> Path:
    layers = json.loads((scene / "layers.json").read_text())
    unis = json.loads((scene / "uniforms.json").read_text())["idle"]
    base = (converted / "Ellah_anim.qml").read_text()
    ids = balsam_ids(base)
    shaders = converted / "aether_shaders"
    shaders.mkdir(exist_ok=True)
    body: list[str] = []
    for p in layer_plan(layers):
        lay, i = layers[p["i"]], p["i"]
        m = lay["mat"]
        if p["kind"] == "skip":
            continue
        uniforms: dict[str, tuple[str, int]] = {}
        if p["kind"] == "shell":
            vert = SHELL_VERT
            frag = translate(m["fs"], "frag", uniforms)
        elif p["kind"] == "shader":
            vert = translate(m["vs"], "vert", uniforms)
            frag = translate(m["fs"], "frag", uniforms)
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
                val = _qml_value(typ, v if v is not None else 0)
                if name in SPEAK and isinstance(v, list):
                    val = SPEAK[name].format(*v)
                props.append(f"property {GLSL_QML[typ]} {name}: {val}")
        if m["blend"] == 2:
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
        body.append(
            f'    Model {{ objectName: "L{i}"; {skin}{tf}\n'
            f'        geometry: LayerGeometry {{ source: "{scene / p["geom"]}"; spec: "{p["spec"]}"; points: {"true" if p["points"] else "false"} }}\n'
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
    a = ap.parse_args(argv)
    print(build(a.scene, a.converted))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
