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
