"""What a person reads when something fails, as opposed to what a model reads.

``arelis.llm.errors`` already does this for Ollama: chat gets a short instruction,
the exception and the URL go to Thinking. Two paths never got the same treatment.

The orchestrator's last line of defence published
``f"Turn failed: {exc.__class__.__name__}: {exc}"``, which the UI put straight in
the transcript — so the worst moment the app has produced the least human sentence
it could, ``Turn failed: ConnectError: [Errno 11001] getaddrinfo failed``.

Failed tool output went to chat verbatim, up to 500 characters. That was a
deliberate choice and half right: "Not a file: C:/typo.csv" is exactly what the
user needs, and hiding it made a wrong path look like a silent no-op. What it did
not anticipate is that tool failures are written *for the model* — the analyze tool
now answers a bad file type with "Call vision(path=…) for an image", which is an
instruction to a 7B appearing in a human's chat window.

So the rule here is not "hide the output". It is: pass through what a person can
act on, and swap out anything addressed to the model. Detail is never lost — it
goes to Thinking and Workspace either way.
"""

from __future__ import annotations

import json
import re

TURN_FAILED_NOTICE = (
    "Something went wrong mid-turn, so I stopped rather than guess. "
    "The details are in Thinking (Ctrl+1). Try again, or rephrase."
)

# Sentences aimed at the model. A tool that says "Call vision(path=…)" or
# "Rejected: `calculator` takes none of…" is mid-conversation with the 7B, and
# repeating that to the user reads as the app talking to itself.
_MODEL_DIRECTED = re.compile(
    r"(?i)("
    r"^rejected:|"
    r"\bcall\s+\w+\(|"
    r"\bcall\s+(?:the\s+)?\w+\s+tool\b|"
    r"\bdo not\s+(?:call|invent|guess|quote|scrape)\b|"
    r"\bwith its own arguments\b|"
    r"\bintent preflight\b|"
    r"\ballow still applies\b"
    r")"
)

# Instruction footers on a successful tool result. Strip only when that result
# is about to become chat because Qwen left the wrap-up empty.
_SUCCESS_FOOTER = re.compile(
    r"(?i)("
    r"summarize these events|"
    r"do not invent(?:\s+events)?|"
    r"do not quote(?:\s+(?:event\s+ids|google/outlook))|"
    r"do not quote event ids"
    r")"
)

_WORKSPACE_LISTING_LINE = re.compile(r"(?m)^\[(?:dir|file)\]\s")
_PAGE_META = re.compile(r"(?i)^(site|by|published|length|url|sources|#+\s*sources)\s*:")
_SEARCH_TITLE = re.compile(r"(?i)^\s*\d+\.\s*Title:\s*(.+)$")
_PAGE_TOOLS = frozenset({"scrape", "web_fetch", "browser"})
_SEARCH_TOOLS = frozenset({"web_search"})
_PAGE_WRITE_TOOLS = frozenset({"scrape", "web_search", "web_fetch", "browser"})
_ALGEBRA_WRITE_TOOLS = frozenset({"cas", "calculator", "python", "units", "plot"})
_BOT_WALL = re.compile(
    r"(?i)\b("
    r"are you a robot|"
    r"captcha|"
    r"access denied|"
    r"sign in to continue|"
    r"password-protected|"
    r"verify you are human"
    r")\b"
)
_PAGE_CHAT_CHARS = 420
# Short fact lines (a price, a one-line hit) can ship as chat.
# A scraped article or a SERP must not — ask the model to write first.
_PAGE_WRITE_NUDGE_CHARS = 400
# They typed an equation. "hard math tonight" is not that.
_TYPED_EQUATION = re.compile(r"(?i)[a-z][a-z0-9]*\s*(?:\*\*|\^|²|[+\-*/]).{0,48}=")


def _algebra_was_asked(ask: str) -> bool:
    from arelis.core.claims import detect_cas_ask, detect_math_ask, detect_units_ask

    raw = ask or ""
    return (
        detect_cas_ask(raw)
        or detect_math_ask(raw)
        or detect_units_ask(raw)
        or bool(_TYPED_EQUATION.search(raw))
    )


