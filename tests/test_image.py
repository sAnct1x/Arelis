"""Image generation helpers — no live ComfyUI."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from arelis.tools.comfy_client import (
    DEFAULT_CHECKPOINT,
    apply_style,
    img2img_workflow,
    inpaint_workflow,
    looks_sdxl,
    pick_checkpoint,
    size_for_aspect,
    txt2img_workflow,
    wait_for_image,
)
from arelis.tools.comfy_lifecycle import default_comfy_roots, discover_comfy
from arelis.tools.image import (
    REMBG_MISSING,
    ImageTool,
    clamp_n,
    mask_from_region,
    pad_for_outpaint,
    rembg_cut,
)
from arelis.tools.image_meta import read_named_sidecar, read_sidecar, write_sidecar


def test_size_for_aspect_is_a_multiple_of_eight() -> None:
    width, height = size_for_aspect("16:9", 768)
    assert width == 768
    assert height == 432
    assert width % 8 == 0 and height % 8 == 0


def test_portrait_aspect_is_taller() -> None:
    width, height = size_for_aspect("9:16", 768)
    assert height > width
    assert height == 768


def test_apply_style_folds_into_the_prompt() -> None:
    prompt, negative = apply_style("a fox", "blurry", "watercolor")
    assert "fox" in prompt
    assert "watercolor" in prompt
    assert "blurry" in negative
    assert "photograph" in negative


def test_unknown_style_names_the_known_ones() -> None:
    try:
        apply_style("a fox", "", "neon-vapor")
    except ValueError as exc:
        assert "watercolor" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_pick_checkpoint_prefers_sdxl_when_present() -> None:
    chosen = pick_checkpoint(
        ["v1-5-pruned-emaonly.safetensors", "sdxl_base.safetensors"]
    )
    assert chosen == "sdxl_base.safetensors"
    assert looks_sdxl(chosen)


def test_pick_checkpoint_keeps_an_explicit_name() -> None:
    assert (
        pick_checkpoint(["sdxl_base.safetensors"], "v1-5-pruned-emaonly.safetensors")
        == "v1-5-pruned-emaonly.safetensors"
    )


def test_pick_checkpoint_falls_back_when_comfy_is_quiet() -> None:
    assert pick_checkpoint([]) == DEFAULT_CHECKPOINT


def test_txt2img_workflow_injects_the_prompt() -> None:
    workflow = txt2img_workflow(
        prompt="a red balloon",
        negative="blurry",
        width=768,
        height=512,
        seed=7,
        checkpoint="demo.safetensors",
        steps=30,
        cfg=6.5,
    )
    assert workflow["6"]["inputs"]["text"] == "a red balloon"
    assert workflow["5"]["inputs"]["width"] == 768
    assert workflow["5"]["inputs"]["height"] == 512
    assert workflow["3"]["inputs"]["denoise"] == 1
    assert workflow["4"]["inputs"]["ckpt_name"] == "demo.safetensors"


def test_img2img_workflow_loads_the_source() -> None:
    workflow = img2img_workflow(
        prompt="watercolor fox",
        negative="blurry",
        seed=3,
        checkpoint="demo.safetensors",
        image_name="fox.png",
        denoise=0.55,
    )
    assert workflow["10"]["class_type"] == "LoadImage"
    assert workflow["10"]["inputs"]["image"] == "fox.png"
    assert workflow["5"]["class_type"] == "VAEEncode"
    assert workflow["3"]["inputs"]["denoise"] == 0.55


def test_inpaint_workflow_uses_vae_encode_for_inpaint() -> None:
    workflow = inpaint_workflow(
        prompt="fill the left",
        negative="blurry",
        seed=2,
        checkpoint="demo.safetensors",
        image_name="fox.png",
        mask_name="fox-mask.png",
    )
    assert workflow["10"]["class_type"] == "LoadImage"
    assert workflow["11"]["class_type"] == "LoadImage"
    assert workflow["11"]["inputs"]["image"] == "fox-mask.png"
    assert workflow["5"]["class_type"] == "VAEEncodeForInpaint"
    assert workflow["5"]["inputs"]["mask"] == ["12", 0]
    assert workflow["3"]["inputs"]["denoise"] == 0.75


def test_image_tool_schema_covers_restyle() -> None:
    props = ImageTool.parameters_schema["properties"]
    assert "path" in props
    assert "style" in props
    assert "aspect" in props
    assert "denoise" in props
    assert "watercolor" in props["style"]["enum"]
    assert "n" in props
    assert "upscale" in props
    assert "mask_region" in props
    assert "outpaint" in props
    assert "remove_background" in props
    assert "center" in props["mask_region"]["enum"]


def test_discover_comfy_finds_main_py(tmp_path: Path) -> None:
    root = tmp_path / "ComfyUI"
    root.mkdir()
    (root / "main.py").write_text("# fake comfy\n", encoding="utf-8")
    empty = tmp_path / "empty"
    empty.mkdir()
    assert discover_comfy(roots=[empty, root]) == root


def test_discover_comfy_finds_nested_main_and_bat(tmp_path: Path) -> None:
    nested = tmp_path / "portable"
    (nested / "ComfyUI").mkdir(parents=True)
    (nested / "ComfyUI" / "main.py").write_text("# nested\n", encoding="utf-8")
    assert discover_comfy(roots=[nested]) == nested

    bats = tmp_path / "bats"
    bats.mkdir()
    (bats / "run_nvidia_gpu.bat").write_text("@echo off\n", encoding="utf-8")
    assert discover_comfy(roots=[bats]) == bats


def test_discover_comfy_skips_a_folder_without_markers(tmp_path: Path) -> None:
    decoy = tmp_path / "Documents"
    decoy.mkdir()
    (decoy / "notes.txt").write_text("no\n", encoding="utf-8")
    assert discover_comfy(roots=[decoy]) is None


def test_default_comfy_roots_are_the_documented_list() -> None:
    roots = default_comfy_roots()
    home = Path.home()
    assert home / "ComfyUI" in roots
    assert home / "Documents" / "ComfyUI" in roots
    assert home / "Documents" / "ComfyUI" / "ComfyUI_windows_portable" in roots
    assert home / "Documents" / "ComfyUI_windows_portable" in roots
    assert home / "Desktop" / "ComfyUI" in roots
    assert Path("C:/ComfyUI") in roots
    assert Path("C:/ComfyUI_windows_portable") in roots
    assert all(root.name != "" for root in roots)


class _EmptyHistory:
    async def get(self, url: str, **kwargs: Any) -> Any:
        del url, kwargs

        class _Resp:
            def json(self) -> dict[str, Any]:
                return {}

        return _Resp()


def test_wait_for_image_surfaces_oom_from_history() -> None:
    from arelis.tools.comfy_client import wait_for_image

    class _OomHistory:
        async def get(self, url: str, **kwargs: Any) -> Any:
            del url, kwargs

            class _Resp:
                def json(self) -> dict[str, Any]:
                    return {
                        "job-oom": {
                            "status": {
                                "status_str": "error",
                                "messages": [
                                    [
                                        "execution_error",
                                        {
                                            "exception_message": (
                                                "Could not allocate tensor. "
                                                "There is not enough GPU video memory available!"
                                            )
                                        },
                                    ]
                                ],
                            }
                        }
                    }

            return _Resp()

    name, err = asyncio.run(
        wait_for_image(
            _OomHistory(),  # type: ignore[arg-type]
            "http://127.0.0.1:8188",
            "job-oom",
            attempts=2,
            interval_s=0,
        )
    )
    assert name is None
    assert "memory" in err.lower()


def test_wait_for_image_timeout_is_fail() -> None:
    name, err = asyncio.run(
        wait_for_image(
            _EmptyHistory(),  # type: ignore[arg-type]
            "http://127.0.0.1:8188",
            "job-9",
            attempts=2,
            interval_s=0,
        )
    )
    assert name is None
    assert err
    assert "job-9" in err
    assert "Queued" not in err


def test_image_tool_timeout_is_fail(tmp_path: Path, monkeypatch: Any) -> None:
    async def _boot(*_a: Any, **_k: Any) -> None:
        return None

    async def _list(*_a: Any, **_k: Any) -> list[str]:
        return ["demo.safetensors"]

    async def _queue(*_a: Any, **_k: Any) -> tuple[str, str]:
        return "pid-1", ""

    async def _wait(*_a: Any, **_k: Any) -> tuple[None, str]:
        return None, "ComfyUI did not produce an image for job pid-1 within 120s."

    monkeypatch.setattr("arelis.tools.image.ensure_comfy_running", _boot)
    monkeypatch.setattr("arelis.tools.image.list_checkpoints", _list)
    monkeypatch.setattr("arelis.tools.image.queue_workflow", _queue)
    monkeypatch.setattr("arelis.tools.image.wait_for_image", _wait)

    tool = ImageTool(comfy_url="http://127.0.0.1:9", output_dir=str(tmp_path))
    result = asyncio.run(tool.run(prompt="a fox"))
    assert result.ok is False
    assert "[fail:image]" in result.output
    assert "Queued" not in result.output


def test_image_tool_reports_progress(tmp_path: Path, monkeypatch: Any) -> None:
    seen: list[str] = []

    async def _boot(*_a: Any, **_k: Any) -> None:
        return None

    async def _list(*_a: Any, **_k: Any) -> list[str]:
        return ["demo.safetensors"]

    async def _queue(*_a: Any, **_k: Any) -> tuple[str, str]:
        return "pid-1", ""

    async def _wait(*_a: Any, on_progress: Any = None, **_k: Any) -> tuple[None, str]:
        if on_progress is not None:
            on_progress(3, 10)
        return None, "ComfyUI did not produce an image for job pid-1 within 120s."

    monkeypatch.setattr("arelis.tools.image.ensure_comfy_running", _boot)
    monkeypatch.setattr("arelis.tools.image.list_checkpoints", _list)
    monkeypatch.setattr("arelis.tools.image.queue_workflow", _queue)
    monkeypatch.setattr("arelis.tools.image.wait_for_image", _wait)

    tool = ImageTool(comfy_url="http://127.0.0.1:9", output_dir=str(tmp_path))
    tool.set_progress(seen.append)
    result = asyncio.run(tool.run(prompt="a fox", n=2))
    assert result.ok is False
    assert any("picture 1 of 2" in line for line in seen)
    assert any("(3/10)" in line for line in seen)


def test_sidecar_roundtrip(tmp_path: Path) -> None:
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG")
    write_sidecar(
        png,
        prompt="a fox",
        negative="blurry",
        seed=11,
        checkpoint="demo.safetensors",
        width=768,
        height=512,
        style="oil",
        mode="txt2img",
        source="",
        denoise=1.0,
        n=2,
    )
    data = read_sidecar(png)
    assert data["prompt"] == "a fox"
    assert data["negative"] == "blurry"
    assert data["seed"] == 11
    assert data["checkpoint"] == "demo.safetensors"
    assert data["width"] == 768
    assert data["height"] == 512
    assert data["style"] == "oil"
    assert data["mode"] == "txt2img"
    assert data["n"] == 2


def test_named_sidecar_reads_under_the_data_root(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    folder = tmp_path / "outputs" / "images"
    folder.mkdir(parents=True)
    png = folder / "arelis_seed.png"
    png.write_bytes(b"\x89PNG")
    write_sidecar(
        png,
        prompt="a fox",
        negative="blurry",
        seed=42,
        checkpoint="demo.safetensors",
        width=768,
        height=768,
        style="",
        mode="txt2img",
        source="",
        denoise=1.0,
        n=1,
    )
    data = read_named_sidecar("outputs/images/arelis_seed.png")
    assert data["seed"] == 42
    assert data["prompt"] == "a fox"


def test_mask_region_bitmap_size() -> None:
    mask = mask_from_region(200, 100, "left")
    assert mask.size == (200, 100)
    assert mask.getpixel((10, 50)) == 255
    assert mask.getpixel((160, 50)) == 0
    center = mask_from_region(200, 100, "center")
    assert center.size == (200, 100)
    assert center.getpixel((100, 50)) == 255
    assert center.getpixel((4, 4)) == 0


def test_outpaint_padded_size() -> None:
    from PIL import Image

    src = Image.new("RGB", (80, 40), (10, 20, 30))
    canvas, mask = pad_for_outpaint(src, "right")
    assert canvas.size[1] == 40
    assert canvas.size[0] >= 80 + int(80 * 0.2)
    assert mask.size == canvas.size
    assert canvas.getpixel((0, 0)) == (10, 20, 30)
    assert mask.getpixel((0, 0)) == 0
    assert mask.getpixel((canvas.size[0] - 1, 0)) == 255
    wide, wide_mask = pad_for_outpaint(src, "all")
    assert wide.size[0] > 80 and wide.size[1] > 40
    assert wide_mask.size == wide.size


def test_n_clamp_is_one_to_four() -> None:
    assert clamp_n(0) == 1
    assert clamp_n(-3) == 1
    assert clamp_n(1) == 1
    assert clamp_n(4) == 4
    assert clamp_n(5) == 4
    assert clamp_n("3") == 3
    assert clamp_n(None) == 1


def test_remove_background_missing_rembg(tmp_path: Path, monkeypatch: Any) -> None:
    import builtins

    real_import = builtins.__import__

    def _blocked(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "rembg" or name.startswith("rembg."):
            raise ImportError("no rembg")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    png = tmp_path / "cut.png"
    png.write_bytes(b"\x89PNG")
    try:
        rembg_cut(png)
    except RuntimeError as exc:
        assert str(exc) == REMBG_MISSING
        assert "[fail:image]" in str(exc)
    else:
        raise AssertionError("expected rembg missing to fail")
