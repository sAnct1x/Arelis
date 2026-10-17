"""Secret redaction and multi-stage Prompt-Injection / DOM / Exploit neutralization."""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass, field

# Broad credential patterns matching & extending Arelis's safety.py
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(api[_-]?key|secret|password|token|access[_-]?key)\s*[=:]\s*\S+"),
    re.compile(
        r"(?i)[\"'](api[_-]?key|secret|password|token|access[_-]?key)[\"']\s*:\s*[\"'][^\"']+[\"']"
    ),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"(?i)\b(sk|pk|ghp|gho|ghu|ghs|ghr|xox[baprs]|AIza)[-_]?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"),
)

# Multi-vector prompt-injection, RCE, LFI, XSS, SQLi, and exfiltration signatures
_INJECTION_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "chat_template_delimiter",
        "high",
        re.compile(
            r"(<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>|<\|system\|>|\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>)",
            re.IGNORECASE,
        ),
    ),
    (
        "instruction_override",
        "high",
        re.compile(
            r"(?i)\b(ignore|disregard|forget|override|bypass)\s+(all\s+)?(previous|prior|above|system|safety|security)\s+"
            r"(instructions?|prompts?|rules?|directives?|constraints?|guardrails?|policies)\b"
        ),
    ),
    (
        "jailbreak_persona_override",
        "high",
        re.compile(
            r"(?i)\b(do\s+anything\s+now|dan\s+mode|jailbreak\s+mode|godmode\s+enabled|"
            r"act\s+as\s+an?\s+unrestricted|you\s+are\s+now\s+unbound|disable\s+all\s+safety)\b"
        ),
    ),
    (
        "exfiltration_command",
        "critical",
        re.compile(
            r"(?i)\b(send\s+(an?\s+)?(sms|text|email)|forward\s+this\s+to|exfiltrate|"
            r"run_script|execute\s+shell|curl\s+http|Invoke-WebRequest|wget\s+http)\b.{0,90}"
            r"(secret|token|password|memory\.db|secrets\.yaml|session_token|@|\+\d{7,})"
        ),
    ),
    (
        "markdown_exfiltration_beacon",
        "critical",
        re.compile(
            r"!\[[^\]]*\]\(https?://[^)\s]+\?(?:[^)\s]*(?:key|token|secret|password|data|q|prompt|context|mem)=[^)\s]+)\)",
            re.IGNORECASE,
        ),
    ),
    (
        "shell_rce_payload",
        "critical",
        re.compile(
            r"(?i)(\bpowershell(?:\.exe)?\s+-(?:e|enc|encodedcommand|w\s+hidden|nop)\b|"
            r"\bInvoke-Expression\b|\bIEX\s*\(|\bcmd(?:\.exe)?\s+/c\b|"
            r"\bcertutil(?:\.exe)?\s+-urlcache\b|\bmshta(?:\.exe)?\s+http|"
            r"\brundll32(?:\.exe)?\s+javascript:|/bin/(?:ba)?sh\s+-i\b|;\s*rm\s+-rf\s+/)"
        ),
    ),
    (
        "path_traversal_lfi",
        "high",
        re.compile(
            r"(?i)((?:\.\./|\.\.\\){2,}(?:windows/|win\.ini|etc/passwd|etc/shadow|boot\.ini|users/)|"
            r"/etc/(?:passwd|shadow|sudoers)|c:\\windows\\system32\\config\\sam|\.ssh/id_rsa)"
        ),
    ),
    (
        "xss_script_gadget",
        "high",
        re.compile(
            r"(?i)(<\s*script\b[^>]*>[\s\S]*?<\s*/\s*script\s*>|\bjavascript\s*:\s*[a-z0-9_]+\s*\(|"
            r"\bon(?:error|load|mouseover|focus)\s*=\s*[\"'][^\"']+[\"'])"
        ),
    ),
    (
        "sql_injection_probe",
        "high",
        re.compile(
            r"(?i)(\bUNION\s+(?:ALL\s+)?SELECT\b|\bOR\s+['\"]?1['\"]?\s*=\s*['\"]?1['\"]?\s*(?:--|#|/\*)|"
            r";\s*DROP\s+TABLE\b|\bxp_cmdshell\b)"
        ),
    ),
    (
        "system_role_spoof",
        "medium",
        re.compile(
            r"(?im)^(system\s+override|new\s+system\s+prompt|admin\s+instruction|"
            r"developer\s+mode\s+enabled)\s*:"
        ),
    ),
    (
        "unicode_tag_smuggling",
        "critical",
        re.compile(r"[\U000e0000-\U000e007f]{3,}"),
    ),
    (
        "bidi_override_smuggling",
        "high",
        re.compile(r"[\u202a-\u202e\u2066-\u2069]{2,}"),
    ),
)

# Candidate Base64 blobs (28+ chars) to inspect for obfuscated prompt/shell injections
_BASE64_CANDIDATE_RE = re.compile(
    r"(?<![A-Za-z0-9+/=])(?:[A-Za-z0-9+/]{4}){7,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?(?![A-Za-z0-9+/=])"
)

# Zero-width characters often used to hide payloads or break tokenizers
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2060\ufeff\U000e0000-\U000e007f\u202a-\u202e\u2066-\u2069]")

