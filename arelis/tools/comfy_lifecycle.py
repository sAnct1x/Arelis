"""Start and wait for a local ComfyUI server when image generation needs it.

The user should not have to open a third-party window by hand. Arelis owns the
lifecycle: probe the API, launch once if configured, wait until healthy, then
the image tool proceeds. Launch details live in config so we never invent a
shell command.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

# One process per Arelis run. Re-launching on every image call would stack GPUs.
_process: subprocess.Popen[bytes] | None = None
# Keep the launch log handle open for the child's lifetime (Windows).
_log_handle: object | None = None

# Windows STATUS_ACCESS_VIOLATION (unsigned and signed forms).
_ACCESS_VIOLATION = frozenset({3221225477, -1073741819})


def comfy_is_healthy(base_url: str, *, timeout_s: float = 2.0) -> bool:
    """True when /system_stats answers. Sync; call from a worker thread if needed."""
    url = base_url.rstrip("/") + "/system_stats"
    try:
        response = httpx.get(url, timeout=timeout_s)
        return response.status_code < 400
    except Exception:
        return False


async def comfy_is_healthy_async(base_url: str, *, timeout_s: float = 2.0) -> bool:
    url = base_url.rstrip("/") + "/system_stats"
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(url)
            return response.status_code < 400
    except Exception:
        return False


def resolve_launch(
    *,
    launch_command: str,
    launch_cwd: str,
    comfy_url: str,
) -> tuple[list[str], Path] | None:
    """Build argv + cwd, or None when auto-start is not configured."""
    raw = (launch_command or "").strip()
    cwd_raw = (launch_cwd or "").strip()
    if not raw and not cwd_raw:
        return None

    host, port = _host_port(comfy_url)

    # Directory that contains main.py
    if cwd_raw:
        root = Path(cwd_raw).expanduser().resolve()
    else:
        root = Path(raw).expanduser().resolve()
        if root.is_file():
            root = root.parent

    # Official Windows portable puts main.py under ComfyUI/ and a GPU bat at root.
    nested_main = root / "ComfyUI" / "main.py"
    main_py = root / "main.py"
    if not main_py.is_file() and nested_main.is_file():
        main_py = nested_main
    embed_py = root / "python_embeded" / "python.exe"
    directml_py = root / "venv_directml" / "Scripts" / "python.exe"
    bat_candidates = [
        root / "run_directml.bat",
        root / "run_amd_gpu.bat",
        root / "run_nvidia_gpu.bat",
        root / "run_cpu.bat",
        root / "run.bat",
    ]

    want_directml = (root / "run_directml.bat").is_file()
    if raw:
        raw_path = Path(raw).expanduser()
        # Config often points at run_directml.bat — still prefer a silent
        # python launch so the user never sees the alembic/AIMDO console.
        if raw_path.suffix.lower() in {".bat", ".cmd"} and "directml" in raw_path.name.lower():
            want_directml = True
        elif raw_path.suffix.lower() in {".bat", ".cmd", ".ps1"}:
            script = raw_path.resolve()
            if not script.is_file():
                return None
            # Only fall through to bat when we cannot run main.py quietly.
            if not main_py.is_file():
                if script.suffix.lower() == ".ps1":
                    return (
                        [
                            "powershell",
                            "-NoProfile",
                            "-ExecutionPolicy",
                            "Bypass",
                            "-File",
                            str(script),
                        ],
                        script.parent,
                    )
                return (
                    ["cmd", "/c", "start", "", "/b", "/wait", str(script)],
                    script.parent,
                )

    if raw and not Path(raw).expanduser().exists() and " " in raw:
        # Free-form command line from config.
        return (raw.split(), root if root.is_dir() else Path.cwd())

    # Prefer python + main.py (no .bat console).
    # DirectML installs use venv_directml — NOT python_embeded. The embedded
    # torch is often ROCm/CUDA and fatally AVs on torch.cuda.is_available()
    # (0xC0000005) when probed by comfy_kitchen on AMD Windows.
    if want_directml and main_py.is_file() and directml_py.is_file():
        return (
            [
                str(directml_py),
                "-s",
                str(main_py),
                "--directml",
                "--listen",
                host,
                "--port",
                str(port),
            ],
            main_py.parent,
        )

    if main_py.is_file() and embed_py.is_file():
        argv = [
            str(embed_py),
            "-s",
            str(main_py),
            "--listen",
            host,
            "--port",
            str(port),
        ]
        if want_directml:
            # No venv_directml — flag only; may still AV on AMD+CUDA embed.
            argv.append("--directml")
        return (argv, main_py.parent)

    if main_py.is_file():
        argv = [
            sys.executable,
            str(main_py),
            "--listen",
            host,
            "--port",
            str(port),
        ]
        if want_directml:
            argv.append("--directml")
        return (argv, main_py.parent)

    for bat in bat_candidates:
        if bat.is_file():
            # /b = same console as hidden cmd; without it python.exe from the
            # bat opens a visible terminal (cwd = ComfyUI folder).
            return (
                ["cmd", "/c", "start", "", "/b", "/wait", str(bat)],
                root,
            )

    if raw:
        path = Path(raw).expanduser().resolve()
        if path.is_file() and path.suffix.lower() == ".py":
            return (
                [sys.executable, str(path), "--listen", host, "--port", str(port)],
                path.parent,
            )
    return None


def _launch_log_path() -> Path:
    path = Path.cwd() / "logs" / "comfy_launch.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _format_exit_code(code: int | None) -> str:
    if code is None:
        return "unknown"
    if code in _ACCESS_VIOLATION:
        return (
            f"{code} (Windows access violation 0xC0000005 — usually the wrong "
            "Python: python_embeded ROCm/CUDA probing CUDA on AMD. Arelis should "
            "use venv_directml when run_directml.bat exists; open Comfy via "
            "run_directml.bat by hand if this persists)"
        )
    return str(code)


def _tail_launch_log(*, max_chars: int = 800) -> str:
    path = _launch_log_path()
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if not text:
        return ""
    if len(text) > max_chars:
        text = "…" + text[-max_chars:]
    return text


def stop_comfy() -> bool:
    """Terminate the ComfyUI process Arelis started. Returns True if we stopped one."""
    global _process, _log_handle
    proc = _process
    if proc is None or proc.poll() is not None:
        _process = None
        return False
    log.info("Stopping ComfyUI (pid=%s) to free VRAM for a chat model", proc.pid)
    try:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    except Exception:
        log.warning("Could not stop ComfyUI pid %s", getattr(proc, "pid", "?"), exc_info=True)
        return False
    _process = None
    if _log_handle is not None:
        try:
            _log_handle.close()  # type: ignore[union-attr]
        except Exception:
            pass
        _log_handle = None
    return True


def start_comfy(argv: list[str], cwd: Path) -> subprocess.Popen[bytes]:
    """Spawn ComfyUI with no console window; capture stdout/stderr to a log."""
    global _process, _log_handle
    if _process is not None and _process.poll() is None:
        return _process
    # Dead handle from a prior crash — clear so we can relaunch.
    _process = None
    if _log_handle is not None:
        try:
            _log_handle.close()  # type: ignore[union-attr]
        except Exception:
            pass
        _log_handle = None

    log_path = _launch_log_path()
    log.info("Starting ComfyUI: %s (cwd=%s, log=%s)", argv, cwd, log_path)
    creationflags = 0
    startupinfo = None
    if sys.platform == "win32":
        # CREATE_NO_WINDOW + SW_HIDE. Do not combine DETACHED_PROCESS — that
        # pair still opens a visible console for python.exe / .bat children.
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
        startupinfo.wShowWindow = 0  # SW_HIDE
    # Truncate prior attempt so the next crash tail is this launch only.
    log_file = open(log_path, "w", encoding="utf-8", errors="replace")
    log_file.write(f"# ComfyUI launch\n# argv={argv!r}\n# cwd={cwd}\n")
    log_file.flush()
    try:
        _process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            startupinfo=startupinfo,
            close_fds=False,
            env=os.environ.copy(),
        )
    except Exception:
        log_file.close()
        raise
    _log_handle = log_file
    return _process


async def ensure_comfy_running(
    comfy_url: str,
    *,
    launch_command: str = "",
    launch_cwd: str = "",
    startup_timeout_s: float = 120.0,
    auto_start: bool = False,
) -> str | None:
    """Make ComfyUI reachable. Returns None on success, else an error message."""
    global _process
    if await comfy_is_healthy_async(comfy_url):
        return None
    if not auto_start:
        return (
            f"ComfyUI is not reachable at {comfy_url}. "
            "Start it, or set tools.image.auto_start and tools.image.launch_cwd."
        )

    resolved = resolve_launch(
        launch_command=launch_command,
        launch_cwd=launch_cwd,
        comfy_url=comfy_url,
    )
    if resolved is None:
        return (
            f"ComfyUI is not reachable at {comfy_url}, and auto-start is not "
            "configured. Set tools.image.launch_cwd to your ComfyUI folder "
            "(the directory that contains main.py), then ask again."
        )

    argv, cwd = resolved
    try:
        await asyncio.to_thread(start_comfy, argv, cwd)
    except OSError as exc:
        return f"Could not start ComfyUI ({exc}). Check tools.image.launch_cwd / launch_command."

    deadline = asyncio.get_running_loop().time() + max(15.0, float(startup_timeout_s))
    while asyncio.get_running_loop().time() < deadline:
        if await comfy_is_healthy_async(comfy_url, timeout_s=3.0):
            log.info("ComfyUI is healthy at %s", comfy_url)
            return None
        proc = _process
        if proc is not None and proc.poll() is not None:
            code = proc.returncode
            _process = None
            tail = _tail_launch_log()
            detail = " See logs/comfy_launch.log for the crash output."
            if tail:
                detail = f" Last log lines:\n{tail}"
            return (
                f"ComfyUI exited immediately (code {_format_exit_code(code)})."
                f"{detail}"
            )
        await asyncio.sleep(1.0)

    return (
        f"Started ComfyUI but it did not become ready at {comfy_url} within "
        f"{int(startup_timeout_s)}s. It may still be loading; try again in a moment."
    )


def _host_port(comfy_url: str) -> tuple[str, int]:
    parsed = urlparse(comfy_url if "://" in comfy_url else f"http://{comfy_url}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8188
    return host, port
