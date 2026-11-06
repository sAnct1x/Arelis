"""CPU mesh export of Iris swarm_blender.sentinel() LODs. No Cycles render."""
import sys
from pathlib import Path

import bpy

IRIS = Path(
    __import__("os").environ.get(
        "IRIS_SWARM_BLENDER",
        "/workspace/team/sentinel/iris-overseer-filament/swarm_blender.py",
    )
)
_args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
DEST = Path(_args[0] if _args else "/tmp/overseer-qt")

src = IRIS.read_text()
head, _sep, _rest = src.partition("# ---------------- pass 5")
if not _sep:
    raise SystemExit("swarm_blender.py missing pass 5 split; will not invent geometry")
exec(compile(head, str(IRIS), "exec"), globals())
DEST = Path(_args[0] if _args else "/tmp/overseer-qt")
DEST.mkdir(parents=True, exist_ok=True)

TARGETS = {0: 12000, 1: 4000, 2: 1000}


def _walk(obj):
    yield obj
    for child in obj.children:
        yield from _walk(child)


def _tris(obj):
    if obj.type != "MESH" or obj.data is None:
        return 0
    obj.data.calc_loop_triangles()
    return len(obj.data.loop_triangles)


def _bucket(name):
    n = (name or "").lower()
    if "lens" in n:
        return "lens"
    if n.startswith("seam") or n.startswith("dseam") or n.startswith("fil") or "fil" == n[:3]:
        return "emissive"
    return "hull"


def _convert_curves(root):
    for obj in list(_walk(root)):
        if obj.type != "CURVE":
            continue
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.convert(target="MESH")


def _join(objs, name):
    objs = [o for o in objs if o.type == "MESH" and o.data]
    if not objs:
        return None
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1:
        bpy.ops.object.join()
    joined = bpy.context.view_layer.objects.active
    joined.name = name
    return joined


def _decimate(obj, target):
    current = _tris(obj)
    if current <= 0:
        return current
    if current <= target:
        return current
    mod = obj.modifiers.new("budget", "DECIMATE")
    mod.ratio = max(0.02, target / current)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier="budget")
    return _tris(obj)


def export_lod(lod):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    # swarm_blender caches primitive meshes in _mesh; joining or decimating
    # must not reuse a combined leftover as the next LOD's "box".
    cached = globals()
    mesh_cache = cached.get("_mesh")
    if mesh_cache is not None:
        mesh_cache.clear()
    rim_cache = cached.get("_rim")
    if rim_cache is not None:
        rim_cache.clear()
    for coll in (bpy.data.meshes, bpy.data.curves, bpy.data.objects):
        for block in list(coll):
            if getattr(block, "users", 1) == 0:
                coll.remove(block)
    build = cached.get("sentinel")
    if build is None:
        raise RuntimeError("swarm_blender.sentinel() did not load")
    root = build((0.0, 0.0, 0.0), 0.0, "#a78bfa", 1.0, eyes=9, tent=10, lod=lod, name=f"LOD{lod}")
    _convert_curves(root)
    for obj in list(_walk(root)):
        if obj.type == "MESH" and obj.data is not None and obj.data.users > 1:
            obj.data = obj.data.copy()
    groups = {"hull": [], "emissive": [], "lens": []}
    for obj in _walk(root):
        if obj.type != "MESH":
            continue
        mat = obj.active_material.name if obj.active_material else ""
        groups[_bucket(mat)].append(obj)
    parts = []
    raw = {}
    for key, objs in groups.items():
        joined = _join(objs, f"lod{lod}_{key}")
        if joined is None:
            continue
        raw[key] = _tris(joined)
        bpy.ops.object.select_all(action="DESELECT")
        joined.select_set(True)
        bpy.context.view_layer.objects.active = joined
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        joined.parent = root
        joined.location = (0.0, 0.0, 0.0)
        joined.rotation_euler = (0.0, 0.0, 0.0)
        joined.scale = (1.0, 1.0, 1.0)
        parts.append(joined)
    total = sum(_tris(p) for p in parts)
    target = TARGETS[lod]
    if total > target and total > 0:
        for p in parts:
            share = max(32, int(target * (_tris(p) / total)))
            _decimate(p, share)
    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = root
    dest = DEST / f"sentinel_lod{lod}.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(dest),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_extras=False,
        export_cameras=False,
        export_lights=False,
    )
    counts = {p.name: _tris(p) for p in parts}
    return {
        "lod": lod,
        "path": str(dest),
        "raw_by_part": raw,
        "tris_by_part": counts,
        "tris": sum(counts.values()),
        "target": target,
    }


report = [export_lod(lod) for lod in (0, 1, 2)]
(DEST / "export_report.json").write_text(__import__("json").dumps(report, indent=2))
print("REPORT", __import__("json").dumps(report, indent=2))
