"""Image fail-replan copy must match the real picture backend."""

from __future__ import annotations

from arelis.core.fail_tags import tool_fail_replan_notice


def test_sdcpp_crash_replan_does_not_blame_comfyui() -> None:
    output = "[fail:image] The picture program stopped before it finished."
    config = {"tools": {"image": {"backend": "sdcpp"}}}
    line = tool_fail_replan_notice("image", output, ok=False, config=config)
    assert line is not None
    lowered = line.lower()
    assert "comfyui" not in lowered
    assert "auto_start" not in lowered
    assert "picture could not be made" in lowered
    comfy = tool_fail_replan_notice(
        "image",
        output,
        ok=False,
        config={"tools": {"image": {"backend": "comfy"}}},
    )
    assert comfy is not None
    assert "ComfyUI" in comfy
