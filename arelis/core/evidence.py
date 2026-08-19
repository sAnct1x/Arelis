"""Per-turn evidence ledger — warrants for contingent claims.

Tools register short spans when they succeed. The exactness finalizer checks
that news/weather/memory/price answers have at least one matching warrant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class Warrant:
    source: str  # tool name or url
    # web | weather | recall | calc | inbox | inbound_sms | send_* | doc |
    # agenda | git | tasks | analyze
    kind: str
    span: str
    ok: bool
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class EvidenceLedger:
    """Accumulates warrants for one agent turn."""

    def __init__(self) -> None:
        self._items: list[Warrant] = []

    def __len__(self) -> int:
        return len(self._items)

    @property
    def items(self) -> list[Warrant]:
        return list(self._items)

    def add(
        self,
        *,
        source: str,
        kind: str,
        span: str,
        ok: bool,
    ) -> None:
        text = (span or "").strip()
        if not text:
            text = "(empty)"
        self._items.append(
            Warrant(
                source=str(source or "unknown")[:200],
                kind=str(kind or "other"),
                span=text[:400],
                ok=bool(ok),
            )
        )

    def record_tool(
        self,
        name: str,
        *,
        ok: bool,
        output: str,
        data: dict[str, Any] | None,
        args: dict[str, Any] | None = None,
    ) -> None:
        """Map a tool result into zero or more warrants."""
        data = data or {}
        args = args or {}
        if name == "calculator":
            self.add(
                source="calculator",
                kind="calc",
                span=str(data.get("value") if data.get("value") is not None else output)[:200],
                ok=ok,
            )
            return
        if name == "cas":
            span = str(data.get("result") or output or "")[:200]
            self.add(source="cas", kind="cas", span=span, ok=ok)
            return
        if name == "units":
            span = str(data.get("value") or output or "")[:300]
            self.add(source="units", kind="units", span=span, ok=ok)
            return
        if name == "plot":
            span = str(data.get("path") or output or "")[:300]
            self.add(source="plot", kind="plot", span=span, ok=ok)
            return
        if name == "catalog":
            span = str(data.get("query") or data.get("target") or output or "")[:300]
            self.add(source="catalog", kind="catalog", span=span, ok=ok)
            return
        if name == "weather":
            self.add(
                source="weather",
                kind="weather",
                span=(output or "")[:300],
                ok=ok,
            )
            return
        if name in {"scrape", "web_fetch"}:
            url = str(data.get("url") or args.get("url") or name)
            # Only a fetched page counts as a web warrant (not search snippets).
            self.add(source=url, kind="web", span=(output or "")[:300], ok=ok)
            # Failure taxonomy for perception honesty.
            if not ok:
                reason = _scrape_fail_reason(output)
                self.add(
                    source=url,
                    kind="web_fail",
                    span=reason,
                    ok=False,
                )
            return
        if name == "web_search":
            self.add(
                source="web_search",
                kind="web_search",
                span=(output or "")[:300],
                ok=ok,
            )
            return
        if name == "research_report":
            # Pipeline always searches; successful scrapes become web warrants.
            self.add(
                source="web_search",
                kind="web_search",
                span=str(data.get("query") or args.get("query") or output or "")[:300],
                ok=ok,
            )
            if ok:
                for item in data.get("sources") or []:
                    if not isinstance(item, dict):
                        continue
                    url = str(item.get("url") or "").strip()
                    if not url:
                        continue
                    title = str(item.get("title") or "").strip()
                    span = title or url
                    self.add(source=url, kind="web", span=span[:300], ok=True)
            return
        if name == "recall":
            self.add(
                source="recall",
                kind="recall",
                span=(output or "")[:300],
                ok=ok,
            )
            return
        if name == "inbox":
            span = _inbox_span(output, data, args)
            self.add(source="inbox", kind="inbox", span=span, ok=ok)
            return
        if name == "inbound_sms":
            span = (output or "")[:300] or str(data.get("count", ""))
            self.add(source="inbound_sms", kind="inbound_sms", span=span, ok=ok)
            return
        if name == "send_sms":
            to = str(data.get("to") or args.get("to") or "").strip()
            body = str(args.get("body") or data.get("body") or "").strip()
            span = f"to={to}" if to else (output or "send_sms")[:200]
            if body:
                span = f"{span} body={body[:120]}"
            self.add(source="send_sms", kind="send_sms", span=span[:300], ok=ok)
            return
        if name == "send_email":
            to = str(data.get("to") or args.get("to") or "").strip()
            subject = str(data.get("subject") or args.get("subject") or "").strip()
            parts = [
                p
                for p in (
                    f"to={to}" if to else "",
                    f"subject={subject}" if subject else "",
                )
                if p
            ]
            span = " ".join(parts) if parts else (output or "send_email")[:200]
            self.add(source="send_email", kind="send_email", span=span[:300], ok=ok)
            return
        # Local PDF extract → doc warrant (path/page span).
        if name == "doc_extract":
            path = str(data.get("path") or args.get("path") or "doc_extract")
            pages = data.get("pages")
            if isinstance(pages, list) and pages:
                span = f"{path} p{pages[0]}-{pages[-1]}: {(output or '')[:200]}"
            else:
                span = f"{path}: {(output or '')[:240]}"
            self.add(source=path, kind="doc", span=span[:400], ok=ok)
            if not ok:
                fail = str(data.get("fail_class") or "")
                if not fail and "[fail:" in (output or ""):
                    fail = (output or "")[:80]
                self.add(
                    source=path,
                    kind="doc_fail",
                    span=(fail or "fail:other")[:200],
                    ok=False,
                )
            return
        # Local ICS agenda → agenda warrant (prefer over inventing meetings).
        if name == "agenda":
            source = str(data.get("source") or "agenda")
            action = str(data.get("action") or args.get("action") or "")
            count = data.get("count")
            head = (output or "").strip().splitlines()[0] if (output or "").strip() else ""
            parts = [p for p in (action, f"count={count}" if count is not None else "", head) if p]
            span = " | ".join(parts) if parts else "agenda"
            self.add(source=source[:200], kind="agenda", span=span[:300], ok=ok)
            return
        # Read-only git → git warrant (only successful readings count).
        if name == "git_info":
            if not ok:
                return
            action = str(data.get("action") or args.get("action") or "status")
            path = str(data.get("path") or args.get("path") or "")
            head = (output or "").strip().splitlines()[0] if (output or "").strip() else ""
            parts = [p for p in (action, path, head) if p]
            span = " | ".join(parts) if parts else "git_info"
            self.add(source="git_info", kind="git", span=span[:300], ok=True)
            return
        # Local tasks → tasks warrant (only successful tool results count).
        if name == "tasks":
            if not ok:
                return
            action = str(data.get("action") or args.get("action") or "")
            title = str(data.get("title") or args.get("title") or "").strip()
            tid = data.get("id") if data.get("id") is not None else args.get("id")
            parts = [
                p
                for p in (
                    action,
                    f"id={tid}" if tid is not None else "",
                    title,
                    (output or "")[:160],
                )
                if p
            ]
            span = " | ".join(parts) if parts else "tasks"
            self.add(source="tasks", kind="tasks", span=span[:300], ok=True)
            return
        # Goals/commitments → goals warrant (only successful tool results count).
        if name == "goals":
            if not ok:
                return
            action = str(data.get("action") or args.get("action") or "")
            title = str(data.get("title") or args.get("title") or "").strip()
            gid = data.get("id") if data.get("id") is not None else args.get("id")
            parts = [
                p
                for p in (
                    action,
                    f"id={gid}" if gid is not None else "",
                    title,
                    (output or "")[:160],
                )
                if p
            ]
            span = " | ".join(parts) if parts else "goals"
            self.add(source="goals", kind="goals", span=span[:300], ok=True)
            return
        # Local table peek → analyze warrant (only successful readings count).
        if name == "analyze":
            if not ok:
                return
            path = str(data.get("path") or args.get("path") or "analyze")
            action = str(data.get("action") or args.get("action") or "summary")
            head = (output or "").strip().splitlines()[0] if (output or "").strip() else ""
            parts = [p for p in (action, path, head) if p]
            span = " | ".join(parts) if parts else "analyze"
            self.add(source=path[:200], kind="analyze", span=span[:300], ok=True)
            return
        # Single-frame VL → vision warrant (describing that image this turn).
        if name == "vision":
            path = str(data.get("path") or args.get("path") or "vision")
            span = (output or "")[:300] if ok else (output or "vision failed")[:300]
            self.add(source=path[:200], kind="vision", span=span, ok=ok)
            return
        # Local OCR is a see warrant (Point-and-Ask Read may never load VL).
        if name == "ocr":
            path = str(data.get("path") or args.get("path") or "ocr")
            span = (output or "")[:300] if ok else (output or "ocr failed")[:300]
            self.add(source=path[:200], kind="vision", span=span, ok=ok)
            return

    def has_ok(self, kind: str) -> bool:
        return any(w.ok and w.kind == kind for w in self._items)

    def ok_web_sources(self) -> list[str]:
        """Distinct successful web sources (urls or web_search)."""
        seen: list[str] = []
        for w in self._items:
            if w.ok and w.kind == "web" and w.source not in seen:
                seen.append(w.source)
        return seen

    def quote_lines(self, *, limit: int = 3) -> list[str]:
        """Short quote lines for quote-first news answers."""
        lines: list[str] = []
        for w in self._items:
            if not w.ok or w.kind not in {"web", "weather", "recall"}:
                continue
            snippet = w.span.replace("\n", " ").strip()
            if len(snippet) > 160:
                snippet = snippet[:159] + "…"
            lines.append(f'- "{snippet}" ({w.source})')
            if len(lines) >= limit:
                break
        return lines

    def satisfies(self, need_kinds: tuple[str, ...]) -> bool:
        """True when every needed kind has a successful warrant."""
        return not self.missing_kinds(need_kinds)

    def missing_kinds(self, need_kinds: tuple[str, ...]) -> list[str]:
        missing: list[str] = []
        for kind in need_kinds:
            if kind == "math" and not self.has_ok("calc"):
                missing.append("math")
            elif kind == "symbolic" and not self.has_ok("cas"):
                missing.append("symbolic")
            elif kind == "units" and not self.has_ok("units"):
                missing.append("units")
            elif kind == "plot" and not self.has_ok("plot"):
                missing.append("plot")
            elif kind == "catalog" and not self.has_ok("catalog"):
                missing.append("catalog")
            elif kind == "web" and not self.has_ok("web"):
                missing.append("web")
            elif kind == "weather" and not self.has_ok("weather"):
                missing.append("weather")
            elif kind == "recall" and not self.has_ok("recall"):
                missing.append("recall")
            elif kind == "inbox" and not self.has_ok("inbox"):
                missing.append("inbox")
            elif kind == "inbound_sms" and not self.has_ok("inbound_sms"):
                missing.append("inbound_sms")
            elif kind == "send_sms" and not self.has_ok("send_sms"):
                missing.append("send_sms")
            elif kind == "send_email" and not self.has_ok("send_email"):
                missing.append("send_email")
            elif kind == "doc" and not self.has_ok("doc"):
                missing.append("doc")
            elif kind == "agenda" and not self.has_ok("agenda"):
                missing.append("agenda")
            elif kind == "git" and not self.has_ok("git"):
                missing.append("git")
            elif kind == "tasks" and not self.has_ok("tasks"):
                missing.append("tasks")
            elif kind == "goals" and not self.has_ok("goals"):
                missing.append("goals")
            # An urgency claim used to need the attention tool, which was the only
            # thing that could warrant it. That tool is gone, and the data it
            # aggregated lives in tasks, goals and agenda — so any one of those,
            # read this turn, is the warrant now. Left as-is the kind became
            # unsatisfiable, and every "what needs my attention" would refuse.
            elif kind == "attention" and not (
                self.has_ok("tasks")
                or self.has_ok("goals")
                or self.has_ok("agenda")
            ):
                missing.append("attention")
            elif kind == "analyze" and not self.has_ok("analyze"):
                missing.append("analyze")
            elif kind == "vision" and not self.has_ok("vision"):
                missing.append("vision")
        return missing


def classify_fetch_failure(output: str) -> str:
    """Stable failure taxonomy tag for scrape/web_fetch outputs."""
    text = (output or "").lower()
    if "403" in text or "forbidden" in text:
        return "fail:http_403"
    if "404" in text or "not found" in text:
        return "fail:http_404"
    if "paywall" in text or "subscribe" in text:
        return "fail:paywall"
    if "javascript" in text or "js shell" in text or "enable javascript" in text:
        return "fail:js_shell"
    if "empty" in text or "no article" in text or "no content" in text:
        return "fail:empty"
    if "timeout" in text:
        return "fail:timeout"
    if "json" in text and "not an article" in text:
        return "fail:non_html"
    if "non-html" in text or "not an html" in text:
        return "fail:non_html"
    return "fail:other"


def classify_search_failure(
    output: str,
    errors: list[str] | None = None,
) -> str:
    """Stable failure taxonomy tag for web_search backend misses."""
    text = " ".join([output or "", *(errors or [])]).lower()
    if (
        "rate limit" in text
        or "ratelimit" in text
        or "429" in text
        or "too many requests" in text
    ):
        return "fail:rate_limit"
    if "timeout" in text or "timed out" in text:
        return "fail:timeout"
    if (
        "connect" in text
        or "connection refused" in text
        or "name or service not known" in text
        or "nodename nor servname" in text
    ):
        return "fail:connect"
    if "blocked" in text:
        return "fail:blocked"
    if "no results" in text or "found nothing" in text or "empty" in text:
        return "fail:empty"
    return "fail:other"


def _scrape_fail_reason(output: str) -> str:
    return classify_fetch_failure(output)


def _inbox_span(
    output: str,
    data: dict[str, Any],
    args: dict[str, Any],
) -> str:
    """Short provenance span for inbox list/search/read."""
    uid = str(data.get("uid") or data.get("id") or args.get("id") or "").strip()
    subject = str(data.get("subject") or args.get("subject") or "").strip()
    sender = str(data.get("sender") or args.get("sender") or "").strip()
    parts = [p for p in (uid, sender, subject) if p]
    if parts:
        return " | ".join(parts)[:300]
    return (output or "inbox")[:300]


_QUOTE_NUDGE = (
    "Exactness: you have page evidence. Answer with at least one short quoted "
    "span from the scrape/search results, then a one-line takeaway. "
    "Do not invent quotes."
)

_DUAL_HIT_NUDGE = (
    "Exactness (research): you have only one web warrant. "
    "Scrape or search one more independent source before a high-confidence "
    "claim, or clearly mark the answer as single-source."
)


def quote_first_notice() -> str:
    return _QUOTE_NUDGE


def dual_hit_notice() -> str:
    return _DUAL_HIT_NUDGE
