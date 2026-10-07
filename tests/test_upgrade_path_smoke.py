"""Pure helpers from scripts/upgrade_path_smoke.py. No Windows, no installer."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_ui

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "upgrade_path_smoke.py"


def _mod():
    spec = importlib.util.spec_from_file_location("upgrade_path_smoke", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_next_patch_version_bumps_only_the_patch() -> None:
    m = _mod()
    assert m.next_patch_version("0.3.0") == "0.3.1"
    assert m.next_patch_version("0.3.9") == "0.3.10"
    assert m.next_patch_version(" 1.2.3 ") == "1.2.4"


def test_next_patch_version_rejects_a_short_number() -> None:
    m = _mod()
    try:
        m.next_patch_version("0.3")
    except ValueError as exc:
        assert "0.3" in str(exc)
    else:
        raise AssertionError("0.3 should not be a version this job will stamp")


def test_rewrite_version_assignment_keeps_the_other_string() -> None:
    m = _mod()
    text = '"""doc"""\n__version__ = "0.3.0"\nOTHER = "0.3.0"\n'
    updated = m.rewrite_version_assignment(text, "0.3.1")
    assert updated == '"""doc"""\n__version__ = "0.3.1"\nOTHER = "0.3.0"\n'
    assert m.version_assignment(updated) == "0.3.1"

    single = "__version__ = '0.3.0'\n"
    assert m.rewrite_version_assignment(single, "0.3.2") == "__version__ = '0.3.2'\n"


def test_bump_tree_version_refuses_the_checkout_and_edits_a_copy(tmp_path: Path) -> None:
    m = _mod()
    repo = tmp_path / "repo"
    checkout = repo / "arelis" / "__init__.py"
    checkout.parent.mkdir(parents=True)
    original = '__version__ = "0.3.0"\n'
    checkout.write_text(original, encoding="utf-8")

    try:
        m.bump_tree_version(checkout, "0.3.1", repo)
    except RuntimeError as exc:
        assert "checkout" in str(exc)
    else:
        raise AssertionError("the checkout version must not be rewritten")
    assert checkout.read_text(encoding="utf-8") == original

    tree = tmp_path / "dist" / "Arelis" / "Lib" / "site-packages" / "arelis"
    tree.mkdir(parents=True)
    init_py = tree / "__init__.py"
    init_py.write_text(original, encoding="utf-8")
    cache = tree / "__pycache__"
    cache.mkdir()
    stale = cache / "__init__.cpython-314.pyc"
    stale.write_bytes(b"stale")

    m.bump_tree_version(init_py, "0.3.1", repo)
    assert init_py.read_text(encoding="utf-8") == '__version__ = "0.3.1"\n'
    assert not stale.exists()
    assert checkout.read_text(encoding="utf-8") == original


def test_version_line_has_does_not_treat_0_3_1_as_0_3_10() -> None:
    m = _mod()
    assert m.version_line_has("arelis 0.3.1\n", "0.3.1")
    assert m.version_line_has("arelis 0.3.1 extra", "0.3.1")
    assert not m.version_line_has("arelis 0.3.10\n", "0.3.1")
    assert not m.version_line_has("arelis 0.3.10 extra", "0.3.1")
    assert not m.version_line_has("arelis 0.3.1", "0.3.10")


def test_parse_sha256_line_and_setup_name() -> None:
    m = _mod()
    digest = "ab" * 32
    parsed, name = m.parse_sha256_line(f"# note\n{digest}  Arelis-0.3.0-win64-setup.exe\n")
    assert parsed == digest
    assert name == "Arelis-0.3.0-win64-setup.exe"
    assert m.setup_version_from_name("Arelis-0.3.0-win64-setup.exe") == "0.3.0"
    assert m.setup_version_from_name("Arelis-0.3.10-win64-setup.exe") == "0.3.10"


def test_audit_backup_folder_accepts_a_sibling_and_rejects_the_bad_shapes(tmp_path: Path) -> None:
    m = _mod()
    data = tmp_path / "Arelis"
    state = data / "data"
    state.mkdir(parents=True)
    backups = tmp_path / "Arelis-backups"
    kept = backups / "pre-0.3.0"
    kept.mkdir(parents=True)
    (kept / "memory.db").write_bytes(b"not a secret")
    (kept / "rooms.yaml").write_text("rooms: {}\n", encoding="utf-8")
    assert m.audit_backup_folder(backups, data) == []

    inside = data / "backups" / "pre-0.3.0"
    inside.mkdir(parents=True)
    problems = m.audit_backup_folder(data / "backups", data)
    assert any("inside the data folder" in item for item in problems)

    leaked = backups / "pre-0.3.1"
    leaked.mkdir()
    (leaked / "secrets.yaml").write_text(f"token: {m.SENTINEL}\n", encoding="utf-8")
    problems = m.audit_backup_folder(backups, data)
    assert any("secrets.yaml" in item for item in problems)

    (leaked / "secrets.yaml").unlink()
    (leaked / "rooms.yaml").write_bytes(m.SENTINEL.encode("utf-8"))
    problems = m.audit_backup_folder(backups, data)
    assert any("secret token" in item for item in problems)
    (leaked / "rooms.yaml").unlink()

    partial = backups / ".pre-0.3.2.abc.partial"
    partial.mkdir()
    problems = m.audit_backup_folder(backups, data)
    assert any("half-finished" in item for item in problems)
    partial.rmdir()

    extra = backups / "pre-ci.3"
    extra.mkdir()
    problems = m.audit_backup_folder(backups, data)
    assert any("only the newest two" in item for item in problems)


def test_seed_fact_source_is_one_v0_3_0_accepts() -> None:
    """Published 0.3.0 rejects any fact source other than explicit or proposed."""
    import ast

    m = _mod()
    tree = ast.parse(m.child_source(m.SEED_MEMORY_PY))
    sources = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else ""
        if name != "add_fact":
            continue
        for keyword in node.keywords:
            if keyword.arg == "source" and isinstance(keyword.value, ast.Constant):
                sources.append(keyword.value.value)
    assert sources == ["explicit"]


def test_headless_hook_calls_exec_with_no_arguments() -> None:
    """PySide6 QApplication.exec() is static. Passing the instance raises."""
    import ast

    m = _mod()
    tree = ast.parse(m.child_source(m.HEADLESS_PY))
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_exec":
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "original"
            ):
                calls.append((len(inner.args), len(inner.keywords)))
    assert calls == [(0, 0)]


def test_child_scripts_parse() -> None:
    m = _mod()
    sources = m.compiled_child_scripts()
    assert set(sources) == {
        "headless_launch.py",
        "seed_memory.py",
        "inspect_state.py",
        "backup_keep.py",
        "updater_launch.py",
        "failure_probe.py",
    }
    assert "backup_before_upgrade" in sources["updater_launch.py"]
    assert "start_installer" in sources["updater_launch.py"]
    assert "backup_before_upgrade" in sources["failure_probe.py"]
    assert "update_prompt.start_installer = tripwire" in sources["failure_probe.py"]
