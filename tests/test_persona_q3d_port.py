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

