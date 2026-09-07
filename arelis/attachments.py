"""Stage chat attachments under data/drops/ for tool-readable paths."""

from __future__ import annotations

import re
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from arelis.history_view import history_pairs
from arelis.paths import display_path, state_dir, user_data_dir

MAX_ATTACHMENTS = 10
MAX_BYTES = 25 * 1024 * 1024  # 25 MiB
DROPS_ROOT = state_dir() / "drops"

# Plain text readable via workspace action=read (logs included — not "other").
_TEXT = frozenset(
    {
        ".txt",
        ".md",
        ".markdown",
        ".log",
        ".out",
        ".err",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".env",
        ".jsonl",
        ".py",
        ".pyi",
    }
)
_DATA = frozenset({".json", ".csv", ".tsv", ".tab", ".xlsx", ".xls"})
_PDF = frozenset({".pdf"})
_IMAGE = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})

_UNSAFE = re.compile(r"[^\w.\- ()\[\]]+", re.UNICODE)

# Short affirmations that mean "do what you just offered" (attachment follow-ups).
_SHORT_AFFIRM = re.compile(
    r"(?i)^\s*("
    r"y(?:ea+|eah|ep|up|es)|"
    r"sure|ok(?:ay)?|please|"
    r"go\s+ahead|do\s+it|"
    r"sounds?\s+good|"
    r"line\s+by\s+line|"
    r"summarize\s+(?:it|that|them)|"
    r"yes\s+please|"
    r"please\s+do"
    r")\.?\s*$"
)

