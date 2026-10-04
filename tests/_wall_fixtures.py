"""Hand-written labelled TEST FIXTURES for challenge-page detection.

Synthetic HTML only. No network. Copied for tests; not live captures.
"""

from __future__ import annotations


def page(title: str, body: str, script: str = "") -> str:
    extra = f"<script>{script}</script>" if script else ""
    return (
        f"<!doctype html><html><head><title>{title}</title>{extra}</head>"
        f"<body>{body}</body></html>"
    )


PARA = (
    "Captchas were invented to tell people from programs. A modern captcha may ask you to pick "
    "traffic lights, or just watch how your mouse moves. Sites such as Cloudflare say 'verify you are human' "
    "when traffic looks odd, and a page may flash 'just a moment' while it decides. "
)
BIG_JS = "var a=1;" + (
    "window._cf_chl_opt={cvId:'3',cZone:'x',cType:'managed',cRay:'0123456789abcdef'};" * 60
)

# (name, label_is_wall, status, body)
WALL_FIXTURES: list[tuple[str, bool, int, str]] = [
    (
        "long article ABOUT captchas (9KB prose)",
        False,
        200,
        page(
            "History of CAPTCHA",
            "<article>" + "".join(f"<p>{PARA}</p>" for _ in range(22)) + "</article>",
        ),
    ),
    (
        "long docs page, reCAPTCHA integration (~5KB)",
        False,
        200,
        page(
            "reCAPTCHA v3 docs",
            "<main><h1>Integrating reCAPTCHA</h1>"
            + "".join(
                "<p>Add the script tag, then call grecaptcha.execute with your site key. "
                "Verify the token server side; if the score is low, ask the user to verify you "
                "are human via a challenge. Captcha tokens expire after two minutes.</p>"
                for _ in range(25)
            )
            + "</main>",
        ),
    ),
    (
        "SHORT docs page, reCAPTCHA integration (~600 chars)",
        False,
        200,
        page(
            "reCAPTCHA quick start",
            "<main><h1>reCAPTCHA quick start</h1><p>Add the script tag and call "
            "grecaptcha.execute with your site key. Verify the token on your server. If the "
            "score is low, show a captcha challenge to the user. Tokens expire after two "
            "minutes. See the full guide for v2 checkbox, invisible and enterprise "
            "variants.</p></main>",
        ),
    ),
    (
        "short blog post about captchas (~700 chars)",
        False,
        200,
        page(
            "I hate captchas",
            "<article><h1>I hate captchas</h1><p>Spent ten minutes today clicking "
            "crosswalks. A captcha should not take longer than the thing it protects. Here "
            "is what I would do instead: rate limit, honeypot field, and move on. Short "
            "post, back to work.</p></article>",
        ),
    ),
    (
        "long article using 'just a moment' / 'access denied' idioms (3KB)",
        False,
        200,
        page(
            "Customer service tips",
            "".join(
                "<p>Just a moment, please. When a customer hears access denied they leave. "
                "Train staff to explain why.</p>"
                for _ in range(30)
            ),
        ),
    ),
    (
        "normal short page (tide table)",
        False,
        200,
        page(
            "Tides",
            "<p>The spring tide arrives at 06:14 tomorrow, about an hour later than today.</p>",
        ),
    ),
    (
        "real-style Cloudflare interstitial, 403, inline JS",
        True,
        403,
        page(
            "Just a moment...",
            "<div class='main-wrapper'><h1>example.test</h1>"
            "<h2>Checking your browser before accessing example.test.</h2>"
            "<p>Verify you are human by completing the action below.</p>"
            "<div id='cf-browser-verification'></div>"
            "<noscript>Enable JavaScript and cookies to continue</noscript></div>",
            BIG_JS,
        ),
    ),
    (
        "Cloudflare interstitial, 403, NO big script (short)",
        True,
        403,
        page(
            "Just a moment...",
            "<h1>Attention Required! | Cloudflare</h1>"
            "<p>Please complete the security check to access example.test. "
            "Verify you are human.</p>",
        ),
    ),
    (
        "Cloudflare interstitial, 503, short",
        True,
        503,
        page("Just a moment...", "<p>Checking your browser before accessing the site.</p>"),
    ),
    (
        "Cloudflare interstitial served with 200 + big inline JS",
        True,
        200,
        page(
            "Just a moment...",
            "<h2>Checking your browser before accessing example.test.</h2>"
            "<p>Verify you are human.</p>",
            BIG_JS,
        ),
    ),
    (
        "hCaptcha challenge page, 200, short",
        True,
        200,
        page(
            "Security check",
            "<h1>Please verify you are human</h1>"
            "<div class='h-captcha' data-sitekey='00000000-0000-0000-0000-000000000000'></div>"
            "<script src='https://js.hcaptcha.com/1/api.js'></script>",
        ),
    ),
    (
        "hCaptcha challenge page, 200, with ~4KB inline JS",
        True,
        200,
        page(
            "Security check",
            "<h1>Please verify you are human</h1><div class='h-captcha'></div>",
            BIG_JS,
        ),
    ),
    (
        "reCAPTCHA 'are you a robot' page, 429, short",
        True,
        429,
        page(
            "Unusual traffic",
            "<p>Our systems have detected unusual traffic. Are you a robot? "
            "Please solve this captcha.</p>",
        ),
    ),
    (
        "login wall 'Sign in to continue', 200, short",
        True,
        200,
        page(
            "Sign in",
            "<h1>Sign in to continue</h1><form><input name=u><input name=p type=password></form>",
        ),
    ),
    (
        "403 Akamai 'Access Denied' body",
        True,
        403,
        "<HTML><HEAD><TITLE>Access Denied</TITLE></HEAD>"
        "<BODY><H1>Access Denied</H1>You don't have permission to access this server."
        "</BODY></HTML>",
    ),
    (
        "bare 403 Forbidden (no wall words)",
        False,
        403,
        "<html><body><h1>403 Forbidden</h1></body></html>",
    ),
    (
        "bare 429 Too Many Requests (rate limit, no wall words)",
        False,
        429,
        "<html><body><h1>429 Too Many Requests</h1><p>Retry later.</p></body></html>",
    ),
    (
        "404 page",
        False,
        404,
        "<html><body><h1>Not found</h1></body></html>",
    ),
    (
        "LONG 403 interstitial: captcha wording + 6KB of real-looking page chrome",
        True,
        403,
        page(
            "Blocked",
            "<h1>Attention Required</h1><p>Complete the captcha to continue.</p>"
            + "<nav>"
            + "<a href='/x'>link</a> " * 400
            + "</nav>",
        ),
    ),
    (
        "cookie-banner-only page",
        False,
        200,
        page("Article", "<p>Please enable cookies to continue reading this article.</p>"),
    ),
]
