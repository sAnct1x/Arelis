"""On-demand image weights: pinned hashes, a plain failure, CPU sessions."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx
import pytest

from arelis.tools.confirm_copy import confirm_headline
from arelis.tools.image_models import (
    ALLOW_ABOVE,
    DISK,
    IDLE_S,
    LATER,
    MISMATCH,
    MODELS,
    OFFLINE,
    UNLICENSED,
    ModelError,
    accept_download,
    allow_headline,
    download_needs_allow,
    drop_idle,
    ensure_model,
    install_bytes,
    intra_threads,
    license_allowed,
    matting_model_name,
    open_cpu_session,
)
from arelis.tools.policy import always_pause

_GB = 1024**3


def test_hash_mismatch_deletes_the_file(tmp_path: Path) -> None:
    blob = tmp_path / "weights.onnx.part"
    blob.write_bytes(b"this is not the model")

    with pytest.raises(ModelError, match="deleted"):
        accept_download(blob, "ab" * 32)

    assert not blob.exists()
    assert "sha" not in MISMATCH.lower()
    assert "http" not in MISMATCH


def test_a_bad_download_is_deleted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("arelis.tools.image_models.models_dir", lambda: tmp_path)

    def _bad(_url: str, dest: Path, _need: int) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"still wrong")

    monkeypatch.setattr("arelis.tools.image_models._download", _bad)
    with pytest.raises(ModelError, match="deleted"):
        ensure_model("u2netp")

    assert not any(tmp_path.rglob("*.onnx"))
    assert not any(tmp_path.rglob("*.part"))


def test_offline_and_http_errors_are_plain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("arelis.tools.image_models.models_dir", lambda: tmp_path)

    class _Down:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def stream(self, *args: object, **kwargs: object):
            raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: _Down())
    with pytest.raises(ModelError) as offline:
        ensure_model("u2netp")
    message = str(offline.value)
    assert message == OFFLINE
    assert "http" not in message
    assert "/" not in message

    class _Busy:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def stream(self, *args: object, **kwargs: object):
            response = httpx.Response(503, request=httpx.Request("GET", "https://example.invalid"))
            raise httpx.HTTPStatusError("nope", request=response.request, response=response)

    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: _Busy())
    with pytest.raises(ModelError) as later:
        ensure_model("u2netp")
    assert str(later.value) == LATER
    assert "503" not in str(later.value)


def test_low_disk_is_plain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("arelis.tools.image_models.models_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "arelis.tools.image_models.shutil.disk_usage",
        lambda _path: type("Usage", (), {"free": 10})(),
    )
    with pytest.raises(ModelError) as exc:
        ensure_model("u2netp")
    assert str(exc.value) == DISK
    assert "/" not in str(exc.value)


def test_matting_does_not_import_rembg() -> None:
    root = Path(__file__).resolve().parents[1] / "arelis" / "tools"
    for name in ("image_models.py", "image_matting.py", "image_upscale.py"):
        text = (root / name).read_text(encoding="utf-8").lower()
        assert "import rembg" not in text
        assert "from rembg" not in text
        assert "cudaexecutionprovider" not in text


def test_registry_has_no_noncommercial_weights() -> None:
    banned = ("rmbg-1.4", "rmbg-2.0", "rmbg")
    for name, spec in MODELS.items():
        assert license_allowed(spec.license)
        assert "non-commercial" not in spec.license.lower()
        assert "noncommercial" not in spec.license.lower()
        assert spec.sha256 and len(spec.sha256) == 64
        assert spec.url.startswith("https://")
        assert spec.bytes > 0
        assert spec.input_size[0] > 0 and spec.input_size[1] > 0
        for word in banned:
            assert word not in name
    assert not license_allowed("non-commercial")
    assert license_allowed("non-commercial", opt_in=True)
    assert "isnet-general-use" in MODELS
    assert "birefnet-general-lite" in MODELS
    assert "u2netp" in MODELS
    assert "realesrgan-x4v3" in MODELS


def test_noncommercial_bytes_are_refused(tmp_path: Path) -> None:
    spec = MODELS["u2netp"]
    refused = type(spec)(
        name=spec.name,
        version=spec.version,
        url=spec.url,
        sha256=spec.sha256,
        nbytes=spec.bytes,
        license="non-commercial",
        input_size=spec.input_size,
        filename=spec.filename,
    )
    with pytest.raises(ModelError) as exc:
        install_bytes(refused, b"weights", tmp_path)
    assert str(exc.value) == UNLICENSED
    assert not any(tmp_path.rglob("*"))


def test_auto_picks_isnet_below_32_gb() -> None:
    assert matting_model_name("auto", 31 * _GB) == "isnet-general-use"
    assert matting_model_name("auto", 32 * _GB - 1) == "isnet-general-use"
    assert matting_model_name("auto", 32 * _GB) == "birefnet-general-lite"
    assert matting_model_name("u2netp", 64 * _GB) == "u2netp"
    assert matting_model_name("", 8 * _GB) == "isnet-general-use"


def test_a_session_is_freed_after_idle() -> None:
    import arelis.tools.image_models as models

    models._sessions.clear()
    marker = object()
    models._sessions["u2netp"] = (marker, 0.0)
    drop_idle(now=IDLE_S - 0.1)
    assert "u2netp" in models._sessions
    drop_idle(now=IDLE_S)
    assert "u2netp" not in models._sessions
    models._sessions.clear()


def test_sessions_request_cpu_only(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _Options:
        def __init__(self) -> None:
            self.intra_op_num_threads = 0
            self.inter_op_num_threads = 0
            self.enable_cpu_mem_arena = True
            self.enable_mem_pattern = True

    class _Session:
        def __init__(self, path: object, sess_options: _Options, providers: list[str]) -> None:
            captured["path"] = path
            captured["providers"] = list(providers)
            captured["threads"] = sess_options.intra_op_num_threads
            captured["arena"] = sess_options.enable_cpu_mem_arena
            captured["pattern"] = sess_options.enable_mem_pattern

    fake = type("ort", (), {"SessionOptions": _Options, "InferenceSession": _Session})
    monkeypatch.setitem(__import__("sys").modules, "onnxruntime", fake)
    open_cpu_session(Path("weights.onnx"))
    assert captured["providers"] == ["CPUExecutionProvider"]
    assert captured["arena"] is False
    assert captured["pattern"] is False
    assert captured["threads"] == intra_threads()
    assert intra_threads() >= 2


def test_large_missing_model_asks_with_the_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("arelis.tools.image_models.model_is_ready", lambda _spec: False)
    monkeypatch.setattr("arelis.tools.image_models.total_ram_bytes", lambda: 8 * _GB)
    args = {"path": "cat.jpg", "remove_background": True}
    assert MODELS["isnet-general-use"].bytes > ALLOW_ABOVE
    assert download_needs_allow(args)
    assert always_pause("image_edit", args)
    line = confirm_headline("image_edit", args)
    assert line == allow_headline(args)
    assert "179" in line
    assert "MB" in line
    assert "\u2013" not in line and "\u2014" not in line

    monkeypatch.setattr("arelis.tools.image_models.model_is_ready", lambda _spec: True)
    assert not download_needs_allow(args)
    assert not always_pause("image_edit", args)
    assert confirm_headline("image_edit", args) == "cut out the background"


def test_zip_install_keeps_the_sidecar_weights(tmp_path: Path) -> None:
    spec = MODELS["realesrgan-x4v3"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "real_esrgan_general_x4v3-onnx-float/real_esrgan_general_x4v3.onnx",
            b"onnx-bytes",
        )
        archive.writestr(
            "real_esrgan_general_x4v3-onnx-float/real_esrgan_general_x4v3.data",
            b"data-bytes",
        )
    import hashlib

    digest = hashlib.sha256(buffer.getvalue()).hexdigest()
    pinned = type(spec)(
        name=spec.name,
        version="test",
        url=spec.url,
        sha256=digest,
        nbytes=len(buffer.getvalue()),
        license=spec.license,
        input_size=spec.input_size,
        filename=spec.filename,
        archive=True,
    )
    path = install_bytes(pinned, buffer.getvalue(), tmp_path)
    assert path.is_file()
    assert path.read_bytes() == b"onnx-bytes"
    assert path.with_suffix(".data").read_bytes() == b"data-bytes"
    registry = (tmp_path / "images" / f"{pinned.name}-{pinned.version}" / "registry.json").read_text(
        encoding="utf-8"
    )
    assert pinned.license in registry
    assert digest in registry
    assert spec.url in registry
