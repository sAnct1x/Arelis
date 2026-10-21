"""An old config that names the retired chat server still loads."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from arelis.llm import build_router
from arelis.llm.legacy import LEGACY_PROVIDER, LEGACY_SECTION, migrate_engine_config
from arelis.llm.llamacpp import LlamaCppProvider


def test_retired_engine_config_loads_as_llama_cpp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = {
        "llm": {"provider": LEGACY_PROVIDER},
        LEGACY_SECTION: {"base_url": "http://127.0.0.1:9", "num_ctx": 1024},
        "llamacpp": {"base_url": "http://127.0.0.1:8080"},
        "models": {"fast": "qwen3.5:9b"},
        "router": {},
    }
    migrated = migrate_engine_config({**raw})
    assert migrated["llm"]["provider"] == "llamacpp"
    assert LEGACY_SECTION not in migrated
    assert migrated["llamacpp"]["base_url"] == "http://127.0.0.1:8080"

    router = build_router(
        {
            "llm": {"provider": LEGACY_PROVIDER},
            LEGACY_SECTION: {"base_url": "http://127.0.0.1:9"},
            "llamacpp": {"base_url": "http://127.0.0.1:8080"},
            "models": {"fast": "qwen3.5:9b"},
            "router": {},
        }
    )
    assert isinstance(router.provider, LlamaCppProvider)
    assert router.provider.base_url == "http://127.0.0.1:8080"

    local = tmp_path / "config.local.yaml"
    local.write_text(
        yaml.safe_dump(
            {
                "llm": {"provider": LEGACY_PROVIDER},
                LEGACY_SECTION: {"base_url": "http://127.0.0.1:9", "num_ctx": 1024},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("arelis.config.LOCAL_CONFIG_PATH", local)
    from arelis.config import load_config

    loaded = load_config()
    assert loaded["llm"]["provider"] == "llamacpp"
    assert LEGACY_SECTION not in loaded
    assert loaded["llamacpp"]["base_url"]
