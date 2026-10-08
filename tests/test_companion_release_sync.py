"""Companion release name and the tag workflow stay in step with the app.

The phone package version name is a literal in the Gradle file. The tag
workflow may attach an APK only when that build is a signed release.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

import arelis
from arelis.companion_pack import parse_gradle_version

pytestmark = pytest.mark.no_ui

REPO = Path(__file__).resolve().parents[1]
_WORKFLOW = REPO / ".github" / "workflows" / "android-companion.yml"
_GRADLE = REPO / "android" / "arelis-notify" / "app" / "build.gradle.kts"


def _workflow() -> dict:
    loaded = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _steps() -> list[dict]:
    job = _workflow()["jobs"]["unit-tests"]
    steps = job["steps"]
    assert isinstance(steps, list)
    return steps


def _named(name: str) -> dict:
    for step in _steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"workflow has no step named {name}")


def test_companion_version_name_matches_the_app() -> None:
    parsed = parse_gradle_version(_GRADLE.read_text(encoding="utf-8"))
    assert parsed is not None
    assert parsed.version_name == arelis.__version__, (
        "The companion version name must be bumped together with the app version."
    )


def test_tagged_release_attaches_only_a_signed_apk() -> None:
    attach = _named("Attach to a draft release")
    condition = str(attach.get("if") or "")
    assert "refs/tags/" in condition, condition
    assert "steps.apk.outputs.kind" in condition, condition
    assert re.search(r"steps\.apk\.outputs\.kind\s*==\s*['\"]release['\"]", condition), condition


def test_companion_artifact_uploads_on_every_run() -> None:
    upload = next(step for step in _steps() if "upload-artifact" in str(step.get("uses") or ""))
    condition = str(upload.get("if") or "")
    assert "refs/tags" not in condition
    assert "kind" not in condition


def test_assemble_step_records_whether_the_apk_is_a_release() -> None:
    assemble = _named("Assemble APK")
    assert assemble.get("id") == "apk"
    script = str(assemble.get("run") or "")
    wrote = [
        line.strip()
        for line in script.splitlines()
        if "GITHUB_OUTPUT" in line and re.search(r"\bkind=", line)
    ]
    assert wrote, "Assemble APK must write kind to GITHUB_OUTPUT"
