"""balsam drops glTF tracks that hold a bone at rest; the converter must restore them."""

import re

from arelis.ui.persona_q3d.convert import disable_timelines, fill_missing_tracks

QML = """Node {
    Node {
        id: thumb
        objectName: "CC_Base_L_Thumb2"
        rotation: Qt.quaternion(0.9, -0.1, 0, 0.05)
        scale: Qt.vector3d(1, 1, 1)
    }
    Timeline {
        objectName: "Talking"
        enabled: true
        KeyframeGroup {
            target: thumb
            property: "rotation"
            keyframeSource: "animations/thumb_rotation_0.qad"
        }
    }
    Timeline {
        objectName: "Idle"
        enabled: true
    }
}
"""


def test_clip_without_a_track_gets_the_rest_pose():
    out, added = fill_missing_tracks(disable_timelines(QML))
    assert added == 1
    idle = out[out.index('objectName: "Idle"') :]
    assert re.search(
        r'target: thumb\s+property: "rotation"\s+Keyframe \{ frame: 0; value: Qt.quaternion\(0.9, -0.1, 0, 0.05\) \}',
        idle,
    )
    assert out.count("KeyframeGroup") == 2  # Talking keeps its own track only
    assert "enabled: true" not in out


def test_no_depth_test_pins_z_inside_main():
    from arelis.ui.persona_q3d.port import no_depth_test

    vert = "void helper() { }\nvoid MAIN() { if (true) { POSITION = vec4(0.0); } }\n"
    out = no_depth_test(vert)
    main = out[out.index("void MAIN") :]
    assert "NEAR_CLIP_VALUE" in main
    assert main.rstrip().endswith("}")
    assert "NEAR_CLIP_VALUE" not in out[: out.index("void MAIN")]


def test_point_layers_do_not_rely_on_point_size():
    """D3D11 and Metal ignore gl_PointSize (every point is 1 px): points must be sized quads."""
    import numpy as np

    from arelis.ui.persona_q3d.geometry import sprite_arrays, sprite_index
    from arelis.ui.persona_q3d.port import GALAXY_VERT, point_sprites, translate

    three = (
        "attribute float seed; uniform float uPx; varying float vS;\n"
        "void main(){ vS=seed; vec4 mv=viewMatrix*vec4(position,1.0); gl_Position=projectionMatrix*mv;\n"
        "  gl_PointSize=(0.9+1.1*seed)*uPx*(3.0/-mv.z); }"
    )
    vert = point_sprites(translate(three, "vert", {}), "vert")
    for src in (vert, GALAXY_VERT):
        assert "POINT_SIZE" not in src and "gl_PointSize" not in src
        assert "POSITION.xy += UV1 *" in src
    assert "(0.9+1.1*seed)*uPx*(3.0/-mv.z)" in vert
    frag = point_sprites(
        "VARYING float vS;\nvoid MAIN(){ float d=length(gl_PointCoord-0.5); }", "frag"
    )
    assert "gl_PointCoord" not in frag and "VARYING vec2 vPc;" in frag

    arrays = {"position": np.arange(6, dtype=np.float32), "seed": np.array([0.25, 0.5], np.float32)}
    out, spec = sprite_arrays(arrays, "VERTEX=position;UV0=seed")
    assert spec.endswith(";UV1=_corner")
    assert out["seed"].tolist() == [0.25] * 4 + [0.5] * 4
    assert np.abs(out["_corner"]).max() == 0.5 and len(out["_corner"]) == 16
    assert sprite_index(2).tolist() == [0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7]
