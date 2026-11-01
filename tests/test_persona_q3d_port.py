"""Shader translation rules in persona_q3d.port that decide whether the look matches v14k."""

import re

from arelis.ui.persona_q3d import port


def _projection(vert: str) -> list[str]:
    return re.findall(r"vec4 mv = VIEW_MATRIX \* w;|POSITION = PROJECTION_MATRIX \* mv;", vert)


def test_fills_and_shells_project_the_same_way():
    # The additive shells draw on the fill surfaces at equal depth; any other expression
    # rounds differently and the shells z-fight the fills (specks on the face and hair).
    assert _projection(port.FILL_VERT) == _projection(port.SHELL_VERT)
    assert len(_projection(port.SHELL_VERT)) == 2


def test_card_alpha_is_sampled_with_gltf_v():
    src = "uniform sampler2D uAlphaMap; varying vec2 vUv2;\nvoid main(){ float ca = texture2D(uAlphaMap, vUv2).a; gl_FragColor = vec4(ca); }"
    out = port.translate(src, "frag", {})
    assert "glTFTex(uAlphaMap, vUv2)" in out and "texture2D(" not in out
    assert "1.0 - (uv).y" in port.FRAG_PRE
    assert "glTFTex(uAlphaMap, vUv)" in port.FILL_FRAG["card"]


def test_skin_opacity_defaults_to_v14k_and_spares_the_head():
    assert port.SKIN_OPACITY == 0.0
    skin = port.FILL_FRAG["skin"]
    assert "uSkinOpacity * (1.0 - nA)" in skin
    assert "discard" in skin
