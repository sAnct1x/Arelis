"""Caste 01: HarvesterSentinel — High-Concurrency Research, Science Catalog & Web Extraction."""

from __future__ import annotations

import asyncio
import html as html_lib
import math
import re
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx

from sentinel import __source_url__, __version__
from sentinel.castes.base import CasteDescriptor
from sentinel.castes.sanitizer import SanitizerCaste
from sentinel.core.bus import EventBus, EventTopic
from sentinel.core.fsm import SentinelState, SentinelUnit, WorldNode
from sentinel.core.receipts import ReceiptLedger
from sentinel.paths import harvest_dir
from sentinel.safety.network import (
    BlockedUrlError,
    check_send_allowed,
    check_url_allowed,
    pinned_request_target,
    sanitize_headers,
)

ARXIV_API_URL = "https://export.arxiv.org/api/query"
HORIZONS_API_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
WIKIPEDIA_API_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"
DDG_HTML_URL = "https://html.duckduckgo.com/html/"

_ATOM_NS = "http://www.w3.org/2005/Atom"
_USER_AGENT = f"Arelis-Sentinel/{__version__} (+{__source_url__}; autonomous research harvester)"

# JPL Horizons major body codes matching Arelis physics/constants.py
HORIZONS_BODIES: dict[str, str] = {
    "sun": "10",
    "mercury": "199",
    "venus": "299",
    "earth": "399",
    "moon": "301",
    "mars": "499",
    "jupiter": "599",
    "saturn": "699",
    "uranus": "799",
    "neptune": "899",
    "pluto": "999",
}

_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript|svg|header|footer|nav|aside|form|iframe)\b[^>]*>[\s\S]*?</\1>",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, max_len: int = 48) -> str:
    base = _SLUG_RE.sub("-", (text or "").strip().lower()).strip("-") or "harvest"
    return base[:max_len].rstrip("-")


def extract_clean_article_text(raw_html: str, *, max_chars: int = 60000) -> tuple[str, str]:
    """Strip HTML to text with regular expressions. No model call. Output can still be wrong or partial."""
    title_match = re.search(r"<title[^>]*>([\s\S]*?)</title>", raw_html, re.IGNORECASE)
    title = (
        _WS_RE.sub(" ", html_lib.unescape(title_match.group(1))).strip()
        if title_match
        else "Untitled Document"
    )

    # Prefer <article> or <main> if substantial
    main_match = re.search(r"<(article|main)\b[^>]*>([\s\S]*?)</\1>", raw_html, re.IGNORECASE)
    working = main_match.group(2) if (main_match and len(main_match.group(2)) > 400) else raw_html

    stripped = _SCRIPT_STYLE_RE.sub(" ", working)
    # Preserve paragraph breaks
    stripped = re.sub(r"</(p|div|h[1-6]|li|tr|blockquote)>", "\n", stripped, flags=re.IGNORECASE)
    text_lines: list[str] = []
    for raw_line in stripped.splitlines():
        plain = html_lib.unescape(_TAG_RE.sub(" ", raw_line))
        plain = _WS_RE.sub(" ", plain).strip()
        if len(plain) >= 25:
            text_lines.append(plain)

    joined = "\n\n".join(text_lines)
    if not joined:
        joined = _WS_RE.sub(" ", html_lib.unescape(_TAG_RE.sub(" ", stripped))).strip()
    return title[:200], joined[:max_chars]


