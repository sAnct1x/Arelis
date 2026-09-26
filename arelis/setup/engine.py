"""Find, start, and pull through the local Ollama engine.

The installer is not rebuilt here. If Ollama is already on the PC we use it
(an older installed copy and this one share tags). If it is missing we download
the official Windows setup into %LOCALAPPDATA%\\Arelis-runtime — never into the
git checkout — and run it. Models still land in the default Ollama store.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from arelis.hidden_proc import hidden_kwargs, hidden_run
from arelis.llm.startup import model_is_available

log = logging.getLogger(__name__)

DEFAULT_BASE = "http://127.0.0.1:11434"
OLLAMA_SETUP_URL = (
    "https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe"
)
Progress = Callable[[str, int, int], None]


def runtime_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Arelis-runtime"


def find_ollama_exe() -> Path | None:
    which = shutil.which("ollama")
    if which:
        path = Path(which)
        if path.is_file():
            return path
    local = os.environ.get("LOCALAPPDATA") or ""
    candidates = [
        Path(local) / "Programs" / "Ollama" / "ollama.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
    ]
    for item in candidates:
        if item.is_file():
            return item
    return None


def ollama_reachable(base_url: str = DEFAULT_BASE, *, timeout_s: float = 1.5) -> bool:
    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.get(f"{base_url.rstrip('/')}/api/tags")
            return resp.status_code < 500
    except Exception:
        return False


def start_ollama(exe: Path | None = None) -> str | None:
    """Start `ollama serve` if nothing is answering. None on success."""
    if ollama_reachable():
        return None
    binary = exe or find_ollama_exe()
    if binary is None:
        return "Ollama is not installed on this PC yet."
    try:
        kwargs = hidden_kwargs()
        subprocess.Popen(
            [str(binary), "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
    except OSError as exc:
        return f"Could not start Ollama: {exc}"
    for _ in range(40):
        if ollama_reachable():
            return None
        time.sleep(0.25)
    return "Ollama started but is not answering yet. Wait a moment and try again."


def parse_pull_status(data: dict[str, object]) -> tuple[str, int, int]:
    """Turn one Ollama /api/pull JSON object into (label, done_bytes, total_bytes)."""
    status = str(data.get("status") or "").strip() or "Working…"
    completed = data.get("completed")
    total = data.get("total")
    try:
        done = int(completed) if completed is not None else 0
    except (TypeError, ValueError):
        done = 0
    try:
        whole = int(total) if total is not None else 0
    except (TypeError, ValueError):
        whole = 0
    return status, max(done, 0), max(whole, 0)


def already_pulled(tag: str, base_url: str = DEFAULT_BASE) -> bool:
    """True when Ollama already has this tag. Used so setup does not re-download."""
    name = (tag or "").strip()
    if not name:
        return False
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{base_url.rstrip('/')}/api/tags")
            resp.raise_for_status()
            payload = resp.json() or {}
    except Exception:
        return False
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return False
    names = [
        str(item.get("name") or "")
        for item in models
        if isinstance(item, dict)
    ]
    return model_is_available(names, name)


def pull_tag(
    tag: str,
    *,
    base_url: str = DEFAULT_BASE,
    progress: Progress | None = None,
    timeout_s: float = 3600,
) -> None:
    """Blocking pull. Raises on failure. Calls progress(status, done, total)."""
    name = (tag or "").strip()
    if not name:
        raise ValueError("empty model tag")
    url = f"{base_url.rstrip('/')}/api/pull"
    with httpx.Client(timeout=timeout_s) as client:
        with client.stream("POST", url, json={"name": name, "stream": True}) as resp:
            if resp.status_code >= 400:
                body = resp.read().decode("utf-8", errors="replace")[:400]
                raise RuntimeError(
                    f"Ollama could not pull `{name}` (HTTP {resp.status_code}). {body}"
                )
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                if data.get("error"):
                    raise RuntimeError(str(data["error"]))
                status, done, total = parse_pull_status(data)
                if progress is not None:
                    progress(status, done, total)


def download_ollama_setup(
    dest: Path,
    *,
    progress: Progress | None = None,
    timeout_s: float = 3600,
) -> Path:
    """Fetch the official Ollama Windows setup into dest. Returns dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
        with client.stream("GET", OLLAMA_SETUP_URL) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with part.open("wb") as handle:
                for chunk in resp.iter_bytes(1024 * 256):
                    handle.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress("Downloading the local engine…", done, total)
    part.replace(dest)
    return dest


def run_ollama_setup(setup_exe: Path) -> str | None:
    """Run the official installer. None on success."""
    if not setup_exe.is_file():
        return "The Ollama installer is missing."
    try:
        result = hidden_run(
            [str(setup_exe), "/VERYSILENT", "/NORESTART"],
            timeout=600,
            check=False,
        )
    except Exception as exc:
        return f"Could not run the Ollama installer: {exc}"
    if result.returncode not in (0, None):
        # Some builds ignore Inno flags. Try a normal launch.
        try:
            subprocess.Popen([str(setup_exe)], **hidden_kwargs())
        except OSError as exc:
            return f"Ollama setup did not finish (code {result.returncode}): {exc}"
        return (
            "The Ollama installer is open. Finish it, then come back and continue."
        )
    return None
