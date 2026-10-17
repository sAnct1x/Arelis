"""DNS-pinned SSRF guard, header sanitization, and pinned egress allowlist."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urlsplit, urlunsplit

# Pinned external hosts named in Sentinel's catalog & search harvesters.
# Any arbitrary user-requested research URL still passes through check_url_allowed()
# (which blocks all loopback, private, link-local, and metadata IPs).
ALLOWED_EGRESS_HOSTS: dict[str, str] = {
    "export.arxiv.org": "arXiv Atom API for scientific paper harvesting",
    "arxiv.org": "arXiv abstract and PDF retrieval",
    "doi.org": "DOI metadata resolution for scientific citations",
    "api.crossref.org": "Crossref bibliographic metadata lookup",
    "ssd.jpl.nasa.gov": "JPL Horizons solar-system ephemeris and state vectors",
    "api.nasa.gov": "NASA APOD and planetary science catalog",
    "api.adsabs.harvard.edu": "NASA Astrophysics Data System (ADS) paper search",
    "html.duckduckgo.com": "DuckDuckGo HTML search discovery for Harvester scouts",
    "lite.duckduckgo.com": "DuckDuckGo Lite fallback search discovery",
    "en.wikipedia.org": "Wikipedia REST/MediaWiki reference extraction",
}

_LOOPBACK_NAMES = frozenset({"localhost", "0.0.0.0", "::", "::1", "[::1]"})

_FORBIDDEN_HEADERS = frozenset(
    {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "keep-alive",
        "upgrade",
        "te",
        "trailer",
        "expect",
        "proxy-authorization",
        "proxy-connection",
    }
)


class BlockedUrlError(RuntimeError):
    """Raised when a URL or redirect hop violates Sentinel network policy."""


class HeaderError(ValueError):
    """Raised when a caller supplies a forbidden or malformed HTTP header."""


@dataclass(frozen=True)
class UrlVerdict:
    reason: str | None = None
    ip: str | None = None
    host: str = ""

    @property
    def allowed(self) -> bool:
        return self.reason is None


def _ip_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, host: str) -> str | None:
    if ip.is_loopback:
        return f"Blocked loopback address: {host} -> {ip}"
    if ip.is_link_local:
        return f"Blocked link-local/metadata address: {host} -> {ip}"
    if ip.is_private or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        return f"Blocked private/reserved address: {host} -> {ip}"
    return None


def is_blocked_url(url: str, *, block_private: bool = True) -> str | None:
    """Fast synchronous textual check before DNS resolution."""
    raw = (url or "").strip()
    if not raw:
        return "Missing URL"
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme in {"file", "ftp", "data", "javascript", "vbscript", "ws", "wss"}:
        return f"Blocked URL scheme: {scheme or '(none)'}"
    if scheme not in {"http", "https"}:
        return f"Unsupported URL scheme: {scheme or '(none)'}"
    host = (parsed.hostname or "").lower().strip("[]")
    if not host:
        return "URL missing host"
    if host in _LOOPBACK_NAMES or host.endswith(".localhost"):
        return f"Blocked local/loopback host: {host}"
    if host == "metadata.google.internal" or host.endswith((".internal", ".local")):
        return f"Blocked internal/metadata host: {host}"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if ip.is_loopback:
            return f"Blocked loopback IP: {host}"
        if block_private:
            return _ip_reason(ip, host)
    return None


def _resolve_all_ips(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    seen: list[str] = []
    for info in infos:
        addr = str(info[4][0])
        if addr not in seen:
            seen.append(addr)
    return seen


async def check_url_allowed(url: str, *, block_private: bool = True) -> UrlVerdict:
    """Full asynchronous URL policy check with DNS resolution and anti-rebinding IP pin."""
    textual = is_blocked_url(url, block_private=block_private)
    if textual is not None:
        return UrlVerdict(reason=textual, ip=None)

    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().strip("[]")
    port = parsed.port or (443 if (parsed.scheme or "").lower() == "https" else 80)

    try:
        ips = await asyncio.to_thread(_resolve_all_ips, host, port)
    except OSError as exc:
        return UrlVerdict(reason=f"DNS resolution failed for {host}: {exc}", ip=None, host=host)

    if not ips:
        return UrlVerdict(reason=f"DNS returned no records for {host}", ip=None, host=host)

    for raw_ip in ips:
        try:
            ip_obj = ipaddress.ip_address(raw_ip)
        except ValueError:
            return UrlVerdict(reason=f"Invalid resolved IP for {host}: {raw_ip}", ip=None, host=host)
        if ip_obj.is_loopback:
            return UrlVerdict(
                reason=f"Blocked loopback DNS resolution: {host} -> {raw_ip}",
                ip=None,
                host=host,
            )
        if block_private:
            reason = _ip_reason(ip_obj, host)
            if reason is not None:
                return UrlVerdict(reason=reason, ip=None, host=host)

    return UrlVerdict(reason=None, ip=ips[0], host=host)


def pinned_request_target(url: str, ip: str) -> tuple[str, str]:
    """Rewrite URL netloc to the verified public IP and return (pinned_url, host_header)."""
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    default_port = 443 if (parsed.scheme or "").lower() == "https" else 80
    literal = f"[{ip}]" if ":" in ip else ip
    netloc = f"{literal}:{parsed.port}" if parsed.port else literal
    pinned = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    host_hdr = f"{host}:{parsed.port}" if (parsed.port and parsed.port != default_port) else host
    return pinned, host_hdr


def sanitize_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """Validate caller-supplied HTTP headers, rejecting forbidden framing/routing headers."""
    clean: dict[str, str] = {}
    for raw_name, raw_value in (headers or {}).items():
        name = str(raw_name).strip()
        value = str(raw_value)
        if not name:
            raise HeaderError("Empty HTTP header name")
        if any(ch in name or ch in value for ch in "\r\n\x00"):
            raise HeaderError(f"Illegal CR/LF/NUL characters in header {name!r}")
        if name.lower() in _FORBIDDEN_HEADERS:
            raise HeaderError(f"Forbidden header {name!r} cannot be overridden")
        clean[name] = value
    return clean