# Human copy for the tools whose failures reach the transcript, used when the raw
# output turns out to be model-directed. Keyed by tool name.
_TOOL_NOTICES: dict[str, str] = {
    "analyze": (
        "That file is not a spreadsheet, so I could not read it as a table. "
        "I will try the right reader for it."
    ),
    "workspace": "I could not read that file. The path is in Workspace.",
    "image": "Image generation failed. The details are in Workspace.",
    "doc_extract": "I could not read that PDF. The details are in Workspace.",
    "document": "I could not write that file. The details are in Thinking.",
    "vision": "I could not open that image.",
}

_GENERIC_TOOL_NOTICE = "`{tool}` did not complete. The details are in Thinking."

# Long enough for "Not a file: <a real Windows path>", short enough that a stack
# trace or a page of scraped text cannot land in the transcript.
_MAX_PASSTHROUGH = 240


_ERRNO_PREFIX = re.compile(r"^\[(?:Errno|WinError)\s*-?\d+\]\s*")


def plain_reason(exc: BaseException) -> str:
    """The readable half of an exception: no class name, no errno bracket.

    ``open failed: [Errno 13] Permission denied: 'C:/x'`` becomes
    ``Permission denied: 'C:/x'``. The refusal itself is usually the useful part —
    a path outside the workspace roots, a file held open by something else — so
    this trims the machine framing rather than replacing the sentence.
    """
    text = str(exc).strip()
    text = _ERRNO_PREFIX.sub("", text)
    if not text:
        return type(exc).__name__
    if len(text) > _MAX_PASSTHROUGH:
        text = text[:_MAX_PASSTHROUGH].rstrip() + "…"
    return text[0].upper() + text[1:] if text[:1].islower() else text


def turn_failed_notice(exc: BaseException) -> tuple[str, str]:
    """Return (chat copy, Thinking detail) for an unhandled turn failure.

    An Ollama exception that reaches this far is still an Ollama exception, so it
    keeps the copy that names the chip in the title bar rather than the generic
    line — the user's next action is different.
    """
    detail = f"{type(exc).__name__}: {exc}"
    try:
        import httpx

        from arelis.llm.errors import classify_ollama_failure

        if isinstance(exc, (httpx.HTTPError, httpx.NetworkError, httpx.TimeoutException)):
            failure = classify_ollama_failure(exc)
            return failure.chat, failure.detail
    except Exception:
        # Copy is not worth an exception inside the handler of an exception.
        pass
    return TURN_FAILED_NOTICE, detail


def is_model_directed(text: str) -> bool:
    """True when this sentence is talking to the model, not to the user."""
    return bool(_MODEL_DIRECTED.search((text or "").strip()))


def tool_failure_notice(tool: str, output: str) -> str:
    """One line a person can act on, for a tool that failed.

    Passes the tool's own first line through when it is plain — "Not a file:
    C:/typo.csv" is the whole answer and swapping it for something vaguer would
    undo the reason this was ever shown. Substitutes human copy when the line is
    addressed to the model, or when there is nothing to show.
    """
    name = (tool or "").strip() or "that tool"
    first = ""
    for line in (output or "").splitlines():
        if line.strip():
            first = line.strip()
            break

    if not first or is_model_directed(first) or is_model_directed(output or ""):
        return _TOOL_NOTICES.get(name, _GENERIC_TOOL_NOTICE.format(tool=name))
    if len(first) > _MAX_PASSTHROUGH:
        return _TOOL_NOTICES.get(name, _GENERIC_TOOL_NOTICE.format(tool=name))
    return first


def _strip_success_footers(text: str) -> str:
    """Drop model-only instruction lines; keep the person-facing body."""
    kept: list[str] = []
    for line in (text or "").splitlines():
        if _SUCCESS_FOOTER.search(line):
            continue
        if is_model_directed(line):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def should_nudge_write_after_page(tool: str, output: str) -> bool:
    """True when empty-after-tool would paste an article instead of a fact.

    Qwen3.5 often leaves chat empty after scrape and puts the wrap-up in
    thinking. Shipping a short price is fine. Shipping a blog is not —
    the user asked for an answer, not the page.
    """
    if (tool or "").strip() not in _PAGE_WRITE_TOOLS:
        return False
    out = output or ""
    if _BOT_WALL.search(out):
        return True
    if "Site:" in out or out.lstrip().startswith("# "):
        return True
    return len(out) >= _PAGE_WRITE_NUDGE_CHARS


def should_nudge_write_after_algebra(tool: str) -> bool:
    """CAS / calc dumps are not a chat line. Ask for a sentence first."""
    return (tool or "").strip() in _ALGEBRA_WRITE_TOOLS


