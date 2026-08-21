"""Where a picture may come from, and how it is handed to a model.

Two jobs that the vision and image_edit tools both need, kept in one place
because getting either of them subtly different in two files is how you end up
with a tool that can see a screenshot and another that cannot find it.

Resolving is not simply "ask the workspace". A pasted screenshot is staged under
``data/drops/`` and a generated picture lands in ``outputs/``, and both of those
live under the data root rather than inside a project. From a source checkout
the data root and the workspace root are the same directory, so resolving
against the workspace alone appears to work; on an installed copy they are
``%LOCALAPPDATA%\\Arelis`` and ``Documents\\Arelis`` respectively, and every
paste would have failed with "outside workspace roots" the first time anyone
tried it. Reading from Arelis's own drop and output folders is not an escape
from the sandbox, so they are named here as places a picture may legitimately
be read from.

Preparing is downscaling. Ollama counts an image against the same context
window as the text, and a 1440p screenshot -- 2560x1440, 7 MB, the ordinary
output of pressing Print Screen -- tokenises to about 4,150 tokens against a
4,096 window and is rejected outright with a 400. That window is the 3B
fallback VL. The chat model that sees images itself (Qwen 3.5) is already
loaded at tens of thousands of tokens, so it can take a longer edge.

Measured against qwen2.5vl:3b, the cost of the picture alone: 1024px is 1,100
tokens, 1280px is 1,221, 1600px is 1,849. All three answer correctly, so 1024
is the fallback cap — margin on a 4096 window, not a quality target. When the
chat model looks, 2048 is the cap: enough that a phone photo of a monitor
still has readable chrome, without shipping a 4K paste as-is.

"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

from arelis.paths import outputs_dir, state_dir, user_data_dir
from arelis.workspace import WorkspaceRoots

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})

# Long edge, in pixels, for an image sent to a vision model. See the module
# docstring: this is a correctness bound for the 3B fallback window, not a
# preference. Chat-sees looks use CHAT_MAX_EDGE.
DEFAULT_MAX_EDGE = 1024
CHAT_MAX_EDGE = 2048

# Re-encode anything above this even when it needs no downscaling, because the
# base64 of a multi-megabyte file is the other half of the same context problem.
_RAW_BYTE_LIMIT = 1_500_000

_PILLOW_HINT = (
    "Pillow is not installed, so images cannot be resized or adjusted. "
    "Install it with: pip install Pillow"
)


def pillow_error() -> str:
    """Empty when Pillow can be imported, else a sentence naming the fix."""
    try:
        import PIL  # noqa: F401
    except Exception:
        return _PILLOW_HINT
    return ""


def readable_image_roots() -> tuple[Path, ...]:
    """Arelis's own folders a picture may be read from, besides the workspace."""
    roots: list[Path] = []
    for candidate in (outputs_dir(), state_dir() / "drops"):
        try:
            roots.append(candidate.resolve())
        except OSError:
            continue
    return tuple(roots)


def _under_own_roots(raw: str) -> Path | None:
    """The path a drops/outputs-relative or absolute reference points at."""
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = user_data_dir() / candidate
    try:
        candidate = candidate.resolve()
    except OSError:
        return None
    for root in readable_image_roots():
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        return candidate
    return None


def resolve_image(workspace: WorkspaceRoots, path_str: str) -> Path:
    """An existing local image file, or an exception naming why not.

    Raises ValueError for a missing or non-image path, PermissionError for one
    outside every readable root, and FileNotFoundError when the location is
    allowed but empty -- the three the callers already turn into tool failures.
    """
    raw = (path_str or "").strip()
    if not raw:
        raise ValueError("Missing path")

    found: Path | None = None
    try:
        found = workspace.resolve_read(raw).path
    except (ValueError, PermissionError, FileNotFoundError):
        found = None

    # A workspace hit that does not exist is not better than a drops hit that
    # does: the model routinely passes `data/drops/...`, which is relative to
    # the data root and only coincidentally inside a project.
    if found is None or not found.is_file():
        fallback = _under_own_roots(raw)
        if fallback is not None:
            found = fallback

    if found is None:
        allowed = ", ".join(str(p) for p in readable_image_roots())
        raise PermissionError(
            f"Path is outside the workspace and outside {allowed}: {raw}"
        )
    if found.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError(f"Unsupported image type `{found.suffix}` (use png/jpg/webp/gif)")
    if not found.is_file():
        raise FileNotFoundError(f"Image not found: {found}")
    return found


def encode_for_vision(
    path: Path,
    *,
    max_edge: int = DEFAULT_MAX_EDGE,
) -> tuple[str, dict[str, Any]]:
    """Base64 for a VL model, downscaled when it would not otherwise fit.

    Returns the payload and what was done to it, so a caller can say so rather
    than silently answering about a picture the user did not send. Without
    Pillow the original bytes go as-is: worse, but the previous behaviour, and a
    missing optional dependency should not turn working vision off.
    """
    raw = path.read_bytes()
    meta: dict[str, Any] = {
        "source_bytes": len(raw),
        "sent_bytes": len(raw),
        "downscaled": False,
        "max_edge": int(max_edge),
    }
    try:
        from PIL import Image
    except Exception:
        meta["pillow"] = False
        return base64.b64encode(raw).decode("ascii"), meta

    meta["pillow"] = True
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            width, height = opened.size
            meta["source_px"] = [width, height]
            longest = max(width, height)
            needs_resize = longest > max_edge
            if not needs_resize and len(raw) <= _RAW_BYTE_LIMIT:
                meta["sent_px"] = [width, height]
                return base64.b64encode(raw).decode("ascii"), meta

            frame = opened.convert("RGB")
            if needs_resize:
                scale = max_edge / float(longest)
                frame = frame.resize(
                    (max(1, round(width * scale)), max(1, round(height * scale))),
                    Image.LANCZOS,
                )
            buffer = io.BytesIO()
            frame.save(buffer, format="JPEG", quality=85, optimize=True)
            payload = buffer.getvalue()
            meta["sent_px"] = [frame.width, frame.height]
            meta["sent_bytes"] = len(payload)
            meta["downscaled"] = needs_resize
            return base64.b64encode(payload).decode("ascii"), meta
    except Exception as exc:
        # An image Pillow cannot parse is still worth showing the model, which
        # may handle a format or a truncation Pillow refuses.
        meta["prepare_error"] = f"{type(exc).__name__}: {exc}"
        return base64.b64encode(raw).decode("ascii"), meta
