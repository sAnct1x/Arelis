"""End-to-end smoke for the Windows installer: install, launch, upgrade, downgrade, uninstall.

Stdlib only. Orchestration runs on the runner Python; probes use the installed
interpreter under %LOCALAPPDATA%\\Programs\\Arelis. Windows-only steps are guarded
by sys.platform. Outputs land in smoke-out/ and feed $GITHUB_STEP_SUMMARY.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = "sAnct1x/Arelis"
APP_ID = "{8F4C2D31-6A5E-4B7C-9E1D-3A2F5B8C7D40}"
UNINSTALL_KEY = f"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{APP_ID}_is1"
SETUP_NAME_RE = re.compile(
    r"^Arelis-(?P<ver>\d+\.\d+\.\d+(?:[a-zA-Z0-9.+-]*)?)-win64-setup\.exe$",
    re.IGNORECASE,
)
SHA256_LINE_RE = re.compile(r"^([0-9a-f]{64})\s+(\S+)\s*$", re.IGNORECASE)
QTOPENGL_MARK = "QtOpenGL"
DOWNLOAD_BACKOFF_S = (10, 30, 60)
INSTALL_TIMEOUT_S = 600
APP_STOP_TIMEOUT_S = 20
DEFAULT_WINDOW_WAIT_S = 60
LOG_TAIL_BYTES = 2 * 1024 * 1024
WINDOW_WARN_S = 30

# Absolute on purpose: the app runs with cwd=install dir and the Inno uninstaller
# re-launches itself from a temp dir, so a relative path would silently break.
OUT = Path(os.environ.get("SMOKE_OUT", "smoke-out")).resolve()
SUMMARY_PATH = OUT / "summary.json"
META_PATH = OUT / "meta.json"


# --- pure helpers (unit-tested on Linux) ---------------------------------


# Steps that are expected to fail when expect_failure is on.
EXPECTED_RED_STEPS = frozenset(
    {"import-probe", "window-probe", "construct-probe", "welcome-probe", "probe"}
)


def parse_version_from_filename(name: str) -> str:
    """Pull the version from Arelis-<ver>-win64-setup.exe."""
    base = Path(name).name
    match = SETUP_NAME_RE.match(base)
    if not match:
        raise ValueError(f"unrecognised installer name: {base}")
    return match.group("ver")


def parse_sha256_file(text: str) -> tuple[str, str]:
    """Parse '<lowercase hash>  <file name>' from a .sha256 sidecar."""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = SHA256_LINE_RE.match(line)
        if match:
            return match.group(1).lower(), match.group(2)
    raise ValueError("no sha256 digest line found")


def classify_qtopengl_failure(stderr_text: str) -> bool:
    """True when captured stderr names the QtOpenGL missing-module signature."""
    return QTOPENGL_MARK in (stderr_text or "")


def window_title_ok(title: str) -> bool:
    """Visible top-level windows need a non-empty title for the probe."""
    return bool((title or "").strip())


# --- summary bookkeeping -------------------------------------------------


def _ensure_out() -> None:
    OUT.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(path: Path, data: Any) -> None:
    _ensure_out()
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _summary() -> dict[str, Any]:
    data = _load_json(SUMMARY_PATH, {"steps": [], "meta": {}})
    if "steps" not in data:
        data["steps"] = []
    if "meta" not in data:
        data["meta"] = {}
    return data


def record(name: str, status: str, detail: str = "", **extra: Any) -> None:
    """Append one PASS/FAIL/INFO row and refresh the GitHub step summary."""
    status = status.upper()
    if status not in {"PASS", "FAIL", "INFO"}:
        raise ValueError(f"bad status: {status}")
    data = _summary()
    row: dict[str, Any] = {"name": name, "status": status, "detail": detail}
    row.update(extra)
    data["steps"].append(row)
    print(f"[{status}] {name}: {detail}", flush=True)
    _save_json(SUMMARY_PATH, data)
    _write_step_summary(data)


def _write_step_summary(data: dict[str, Any]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not path:
        return
    lines = [
        "### Installer smoke",
        "",
        f"ImageVersion: {os.environ.get('ImageVersion', '(unset)')}",
        f"WINDOW_PROBE_MODE: {window_probe_mode()}",
        "",
        "| Step | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for step in data.get("steps", []):
        detail = str(step.get("detail", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {step.get('name', '')} | {step.get('status', '')} | {detail} |")
    result = data.get("expect_failure_result")
    if result:
        lines.extend(["", result])
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def meta_get() -> dict[str, Any]:
    return _load_json(META_PATH, {})


def meta_update(**kwargs: Any) -> dict[str, Any]:
    data = meta_get()
    data.update(kwargs)
    _save_json(META_PATH, data)
    return data


def window_probe_mode() -> str:
    mode = os.environ.get("WINDOW_PROBE_MODE", "window").strip().lower()
    if mode not in {"window", "construct", "either"}:
        return "window"
    return mode


def window_wait_s() -> float:
    raw = os.environ.get("WINDOW_WAIT_S", "").strip()
    if not raw:
        return float(DEFAULT_WINDOW_WAIT_S)
    try:
        return max(1.0, float(raw))
    except ValueError:
        return float(DEFAULT_WINDOW_WAIT_S)


def expect_failure() -> bool:
    raw = os.environ.get("EXPECT_FAILURE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def default_install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        return Path(local) / "Programs" / "Arelis"
    return Path.home() / "AppData" / "Local" / "Programs" / "Arelis"


def default_user_data_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        return Path(local) / "Arelis"
    return Path.home() / "AppData" / "Local" / "Arelis"


def _is_windows() -> bool:
    return sys.platform == "win32"


def _require_windows(step: str) -> None:
    if not _is_windows():
        record(step, "FAIL", f"{step} requires Windows (sys.platform={sys.platform})")
        raise SystemExit(2)


# --- downloads -----------------------------------------------------------


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_err: Exception | None = None
    for attempt, delay in enumerate((0, *DOWNLOAD_BACKOFF_S), start=1):
        if delay:
            time.sleep(delay)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "arelis-installer-smoke"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            dest.write_bytes(data)
            return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = exc
            print(f"download attempt {attempt} failed: {exc}", flush=True)
    raise RuntimeError(f"download failed after retries: {url}: {last_err}")


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _verify_sha256(exe: Path, sha_path: Path) -> str:
    digest, named = parse_sha256_file(sha_path.read_text(encoding="utf-8"))
    if named and named != exe.name:
        raise RuntimeError(f"sha256 names {named!r} but file is {exe.name!r}")
    got = _file_sha256(exe)
    if got != digest:
        raise RuntimeError(f"hash mismatch for {exe.name}: got {got}, expected {digest}")
    return got


def _gh_json(path: str) -> Any:
    env = os.environ.copy()
    # Prefer gh when available (token already in env on runners).
    try:
        done = subprocess.run(
            ["gh", "api", path],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=60,
        )
        if done.returncode == 0 and done.stdout.strip():
            return json.loads(done.stdout)
    except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
        pass
    url = f"https://api.github.com/{path}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "arelis-installer-smoke", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _release_asset_urls(tag: str) -> tuple[str, str, str]:
    """Return (exe_url, sha_url, version) for a release tag."""
    data = _gh_json(f"repos/{REPO}/releases/tags/{tag}")
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    exe_name = None
    for name in assets:
        if SETUP_NAME_RE.match(name):
            exe_name = name
            break
    if not exe_name:
        raise RuntimeError(f"no setup exe on release {tag}")
    sha_name = exe_name + ".sha256"
    if sha_name not in assets:
        raise RuntimeError(f"no {sha_name} on release {tag}")
    return assets[exe_name], assets[sha_name], parse_version_from_filename(exe_name)


def _resolve_previous_tag(candidate_version: str) -> str:
    try:
        latest = _gh_json(f"repos/{REPO}/releases/latest")
        tag = str(latest.get("tag_name") or "")
        if tag and not latest.get("draft") and not latest.get("prerelease"):
            ver = tag.lstrip("v")
            if ver != candidate_version:
                return tag
    except (RuntimeError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        pass
    releases = _gh_json(f"repos/{REPO}/releases?per_page=30")
    if not isinstance(releases, list):
        raise RuntimeError("releases list malformed")
    for rel in releases:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        tag = str(rel.get("tag_name") or "")
        ver = tag.lstrip("v")
        if tag and ver != candidate_version:
            return tag
    raise RuntimeError("no suitable previous release tag")


def cmd_fetch_candidate(args: argparse.Namespace) -> int:
    _ensure_out()
    artifact_dir = Path(args.artifact_dir) if args.artifact_dir else None
    tag = (args.tag or "").strip()
    if bool(artifact_dir) == bool(tag):
        record(
            "fetch-candidate",
            "FAIL",
            "exactly one of --artifact-dir or --tag is required",
        )
        return 1
    try:
        if artifact_dir is not None:
            exes = sorted(artifact_dir.glob("Arelis-*-win64-setup.exe"))
            if not exes:
                raise RuntimeError(f"no setup exe under {artifact_dir}")
            exe = exes[0]
            sha = Path(str(exe) + ".sha256")
            if not sha.is_file():
                raise RuntimeError(f"missing sidecar {sha.name}")
            dest_exe = OUT / exe.name
            dest_sha = OUT / sha.name
            shutil.copy2(exe, dest_exe)
            shutil.copy2(sha, dest_sha)
            digest = _verify_sha256(dest_exe, dest_sha)
            version = parse_version_from_filename(dest_exe.name)
            source = f"artifact:{artifact_dir}"
        else:
            exe_url, sha_url, version = _release_asset_urls(tag)
            dest_exe = OUT / f"Arelis-{version}-win64-setup.exe"
            dest_sha = Path(str(dest_exe) + ".sha256")
            _download(exe_url, dest_exe)
            _download(sha_url, dest_sha)
            digest = _verify_sha256(dest_exe, dest_sha)
            source = f"tag:{tag}"
        meta_update(
            candidate_exe=str(dest_exe.resolve()),
            candidate_sha=str(dest_sha.resolve()),
            candidate_version=version,
            candidate_digest=digest,
            candidate_source=source,
        )
        record(
            "fetch-candidate",
            "PASS",
            f"{dest_exe.name} version={version} sha256={digest[:12]}... source={source}",
        )
        return 0
    except Exception as exc:
        record("fetch-candidate", "FAIL", str(exc))
        return 1


def cmd_fetch_previous(args: argparse.Namespace) -> int:
    _ensure_out()
    meta = meta_get()
    candidate_version = (args.candidate_version or meta.get("candidate_version") or "").strip()
    if not candidate_version:
        record("fetch-previous", "FAIL", "candidate version unknown; fetch-candidate first")
        return 1
    tag = (args.tag or "").strip()
    try:
        if not tag:
            tag = _resolve_previous_tag(candidate_version)
        exe_url, sha_url, version = _release_asset_urls(tag)
        dest_exe = OUT / f"Arelis-{version}-win64-setup.exe"
        # Avoid clobbering the candidate if versions somehow match names.
        if dest_exe.resolve() == Path(meta.get("candidate_exe", "")).resolve():
            dest_exe = OUT / f"previous-Arelis-{version}-win64-setup.exe"
        dest_sha = Path(str(dest_exe) + ".sha256")
        _download(exe_url, dest_exe)
        _download(sha_url, dest_sha)
        # Sidecar may name the original file; verify hash only.
        digest_expected, _named = parse_sha256_file(dest_sha.read_text(encoding="utf-8"))
        got = _file_sha256(dest_exe)
        if got != digest_expected:
            raise RuntimeError(
                f"hash mismatch for previous {dest_exe.name}: got {got}, expected {digest_expected}"
            )
        meta_update(
            previous_exe=str(dest_exe.resolve()),
            previous_sha=str(dest_sha.resolve()),
            previous_version=version,
            previous_tag=tag,
            previous_digest=got,
        )
        record(
            "fetch-previous",
            "PASS",
            f"{dest_exe.name} tag={tag} version={version} sha256={got[:12]}...",
        )
        return 0
    except Exception as exc:
        record("fetch-previous", "FAIL", str(exc))
        return 1


# --- process / install helpers (Windows) ---------------------------------


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    stdout_f = None
    stderr_f = None
    try:
        if stdout_path is not None:
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            stdout_f = stdout_path.open("w", encoding="utf-8", errors="replace")
        if stderr_path is not None:
            stderr_path.parent.mkdir(parents=True, exist_ok=True)
            stderr_f = stderr_path.open("w", encoding="utf-8", errors="replace")
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            timeout=timeout,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=stdout_f if stdout_f else subprocess.PIPE,
            stderr=stderr_f if stderr_f else subprocess.PIPE,
            check=False,
        )
    finally:
        if stdout_f is not None:
            stdout_f.close()
        if stderr_f is not None:
            stderr_f.close()


def _tail_file(path: Path, limit: int = LOG_TAIL_BYTES) -> str:
    if not path.is_file():
        return ""
    data = path.read_bytes()
    if len(data) > limit:
        data = data[-limit:]
    return data.decode("utf-8", errors="replace")


def _kill_tree(pid: int) -> None:
    if not _is_windows():
        return
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )


def _sweep_install_dir(install_dir: Path) -> list[str]:
    """Kill any process whose executable path lives under the install dir."""
    killed: list[str] = []
    if not _is_windows() or not install_dir.exists():
        return killed
    root = str(install_dir.resolve()).lower()
    ps = (
        f"$root = '{root}'.ToLower(); "
        "Get-Process -ErrorAction SilentlyContinue | ForEach-Object { "
        "  try { $p = $_.Path } catch { $p = $null } "
        "  if ($p -and $p.ToLower().StartsWith($root)) { "
        "    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue; "
        "    $_.Id "
        "  } "
        "}"
    )
    # Job rule: shell snippets with $ go through a .ps1 file.
    script = OUT / "_sweep.ps1"
    _ensure_out()
    script.write_text(ps + "\n", encoding="utf-8")
    done = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True,
        text=True,
        check=False,
        timeout=APP_STOP_TIMEOUT_S,
    )
    for line in (done.stdout or "").splitlines():
        line = line.strip()
        if line:
            killed.append(line)
    deadline = time.time() + APP_STOP_TIMEOUT_S
    while time.time() < deadline:
        still = _pids_under(install_dir)
        if not still:
            break
        for pid in still:
            _kill_tree(pid)
        time.sleep(0.5)
    return killed


def _pids_under(install_dir: Path) -> list[int]:
    if not _is_windows() or not install_dir.exists():
        return []
    root = str(install_dir.resolve()).lower()
    ps = (
        f"$root = '{root}'.ToLower(); "
        "Get-Process -ErrorAction SilentlyContinue | ForEach-Object { "
        "  try { $p = $_.Path } catch { $p = $null } "
        "  if ($p -and $p.ToLower().StartsWith($root)) { $_.Id } "
        "}"
    )
    script = OUT / "_pids.ps1"
    _ensure_out()
    script.write_text(ps + "\n", encoding="utf-8")
    done = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    out: list[int] = []
    for line in (done.stdout or "").splitlines():
        line = line.strip()
        if line.isdigit():
            out.append(int(line))
    return out


def _uninstall_key_present() -> bool:
    if not _is_windows():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY):
            return True
    except OSError:
        return False


def _uninstall_entry_count() -> int:
    if not _is_windows():
        return 0
    import winreg

    base = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    count = 0
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as key:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                if (
                    "8F4C2D31-6A5E-4B7C-9E1D-3A2F5B8C7D40" in name.upper()
                    or name.lower().startswith("arelis")
                ):
                    # Prefer AppId match; also count DisplayName Arelis.
                    try:
                        with winreg.OpenKey(key, name) as sub:
                            try:
                                display, _ = winreg.QueryValueEx(sub, "DisplayName")
                            except OSError:
                                display = ""
                        if "8F4C2D31-6A5E-4B7C-9E1D-3A2F5B8C7D40" in name.upper() or str(
                            display
                        ).lower().startswith("arelis"):
                            count += 1
                    except OSError:
                        if "8F4C2D31-6A5E-4B7C-9E1D-3A2F5B8C7D40" in name.upper():
                            count += 1
    except OSError:
        return count
    return count


def _silent_install(setup: Path, log_path: Path, *, updater_flags: bool = False) -> int:
    if updater_flags:
        flags = [
            str(setup),
            "/SILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/relaunch=yes",
            f"/LOG={log_path}",
        ]
    else:
        flags = [
            str(setup),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/SP-",
            "/CURRENTUSER",
            f"/LOG={log_path}",
        ]
    done = _run(flags, timeout=INSTALL_TIMEOUT_S)
    return int(done.returncode)


def _assert_install_layout(install_dir: Path) -> None:
    needed = [
        install_dir / "python.exe",
        install_dir / "pythonw.exe",
        install_dir / "Lib" / "site-packages" / "arelis" / "__init__.py",
    ]
    missing = [str(p) for p in needed if not p.is_file()]
    if missing:
        raise RuntimeError("install incomplete, missing: " + ", ".join(missing))


def _installed_version(install_dir: Path) -> str:
    py = install_dir / "python.exe"
    done = _run(
        [str(py), "-I", "-m", "arelis", "--version"],
        cwd=install_dir,
        timeout=60,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    text = (done.stdout or "") + (done.stderr or "")
    if done.returncode != 0:
        raise RuntimeError(f"--version failed ({done.returncode}): {text.strip()}")
    return text.strip()


def _patch_yaml_key(text: str, top_key: str, leaf: str, new_value: str) -> str:
    """Replace the first `leaf:` under a top-level `top_key:` mapping."""
    lines = text.splitlines(keepends=True)
    in_block = False
    for i, line in enumerate(lines):
        if re.match(rf"^{re.escape(top_key)}:\s*(#.*)?$", line):
            in_block = True
            continue
        if in_block and re.match(r"^[^\s#]", line):
            in_block = False
        if in_block and re.match(rf"^[ \t]+{re.escape(leaf)}:\s*\S+", line):
            indent = re.match(r"^([ \t]+)", line)
            prefix = indent.group(1) if indent else "  "
            nl = "\n" if line.endswith("\n") else ""
            lines[i] = f"{prefix}{leaf}: {new_value}{nl}"
            return "".join(lines)
    return text


def _write_smoke_config(install_dir: Path, dest: Path) -> Path:
    """Build smoke.yaml from the installed default.yaml (load_config replaces)."""
    default_yaml = install_dir / "Lib" / "site-packages" / "arelis" / "config" / "default.yaml"
    if not default_yaml.is_file():
        raise RuntimeError(f"installed default.yaml missing: {default_yaml}")
    text = default_yaml.read_text(encoding="utf-8")
    # load_config(path) loads only that file (no merge with defaults), so start
    # from the shipped default and patch the few keys smoke needs.
    text = _patch_yaml_key(text, "updates", "check", "false")
    if not re.search(r"(?m)^updates:\s*$", text) and "updates:" not in text:
        text = text.rstrip() + "\n\nupdates:\n  check: false\n"
    text = _patch_yaml_key(text, "location", "enabled", "false")
    text = _patch_yaml_key(text, "presence", "close_to_tray", "false")
    dest.write_text(text, encoding="utf-8")
    return dest


def seed_completed_first_run_profile(
    data_dir: Path, *, tag: str = "qwen3.5:9b", root: Path | None = None
) -> Path:
    """Pre-seed a profile so the main-window probe is not blocked by first-run.

    Writes first-run.json (folder + model complete) and a local model pin.
    Does not prove Welcome glass; use a fresh folder for that check separately.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    state = data_dir / "data"
    state.mkdir(parents=True, exist_ok=True)
    workspace = Path(root) if root is not None else (data_dir / "workspace")
    workspace.mkdir(parents=True, exist_ok=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    marker = {
        "version": 1,
        "workspace_root": str(workspace),
        "answered_at": now,
        "model_setup": {
            "complete": True,
            "tag": tag,
            "completed_at": now,
        },
    }
    (state / "first-run.json").write_text(
        json.dumps(marker, indent=2) + "\n", encoding="utf-8"
    )
    # Hand-written YAML: this script stays stdlib-only.
    local = (
        "workspace:\n"
        "  roots:\n"
        f"    - {json.dumps(str(workspace))}\n"
        "models:\n"
        f"  fast: {json.dumps(tag)}\n"
        f"  research: {json.dumps(tag)}\n"
    )
    (state / "config.local.yaml").write_text(local, encoding="utf-8")
    return workspace


def welcome_title_ok(title: str) -> bool:
    """True when a window title is the first-run folder glass."""
    return (title or "").strip() == "Welcome to Arelis"


def cmd_install(args: argparse.Namespace) -> int:
    _require_windows("install")
    _ensure_out()
    meta = meta_get()
    label = (args.label or "candidate").strip()
    setup = Path(args.setup) if args.setup else Path(meta.get(f"{label}_exe", ""))
    if not setup.is_file():
        record("install", "FAIL", f"setup not found for label={label}: {setup}")
        return 1
    install_dir = default_install_dir()
    _sweep_install_dir(install_dir)
    log_path = OUT / f"setup-{label}.log"
    try:
        code = _silent_install(setup, log_path, updater_flags=bool(args.updater_flags))
        if code != 0:
            raise RuntimeError(f"setup exit {code}; log={log_path}")
        _assert_install_layout(install_dir)
        ver_line = _installed_version(install_dir)
        expected = str(meta.get(f"{label}_version") or "")
        if expected and expected not in ver_line:
            raise RuntimeError(f"version mismatch: expected {expected!r} in {ver_line!r}")
        meta_update(install_dir=str(install_dir), last_install_label=label)
        record(
            f"install-{label}",
            "PASS",
            f"exit=0 dir={install_dir} version_line={ver_line!r}",
        )
        return 0
    except Exception as exc:
        record(f"install-{label}", "FAIL", str(exc))
        return 1


def cmd_uninstall(args: argparse.Namespace) -> int:
    _require_windows("uninstall")
    _ensure_out()
    install_dir = Path(meta_get().get("install_dir") or default_install_dir())
    _sweep_install_dir(install_dir)
    unins = install_dir / "unins000.exe"
    log_path = OUT / "uninstall.log"
    try:
        if unins.is_file():
            code = _run(
                [
                    str(unins),
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART",
                    "/wipe=yes",
                    f"/LOG={log_path}",
                ],
                timeout=INSTALL_TIMEOUT_S,
            ).returncode
            if code != 0:
                raise RuntimeError(f"uninstall exit {code}")
        else:
            record("uninstall", "INFO", f"unins000.exe already gone under {install_dir}")
        # Directory may linger briefly.
        deadline = time.time() + 30
        while install_dir.exists() and time.time() < deadline:
            time.sleep(0.5)
        if install_dir.exists():
            raise RuntimeError(f"install dir still present: {install_dir}")
        if _uninstall_key_present():
            raise RuntimeError(f"uninstall registry key still present: HKCU\\{UNINSTALL_KEY}")
        leftover = _pids_under(install_dir)
        if leftover:
            raise RuntimeError(f"processes still under install dir: {leftover}")
        record("uninstall", "PASS", "dir gone, registry key gone, no leftover processes")
        return 0
    except Exception as exc:
        record("uninstall", "FAIL", str(exc))
        return 1


# --- desktop / window probe ----------------------------------------------


def detect_interactive_desktop() -> dict[str, Any]:
    """Report whether this session looks like it has an interactive desktop."""
    info: dict[str, Any] = {
        "platform": sys.platform,
        "interactive": None,
        "detail": "",
    }
    if not _is_windows():
        info["interactive"] = False
        info["detail"] = "not windows"
        return info
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    foreground = int(user32.GetForegroundWindow())
    metrics = int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    # OpenInputDesktop returns NULL when the session has no input desktop.
    desk = user32.OpenInputDesktop(0, False, 0x0100)  # GENERIC_READ-ish
    has_desk = bool(desk)
    if desk:
        user32.CloseDesktop(desk)
    info["foreground_hwnd"] = foreground
    info["screen_metrics"] = {"cx": metrics[0], "cy": metrics[1]}
    info["open_input_desktop"] = has_desk
    info["interactive"] = bool(has_desk or foreground or (metrics[0] > 0 and metrics[1] > 0))
    info["detail"] = (
        f"OpenInputDesktop={has_desk} GetForegroundWindow={foreground} "
        f"metrics={metrics[0]}x{metrics[1]}"
    )
    return info


def _enum_windows_for_pids(pids: set[int]) -> list[tuple[int, str]]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    found: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) not in pids:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if window_title_ok(title):
            found.append((int(hwnd), title))
        return True

    user32.EnumWindows(_callback, 0)
    return found


