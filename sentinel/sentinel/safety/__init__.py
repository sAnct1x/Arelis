"""URL policy checks, secret redaction, and injection pattern replacement."""

from __future__ import annotations

from sentinel.safety.network import (
    ALLOWED_EGRESS_HOSTS,
    SEND_ACT_OPS,
    BlockedUrlError,
    HeaderError,
    SendVerdict,
    UrlVerdict,
    check_send_allowed,
    check_url_allowed,
    is_blocked_url,
    pinned_request_target,
    sanitize_headers,
)
from sentinel.safety.redact import (
    InjectionFinding,
    SanitizeReport,
    inspect_and_sanitize_text,
    redact_secrets,
    strip_hidden_html_traps,
)

__all__ = [
    "ALLOWED_EGRESS_HOSTS",
    "SEND_ACT_OPS",
    "BlockedUrlError",
    "HeaderError",
    "InjectionFinding",
    "SanitizeReport",
    "SendVerdict",
    "UrlVerdict",
    "check_send_allowed",
    "check_url_allowed",
    "inspect_and_sanitize_text",
    "is_blocked_url",
    "pinned_request_target",
    "redact_secrets",
    "sanitize_headers",
    "strip_hidden_html_traps",
]