_RESULT_TOOLS = frozenset({"calculator", "units"})


def _algebra_result_tokens(output: str) -> list[str]:
    """Numeric / unit tokens from a calculator or units receipt."""
    body = (output or "").strip()
    if not body:
        return []
    right = body.rsplit(" = ", 1)[-1].strip() if " = " in body else body
    tokens: list[str] = []
    if " (exactly " in right:
        main, rest = right.split(" (exactly ", 1)
        main = main.strip()
        exact = rest.rstrip(")").strip()
        if main:
            tokens.append(main)
        if exact:
            tokens.append(exact)
    elif right:
        tokens.append(right.split()[0] if right.split() else right)
        # "5 mi = 8.047 km" — keep the converted magnitude too.
        parts = right.split()
        if len(parts) >= 2 and parts[-1].isalpha():
            tokens.append(parts[0])
    return [t for t in tokens if t]


def _token_in_reply(token: str, text: str) -> bool:
    tok = (token or "").strip()
    if not tok or not text:
        return False
    if re.fullmatch(r"-?\d+(?:\.\d+)?", tok):
        # "2." is the answer plus a period. "2.5" is a different number.
        return bool(re.search(rf"(?<![\d.]){re.escape(tok)}(?!\d)(?!\.\d)", text))
    return tok in text


def reply_states_algebra_result(content: str, tool: str, output: str) -> bool:
    """True when chat already states the calculator / units result.

    Qwen3.5 often puts the number in thinking and ships 'What's next?' as
    the bubble. Empty-after-tool only catches a blank reply; this is the
    filler case. CAS dumps stay on the write-up path — do not police them.
    """
    name = (tool or "").strip()
    if name not in _RESULT_TOOLS:
        return True
    tokens = _algebra_result_tokens(output)
    if not tokens:
        return True
    return any(_token_in_reply(tok, content or "") for tok in tokens)


def chat_followup_from_tool(tool: str, output: str, *, ask: str = "") -> str:
    """Person-facing copy when the model leaves chat empty after a tool.

    The model still sees the raw tool result (including instruction footers).
    This path is only the last-resort chat line.
    """
    body = (output or "").strip()
    name = (tool or "").strip()
    if name in _ALGEBRA_WRITE_TOOLS and name != "plot" and not _algebra_was_asked(ask):
        return "Ready when you are. What problem do you want to start with?"
    if not body:
        return "The tool finished, but I could not write a follow-up. Send the same ask again."
    listing = _WORKSPACE_LISTING_LINE.search(body) or body.lstrip().startswith(("[dir]", "[file]"))
    if name == "workspace" and listing:
        return "That listing is in Workspace."
    if listing and name in {"", "workspace"}:
        return "That listing is in Workspace."
    cleaned = _strip_success_footers(body)
    if not cleaned:
        if name == "agenda":
            return "No events in this window."
        return "The tool finished. The details are in Workspace."
    # Ahead of the page branch, because web_fetch is on both lists now: it was
    # a page reader when that branch was written and it answers APIs as well
    # since it grew POST/PUT/PATCH/DELETE. _page_talk has no idea what to do
    # with a response body, so it handed the whole object back unchanged.
    if _is_json_body(cleaned):
        return (
            "The call went through and came back with data, but I did not get "
            "a sentence out of it. Ask again and I will read the response."
        )
    if name == "calculator":
        return pretty_calculator_chat(cleaned)
    if name in _PAGE_TOOLS:
        if _BOT_WALL.search(cleaned):
            return (
                "That page did not give a usable source (login, captcha, "
                "or a bot check). I need another URL or a search — this "
                "is not the report."
            )
        return _page_talk(cleaned)
    if name in _SEARCH_TOOLS:
        return _search_talk(cleaned)
    if name == "doc_extract" and (
        "source: ink" in cleaned.lower() or "no text layer" in cleaned.lower()
    ):
        return (
            "That PDF is handwritten or scanned — I still need to look at "
            "the page images. Ask me again if I stopped on the path list."
        )
    if len(cleaned) > 1600:
        cleaned = cleaned[:1597].rstrip() + "…"
    return cleaned


_SIMPLE_FRAC = re.compile(r"^-?\d{1,2}/\d{1,2}$")
_CALC_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")


