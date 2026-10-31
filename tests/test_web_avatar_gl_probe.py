"""The page poll must not leave a new WebGL context behind on every tick."""

from __future__ import annotations

from arelis.ui.persona_face.web_avatar import check_script


def test_only_the_first_poll_probes_webgl_and_it_releases_the_context() -> None:
    first = check_script(probe_gl=True)
    assert "getContext('webgl2')" in first and "loseContext()" in first
    assert "getContext" not in check_script(probe_gl=False)
