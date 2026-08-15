"""Local OCR via system Tesseract (CPU). No cloud, no GPU.

action=text — OCR an image under workspace roots or outputs/images/.
action=screen — capture the primary display to outputs/images/, then OCR.
Always Allow (confirm_vision): screen/clipboard-adjacent privacy.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arelis.core.look import OcrInspect, inspect_ocr_text
from arelis.paths import outputs_dir, user_data_dir
from arelis.tools.base import ToolResult
from arelis.tools.safety import redact_secrets
from arelis.workspace import WorkspaceRoots

log = logging.getLogger(__name__)

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
_MAX_CHARS = 12_000


def _tesseract_exe() -> str | None:
    """Resolve tesseract even when User PATH is not visible to this process."""
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in (
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def tesseract_available() -> bool:
    return _tesseract_exe() is not None


def run_tesseract(path: Path, *, lang: str = "eng") -> str:
    """Synchronous OCR. Raises RuntimeError with a clear message on miss."""
    return run_tesseract_inspect(path, lang=lang).text


def run_tesseract_inspect(path: Path, *, lang: str = "eng") -> OcrInspect:
    """OCR plus exogenous TSV confidence — CPU only, no VL self-score."""
    exe = _tesseract_exe()
    if not exe:
        raise RuntimeError(
            "tesseract is not on PATH. Install Tesseract OCR for Windows "
            "(UB Mannheim build) or set tools.ocr.enabled: false. "
            "GPU chat models stay unloaded — this path is CPU-only."
        )
    if not path.is_file():
        raise FileNotFoundError(f"Image not found: {path}")
    proc = subprocess.run(
        [exe, str(path), "stdout", "-l", lang, "--psm", "3", "tsv"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "tesseract failed").strip()
        raise RuntimeError(err[:500])
    return _inspect_from_tsv(proc.stdout or "")


def _inspect_from_tsv(tsv: str) -> OcrInspect:
    """Parse Tesseract TSV (level 5 = words). conf=-1 rows are skipped."""
    words: list[str] = []
    confs: list[float] = []
    for i, line in enumerate((tsv or "").splitlines()):
        if i == 0 and line.lower().startswith("level"):
            continue
        cols = line.split("\t")
        if len(cols) < 12:
            continue
        try:
            level = int(float(cols[0]))
        except ValueError:
            continue
        if level != 5:
            continue
        try:
            conf = float(cols[10])
        except ValueError:
            conf = -1.0
        token = (cols[11] if len(cols) > 11 else "").strip()
        if conf >= 0 and token:
            words.append(token)
            confs.append(conf)
    text = " ".join(words).strip()
    if not text:
        # TSV empty — keep any leftover stdout-shaped prose.
        leftover = "\n".join(
            ln for ln in (tsv or "").splitlines() if ln and not ln.lower().startswith("level")
        ).strip()
        if leftover and "\t" not in leftover:
            text = leftover
    mean = (sum(confs) / len(confs)) if confs else None
    return inspect_ocr_text(text, mean_conf=mean)


def capture_primary_screen(dest: Path) -> Path:
    """Grab the primary screen to ``dest`` (PNG). Requires a Qt GUI app."""
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QGuiApplication.instance()
    if app is None:
        raise RuntimeError(
            "No GUI application is running; cannot capture the screen. "
            "Use action=text with an image path, or run from the desktop UI."
        )
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        raise RuntimeError("No primary screen available.")
    pix = screen.grabWindow(0)
    if pix.isNull():
        raise RuntimeError("Screen grab returned an empty image.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not pix.save(str(dest), "PNG"):
        raise RuntimeError(f"Could not write screenshot to {dest}")
    return dest


class OcrTool:
    name = "ocr"
    description = (
        "Extract text from a local image with CPU Tesseract (not the VL model). "
        "action=text path=… for an existing screenshot/PNG; action=screen to "
        "capture the primary display then OCR. Always Allow. Prefer vision when "
        "you need a description rather than exact text."
    )
    risk = "side_effect"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["text", "screen"],
                "description": "text=OCR path; screen=capture primary display then OCR.",
            },
            "path": {
                "type": "string",
                "description": "Image path for action=text (workspace or outputs/images/).",
            },
            "lang": {
                "type": "string",
                "description": "Tesseract language pack (default eng).",
            },
        },
        "required": ["action"],
    }

    def __init__(
        self,
        workspace: WorkspaceRoots,
        *,
        output_dir: Path | None = None,
        max_chars: int = _MAX_CHARS,
        runner: Callable[[Path, str], str] | None = None,
        capturer: Callable[[Path], Path] | None = None,
    ) -> None:
        self.workspace = workspace
        self.output_dir = output_dir or (outputs_dir() / "images")
        self.max_chars = max(256, int(max_chars))
        self._runner = runner or (lambda p, lang: run_tesseract(p, lang=lang))
        self._capturer = capturer or capture_primary_screen
        self._uses_default_runner = runner is None

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip().lower()
        lang = str(kwargs.get("lang") or "eng").strip() or "eng"
        if action not in {"text", "screen"}:
            return ToolResult(
                ok=False,
                output="Unknown action. Use text or screen.",
            )
        try:
            if action == "screen":
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                dest = self.output_dir / f"ocr_screen_{stamp}.png"
                path = await asyncio.to_thread(self._capturer, dest)
            else:
                path = self._resolve_image(str(kwargs.get("path") or ""))
            inspect = await asyncio.to_thread(self._inspect, path, lang)
            text = inspect.text
        except FileNotFoundError as exc:
            return ToolResult(
                ok=False,
                output=f"[fail:empty] {exc}",
                data={"fail_class": "fail:empty"},
            )
        except Exception as exc:
            msg = str(exc)
            tag = "fail:other"
            if "not on PATH" in msg or ("tesseract" in msg.lower() and "not" in msg.lower()):
                tag = "fail:other"
            return ToolResult(
                ok=False,
                output=f"[{tag}] OCR failed: {msg}",
                data={"fail_class": tag},
            )

        cleaned = redact_secrets((text or "").strip())
        features = inspect_ocr_text(
            cleaned,
            mean_conf=inspect.mean_conf,
        )
        extra = {
            "mean_conf": features.mean_conf,
            "word_count": features.word_count,
            "printable_ratio": round(features.printable_ratio, 3),
            "short_token_ratio": round(features.short_token_ratio, 3),
            "letter_ratio": round(features.letter_ratio, 3),
        }
        if not cleaned:
            return ToolResult(
                ok=True,
                output=(
                    f"OCR found no readable text in {path.name}. "
                    "Try vision for a description, or a sharper screenshot."
                ),
                data={
                    "path": str(path),
                    "chars": 0,
                    "empty": True,
                    **extra,
                },
            )
        truncated = len(cleaned) > self.max_chars
        body = cleaned[: self.max_chars]
        if truncated:
            body += f"\n…(truncated, {len(cleaned)} chars total)"
        return ToolResult(
            ok=True,
            output=f"OCR text from {path.name} ({len(cleaned)} chars):\n{body}",
            data={
                "path": str(path),
                "chars": len(cleaned),
                "truncated": truncated,
                "action": action,
                "empty": False,
                **extra,
            },
        )

    def _inspect(self, path: Path, lang: str) -> OcrInspect:
        if self._uses_default_runner:
            return run_tesseract_inspect(path, lang=lang)
        text = self._runner(path, lang)
        return inspect_ocr_text(text or "")

    def _resolve_image(self, path_str: str) -> Path:
        raw = (path_str or "").strip()
        if not raw:
            raise FileNotFoundError("Missing path for action=text.")
        try:
            resolved = self.workspace.resolve_read(raw)
            path = resolved.path
        except Exception:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = (user_data_dir() / candidate).resolve()
            else:
                candidate = candidate.resolve()
            images_root = (outputs_dir() / "images").resolve()
            try:
                candidate.relative_to(images_root)
            except ValueError as exc:
                raise FileNotFoundError(
                    f"Path not under workspace roots or outputs/images/: {raw}"
                ) from exc
            path = candidate
        if path.suffix.lower() not in _IMAGE_SUFFIXES:
            raise FileNotFoundError(
                f"Not an image file ({path.suffix or 'no suffix'}): {path.name}"
            )
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {path}")
        return path