def _child_pids(root_pid: int) -> set[int]:
    """Best-effort pid tree via PowerShell CIM."""
    pids = {root_pid}
    if not _is_windows():
        return pids
    ps = (
        f"$target = {root_pid}; "
        "$all = Get-CimInstance Win32_Process; "
        "$map = @{}; "
        "foreach ($p in $all) { $map[[int]$p.ProcessId] = [int]$p.ParentProcessId }; "
        "$queue = New-Object System.Collections.Generic.Queue[int]; "
        "$queue.Enqueue($target); "
        "$seen = @{}; "
        "while ($queue.Count -gt 0) { "
        "  $id = $queue.Dequeue(); "
        "  if ($seen.ContainsKey($id)) { continue }; "
        "  $seen[$id] = $true; "
        "  foreach ($kv in $map.GetEnumerator()) { "
        "    if ($kv.Value -eq $id) { $queue.Enqueue($kv.Key) } "
        "  } "
        "}; "
        "$seen.Keys"
    )
    script = OUT / "_tree.ps1"
    script.write_text(ps + "\n", encoding="utf-8")
    done = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    for line in (done.stdout or "").splitlines():
        line = line.strip()
        if line.isdigit():
            pids.add(int(line))
    return pids


def _screenshot(dest: Path) -> str:
    if not _is_windows():
        return "screenshot skipped: not windows"
    dest.parent.mkdir(parents=True, exist_ok=True)
    ps = f"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bmp.Save('{str(dest).replace("'", "''")}')