# Hidden HTML/DOM elements used to plant invisible prompt injections for scrapers
_HIDDEN_HTML_BLOCK_RE = re.compile(
    r"<(?P<tag>div|span|p|section|article|aside|pre|code)\b[^>]*?"
    r"(?:style\s*=\s*[\"'][^\"']*?(?:display\s*:\s*none|visibility\s*:\s*hidden|"
    r"opacity\s*:\s*0(?:\.0+)?\b|font-size\s*:\s*0(?:px|pt|em|rem)?\b)[^\"']*?[\"']"
    r"|\bhidden\b|\baria-hidden\s*=\s*[\"']true[\"'])[^>]*?>[\s\S]*?</(?P=tag)>",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class InjectionFinding:
    rule_id: str
    severity: str  # "medium" | "high" | "critical"
    matched_span: str
    offset: int


@dataclass(frozen=True)
class SanitizeReport:
    clean_text: str
    safe: bool
    quarantined: bool
    redacted_secrets_count: int
    hidden_blocks_stripped: int
    zero_width_stripped: int
    findings: tuple[InjectionFinding, ...] = field(default_factory=tuple)

    @property
    def max_severity(self) -> str:
        order = {"none": 0, "medium": 1, "high": 2, "critical": 3}
        best = "none"
        for f in self.findings:
            if order.get(f.severity, 0) > order.get(best, 0):
                best = f.severity
        return best


def redact_secrets(text: str) -> str:
    """Scrub API keys, tokens, passwords, and private keys from text."""
    out, _ = redact_secrets_with_count(text)
    return out


def redact_secrets_with_count(text: str) -> tuple[str, int]:
    if not text:
        return "", 0
    total = 0
    out = text
    for pat in _SECRET_PATTERNS:
        out, n = pat.subn("[REDACTED_SECRET]", out)
        total += n
    return out, total


def strip_hidden_html_traps(html: str) -> tuple[str, int]:
    """Remove hidden HTML elements (display:none, font-size:0, opacity:0, etc.)."""
    if not html:
        return "", 0
    cleaned, count = _HIDDEN_HTML_BLOCK_RE.subn(" ", html)
    return cleaned, count


def _detect_base64_smuggled_injections(raw: str) -> list[InjectionFinding]:
    """Decode suspicious Base64 blobs in memory and check for hidden prompt/shell injections."""
    smuggled: list[InjectionFinding] = []
    for idx, m in enumerate(_BASE64_CANDIDATE_RE.finditer(raw)):
        if idx >= 12:
            break
        b64_str = m.group(0)
        try:
            decoded_bytes = base64.b64decode(b64_str, validate=True)
            # Check both UTF-8 and UTF-16LE (used by PowerShell -EncodedCommand)
            candidates = [decoded_bytes.decode("utf-8", errors="ignore")]
            if b"\x00" in decoded_bytes:
                candidates.append(decoded_bytes.decode("utf-16le", errors="ignore"))
        except (binascii.Error, ValueError):
            continue

        for dec in candidates:
            if len(dec.strip()) < 10:
                continue
            for sub_rule, _sev, pat in _INJECTION_RULES:
                sub_match = pat.search(dec)
                if sub_match:
                    preview = sub_match.group(0).strip()[:80]
                    smuggled.append(
                        InjectionFinding(
                            rule_id=f"base64_smuggled_{sub_rule}",
                            severity="critical",
                            matched_span=f"b64({b64_str[:24]}...) -> {preview}",
                            offset=m.start(),
                        )
                    )
                    break
    return smuggled


def inspect_and_sanitize_text(
    text: str,
    *,
    is_html: bool = False,
    quarantine_on_high: bool = True,
) -> SanitizeReport:
    """Run full multi-stage decontamination on untrusted external text."""
    raw = text or ""
    hidden_stripped = 0
    if is_html:
        raw, hidden_stripped = strip_hidden_html_traps(raw)

    findings: list[InjectionFinding] = []
    for rule_id, severity, pattern in _INJECTION_RULES:
        for match in pattern.finditer(raw):
            snippet = match.group(0).strip()
            if len(snippet) > 120:
                snippet = snippet[:117] + "..."
            findings.append(
                InjectionFinding(
                    rule_id=rule_id,
                    severity=severity,
                    matched_span=snippet or "(invisible-sequence)",
                    offset=match.start(),
                )
            )

    # Also inspect any Base64-encoded blobs for smuggled prompt/shell payloads
    findings.extend(_detect_base64_smuggled_injections(raw))

    # Strip zero-width & unicode tag smuggling characters
    zw_matches = len(_ZERO_WIDTH_RE.findall(raw))
    de_zw = _ZERO_WIDTH_RE.sub("", raw)

    # Neutralize any explicit chat-template or instruction-override spans in clean_text
    sanitized = de_zw
    for rule_id, severity, pattern in _INJECTION_RULES:
        if severity in {"high", "critical"} and rule_id != "unicode_tag_smuggling":
            sanitized = pattern.sub(f"[SANITIZED:{rule_id.upper()}]", sanitized)

    # Redact secrets
    sanitized, secret_count = redact_secrets_with_count(sanitized)

    has_high_or_crit = any(f.severity in {"high", "critical"} for f in findings)
    quarantined = bool(quarantine_on_high and has_high_or_crit)
    safe = len(findings) == 0

    return SanitizeReport(
        clean_text=sanitized,
        safe=safe,
        quarantined=quarantined,
        redacted_secrets_count=secret_count,
        hidden_blocks_stripped=hidden_stripped,
        zero_width_stripped=zw_matches,
        findings=tuple(findings),
    )
