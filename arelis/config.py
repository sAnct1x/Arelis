from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config" / "default.yaml"
LOCAL_CONFIG_PATH = PROJECT_ROOT / "data" / "config.local.yaml"


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge overlay into base (mutates base) and return it."""
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def merge_local_config(patch: dict[str, Any], path: Path | None = None) -> Path:
    """Merge a patch into data/config.local.yaml. Never writes default.yaml."""
    target = path or LOCAL_CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if target.is_file():
        existing = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if not isinstance(existing, dict):
            existing = {}
    deep_merge(existing, patch)
    target.write_text(
        yaml.safe_dump(existing, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return target


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load YAML config and resolve every path in it to an absolute one.

    Resolution happens here, once, so the sandbox never has to reason about the
    process working directory. Arelis can be started from the Start menu, from
    a shortcut, or from any shell, and "." in workspace.roots has to mean the
    repo either way.

    When ``path`` is omitted, ``data/config.local.yaml`` is deep-merged on top
    of default.yaml so device prefs and toggles can persist without editing the
    shipped file.

    workspace.roots accepts a flat list of path strings (name = directory
    basename) or a list of {name, path, read_only?} mappings. read_only roots
    reject write/edit/create in WorkspaceRoots.resolve.
    """
    cfg_path = path or DEFAULT_CONFIG_PATH
    with cfg_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        data = {}

    if path is None and LOCAL_CONFIG_PATH.is_file():
        local = yaml.safe_load(LOCAL_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        if isinstance(local, dict):
            deep_merge(data, local)

    named_roots = _parse_workspace_roots(data.get("workspace", {}).get("roots", ["."]))
    data.setdefault("workspace", {})
    data["workspace"]["named_roots"] = named_roots
    # Flat absolute paths kept for anything that still reads roots as strings.
    data["workspace"]["roots"] = [entry["path"] for entry in named_roots]

    persona_rel = data.get("persona_file", "persona/arelis.md")
    persona_path = PACKAGE_ROOT / persona_rel
    data["_persona_path"] = str(persona_path)
    data["_project_root"] = str(PROJECT_ROOT)

    # One resolver shared by the agent loop, which injects the summary line, and
    # the user_location tool, which serves the detail. Two instances would mean
    # a refresh through the tool was invisible to the next prompt. Imported here
    # rather than at module scope because the location package reads PROJECT_ROOT
    # back out of this one.
    if (data.get("location") or {}).get("enabled", True):
        from arelis.location import build_location

        data["_location"] = build_location(data)
    return data


def _parse_workspace_roots(roots: list[Any]) -> list[dict[str, Any]]:
    if not roots:
        roots = ["."]
    named: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in roots:
        if isinstance(item, str):
            p = _resolve_root_path(item)
            name = p.name or "root"
            read_only = False
        elif isinstance(item, dict):
            if "path" not in item:
                raise ValueError("workspace.roots entries need a path")
            p = _resolve_root_path(str(item["path"]))
            name = str(item["name"]).strip() if item.get("name") else (p.name or "root")
            read_only = bool(item.get("read_only", False))
        else:
            raise ValueError(f"Invalid workspace.roots entry: {item!r}")
        if not name:
            raise ValueError("workspace root name must not be empty")
        if name in seen:
            raise ValueError(
                f"Duplicate workspace root name `{name}`; "
                "give each root an explicit unique name in config"
            )
        seen.add(name)
        named.append({"name": name, "path": str(p), "read_only": read_only})
    return named


def _resolve_root_path(root: str) -> Path:
    p = Path(root)
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    else:
        p = p.resolve()
    return p


def load_persona(config: dict[str, Any]) -> str:
    path = Path(config["_persona_path"])
    if not path.exists():
        return "You are Arelis, a helpful local research assistant."
    return path.read_text(encoding="utf-8")
