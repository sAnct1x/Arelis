"""On-demand image weights: pinned hashes, a plain failure, CPU sessions."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from arelis.tools.image_models import (
    LATER,
    MISMATCH,
    MODELS,
    OFFLINE,
    UNLICENSED,
    ModelError,
    accept_download,
    ensure_model,
    install_bytes,
)

_GB = 1024**3


def test_hash_mismatch_deletes_the_file(tmp_path: Path) -> None:
    blob = tmp_path / "weights.onnx.part"
    blob.write_bytes(b"this is not the model")

    with pytest.raises(ModelError, match="deleted"):
        accept_download(blob, "ab" * 32)

    assert not blob.exists()
    assert "sha" not in MISMATCH.lower()
    assert "http" not in MISMATCH


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


