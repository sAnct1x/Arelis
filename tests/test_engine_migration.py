"""An old config that names the retired chat server still loads."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from arelis.config import DEFAULT_CONFIG_PATH
from arelis.llm import build_router
from arelis.llm.legacy import LEGACY_PROVIDER, LEGACY_SECTION, migrate_engine_config
from arelis.llm.llama_launch import MODEL_FILENAME, launch_args_for
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


def test_old_ollama_model_names_resolve_to_35b_launch_args(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """name:tag roles from an old config launch the 35B with config C.

    A missing GGUF returns None. It does not raise.
    """
    shipped = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert shipped["models"]["fast"] == "Qwen3.6-35B-A3B"
    assert shipped["models"]["research"] == "Qwen3.6-35B-A3B"
    assert shipped["models"]["vision"] == "Qwen3.6-35B-A3B"
    assert shipped["llamacpp"]["model"] == MODEL_FILENAME

    weights = tmp_path / MODEL_FILENAME
    weights.write_bytes(b"gguf")
    monkeypatch.setattr("arelis.paths.models_dir", lambda: tmp_path)
    monkeypatch.setattr("arelis.llm.llama_launch._cache_roots", lambda: [])

    config = {
        "llm": {"provider": LEGACY_PROVIDER},
        LEGACY_SECTION: {"base_url": "http://127.0.0.1:11434", "num_ctx": 1024},
        "models": {
            "fast": "qwen3.5:9b",
            "research": "llama3:8b",
            "vision": "qwen2.5vl:3b",
        },
        "llamacpp": {"base_url": "http://127.0.0.1:8080"},
    }
    migrate_engine_config(config)
    assert LEGACY_SECTION not in config
    assert config["llm"]["provider"] == "llamacpp"
    assert config["models"]["fast"] == "Qwen3.6-35B-A3B"
    assert config["models"]["research"] == "Qwen3.6-35B-A3B"
    assert config["models"]["vision"] == "Qwen3.6-35B-A3B"
    assert config["llamacpp"]["model"] == MODEL_FILENAME

    args = launch_args_for(config)
    assert args is not None
    assert args[args.index("-m") + 1] == str(weights.resolve())
    assert args[args.index("--mmproj") + 1] == str(
        (tmp_path / "mmproj-Qwen3.6-35B-A3B-Q8_0.gguf").resolve()
    )
    assert args[args.index("--n-cpu-moe") + 1] == "32"
    assert args[args.index("-fa") + 1] == "off"
    assert args[args.index("--image-max-tokens") + 1] == "1024"
    assert args[args.index("--cache-type-k") + 1] == "f16"
    assert args[args.index("--cache-type-v") + 1] == "f16"

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr("arelis.paths.models_dir", lambda: empty)
    missing = {
        "models": {
            "fast": "qwen3.5:9b",
            "research": "qwen3.5:9b",
            "vision": "qwen2.5vl:3b",
        },
    }
    migrate_engine_config(missing)
    assert missing["models"]["vision"] == "Qwen3.6-35B-A3B"
    assert launch_args_for(missing) is None