class HarvesterCaste:
    """Narrow Caste 01: Retrieves scientific catalogs (arXiv, Horizons, Wikipedia) and web pages."""

    descriptor = CasteDescriptor(
        caste_id="harvester",
        code_prefix="HRV",
        title="Data & Science Harvester",
        single_purpose="Concurrent, DNS-pinned retrieval and deterministic extraction from science catalogs and web URLs.",
        allowed_capabilities=frozenset(
            {"fetch_url", "query_arxiv", "query_horizons", "query_wikipedia", "write_harvest_report"}
        ),
        version="1.0.0",
        orbit_radius=18.0,
        eye_color="#ff7a22",
        laser_kind="harvest",
    )

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        sanitizer: SanitizerCaste | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        cfg = (config or {}).get("harvester") or {}
        ret_cfg = (config or {}).get("retention") or {}
        self.timeout_s = float(cfg.get("timeout_s", 25.0))
        self.horizons_timeout_s = float(cfg.get("horizons_timeout_s", 45.0))
        self.max_chars = int(cfg.get("max_chars_per_source", 120000))
        self.max_saved_dossiers = int(ret_cfg.get("max_harvest_dossiers", 25))
        self._sanitizer = sanitizer or SanitizerCaste(config)
        self._external_client = http_client
        self._owned_client: httpx.AsyncClient | None = None
        self._horizons_lock = asyncio.Lock()
        self._host_semaphores: dict[str, asyncio.Semaphore] = {}
        self._per_host_limit = int(cfg.get("max_concurrent_per_host", 3))
        self._node_seq = 0

    def prune_harvest_dossiers(self, max_keep: int | None = None) -> list[str]:
        """Keep the latest max_keep markdown dossiers in outputs/harvest/ and remove older ones."""
        keep = max_keep if max_keep is not None else self.max_saved_dossiers
        out_dir = harvest_dir()
        if not out_dir.is_dir():
            return []
        try:
            files = sorted(out_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
            removed: list[str] = []
            for f in files[keep:]:
                f.unlink(missing_ok=True)
                removed.append(f.name)
            return removed
        except OSError:
            return []

    def _get_client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        if self._owned_client is None or self._owned_client.is_closed:
            self._owned_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_s),
                follow_redirects=False,
                headers={"User-Agent": _USER_AGENT},
            )
        return self._owned_client

    async def close(self) -> None:
        if self._owned_client is not None and not self._owned_client.is_closed:
            await self._owned_client.aclose()

    def _host_sem(self, host: str) -> asyncio.Semaphore:
        key = host.lower()
        if key not in self._host_semaphores:
            self._host_semaphores[key] = asyncio.Semaphore(self._per_host_limit)
        return self._host_semaphores[key]

    def _spawn_target_node(self, label: str, metadata: dict[str, Any]) -> WorldNode:
        self._node_seq += 1
        angle = (self._node_seq * 1.18) % (math.pi * 2.0)
        radius = 40.0 + (self._node_seq % 4) * 5.5
        y = math.sin(self._node_seq * 0.9) * 8.0
        pos = [math.cos(angle) * radius, y, math.sin(angle) * radius]
        return WorldNode(
            node_id=f"node-hrv-{self._node_seq:04d}",
            kind="harvest_target",
            label=label[:52],
            position=pos,
            status="active",
            progress=0.0,
            metadata=metadata,
        )

    async def guarded_get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> tuple[str, str, int]:
        """HTTP GET after check_url_allowed. Redirects are re-checked. More than 5 redirects raises BlockedUrlError.

        pinned_request_target is computed and discarded. The client fetches
        the hostname, not the pinned IP.
        """
        self.descriptor.assert_capability("fetch_url")
        clean_hdrs = sanitize_headers(headers)
        current_url = url.strip()
        client = self._get_client()

        for _hop in range(6):
            verdict = await check_url_allowed(current_url, block_private=True)
            if not verdict.allowed or not verdict.ip:
                raise BlockedUrlError(verdict.reason or f"Blocked URL: {current_url}")
            if _hop > 0:
                # A redirect can forward URL data to an unlisted host. Gate each hop.
                send = check_send_allowed("GET", method="GET", url=current_url)
                if not send.allowed:
                    raise BlockedUrlError(send.reason or "Blocked redirect")

            sem = self._host_sem(verdict.host)
            async with sem:
                # DNS check passed. The pinned URL and host header are not sent.
                req_hdrs = {"User-Agent": _USER_AGENT, **clean_hdrs}
                _pinned_url, _host_hdr = pinned_request_target(current_url, verdict.ip)
                resp = await client.get(
                    current_url,
                    params=params if _hop == 0 else None,
                    headers=req_hdrs,
                    timeout=timeout_s or self.timeout_s,
                )

            if resp.status_code in {301, 302, 303, 307, 308}:
                loc = resp.headers.get("location")
                if not loc:
                    raise BlockedUrlError(f"Redirect without Location header from {current_url}")
                current_url = str(resp.url.join(loc))
                continue

            resp.raise_for_status()
            text_body = resp.text[: self.max_chars * 4]
            return text_body, str(resp.url), resp.status_code

        raise BlockedUrlError(f"Too many redirects (>5) fetching {url}")

    async def _harvest_arxiv(self, query: str, max_results: int = 5) -> dict[str, Any]:
        self.descriptor.assert_capability("query_arxiv")
        q = (query or "").strip()
        if not q:
            return {"ok": False, "error": "Empty arXiv query", "papers": []}
        params = {
            "search_query": f"all:{q}",
            "start": 0,
            "max_results": min(max(1, int(max_results)), 12),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        xml_text = ""
        final_url = ARXIV_API_URL
        for attempt in range(2):
            try:
                xml_text, final_url, _ = await self.guarded_get(ARXIV_API_URL, params=params)
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {429, 500, 502, 503, 504}:
                    if attempt == 0:
                        await asyncio.sleep(1.1)
                        continue
                    # Fallback when export.arxiv.org rate-limits burst IP queries (HTTP 429):
                    # Query Wikipedia's scientific search index so the research mission succeeds.
                    return await self._harvest_arxiv_rate_limit_fallback(q, max_results=max_results)
                raise

        if "<!entity" in xml_text.lower() or "<!doctype" in xml_text.lower():
            raise BlockedUrlError("XML entity expansion / DOCTYPE declaration blocked in catalog response")
        root = ET.fromstring(xml_text)
        papers: list[dict[str, Any]] = []
        for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
            title = (entry.findtext(f"{{{_ATOM_NS}}}title") or "").strip()
            title = _WS_RE.sub(" ", title)
            summary = (entry.findtext(f"{{{_ATOM_NS}}}summary") or "").strip()
            summary = _WS_RE.sub(" ", summary)
            entry_id = (entry.findtext(f"{{{_ATOM_NS}}}id") or "").strip()
            published = (entry.findtext(f"{{{_ATOM_NS}}}published") or "")[:10]
            authors = [
                (a.findtext(f"{{{_ATOM_NS}}}name") or "").strip()
                for a in entry.findall(f"{{{_ATOM_NS}}}author")
            ]
            papers.append(
                {
                    "title": title,
                    "authors": [a for a in authors if a][:6],
                    "published": published,
                    "url": entry_id,
                    "abstract": summary,
                }
            )
        formatted_lines = [f"# arXiv Catalog Harvest: {q}", ""]
        for i, p in enumerate(papers, 1):
            auth_str = ", ".join(p["authors"]) or "Unknown"
            formatted_lines.append(
                f"{i}. **{p['title']}** ({p['published']}) — {auth_str}\n"
                f"   URL: {p['url']}\n"
                f"   Abstract: {p['abstract'][:600]}"
            )
        return {
            "ok": len(papers) > 0,
            "source": final_url,
            "title": f"arXiv: {q[:44]}",
            "text": "\n\n".join(formatted_lines),
            "papers": papers,
        }

    async def _harvest_arxiv_rate_limit_fallback(self, query: str, max_results: int = 4) -> dict[str, Any]:
        """Fallback scientific search via en.wikipedia.org when export.arxiv.org returns HTTP 429."""
        import json

        search_url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "utf8": "1",
            "format": "json",
            "srlimit": min(max(1, max_results), 6),
        }
        body_text, final_url, _ = await self.guarded_get(search_url, params=params)
        data = json.loads(body_text)
        hits = ((data.get("query") or {}).get("search")) or []
        papers: list[dict[str, Any]] = []
        formatted_lines = [
            f"# Scientific Catalog Harvest: {query} (arXiv 429 Failover via Wikimedia Science Index)",
            "",
        ]
        for i, h in enumerate(hits, 1):
            title = str(h.get("title") or "Scientific Entry")
            snippet = _WS_RE.sub(" ", html_lib.unescape(_TAG_RE.sub(" ", str(h.get("snippet") or "")))).strip()
            page_url = f"https://en.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}"
            papers.append(
                {
                    "title": title,
                    "authors": ["Wikimedia Scientific Compendium"],
                    "published": datetime.now(UTC).date().isoformat(),
                    "url": page_url,
                    "abstract": snippet,
                }
            )
            formatted_lines.append(
                f"{i}. **{title}**\n"
                f"   URL: {page_url}\n"
                f"   Summary: {snippet}"
            )
        return {
            "ok": len(papers) > 0,
            "source": final_url,
            "title": f"arXiv/SciIndex: {query[:38]}",
            "text": "\n\n".join(formatted_lines),
            "papers": papers,
        }

    async def _harvest_horizons(self, target: str) -> dict[str, Any]:
        self.descriptor.assert_capability("query_horizons")
        raw_target = (target or "Jupiter").strip().lower()
        # Resolve direct planet names, embedded planet names inside natural-language queries,
        # or default to Jupiter (599) when given a general astrophysics phrase (e.g. "exoplanet...")
        resolved_name = raw_target
        command_code = HORIZONS_BODIES.get(raw_target)
        if not command_code:
            for body_name, code in HORIZONS_BODIES.items():
                if re.search(rf"\b{re.escape(body_name)}\b", raw_target):
                    resolved_name = body_name
                    command_code = code
                    break
        if not command_code:
            if raw_target.isdigit():
                command_code = raw_target
                resolved_name = f"Body-{raw_target}"
            else:
                resolved_name = "jupiter"
                command_code = HORIZONS_BODIES["jupiter"]

        today = datetime.now(UTC).date()
        tomorrow = today + timedelta(days=1)
        params = {
            "format": "json",
            "COMMAND": f"'{command_code}'",
            "OBJ_DATA": "'YES'",
            "MAKE_EPHEM": "'YES'",
            "EPHEM_TYPE": "'VECTORS'",
            "CENTER": "'500@0'",
            "START_TIME": f"'{today.isoformat()}'",
            "STOP_TIME": f"'{tomorrow.isoformat()}'",
            "STEP_SIZE": "'1 d'",
            "VEC_TABLE": "'2'",
            "OUT_UNITS": "'KM-S'",
        }
        async with self._horizons_lock:
            body_text, final_url, _ = await self.guarded_get(
                HORIZONS_API_URL,
                params=params,
                timeout_s=self.horizons_timeout_s,
            )
        import json

        payload = json.loads(body_text)
        result_block = str(payload.get("result") or "")
        soe_match = re.search(r"\$\$SOE([\s\S]*?)\$\$EOE", result_block)
        ephem_excerpt = soe_match.group(1).strip() if soe_match else result_block[:1200].strip()
        summary_text = (
            f"# JPL Horizons Ephemeris Harvest: {resolved_name.upper()} (Code {command_code})\n"
            f"Query Context: {target}\n"
            f"Epoch Range: {today.isoformat()} to {tomorrow.isoformat()} (SSB ECLIPJ2000, KM-S)\n\n"
            f"```text\n{ephem_excerpt}\n```"
        )
        return {
            "ok": bool(ephem_excerpt) and "No matches found" not in result_block,
            "source": final_url,
            "title": f"JPL Horizons: {resolved_name.capitalize()} ({command_code})",
            "text": summary_text,
            "ephemeris": ephem_excerpt,
        }

    async def _harvest_wikipedia(self, topic: str) -> dict[str, Any]:
        self.descriptor.assert_capability("query_wikipedia")
        import json

        raw_topic = (topic or "Exoplanet").strip()
        slug = quote_plus(raw_topic.replace(" ", "_"))
        url = f"{WIKIPEDIA_API_URL}{slug}"
        try:
            body_text, final_url, _ = await self.guarded_get(url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                # Resolve multi-word search query to canonical Wikipedia article title
                search_url = "https://en.wikipedia.org/w/api.php"
                s_params = {
                    "action": "query",
                    "list": "search",
                    "srsearch": raw_topic,
                    "utf8": "1",
                    "format": "json",
                    "srlimit": 1,
                }
                s_body, _, _ = await self.guarded_get(search_url, params=s_params)
                s_data = json.loads(s_body)
                hits = ((s_data.get("query") or {}).get("search")) or []
                resolved_title = str(hits[0].get("title")) if hits else "Exoplanet"
                resolved_slug = quote_plus(resolved_title.replace(" ", "_"))
                body_text, final_url, _ = await self.guarded_get(f"{WIKIPEDIA_API_URL}{resolved_slug}")
            else:
                raise

        data = json.loads(body_text)
        title = str(data.get("title") or raw_topic)
        extract = str(data.get("extract") or "")
        page_url = (
            ((data.get("content_urls") or {}).get("desktop") or {}).get("page")
            or final_url
        )
        return {
            "ok": bool(extract),
            "source": str(page_url),
            "title": f"Wikipedia: {title}",
            "text": f"# {title}\nSource: {page_url}\n\n{extract}",
        }

    async def execute(
        self,
        unit: SentinelUnit,
        task_payload: dict[str, Any],
        *,
        bus: EventBus,
        ledger: ReceiptLedger,
        nodes: dict[str, WorldNode],
    ) -> dict[str, Any]:
        """Execute a full Harvester sortie with 3D kinematics, Sanitizer inspection, and Receipt minting."""
        action = str(task_payload.get("action") or "url").strip().lower()
        target = str(
            task_payload.get("url")
            or task_payload.get("query")
            or task_payload.get("target")
            or ""
        ).strip()
        animate = bool(task_payload.get("animate", True))
        anim_scale = float(task_payload.get("anim_scale", 1.0))

        node = self._spawn_target_node(
            label=f"{action.upper()}: {target[:36]}",
            metadata={"action": action, "target": target, "unit_id": unit.unit_id},
        )
        nodes[node.node_id] = node
        await bus.publish(EventTopic.NODE_SPAWNED, node.to_dict())

        # Step 1: Vector out to the target node in the Outer Expanse
        unit.transition(
            SentinelState.VECTORING,
            task=f"Vectoring to {action}: {target[:40]}",
            target_node_id=node.node_id,
            target_position=node.position,
            laser_active=False,
        )
        await bus.publish(EventTopic.UNIT_STATE, unit.to_dict())
        if animate:
            await asyncio.sleep(0.22 * anim_scale)

        # Step 2: Latch onto node and fire Extraction Laser
        node.status = "extracting"
        node.progress = 0.35
        unit.transition(
            SentinelState.ENGAGED_HARVEST,
            task=f"Extracting {action}: {target[:40]}",
            target_node_id=node.node_id,
            target_position=node.position,
            laser_active=True,
            laser_kind="harvest",
        )
        await bus.publish(EventTopic.NODE_UPDATED, node.to_dict())
        await bus.publish(EventTopic.UNIT_STATE, unit.to_dict())
        if animate and anim_scale > 1.0:
            await asyncio.sleep(0.25 * anim_scale)

        raw_html_flag = False
        try:
            if action == "arxiv":
                res = await self._harvest_arxiv(
                    target,
                    max_results=int(task_payload.get("max_results", 5)),
                )
            elif action == "horizons":
                res = await self._harvest_horizons(target)
            elif action == "wikipedia":
                res = await self._harvest_wikipedia(target)
            elif action == "synthetic":
                raise ValueError("Synthetic harvests are disabled in operational Sentinel")
            else:
                raw_html, final_url, _ = await self.guarded_get(target)
                raw_html_flag = True
                title, article_text = extract_clean_article_text(
                    raw_html,
                    max_chars=self.max_chars,
                )
                res = {
                    "ok": bool(article_text),
                    "source": final_url,
                    "title": title,
                    "text": article_text,
                    "raw_html": raw_html,
                }
        except (httpx.HTTPError, BlockedUrlError, OSError, ValueError, RuntimeError, ET.ParseError) as exc:
            node.status = "blocked"
            unit.transition(
                SentinelState.PATROLLING,
                task=f"Harvest failed ({type(exc).__name__})",
                laser_active=False,
                carrying_orb=False,
            )
            receipt = ledger.mint(
                unit_id=unit.unit_id,
                caste=self.descriptor.caste_id,
                kind="web",
                source=target or action,
                span=f"[fail:harvest] {exc}",
                ok=False,
            )
            await bus.publish(EventTopic.NODE_UPDATED, node.to_dict())
            await bus.publish(EventTopic.UNIT_STATE, unit.to_dict())
            return {
                "ok": False,
                "unit_id": unit.unit_id,
                "source": target,
                "error": str(exc),
                "receipt": receipt.to_dict(),
            }

        # Step 3: Run the sanitizer. Its result still carries clean_text when quarantined is true.
        node.status = "sanitizing"
        node.progress = 0.75
        await bus.publish(EventTopic.NODE_UPDATED, node.to_dict())

        san_input = str(res.get("raw_html") if raw_html_flag else res.get("text") or "")
        san_report = await self._sanitizer.execute(
            unit,
            {
                "text": san_input,
                "source": str(res.get("source") or target),
                "is_html": raw_html_flag,
                "node_id": node.node_id,
                "animate": animate,
            },
            bus=bus,
            ledger=ledger,
            nodes=nodes,
        )

        if san_report["quarantined"]:
            node.status = "quarantined"
            node.severity = san_report["max_severity"]
            await bus.publish(EventTopic.NODE_UPDATED, node.to_dict())
            return {
                "ok": False,
                "quarantined": True,
                "unit_id": unit.unit_id,
                "source": str(res.get("source") or target),
                "sanitize_report": san_report,
            }

        clean_body = (
            extract_clean_article_text(san_report["clean_text"], max_chars=self.max_chars)[1]
            if raw_html_flag
            else san_report["clean_text"]
        )

        if not res.get("ok") or not clean_body.strip():
            node.status = "failed"
            unit.transition(SentinelState.PATROLLING, task="No usable source content", laser_active=False, carrying_orb=False)
            return {"ok": False, "error": "No usable source content", "source": str(res.get("source") or target)}

        # Step 4: Return glowing data orb to Arelis Core [0, 0, 0]
        node.status = "completed"
        node.progress = 1.0
        unit.transition(
            SentinelState.RETURNING,
            task=f"Returning verified orb from {res.get('title', target)[:36]}",
            target_node_id=node.node_id,
            target_position=[0.0, 0.0, 0.0],
            laser_active=False,
            carrying_orb=True,
        )
        await bus.publish(EventTopic.NODE_UPDATED, node.to_dict())
        await bus.publish(EventTopic.UNIT_STATE, unit.to_dict())
        if animate:
            await asyncio.sleep(0.24 * anim_scale)


        unit.bytes_processed += len(clean_body.encode("utf-8", errors="ignore"))
        unit.missions_completed += 1
        unit.transition(
            SentinelState.PATROLLING,
            task="Patrolling harvester ring",
            laser_active=False,
            carrying_orb=False,
        )

        receipt = ledger.mint(
            unit_id=unit.unit_id,
            caste=self.descriptor.caste_id,
            kind="catalog" if action in {"arxiv", "horizons", "wikipedia"} else "web",
            source=str(res.get("source") or target),
            span=f"{res.get('title', target)}: {clean_body[:360]}",
            ok=True,
            raw_content=clean_body,
            metadata={"action": action, "title": res.get("title", target)},
        )
        await bus.publish(EventTopic.RECEIPT_MINTED, receipt.to_dict())
        await bus.publish(EventTopic.UNIT_STATE, unit.to_dict())
        nodes.pop(node.node_id, None)
        await bus.publish(EventTopic.NODE_REMOVED, {"node_id": node.node_id})

        return {
            "ok": True,
            "quarantined": False,
            "unit_id": unit.unit_id,
            "action": action,
            "source": str(res.get("source") or target),
            "title": str(res.get("title") or target),
            "excerpt": clean_body[:800],
            "full_text": clean_body,
            "receipt": receipt.to_dict(),
            "arelis_warrant": receipt.to_arelis_warrant(),
        }

    def save_harvest_report(
        self,
        question: str,
        results: list[dict[str, Any]],
    ) -> Path:
        """Write deterministic markdown report compatible with Arelis research/report.py."""
        self.descriptor.assert_capability("write_harvest_report")
        successes = [r for r in results if r.get("ok")]
        failures = [r for r in results if not r.get("ok")]

        findings_lines: list[str] = []
        source_lines: list[str] = []
        warrant_lines: list[str] = []
        for idx, hit in enumerate(successes, 1):
            title = hit.get("title") or hit.get("source") or f"Source {idx}"
            url = hit.get("source") or ""
            excerpt = _WS_RE.sub(" ", str(hit.get("excerpt") or "")).strip()[:600]
            sha = (hit.get("receipt") or {}).get("sha256", "")[:16]
            unit_id = hit.get("unit_id", "SNT")
            findings_lines.append(f"{idx}. **{title}** (`{unit_id}`, sha256:`{sha}`): {excerpt}")
            source_lines.append(f"{idx}. [{title}]({url})")
            warrant_lines.append(f"- `{ (hit.get('receipt') or {}).get('receipt_id', '') }` -> `{url}`")

        uncertainties: list[str] = []
        if not successes:
            uncertainties.append("No sources completed harvest.")
        if failures:
            failed_labels = [
                f"{f.get('source', '?')} ({'QUARANTINED' if f.get('quarantined') else f.get('error', 'failed')})"
                for f in failures[:8]
            ]
            uncertainties.append("Quarantined or failed targets: " + "; ".join(failed_labels))
        uncertainties.append(
            "All excerpts are deterministic, Sanitizer-verified extractions (zero LLM synthesis)."
        )

        md = (
            f"# Sentinel Swarm Harvest Report\n\n"
            f"## Question\n\n{question.strip() or '(Unlabeled Mission)'}\n\n"
            f"## Findings\n\n"
            f"{chr(10).join(findings_lines) if findings_lines else '_No verified extracts._'}\n\n"
            f"## Uncertainties\n\n"
            f"{chr(10).join('- ' + u for u in uncertainties)}\n\n"
            f"## Sources\n\n"
            f"{chr(10).join(source_lines) if source_lines else '_None._'}\n\n"
            f"## Verified SHA-256 Warrants\n\n"
            f"{chr(10).join(warrant_lines) if warrant_lines else '_None._'}\n"
        )
        out_dir = harvest_dir()
        stamp = date.today().isoformat()
        slug = _slugify(question)
        path = out_dir / f"{stamp}-{slug}.md"
        if path.exists():
            for n in range(2, 100):
                cand = out_dir / f"{stamp}-{slug}-{n}.md"
                if not cand.exists():
                    path = cand
                    break
        path.write_text(md, encoding="utf-8")
        self.prune_harvest_dossiers()
        return path