def pretty_calculator_chat(output: str) -> str:
    """Chat line from a calculator receipt — not 15 decimals and a fraction.

    The model still sees the exact tool output. This is only what we ship
    when she leaves the bubble empty (or filler without the number).
    """
    body = (output or "").strip()
    if not body:
        return body
    if " = " not in body:
        return _pretty_number_token(body)
    left, right = body.rsplit(" = ", 1)
    main = right.strip()
    exact = ""
    if " (exactly " in main:
        main, rest = main.split(" (exactly ", 1)
        main = main.strip()
        exact = rest.rstrip(")").strip()
    pretty = _pretty_number_token(main, expr=left)
    if exact and _SIMPLE_FRAC.fullmatch(exact) and pretty != exact:
        return f"{left} = {pretty} (exactly {exact})"
    return f"{left} = {pretty}"


def _pretty_number_token(raw: str, *, expr: str = "") -> str:
    text = (raw or "").strip()
    if not _CALC_NUMBER.fullmatch(text):
        return text
    if "." not in text and "e" not in text.lower():
        return text
    try:
        val = float(text)
    except ValueError:
        return text
    if val.is_integer() and abs(val) < 2**53:
        return str(int(val))
    # `((now-then)/then)*100` is a percent. One decimal, not 15.
    if expr and re.search(r"\*\s*100\b", expr) and abs(val) < 10000:
        return f"{val:.1f}"
    decimals = 0
    frac = text.split(".", 1)[1]
    frac = re.split(r"[eE]", frac, maxsplit=1)[0]
    decimals = len(frac)
    if decimals > 4:
        if abs(val) < 1:
            return f"{val:.4g}"
        shown = f"{val:.2f}".rstrip("0").rstrip(".")
        return shown or "0"
    return text


def _is_json_body(text: str) -> bool:
    """True when the whole output is one JSON value.

    The last branch of `chat_followup_from_tool` pastes the tool's output into
    chat verbatim, which is right for a tool that answers in words and wrong
    for one that answers in data. `web_fetch` grew POST/PUT/PATCH/DELETE and
    now returns API bodies, so an empty model reply put a raw response object —
    tokens and all — in the bubble as if she had written it.

    Parsed rather than pattern-matched, so a sentence that merely starts with a
    brace is still a sentence, and a body that only looks like JSON is still
    shown rather than swallowed.
    """
    body = (text or "").strip()
    if not body or body[0] not in "{[":
        return False
    try:
        json.loads(body)
    except (ValueError, TypeError):
        return False
    return True


def _first_sentences(text: str, *, n: int = 2, cap: int = _PAGE_CHAT_CHARS) -> str:
    raw = " ".join((text or "").split())
    if not raw:
        return ""
    parts: list[str] = []
    start = 0
    for i, ch in enumerate(raw):
        if ch in ".!?" and i + 1 < len(raw) and raw[i + 1] == " ":
            parts.append(raw[start : i + 1].strip())
            start = i + 2
            if len(parts) >= n:
                break
    if not parts:
        parts.append(raw)
    out = " ".join(parts)
    if len(out) > cap:
        out = out[: cap - 1].rstrip() + "…"
    return out


def _page_talk(output: str) -> str:
    """Title + a couple of sentences. Not the article."""
    title = ""
    body: list[str] = []
    for raw in (output or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[") or line.startswith("On-page"):
            continue
        if _PAGE_META.match(line):
            continue
        if line.startswith("# "):
            if not title:
                title = line[2:].strip()
            continue
        body.append(line)
    lede = _first_sentences(" ".join(body))
    if title and lede:
        if lede.lower().startswith(title.lower()[:24]):
            return lede
        return f"{title}\n\n{lede}"
    return title or lede or output[:_PAGE_CHAT_CHARS]


def _search_talk(output: str) -> str:
    """First hit, not the whole SERP."""
    for raw in (output or "").splitlines():
        hit = _SEARCH_TITLE.match(raw)
        if hit:
            title = hit.group(1).strip()
            if title:
                return title
    return _first_sentences(output, n=1, cap=240)


__all__ = [
    "TURN_FAILED_NOTICE",
    "chat_followup_from_tool",
    "is_model_directed",
    "plain_reason",
    "reply_states_algebra_result",
    "should_nudge_write_after_algebra",
    "should_nudge_write_after_page",
    "tool_failure_notice",
    "turn_failed_notice",
]
