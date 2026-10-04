"""The shape of .github/workflows/pr-text-privacy.yml, pinned the way tests/test_ci_gate.py pins ci.yml.

The workflow reads text that strangers can write. Every property worth protecting is about
what that text can reach: no shell, no write token, no unpinned third-party code, no log
line. A reviewer would check these by eye once; a test checks them on every later edit.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-text-privacy.yml"
SCRIPT = ROOT / "scripts" / "check_pr_text_privacy.py"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers(doc: dict) -> dict:
    # PyYAML reads the bare key `on` as the boolean True.
    return doc.get("on", doc.get(True))


def _steps(doc: dict) -> list[dict]:
    return [step for job in doc["jobs"].values() for step in job["steps"]]


def test_it_runs_on_every_event_that_carries_user_text() -> None:
    triggers = _triggers(_load())
    assert set(triggers) == {
        "pull_request",
        "pull_request_review",
        "pull_request_review_comment",
        "issues",
        "issue_comment",
    }
    assert set(triggers["pull_request"]["types"]) == {"opened", "edited", "synchronize", "reopened"}
    assert set(triggers["issues"]["types"]) == {"opened", "edited"}
    assert set(triggers["issue_comment"]["types"]) == {"created", "edited"}


def test_it_never_uses_the_privileged_pull_request_trigger() -> None:
    """pull_request_target hands fork PRs a write token and secrets, and its run is not tied
    to the PR head commit, so it would be both more dangerous and less visible."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target" not in yaml.dump(_triggers(_load()))
    assert not re.search(r"(?m)^\s*pull_request_target\s*:", text)
    assert "workflow_run" not in yaml.dump(_triggers(_load()))


def test_the_token_is_read_only() -> None:
    doc = _load()
    perms = doc["permissions"]
    assert perms == {"contents": "read", "issues": "read", "pull-requests": "read"}
    for job in doc["jobs"].values():
        assert "permissions" not in job or all(v == "read" for v in job["permissions"].values())
    assert "write" not in yaml.dump(doc["permissions"])


def test_no_expression_is_ever_interpolated_into_a_shell_script() -> None:
    """The one rule that matters: `${{ }}` inside `run:` turns a PR title into code."""
    for step in _steps(_load()):
        if "run" in step:
            assert "${{" not in step["run"], f"expression inside run: of {step.get('name')}"


def test_no_user_text_expression_is_used_anywhere_in_the_workflow() -> None:
    """Even outside run:, a title, body or comment must not be copied into env or a name."""
    text = WORKFLOW.read_text(encoding="utf-8")
    expressions = re.findall(r"\$\{\{(.*?)\}\}", text)
    for expression in expressions:
        for forbidden in (".title", ".body", ".head.ref", ".head_ref", "comment", "label", "message"):
            assert forbidden not in expression, f"user-controlled text in expression: {forbidden}"


def test_the_run_name_is_fixed_so_a_pr_title_is_not_echoed() -> None:
    doc = _load()
    assert "run-name" in doc
    assert "${{" not in doc["run-name"]


def test_third_party_actions_are_pinned_to_a_full_commit_sha() -> None:
    for step in _steps(_load()):
        if "uses" in step:
            ref = step["uses"]
            assert not ref.startswith("./")
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), f"not SHA pinned: {ref}"


def test_checkout_stores_no_credentials_and_takes_only_the_script() -> None:
    checkouts = [s for s in _steps(_load()) if str(s.get("uses", "")).startswith("actions/checkout@")]
    assert len(checkouts) == 1
    options = checkouts[0]["with"]
    assert options["persist-credentials"] is False
    assert options["sparse-checkout"] == "scripts/check_pr_text_privacy.py"
    assert (ROOT / options["sparse-checkout"]).is_file()


def test_the_script_is_run_with_files_and_the_log_cannot_carry_the_text() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--event-file" in text and "GITHUB_EVENT_PATH" in text
    assert "--env-text" not in text, "the Actions log prints step env values"
    assert "set -x" not in text and "echo " not in text


def test_the_username_secret_is_optional_and_only_reaches_the_scan_step() -> None:
    steps = _steps(_load())
    holders = [s["name"] for s in steps if "PRIVACY_CHECK_USERNAMES" in s.get("env", {})]
    assert holders == ["Scan for personal data"]
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets.PRIVACY_CHECK_USERNAMES" in text


def test_the_job_has_a_timeout() -> None:
    for job in _load()["jobs"].values():
        assert job["timeout-minutes"] <= 10


def test_the_script_the_workflow_calls_exists() -> None:
    assert "scripts/check_pr_text_privacy.py" in WORKFLOW.read_text(encoding="utf-8")
    assert SCRIPT.is_file()