_ATTACH_LINE = re.compile(
    r"^\s*-\s+(?P<path>\S+)\s+\((?P<kind>[a-z]+)\)"
    r"(?:\s+source=(?P<source>.+?))?"
    r"(?:\s+→\s+.+)?"
    r"\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class Attachment:
    """One staged file ready for USER_MESSAGE / tools."""

    id: str
    name: str
    path: str  # workspace-relative posix (under data/drops/…)
    source_path: str
    kind: str
    bytes: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StageResult:
    ok: list[Attachment]
    errors: list[str]


def detect_kind(path: Path | str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in _TEXT:
        return "text"
    if suffix in _DATA:
        return "data"
    if suffix in _PDF:
        return "pdf"
    if suffix in _IMAGE:
        return "image"
    return "other"


# User asked to read glyphs in an image (not merely describe it).
# "add text in this image" is an overlay, not OCR — wants_image_edit wins first.
_IMAGE_TEXT_ASK = re.compile(
    r"(?i)\b("
    r"ocr|"
    r"extract\s+text|"
    r"read\s+(?:the\s+)?text|"
    r"what(?:'s|\s+is)\s+written|"
    r"transcribe|"
    r"text\s+in\s+(?:this\s+)?(?:image|photo|screenshot|png)"
    r")\b"
)

# User asked for the picture itself to come back changed, not described. Without
# this the routing block told her to call vision, which can only look, and she
# spent the turn hunting for a tool that would do it -- ending on the image
# generator, which produced a different picture at the requested size.
# Overlay phrasing ("add text right in the middle that says Arelis") used to
# parse as send_sms(to="right in the middle") because of the bare "text" verb.
# Pixel-exact work on a file that already exists. "Turn this into a watercolor"
# is generative restyle (image + path), not this — only named product sizes
# and arithmetic on pixels count here.
_IMAGE_EDIT_ASK = re.compile(
    r"(?i)\b("
    r"resize|resized|resizing|"
    r"re-?scale|scale\s+(?:it|this|that|the\s+image)|"
    r"crop|cropped|"
    r"rotate|rotated|upside[\s-]?down|"
    r"flip|flipped|mirror|"
    r"grayscale|greyscale|black[\s-]?and[\s-]?white|\bb\s*&\s*w\b|"
    r"blur|blurred|"
    r"invert|inverted|"
    r"vibrant|vibrance|saturate|saturation|"
    r"brighten|brighter|darken|darker|"
    r"contrast|sharpen|sharper|"
    r"thumbnail|"
    r"upscale|upscaled|upscaling|"
    r"enlarge|enlarged|"
    r"(?:make|blow)\s+(?:it|this|that)\s+(?:up|bigger|larger)|"
    r"scale\s*=\s*2|"
    r"(?:make|do|scale)\s+(?:it|this|that)\s+2x|"
    r"\b2x\s+(?:bigger|larger|please)\b|"
    r"twice\s+(?:as\s+)?(?:big|large)|"
    r"twice\s+the\s+size|"
    r"(?:make|convert|turn)\s+(?:it|this|that)\s+into\s+(?:an?\s+)?"
    r"(?:youtube\s+|instagram\s+|tiktok\s+)?"
    r"(?:thumbnail|banner|wallpaper|icon|avatar|story)|"
    r"aspect\s+ratio|"
    r"\d{2,5}\s*(?:x|\u00d7|by)\s*\d{2,5}|"
    r"edit\s+(?:the\s+|this\s+|that\s+)?(?:picture|image|photo|png)"
    r"(?:\s+you\s+just\s+(?:created|generated|made))?|"
    r"(?:add|put|overlay|write)\s+(?:the\s+)?"
    r"(?:text|caption|title|watermark)(?!\s+message)\s+"
    r"(?:right\s+)?"
    r"(?:in\s+the\s+(?:middle|center|centre)|on\s+(?:to\s+)?"
    r"(?:the\s+)?(?:image|picture|photo|png)|that\s+says|onto)|"
    r"(?:add|put)\s+(?:a\s+)?(?:caption|title|watermark)\s+on|"
    r"text\s+(?:right\s+)?in\s+the\s+(?:middle|center|centre)"
    r")\b"
)

# Generative change of an existing picture: needs Comfy img2img, not Pillow.
_IMAGE_RESTYLE_ASK = re.compile(
    r"(?i)\b("
    r"in\s+the\s+style\s+of|"
    r"restyle|re-?style|"
    r"re-?imagine|reimagine|"
    r"re-?draw|redraw|"
    r"img2img|"
    r"(?:watercolor|watercolour)\s+restyle|"
    r"(?:look|looks)\s+like\s+(?:an?\s+)?"
    r"(?:watercolor|watercolour|oil\s+painting|painting|sketch|"
    r"anime|cartoon|comic|photograph|photoreal|cinematic|illustration)|"
    r"make\s+(?:it|this|that|the\s+(?:picture|image|photo|png)"
    r"(?:\s+you\s+just\s+(?:created|generated|made))?)\s+look\s+like|"
    r"give\s+(?:it|this|that)\s+a\s+"
    r"(?:watercolor|watercolour|oil|anime|sketch|painted)\s+look|"
    r"(?:as|into)\s+a\s+(?:watercolor|watercolour|oil\s+painting|"
    r"painting|sketch|anime|cartoon|comic|photograph)|"
    r"(?:make|convert|turn)\s+(?:it|this|that)\s+into\s+(?:an?\s+)?"
    r"(?:watercolor|watercolour|oil(?:\s+painting)?|painting|sketch|"
    r"anime|cartoon|comic|photograph)"
    r")\b"
)

# Comfy surgical work on a file that already exists. Pixel crop/scale is
# image_edit — this is rembg, outpaint, or a generative region inpaint.
_IMAGE_SURGICAL_ASK = re.compile(
    r"(?i)\b("
    r"(?:remove|cut\s+out|erase|knock\s+out)\s+(?:the\s+)?background|"
    r"background\s+(?:remov(?:al|e)|cut.?out)|"
    r"outpaint|uncrop|"
    r"extend\s+(?:the\s+)?(?:canvas|image|picture|photo|png)|"
    r"(?:remove|change|replace|inpaint)\s+(?:the\s+)?"
    r"(?:left|right|top|bottom|center|centre)\s+"
    r"(?:of\s+(?:the\s+)?(?:picture|image|photo|png|shot)|"
    r"side|region|area|part|half)"
    r")\b"
)

# Batch generate. "another four" / "n=4" / "four versions".
_IMAGE_VARIATIONS_ASK = re.compile(
    r"(?i)\b("
    r"(?:four|4)\s+(?:versions?|variations?|variants?)|"
    r"another\s+(?:four|4)(?:\s+(?:versions?|variations?|variants?))?|"
    r"n\s*=\s*[1-4]"
    r")\b"
)

# Reproduce the last generate with the seed in its sidecar.
_IMAGE_SAME_SEED = re.compile(
    r"(?i)\b("
    r"same\s+seed|"
    r"reproduce(?:\s+that\s+(?:image|picture))?|"
    r"(?:do|make|generate|draw|render)\s+(?:it|that|this)\s+again|"
    r"again\s+with\s+(?:the\s+)?same\s+seed|"
    r"rerun\s+that\s+(?:image|picture)"
    r")\b"
)

# Pasted-photo identity, not camera Point-and-Ask and not "who are you".
_PERSON_IDENTIFY = re.compile(
    r"(?i)\b("
    r"who\s+is\s+(?:this|that|he|she|they)|"
    r"who(?:'s|\s+is)\s+(?:in|on)\s+(?:this|the)\s+(?:photo|picture|image)|"
    r"identify\s+(?:this|that)\s+(?:person|man|woman|people)|"
    r"name\s+(?:this|that)\s+(?:person|man|woman)"
    r")\b"
)

# "add text … that says Arelis, centered perfectly"
_OVERLAY_SAYS = re.compile(
    r"(?is)\b(?:add|put|overlay|write)\s+(?:the\s+)?"
    r"(?:text|caption|title|watermark)\b.{0,120}?"
    r"(?:that\s+)?(?:says|saying|reading)\s+"
    r"""['"]?(?P<text>.+?)['"]?"""
    r"(?=\s*,?\s*(?:centered|centred|perfectly|"
    r"(?:right\s+)?in\s+the\s+(?:middle|center|centre))|[.!]?\s*$)"
)
_OVERLAY_QUOTED = re.compile(
    r"(?i)\b(?:add|put|overlay|write)\s+(?:the\s+)?"
    r"(?:text\s+)?"
    r"""['"](?P<text>[^'"]+)['"]"""
)
_OVERLAY_TRAIL = re.compile(
    r"(?i)\s*,?\s*(?:centered|centred|perfectly|"
    r"(?:right\s+)?in\s+the\s+(?:middle|center|centre)).*$"
)


def wants_image_text(user_text: str = "") -> bool:
    """True when the user asked to read text *in* an image (OCR), not describe it."""
    raw = user_text or ""
    # Overlay ("add text in this image that says …") is image_edit, not OCR.
    if wants_image_edit(raw):
        return False
    return bool(_IMAGE_TEXT_ASK.search(raw))


def wants_image_restyle(user_text: str = "") -> bool:
    """True when the ask is a generative restyle of a picture that already exists."""
    return bool(_IMAGE_RESTYLE_ASK.search(user_text or ""))


def wants_image_surgical(user_text: str = "") -> bool:
    """True for rembg / outpaint / region inpaint — Comfy, not Pillow crop."""
    return bool(_IMAGE_SURGICAL_ASK.search(user_text or ""))


def wants_image_variations(user_text: str = "") -> bool:
    """True for four versions / variations / n=4 — image with n, not a crop."""
    return bool(_IMAGE_VARIATIONS_ASK.search(user_text or ""))


def wants_same_seed(user_text: str = "") -> bool:
    """True when they want the last generate reproduced, not a new roll."""
    return bool(_IMAGE_SAME_SEED.search(user_text or ""))


def wants_image_edit(user_text: str = "") -> bool:
    """True when the ask is to change the picture: size, crop, overlay, or strength."""
    raw = user_text or ""
    if wants_image_restyle(raw) or wants_image_surgical(raw):
        return False
    from arelis.core.claims import detect_cas_ask

    if detect_cas_ask(raw):
        return False
    return bool(_IMAGE_EDIT_ASK.search(raw))


def wants_person_identify(user_text: str = "") -> bool:
    """True for a pasted-photo 'who is this?' — not camera Point-and-Ask."""
    return bool(_PERSON_IDENTIFY.search(user_text or ""))


def overlay_text_from_ask(user_text: str = "") -> str:
    """Glyphs to stamp on a picture, or '' when the ask is not an overlay."""
    raw = (user_text or "").strip()
    if not raw:
        return ""
    for pat in (_OVERLAY_SAYS, _OVERLAY_QUOTED):
        hit = pat.search(raw)
        if not hit:
            continue
        text = (hit.group("text") or "").strip().strip("\"'")
        text = _OVERLAY_TRAIL.sub("", text).strip(" ,.")
        if text:
            return text[:80]
    return ""


def route_tool(kind: str, user_text: str = "") -> str:
    """Pick the tool for an attachment kind given the user's ask."""
    kind = (kind or "other").strip().lower()
    from arelis.core.email_complete import looks_like_compose_email

    if looks_like_compose_email(user_text):
        return "send_email"
    if kind == "image":
        # Overlay / resize beats OCR: "add text in this image" is not a read.
        # Restyle is Comfy img2img (image + path), not Pillow.
        if (
            wants_image_restyle(user_text)
            or wants_image_surgical(user_text)
            or wants_image_variations(user_text)
        ):
            return "image"
        if wants_image_edit(user_text):
            return "image_edit"
        if wants_image_text(user_text):
            return "ocr"
        return "vision"
    if kind == "pdf":
        return "doc_extract"
    if kind == "data":
        return "analyze"
    if kind == "text":
        return "workspace read"
    return "(unsupported — say what you can)"


_ATTACH_KIND_LINE = re.compile(
    r"^\s*-\s+\S+\s+\((?P<kind>[a-z]+)\)",
    re.IGNORECASE | re.MULTILINE,
)


def attachment_kinds_from_turn(text: str) -> set[str]:
    """Parse kinds from an Attachments-for-this-turn block in the user message."""
    raw = text or ""
    if "Attachments for this turn" not in raw:
        return set()
    return {m.group("kind").lower() for m in _ATTACH_KIND_LINE.finditer(raw)}


def is_short_affirmation(text: str) -> bool:
    """True for bare yes/yea/ok-style replies that continue a prior offer."""
    return bool(_SHORT_AFFIRM.match((text or "").strip()))


def parse_attachments_from_turn(text: str) -> list[dict[str, Any]]:
    """Pull path/kind/source rows from an Attachments-for-this-turn block."""
    raw = text or ""
    if "Attachments for this turn" not in raw:
        return []
    rows: list[dict[str, Any]] = []
    for match in _ATTACH_LINE.finditer(raw):
        path = (match.group("path") or "").strip()
        if not path:
            continue
        source = (match.group("source") or "").strip()
        # Re-detect kind from path so a prior "other" .log becomes text after fixes.
        rows.append(
            {
                "path": path,
                "name": Path(path).name,
                "kind": detect_kind(path),
                "source_path": source,
            }
        )
    return rows


def split_attachments_turn(text: str) -> tuple[str, str]:
    """Split a user turn into (attachments_block, ask). Ask may be empty."""
    raw = text or ""
    marker = "Attachments for this turn"
    if marker not in raw:
        return "", raw.strip()
    start = raw.find(marker)
    # Block ends at the first blank line after the last attachment/rule line,
    # or at end of string.
    rest = raw[start:]
    parts = rest.split("\n\n", 1)
    block = parts[0].strip()
    ask = parts[1].strip() if len(parts) > 1 else ""
    return block, ask


NEW_SESSION_TITLE = "new chat"


def display_session_title(raw: str) -> str:
    """History / phone label. Blank threads read as ``new chat``, not untitled."""
    text = (raw or "").strip()
    if not text or text in {"(untitled)", "untitled"}:
        return NEW_SESSION_TITLE
    if text.startswith("Attachments for this turn") or "\nAttachments for this turn" in text:
        return session_title_from_turn(text) or NEW_SESSION_TITLE
    if text.startswith("Continue the prior request"):
        return session_title_from_turn(text) or NEW_SESSION_TITLE
    return text


def session_title_from_turn(content: str, *, max_len: int = 80) -> str:
    """Human session title from a user turn — never the attachments boilerplate.

    Attach turns are stored as ``Attachments for this turn…\\n\\n{ask}``. Using
    the first line raw made History look like a system prompt dump.
    """
    raw = (content or "").strip()
    if not raw:
        return ""
    _block, ask = split_attachments_turn(raw)
    text = ask.strip() if ask.strip() else raw
    # Affirmation continuations: prefer "Prior ask:" when present.
    prior = re.search(
        r"(?im)^Prior ask:\s*(.+)$",
        text,
    )
    if prior:
        text = prior.group(1).strip()
    if text.startswith("Attachments for this turn"):
        for line in text.splitlines()[1:]:
            line = line.strip()
            if not line.startswith("- "):
                continue
            path = line[2:].split(" (", 1)[0].strip()
            name = Path(path).name
            if name:
                return f"Attached {name}"[:max_len]
        return "Attached files"
    first = text.splitlines()[0].strip()
    if not first or first.startswith("Attachments for this turn"):
        return "Attached files"
    if first.startswith("Continue the prior request"):
        return "Attached files"
    return first[:max_len]


_DESCRIBE_OFFER = re.compile(
    r"(?i)\b(describe|caption|tell\s+me\s+about|what\s+do\s+you\s+see)\b"
)


def continue_prior_image_describe(
    user_text: str,
    history: list[Any] | None = None,
) -> str | None:
    """Expand 'yes' after Arelis offered to describe a just-generated image."""
    if not is_short_affirmation(user_text):
        return None
    pairs = history_pairs(history)
    prior_assistant = ""
    for role, content in reversed(pairs):
        if role == "assistant":
            prior_assistant = (content or "").strip()
            break
    if not prior_assistant or not _DESCRIBE_OFFER.search(prior_assistant):
        return None
    path = ""
    for _role, content in reversed(pairs):
        text = content or ""
        if "outputs" in text.lower() and any(
            ext in text.lower() for ext in (".png", ".jpg", ".jpeg", ".webp")
        ):
            match = re.search(
                r"((?:[A-Za-z]:)?[^\s\"']+outputs[^\s\"']+\.(?:png|jpe?g|webp|gif))",
                text,
                flags=re.I,
            )
            if match:
                path = match.group(1)
                break
            match = re.search(
                r"(outputs[/\\]images[/\\][^\s\"']+\.(?:png|jpe?g|webp|gif))",
                text,
                flags=re.I,
            )
            if match:
                path = match.group(1)
                break
    if not path:
        return None
    return (
        "The user affirmed your offer to describe the generated image.\n"
        f"Call vision with path={path} now. Do not ask what they meant."
    )


def continue_prior_attachment_ask(
    user_text: str,
    history: list[Any] | None = None,
) -> str | None:
    """Expand a short affirmation into a fresh attachment turn when history has one.

    Re-builds the Attachments block with current kind routing so a previously
    misclassified .log (other) becomes workspace-readable text.
    """
    if not is_short_affirmation(user_text):
        return None
    pairs = history_pairs(history)
    prior_user = ""
    prior_ask = ""
    prior_assistant = ""
    for role, content in reversed(pairs):
        if role == "assistant" and not prior_assistant:
            prior_assistant = (content or "").strip()
            continue
        if role == "user" and "Attachments for this turn" in (content or ""):
            prior_user = content or ""
            _, prior_ask = split_attachments_turn(prior_user)
            break
    if not prior_user:
        return None
    atts = parse_attachments_from_turn(prior_user)
    if not atts:
        return None
    # Prefer the original ask for tool routing (e.g. OCR vs vision); fall back
    # to the affirmation when the prior turn was attachments-only.
    route_text = prior_ask or user_text.strip()
    block = format_attachments_block(atts, user_text=route_text)
    if not block:
        return None
    offer = ""
    if prior_assistant:
        # Keep the offer short so it does not crowd the turn.
        offer = " ".join(prior_assistant.split())
        if len(offer) > 280:
            offer = offer[:279].rstrip() + "…"
    lines = [
        block,
        "",
        "Continue the prior request about these attachments. "
        "Call the listed tool(s); do not invent file contents and do not "
        "reset into a generic greeting.",
    ]
    if prior_ask:
        lines.append(f"Prior ask: {prior_ask}")
    if offer:
        lines.append(f"Assistant offered: {offer}")
    lines.append(f"User affirmed: {user_text.strip()}")
    return "\n".join(lines)


def _safe_name(name: str) -> str:
    base = Path(name).name.strip() or "file"
    cleaned = _UNSAFE.sub("_", base).strip(" ._")
    return cleaned or "file"


def _unique_dest(directory: Path, name: str) -> Path:
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem = Path(name).stem
    suffix = Path(name).suffix
    n = 2
    while True:
        alt = directory / f"{stem}-{n}{suffix}"
        if not alt.exists():
            return alt
        n += 1


def _rel_posix(path: Path) -> str:
    return display_path(path)


def resolve_staged_path(stored: str) -> Path | None:
    """Absolute file for a staged attachment path, or None if it is gone.

    ``Attachment.path`` is workspace-relative posix under ``user_data_dir()``.
    Tests and clipboard pastes may also pass an absolute path. The composer
    rail and the sent bubble share this so they cannot disagree.
    """
    raw = (stored or "").strip()
    if not raw:
        return None
    path = Path(raw)
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append(user_data_dir() / path)
        candidates.append(Path.cwd() / path)
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            if resolved.is_file():
                return resolved
        except OSError:
            continue
    return None


def stage_files(
    paths: list[Path | str],
    *,
    drops_root: Path | None = None,
    max_attachments: int = MAX_ATTACHMENTS,
    max_bytes: int = MAX_BYTES,
    existing_count: int = 0,
) -> StageResult:
    """Copy files into data/drops/<YYYYMMDD>/; return ok + per-file errors."""
    root = drops_root or DROPS_ROOT
    day = datetime.now(UTC).strftime("%Y%m%d")
    dest_dir = root / day
    dest_dir.mkdir(parents=True, exist_ok=True)

    ok: list[Attachment] = []
    errors: list[str] = []
    room = max(0, max_attachments - max(0, existing_count))

    for raw in paths:
        if len(ok) >= room:
            errors.append(f"Attachment limit is {max_attachments} per message.")
            break
        src = Path(raw)
        try:
            src = src.expanduser().resolve()
        except OSError as exc:
            errors.append(f"Could not resolve {raw}: {exc}")
            continue
        if not src.is_file():
            errors.append(f"Not a file: {src.name}")
            continue
        try:
            size = src.stat().st_size
        except OSError as exc:
            errors.append(f"Could not read {src.name}: {exc}")
            continue
        if size <= 0:
            errors.append(f"Empty file skipped: {src.name}")
            continue
        if size > max_bytes:
            mb = max_bytes / (1024 * 1024)
            errors.append(f"{src.name} is larger than {mb:.0f} MB.")
            continue
        dest = _unique_dest(dest_dir, _safe_name(src.name))
        try:
            shutil.copy2(src, dest)
        except OSError as exc:
            errors.append(f"Could not copy {src.name}: {exc}")
            continue
        ok.append(
            Attachment(
                id=uuid4().hex,
                name=dest.name,
                path=_rel_posix(dest),
                source_path=str(src),
                kind=detect_kind(dest),
                bytes=int(size),
            )
        )
    return StageResult(ok=ok, errors=errors)


def stage_bytes(
    data: bytes,
    name: str,
    *,
    drops_root: Path | None = None,
    max_bytes: int = MAX_BYTES,
    existing_count: int = 0,
    max_attachments: int = MAX_ATTACHMENTS,
) -> StageResult:
    """Write named bytes into drops. Phone uploads land here, same as a desktop drop."""
    if existing_count >= max_attachments:
        return StageResult(
            ok=[],
            errors=[f"Attachment limit is {max_attachments} per message."],
        )
    if not data:
        return StageResult(ok=[], errors=["File was empty."])
    if len(data) > max_bytes:
        mb = max_bytes / (1024 * 1024)
        return StageResult(ok=[], errors=[f"File is larger than {mb:.0f} MB."])
    root = drops_root or DROPS_ROOT
    day = datetime.now(UTC).strftime("%Y%m%d")
    dest_dir = root / day
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique_dest(dest_dir, _safe_name(name))
    try:
        dest.write_bytes(data)
    except OSError as exc:
        return StageResult(ok=[], errors=[f"Could not save {name}: {exc}"])
    att = Attachment(
        id=uuid4().hex,
        name=dest.name,
        path=_rel_posix(dest),
        source_path="",
        kind=detect_kind(dest),
        bytes=len(data),
    )
    return StageResult(ok=[att], errors=[])


def stage_image_bytes(
    data: bytes,
    *,
    suffix: str = ".png",
    drops_root: Path | None = None,
    max_bytes: int = MAX_BYTES,
    existing_count: int = 0,
    max_attachments: int = MAX_ATTACHMENTS,
) -> StageResult:
    """Write clipboard/image bytes into drops as paste-<timestamp>.<suffix>."""
    if existing_count >= max_attachments:
        return StageResult(
            ok=[],
            errors=[f"Attachment limit is {max_attachments} per message."],
        )
    if not data:
        return StageResult(ok=[], errors=["Clipboard image was empty."])
    if len(data) > max_bytes:
        mb = max_bytes / (1024 * 1024)
        return StageResult(ok=[], errors=[f"Image is larger than {mb:.0f} MB."])

    root = drops_root or DROPS_ROOT
    day = datetime.now(UTC).strftime("%Y%m%d")
    dest_dir = root / day
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = suffix if suffix.startswith(".") else f".{suffix}"
    if ext.lower() not in _IMAGE:
        ext = ".png"
    stamp = datetime.now(UTC).strftime("%H%M%S")
    dest = _unique_dest(dest_dir, f"paste-{stamp}{ext.lower()}")
    try:
        dest.write_bytes(data)
    except OSError as exc:
        return StageResult(ok=[], errors=[f"Could not save pasted image: {exc}"])
    att = Attachment(
        id=uuid4().hex,
        name=dest.name,
        path=_rel_posix(dest),
        source_path="",
        kind="image",
        bytes=len(data),
    )
    return StageResult(ok=[att], errors=[])


def format_attachments_block(
    attachments: list[dict[str, Any] | Attachment],
    *,
    user_text: str = "",
) -> str:
    """Deterministic prefix for the model: paths + required tools by kind."""
    if not attachments:
        return ""
    lines = [
        "Attachments for this turn (call the listed tool; do not invent contents):",
    ]
    kinds: set[str] = set()
    for item in attachments:
        if isinstance(item, Attachment):
            data = item.as_dict()
        else:
            data = item
        path = str(data.get("path") or "").strip()
        kind = str(data.get("kind") or detect_kind(path)).strip() or "other"
        kinds.add(kind)
        source = str(data.get("source_path") or "").strip()
        tool = route_tool(kind, user_text)
        extra = f" source={source}" if source else ""
        lines.append(f"- {path} ({kind}){extra} → {tool}")
    rules: list[str] = []
    from arelis.core.email_complete import looks_like_compose_email

    emailing = looks_like_compose_email(user_text)
    if emailing:
        rules.append(
            "Email ask: call send_email with attach= the staged path (or "
            "source= absolute path). Do not call analyze unless they asked "
            "for row/column stats."
        )
    if "image" in kinds and not emailing:
        # "analyze" is named here for the same reason doc_extract is: the user
        # says "analyze this picture", and the tool wearing that name reads
        # spreadsheets. Without the line the ask lands on a pandas reader.
        if (
            wants_image_restyle(user_text)
            or wants_image_surgical(user_text)
            or wants_image_variations(user_text)
        ):
            rules.append(
                "Images: call image with path= the staged path above. "
                "Restyle: prompt the look (watercolor, anime, …) — img2img. "
                "Four versions / variations: n=4. Cut-out: "
                "remove_background=true. Outpaint/uncrop/extend the canvas: "
                "outpaint=all. Change the left/right/top/bottom/center: "
                "mask_region=. Do not call image_edit; Pillow cannot paint "
                "or cut a background. Do not call vision. Do not web_search "
                "for stock photos."
            )
        elif wants_image_edit(user_text):
            # The three wrong tools are named because all three were tried on
            # this exact ask before image_edit existed.
            rules.append(
                "Images: call image_edit with the exact staged path above and the "
                "size, adjustments, or text overlay asked for (e.g. "
                "preset=youtube_thumbnail or width=1280 height=720, vibrance=1.3, "
                "crop=left/right/center, scale=2, or text=Arelis). It writes a "
                "new file and leaves the original alone. Do not call image — "
                "that generates a different picture from a text prompt and "
                "cannot modify this file. Do not call vision, which can only "
                "look at it. Do not call send_sms — 'add text' on a picture is "
                "an overlay, not a message. Do not call the calculator for "
                "the pixel dimensions."
            )
        elif wants_image_text(user_text):
            rules.append(
                "Images: call ocr(action=text, path=…). "
                "Do not call doc_extract (PDF-only) or analyze (tables only) "
                "on images, whatever verb the user used."
            )
        else:
            rules.append(
                "Images: call vision(path=…) using the exact staged path above "
                "(not a different filename the user typed). "
                "Do not call doc_extract (PDF-only) or analyze (tables only) "
                "on images, whatever verb the user used."
            )
    if "pdf" in kinds and not emailing:
        rules.append(
            "PDFs: call doc_extract. Do not call analyze on a PDF (tables only)."
        )
    if "data" in kinds and not emailing:
        rules.append("Tables (csv/xlsx/json): call analyze.")
    if "text" in kinds and not emailing:
        rules.append(
            "Text/markdown/logs (txt, md, log, yaml, …): call workspace action=read."
        )
    if rules:
        lines.append("Rules: " + " ".join(rules))
    return "\n".join(lines)
