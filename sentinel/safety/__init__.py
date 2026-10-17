"""Network SSRF guards, pinned egress policy, secret redaction, and injection detection."""

from __future__ import annotations

from sentinel.safety.network import (
    ALLOWED_EGRESS_HOSTS,
    BlockedUrlError,
    HeaderError,
    UrlVerdict,
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
    "BlockedUrlError",
    "HeaderError",
    "InjectionFinding",
    "SanitizeReport",
    "UrlVerdict",
    "check_url_allowed",
    "inspect_and_sanitize_text",
    "is_blocked_url",
    "pinned_request_target",
    "redact_secrets",
    "sanitize_headers",
    "strip_hidden_html_traps",
]
