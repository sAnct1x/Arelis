from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

# Redaction runs on every tool output before it reaches the model, the UI, or a
# confirm card. Patterns are deliberately broad: a false positive costs one
# unreadable line, a false negative leaks a live credential into model context.
_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|password|token|access[_-]?key)\s*[=:]\s*\S+"),
    re.compile(r"(?i)(sk|pk|ghp|gho|xox[baprs])-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"),
]

_LOOPBACK_NAMES = {"localhost", "0.0.0.0", "::1", "[::1]"}


def _ip_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, host: str) -> str | None:
    """Classify a resolved address against the local-first network policy."""
    if ip.is_loopback:
        return f"Blocked loopback address: {host} -> {ip}"
    if ip.is_link_local:
        # Covers 169.254.0.0/16, which includes the cloud metadata endpoints.
        return f"Blocked link-local address: {host} -> {ip}"
    if ip.is_private or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        return f"Blocked private/reserved address: {host} -> {ip}"
    return None


def is_blocked_url(url: str, *, block_private: bool = True) -> str | None:
    """Cheap textual URL policy check. Return a reason to block, or None to allow.

    This inspects only what is written in the URL. It cannot see where a
    hostname actually points, so it is necessary but not sufficient: callers
    that perform real network I/O must use check_url_allowed instead, which
    also resolves DNS. Kept separate because it is synchronous and is what the
    unit tests and argument previews use.
    """
    raw = (url or "").strip()
    if not raw:
        return "Missing url"
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme in {"file", "ftp", "data", "javascript"}:
        return f"Blocked URL scheme: {scheme or '(none)'}"
    if scheme not in {"http", "https"}:
        return f"Unsupported URL scheme: {scheme or '(none)'}"
    host = (parsed.hostname or "").lower()
    if not host:
        return "URL missing host"
    # Loopback names are refused even when block_private is off, because the
    # only thing reachable there is Arelis' own Ollama and ComfyUI ports.
    if host in _LOOPBACK_NAMES or host.endswith(".localhost"):
        return "Blocked local/loopback URL"
    if not block_private:
        return None
    try:
        return _ip_reason(ipaddress.ip_address(host), host)
    except ValueError:
        # Not a literal IP. Catch the well-known metadata name here; anything
        # else needs DNS, which happens in check_url_allowed.
        if host == "metadata.google.internal" or host.endswith(".internal"):
            return f"Blocked metadata host: {host}"
    return None


def _resolved_ips(host: str, port: int) -> list[str]:
    """Every address the OS would connect to for this host, v4 and v6."""
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos]


async def check_url_allowed(url: str, *, block_private: bool = True) -> str | None:
    """Full URL policy check including DNS. Return a reason to block, or None.

    The textual check alone is bypassable three ways: a hostname whose DNS
    record points at 127.0.0.1 or 192.168.x.x, a non-dotted literal such as
    http://2130706433/ or http://127.1/ that ipaddress rejects but the resolver
    accepts, and any host that resolves to a mix of public and private records.
    Resolving first and rejecting if *any* answer is private closes all three.

    Resolution runs in a worker thread: getaddrinfo blocks, and the agent loop,
    event delivery, and the confirm gate all share this event loop.
    """
    textual = is_blocked_url(url, block_private=block_private)
    if textual is not None:
        return textual
    if not block_private:
        return None

    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        # Literal IP already validated by the textual pass.
        return None

    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        addresses = await asyncio.to_thread(_resolved_ips, host, port)
    except OSError as exc:
        return f"Could not resolve host {host}: {exc}"
    for address in addresses:
        # getaddrinfo can return a scoped v6 literal such as fe80::1%eth0.
        try:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError:
            continue
        reason = _ip_reason(ip, host)
        if reason is not None:
            return reason
    return None


def redact_secrets(text: str) -> str:
    if not text:
        return text
    out = text
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("[redacted]", out)
    return out


@dataclass(frozen=True)
class TruncationInfo:
    """Whether a tool body was clipped before the model saw it."""

    truncated: bool
    original_chars: int
    kept_chars: int


def truncate_tool_output(
    text: str, max_chars: int
) -> tuple[str, TruncationInfo]:
    """Cap a single tool result. The marker matters: without it the model
    cannot tell a short file from a clipped one and will summarize confidently
    over missing content.

    Returns ``(text_for_model, TruncationInfo)`` so the agent loop can log
    truncation loudly (THINKING + turns.log) instead of only burying a marker.
    """
    raw = text or ""
    original = len(raw)
    if max_chars <= 0 or original <= max_chars:
        return raw, TruncationInfo(
            truncated=False, original_chars=original, kept_chars=original
        )
    clipped = raw[:max_chars] + f"\n\n[truncated to {max_chars} chars]"
    return clipped, TruncationInfo(
        truncated=True, original_chars=original, kept_chars=max_chars
    )