$g.Dispose(); $bmp.Dispose()
"""
    script = OUT / "_shot.ps1"
    script.write_text(ps, encoding="utf-8")
    done = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if done.returncode != 0 or not dest.is_file():
        return f"screenshot failed: {(done.stderr or done.stdout or '').strip()}"
    return f"wrote {dest}"


def _process_alive(pid: int) -> bool:
    if not _is_windows():
        return False
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    exit_code = ctypes.c_ulong()
    ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
    kernel32.CloseHandle(handle)
    if not ok:
        return False
    return int(exit_code.value) == 259  # STILL_ACTIVE


def _construct_probe(install_dir: Path, data_dir: Path, config_path: Path) -> dict[str, Any]:
    """Offscreen construction of ArelisWindow without entering the event loop."""
    py = install_dir / "python.exe"
    inline = r"""
import os, sys, asyncio
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["ARELIS_ALLOW_OFFSCREEN"] = "1"
os.environ["ARELIS_DATA_DIR"] = os.environ["SMOKE_DATA_DIR"]
os.environ["PYTHONUTF8"] = "1"
import arelis.ui.launch  # noqa: F401
import arelis.ui.solar_gl  # noqa: F401
from PySide6.QtWidgets import QApplication
from arelis.ui.app import ArelisWindow, BusBridge
from arelis.core.bus import EventBus
from arelis.config import load_config
cfg = load_config(__import__("pathlib").Path(os.environ["SMOKE_CONFIG"]))
app = QApplication.instance() or QApplication([])
loop = asyncio.new_event_loop()
bus = EventBus()
bridge = BusBridge()
win = ArelisWindow(cfg, bridge, loop, bus)
title = win.windowTitle()
print("construct_ok title=%r class=%s" % (title, type(win).__name__))
sys.exit(0)
"""
    stdout_path = OUT / "construct-stdout.txt"
    stderr_path = OUT / "construct-stderr.txt"
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "ARELIS_ALLOW_OFFSCREEN": "1",
        "ARELIS_DATA_DIR": str(data_dir),
        "SMOKE_DATA_DIR": str(data_dir),
        "SMOKE_CONFIG": str(config_path),
        "PYTHONUTF8": "1",
    }
    done = _run(
        [str(py), "-I", "-c", inline],
        cwd=install_dir,
        env=env,
        timeout=120,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    stderr = _tail_file(stderr_path)
    stdout = _tail_file(stdout_path)
    return {
        "ok": done.returncode == 0,
        "exit_code": done.returncode,
        "stdout": stdout[-2000:],
        "stderr": stderr[-4000:],
        "qtopengl": classify_qtopengl_failure(stderr + stdout),
    }


def _import_probe(install_dir: Path) -> dict[str, Any]:
    py = install_dir / "python.exe"
    stdout_path = OUT / "import-stdout.txt"
    stderr_path = OUT / "import-stderr.txt"
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONUTF8": "1"}
    done = _run(
        [
            str(py),
            "-I",
            "-c",
            "import arelis.ui.launch, arelis.ui.solar_gl",
        ],
        cwd=install_dir,
        env=env,
        timeout=60,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    stderr = _tail_file(stderr_path)
    stdout = _tail_file(stdout_path)
    return {
        "ok": done.returncode == 0,
        "exit_code": done.returncode,
        "stdout": stdout[-2000:],
        "stderr": stderr[-4000:],
        "qtopengl": classify_qtopengl_failure(stderr + stdout),
    }


def _window_probe(
    install_dir: Path, data_dir: Path, config_path: Path, label: str
) -> dict[str, Any]:
    py = install_dir / "python.exe"
    stdout_path = OUT / f"window-{label}-stdout.txt"
    stderr_path = OUT / f"window-{label}-stderr.txt"
    env = {
        **os.environ,
        "ARELIS_DATA_DIR": str(data_dir),
        "PYTHONUTF8": "1",
    }
    # Real windows platform: do not set QT_QPA_PLATFORM=offscreen.
    env.pop("QT_QPA_PLATFORM", None)
    env.pop("ARELIS_ALLOW_OFFSCREEN", None)
    proc = subprocess.Popen(
        [str(py), "-m", "arelis", "--config", str(config_path)],
        cwd=str(install_dir),
        env=env,
        stdout=stdout_path.open("w", encoding="utf-8", errors="replace"),
        stderr=stderr_path.open("w", encoding="utf-8", errors="replace"),
    )
    wait_s = window_wait_s()
    deadline = time.time() + wait_s
    found: list[tuple[int, str]] = []
    seconds = None
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            pids = _child_pids(proc.pid)
            found = _enum_windows_for_pids(pids)
            if found:
                seconds = round(wait_s - (deadline - time.time()), 2)
                break
            time.sleep(0.5)
        stderr = _tail_file(stderr_path)
        stdout = _tail_file(stdout_path)
        shot_note = ""
        if found:
            shot_note = _screenshot(OUT / f"window-{label}.png")
            result = {
                "ok": True,
                "status": "FOUND",
                "hwnd": found[0][0],
                "title": found[0][1],
                "seconds": seconds,
                "exit_code": proc.poll(),
                "stderr": stderr[-4000:],
                "stdout": stdout[-2000:],
                "qtopengl": classify_qtopengl_failure(stderr),
                "screenshot": shot_note,
            }
        elif proc.poll() is not None:
            _screenshot(OUT / f"window-{label}-fail.png")
            result = {
                "ok": False,
                "status": "PROCESS_EXITED",
                "exit_code": proc.returncode,
                "stderr": stderr[-4000:],
                "stdout": stdout[-2000:],
                "qtopengl": classify_qtopengl_failure(stderr),
                "seconds": None,
            }
        else:
            # Alive but no window.
            _screenshot(OUT / f"window-{label}-fail.png")
            result = {
                "ok": False,
                "status": "NOT FOUND (process alive)",
                "exit_code": None,
                "pid": proc.pid,
                "stderr": stderr[-4000:],
                "stdout": stdout[-2000:],
                "qtopengl": classify_qtopengl_failure(stderr),
                "seconds": wait_s,
            }
        if seconds is not None and seconds > WINDOW_WARN_S:
            result["warn_slow"] = True
        return result
    finally:
        if proc.poll() is None:
            _kill_tree(proc.pid)
        _sweep_install_dir(install_dir)


def _gate_window_result(window: dict[str, Any], construct: dict[str, Any]) -> bool:
    mode = window_probe_mode()
    if mode == "construct":
        return bool(construct.get("ok"))
    if mode == "either":
        return bool(window.get("ok") or construct.get("ok"))
    return bool(window.get("ok"))


def cmd_probe(args: argparse.Namespace) -> int:
    _require_windows("probe")
    _ensure_out()
    meta = meta_get()
    install_dir = Path(meta.get("install_dir") or default_install_dir())
    label = (args.label or "candidate").strip()
    expected_version = str(meta.get(f"{label}_version") or meta.get("candidate_version") or "")
    desktop = detect_interactive_desktop()
    record(
        "desktop",
        "INFO",
        desktop.get("detail", ""),
        **{k: v for k, v in desktop.items() if k != "detail"},
    )
    data_dir = Path(tempfile.mkdtemp(prefix="arelis-smoke-data-"))
    meta_update(last_probe_data_dir=str(data_dir))
    try:
        config_path = _write_smoke_config(install_dir, OUT / f"smoke-{label}.yaml")
    except Exception as exc:
        record("probe-config", "FAIL", str(exc))
        return 1

    # Version assertion
    try:
        ver_line = _installed_version(install_dir)
        if expected_version and expected_version not in ver_line:
            record(
                "probe-version",
                "FAIL",
                f"expected {expected_version!r} in {ver_line!r}",
            )
            return 1
        record("probe-version", "PASS", ver_line)
    except Exception as exc:
        record("probe-version", "FAIL", str(exc))
        return 1

    imp = _import_probe(install_dir)
    record(
        "import-probe",
        "PASS" if imp["ok"] else "FAIL",
        f"exit={imp['exit_code']} qtopengl={imp['qtopengl']}",
        **{k: imp[k] for k in ("exit_code", "qtopengl") if k in imp},
    )

    # Separate check: a fresh folder still shows Welcome to Arelis.
    # Do not treat Welcome alone as proof the main window opens.
    welcome_dir = Path(tempfile.mkdtemp(prefix="arelis-smoke-welcome-"))
    welcome = _window_probe(install_dir, welcome_dir, config_path, f"{label}-welcome")
    welcome_title = str(welcome.get("title") or "")
    welcome_ok = bool(welcome.get("ok")) and welcome_title_ok(welcome_title)
    record(
        "welcome-probe",
        "PASS" if welcome_ok else "FAIL",
        f"status={welcome.get('status')} title={welcome_title!r} "
        f"(Welcome alone is not the main-window gate)",
        title=welcome_title,
        status_text=welcome.get("status"),
    )

    # Main-window / construct probes need a completed first-run profile.
    seed_completed_first_run_profile(data_dir)
    win = _window_probe(install_dir, data_dir, config_path, label)
    detail = (
        f"status={win.get('status')} title={win.get('title')!r} "
        f"seconds={win.get('seconds')} qtopengl={win.get('qtopengl')} "
        f"mode={window_probe_mode()}"
    )
    record(
        "window-probe",
        "PASS" if win.get("ok") else "FAIL",
        detail,
        status_text=win.get("status"),
        title=win.get("title"),
        seconds=win.get("seconds"),
        qtopengl=win.get("qtopengl"),
    )
    if win.get("warn_slow"):
        record(
            "window-probe-timing",
            "INFO",
            f"time-to-window {win.get('seconds')}s > {WINDOW_WARN_S}s",
        )

    construct = _construct_probe(install_dir, data_dir, config_path)
    record(
        "construct-probe",
        "PASS" if construct.get("ok") else "FAIL",
        f"exit={construct.get('exit_code')} qtopengl={construct.get('qtopengl')} "
        f"stdout={(construct.get('stdout') or '')[:200]!r}",
        qtopengl=construct.get("qtopengl"),
        exit_code=construct.get("exit_code"),
    )

    # Optional pythonw shortcut-form launch (informational).
    if not expect_failure():
        pyw = install_dir / "pythonw.exe"
        if pyw.is_file():
            env = {
                **os.environ,
                "ARELIS_DATA_DIR": str(data_dir),
                "PYTHONUTF8": "1",
            }
            env.pop("QT_QPA_PLATFORM", None)
            env.pop("ARELIS_ALLOW_OFFSCREEN", None)
            stdout_path = OUT / f"pythonw-{label}-stdout.txt"
            stderr_path = OUT / f"pythonw-{label}-stderr.txt"
            proc = subprocess.Popen(
                [str(pyw), "-m", "arelis", "--config", str(config_path)],
                cwd=str(install_dir),
                env=env,
                stdout=stdout_path.open("w", encoding="utf-8", errors="replace"),
                stderr=stderr_path.open("w", encoding="utf-8", errors="replace"),
            )
            deadline = time.time() + min(30.0, window_wait_s())
            pyw_found = []
            while time.time() < deadline and proc.poll() is None:
                pyw_found = _enum_windows_for_pids(_child_pids(proc.pid))
                if pyw_found:
                    break
                time.sleep(0.5)
            if proc.poll() is None:
                _kill_tree(proc.pid)
            _sweep_install_dir(install_dir)
            title = repr(pyw_found[0][1]) if pyw_found else "None"
            record(
                "pythonw-probe",
                "INFO",
                f"window={'FOUND' if pyw_found else 'NOT FOUND'} title={title}",
            )

    gated_ok = bool(imp["ok"]) and welcome_ok and _gate_window_result(win, construct)
    data = _summary()

    if expect_failure():
        stderr_blob = (imp.get("stderr") or "") + (win.get("stderr") or "")
        reproduced = (
            (not imp["ok"]) and (not win.get("ok")) and classify_qtopengl_failure(stderr_blob)
        )
        msg = (
            "EXPECTED FAILURE REPRODUCED: QtOpenGL"
            if reproduced
            else "EXPECTED FAILURE NOT REPRODUCED"
        )
        data["expect_failure_result"] = msg
        _save_json(SUMMARY_PATH, data)
        _write_step_summary(data)
        record("expect-failure", "PASS" if reproduced else "FAIL", msg)
        # Copy app logs from data dir.
        _copy_app_logs(data_dir, label)
        return 0 if reproduced else 1

    data["expect_failure_result"] = None
    _save_json(SUMMARY_PATH, data)
    _copy_app_logs(data_dir, label)
    if not gated_ok:
        reason = []
        if not imp["ok"]:
            reason.append("import-probe failed")
        if not welcome_ok:
            reason.append(f"welcome-probe failed title={welcome_title!r}")
        if not _gate_window_result(win, construct):
            reason.append(
                f"window gate ({window_probe_mode()}) failed: "
                f"window={win.get('status')} construct_ok={construct.get('ok')}"
            )
        record("probe", "FAIL", "; ".join(reason))
        return 1
    record("probe", "PASS", f"import+welcome+{window_probe_mode()} gate ok")
    return 0


def _copy_app_logs(data_dir: Path, label: str) -> None:
    src = data_dir / "logs"
    if not src.is_dir():
        return
    dest = OUT / f"app-logs-{label}"
    dest.mkdir(parents=True, exist_ok=True)
    for path in src.rglob("*"):
        if path.is_file():
            rel = path.relative_to(src)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            data = path.read_bytes()
            if len(data) > LOG_TAIL_BYTES:
                data = data[-LOG_TAIL_BYTES:]
            target.write_bytes(data)


def cmd_upgrade(args: argparse.Namespace) -> int:
    _require_windows("upgrade")
    _ensure_out()
    if expect_failure():
        record("upgrade", "INFO", "skipped: expect_failure mode")
        return 0
    meta = meta_get()
    previous = Path(meta.get("previous_exe", ""))
    candidate = Path(meta.get("candidate_exe", ""))
    if not previous.is_file() or not candidate.is_file():
        record("upgrade", "FAIL", "previous/candidate exe missing")
        return 1
    install_dir = default_install_dir()
    try:
        # Fresh previous install.
        _sweep_install_dir(install_dir)
        if install_dir.exists():
            # Best effort clean.
            unins = install_dir / "unins000.exe"
            if unins.is_file():
                _run(
                    [
                        str(unins),
                        "/VERYSILENT",
                        "/SUPPRESSMSGBOXES",
                        "/NORESTART",
                        "/wipe=yes",
                        f"/LOG={OUT / 'uninstall-before-upgrade.log'}",
                    ],
                    timeout=INSTALL_TIMEOUT_S,
                )
        code = _silent_install(previous, OUT / "setup-previous-for-upgrade.log")
        if code != 0:
            raise RuntimeError(f"previous install exit {code}")
        _assert_install_layout(install_dir)
        prev_ver = str(meta.get("previous_version") or "")
        ver_line = _installed_version(install_dir)
        if prev_ver and prev_ver not in ver_line:
            raise RuntimeError(f"previous version not active: {ver_line}")

        default_data = default_user_data_dir()
        default_data.mkdir(parents=True, exist_ok=True)
        marker_default = default_data / "smoke-upgrade-marker-default.txt"
        marker_default.write_text("default-data-marker\n", encoding="utf-8")
        redirect = Path(tempfile.mkdtemp(prefix="arelis-smoke-upgrade-"))
        marker_redirect = redirect / "smoke-upgrade-marker-redirect.txt"
        marker_redirect.write_text("redirect-data-marker\n", encoding="utf-8")

        _sweep_install_dir(install_dir)
        # Kill any relaunch the updater flags would start.
        code = _silent_install(candidate, OUT / "setup-upgrade-candidate.log", updater_flags=True)
        _sweep_install_dir(install_dir)
        if code != 0:
            raise RuntimeError(f"candidate upgrade exit {code}")
        _assert_install_layout(install_dir)
        cand_ver = str(meta.get("candidate_version") or "")
        ver_line = _installed_version(install_dir)
        if cand_ver and cand_ver not in ver_line:
            raise RuntimeError(f"candidate version not active after upgrade: {ver_line}")
        entries = _uninstall_entry_count()
        default_kept = marker_default.is_file()
        redirect_kept = marker_redirect.is_file()
        record(
            "upgrade-markers",
            "INFO",
            f"default_data_kept={default_kept} redirect_kept={redirect_kept} "
            f"uninstall_entries={entries}",
        )
        if entries != 1:
            raise RuntimeError(f"expected 1 uninstall entry, found {entries}")
        if not default_kept or not redirect_kept:
            raise RuntimeError(f"marker missing: default={default_kept} redirect={redirect_kept}")
        meta_update(install_dir=str(install_dir), last_install_label="candidate")
        # Probe upgraded copy (window/import).
        os.environ.pop("EXPECT_FAILURE", None)
        probe_rc = cmd_probe(argparse.Namespace(label="candidate"))
        if probe_rc != 0:
            record("upgrade", "FAIL", "probe after upgrade failed")
            return 1
        record(
            "upgrade",
            "PASS",
            f"previous->{cand_ver} markers kept uninstall_entries={entries}",
        )
        return 0
    except Exception as exc:
        record("upgrade", "FAIL", str(exc))
        return 1


def cmd_downgrade(args: argparse.Namespace) -> int:
    _require_windows("downgrade")
    _ensure_out()
    if expect_failure():
        record("downgrade", "INFO", "skipped: expect_failure mode")
        return 0
    meta = meta_get()
    previous = Path(meta.get("previous_exe", ""))
    if not previous.is_file():
        record("downgrade", "FAIL", "previous exe missing")
        return 1
    install_dir = Path(meta.get("install_dir") or default_install_dir())
    previous_known_good = os.environ.get("PREVIOUS_KNOWN_GOOD", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    try:
        _sweep_install_dir(install_dir)
        code = _silent_install(previous, OUT / "setup-downgrade.log")
        ver_line = ""
        classification = ""
        if code == 0:
            try:
                _assert_install_layout(install_dir)
                ver_line = _installed_version(install_dir)
            except Exception as exc:
                classification = f"downgrade: allowed but post-check failed ({exc})"
            else:
                prev_ver = str(meta.get("previous_version") or "")
                entries = _uninstall_entry_count()
                if prev_ver and prev_ver not in ver_line:
                    classification = f"downgrade: allowed but version unexpected ({ver_line!r})"
                elif entries != 1:
                    classification = f"downgrade: allowed but uninstall_entries={entries}"
                else:
                    classification = "downgrade: allowed"
        else:
            classification = f"downgrade: refused (exit={code})"
        record("downgrade", "INFO", classification, version_line=ver_line, exit_code=code)
        # Not a failure either way unless policy says so (Christopher decides).
        if previous_known_good and code == 0 and classification.startswith("downgrade: allowed"):
            rc = cmd_probe(argparse.Namespace(label="previous"))
            if rc != 0:
                record("downgrade-probe", "FAIL", "window probe after downgrade failed")
                return 1
            record("downgrade-probe", "PASS", "previous_known_good probe ok")
        return 0
    except Exception as exc:
        record("downgrade", "FAIL", str(exc))
        return 1


def cmd_summary(_args: argparse.Namespace) -> int:
    _ensure_out()
    data = _summary()
    data.setdefault("meta", {}).update(meta_get())
    data["meta"]["ImageVersion"] = os.environ.get("ImageVersion", "")
    data["meta"]["WINDOW_PROBE_MODE"] = window_probe_mode()
    _save_json(SUMMARY_PATH, data)
    _write_step_summary(data)
    steps = data.get("steps", [])
    if expect_failure():
        # Probe failures are the point in this mode; only the verdict step decides.
        failed = [
            s
            for s in steps
            if s.get("status") == "FAIL" and s.get("name") not in EXPECTED_RED_STEPS
        ]
        if not any(s.get("name") == "expect-failure" and s.get("status") == "PASS" for s in steps):
            failed.append({"name": "expect-failure", "status": "FAIL"})
    else:
        failed = [s for s in steps if s.get("status") == "FAIL"]
    print(json.dumps(data, indent=2), flush=True)
    return 1 if failed else 0


def cmd_run(args: argparse.Namespace) -> int:
    """Full orchestrator used by the workflow YAML."""
    _ensure_out()
    os.environ["PYTHONUTF8"] = "1"
    if args.expect_failure:
        os.environ["EXPECT_FAILURE"] = "true"
    if args.window_probe_mode:
        os.environ["WINDOW_PROBE_MODE"] = args.window_probe_mode

    # Validate inputs.
    artifact = (args.candidate_artifact or "").strip()
    tag = (args.candidate_tag or "").strip()
    if bool(artifact) == bool(tag):
        record(
            "inputs",
            "FAIL",
            "exactly one of candidate_artifact or candidate_tag must be set",
        )
        cmd_summary(args)
        return 1
    record(
        "inputs",
        "INFO",
        f"artifact={artifact!r} tag={tag!r} previous_tag={args.previous_tag!r} "
        f"expect_failure={expect_failure()} WINDOW_PROBE_MODE={window_probe_mode()}",
    )

    rc = 0
    if artifact:
        # Caller already downloaded the artifact next to CWD or into smoke-in/.
        art_dir = Path(args.artifact_dir or "smoke-in")
        if not art_dir.is_dir():
            # Also accept files already under smoke-out from a prior step.
            art_dir = Path(".")
        step = cmd_fetch_candidate(argparse.Namespace(artifact_dir=str(art_dir), tag=""))
    else:
        step = cmd_fetch_candidate(argparse.Namespace(artifact_dir="", tag=tag))
    rc = rc or step

    if not expect_failure():
        step = cmd_fetch_previous(
            argparse.Namespace(tag=(args.previous_tag or "").strip(), candidate_version="")
        )
        rc = rc or step

    if rc:
        cmd_summary(args)
        return rc

    if not _is_windows():
        record("run", "FAIL", "orchestrator install/probe steps require Windows")
        cmd_summary(args)
        return 1

    # Fresh install of candidate.
    # Ensure clean slate.
    install_dir = default_install_dir()
    _sweep_install_dir(install_dir)
    if (install_dir / "unins000.exe").is_file():
        cmd_uninstall(argparse.Namespace())

    step = cmd_install(argparse.Namespace(setup="", label="candidate", updater_flags=False))
    if step:
        cmd_summary(args)
        return step

    step = cmd_probe(argparse.Namespace(label="candidate"))
    if expect_failure():
        # Skip upgrade/downgrade; uninstall for cleanliness.
        cmd_uninstall(argparse.Namespace())
        cmd_summary(args)
        return step
    if step:
        cmd_uninstall(argparse.Namespace())
        cmd_summary(args)
        return step

    step = cmd_uninstall(argparse.Namespace())
    if step:
        cmd_summary(args)
        return step

    step = cmd_upgrade(argparse.Namespace())
    # Downgrade even if upgrade probe failed? Spec: run the sequence. Stop on hard fail.
    if step:
        cmd_uninstall(argparse.Namespace())
        cmd_summary(args)
        return step

    step = cmd_downgrade(argparse.Namespace())
    # Final uninstall.
    cmd_uninstall(argparse.Namespace())
    final = cmd_summary(args)
    return step or final


# --- CLI -----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="installer_smoke", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch-candidate", help="Fetch or stage the candidate installer")
    f.add_argument("--artifact-dir", default="", help="Directory with artifact exe+sha256")
    f.add_argument("--tag", default="", help="Release tag to download")
    f.set_defaults(func=cmd_fetch_candidate)

    f = sub.add_parser("fetch-previous", help="Fetch the previous release installer")
    f.add_argument("--tag", default="", help="Previous tag (empty = resolve)")
    f.add_argument("--candidate-version", default="", help="Override candidate version")
    f.set_defaults(func=cmd_fetch_previous)

    f = sub.add_parser("install", help="Silent-install a staged setup exe")
    f.add_argument("--setup", default="", help="Path to setup exe")
    f.add_argument("--label", default="candidate", help="candidate|previous")
    f.add_argument(
        "--updater-flags",
        action="store_true",
        help="Use /SILENT ... /relaunch=yes like update.py",
    )
    f.set_defaults(func=cmd_install)

    f = sub.add_parser("probe", help="Import probe + window probe + construct probe")
    f.add_argument("--label", default="candidate")
    f.set_defaults(func=cmd_probe)

    f = sub.add_parser("uninstall", help="Silent wipe uninstall of the default install")
    f.set_defaults(func=cmd_uninstall)

    f = sub.add_parser("upgrade", help="Install previous, upgrade to candidate, probe")
    f.set_defaults(func=cmd_upgrade)

    f = sub.add_parser("downgrade", help="Run previous over candidate; classify result")
    f.set_defaults(func=cmd_downgrade)

    f = sub.add_parser("summary", help="Write summary.json and step summary")
    f.set_defaults(func=cmd_summary)

    for name in ("all", "run"):
        f = sub.add_parser(name, help="Full orchestrator for CI")
        f.add_argument("--candidate-artifact", default="")
        f.add_argument("--candidate-tag", default="")
        f.add_argument("--previous-tag", default="")
        f.add_argument("--artifact-dir", default="smoke-in")
        f.add_argument("--expect-failure", action="store_true")
        f.add_argument(
            "--window-probe-mode",
            default="",
            choices=["", "window", "construct", "either"],
        )
        f.set_defaults(func=cmd_run)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _ensure_out()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
