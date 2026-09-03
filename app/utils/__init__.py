"""Common utility helpers."""
from __future__ import annotations
import re
import hashlib
from urllib.parse import urlparse, urljoin, urldefrag
from typing import Iterable, Dict, Optional


def normalize_url(url: str) -> str:
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    while "//" in path:
        path = path.replace("//", "/")
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = "/"
    return f"{scheme}://{netloc}{path}"


def is_same_domain(url_a: str, url_b: str) -> bool:
    a = urlparse(url_a).netloc.lower()
    b = urlparse(url_b).netloc.lower()
    return a == b


def is_internal(url: str, base_domain: str) -> bool:
    host = urlparse(url).netloc.lower()
    base = urlparse(base_domain).netloc.lower()
    return host == "" or host == base


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def safe_join(*parts: Iterable[str]) -> str:
    out = ""
    for p in parts:
        if not p:
            continue
        if not out:
            out = p
        else:
            out = out.rstrip("/") + "/" + p.lstrip("/")
    return out


def detect_language_simple(text: str) -> str:
    """Very rough language detector for HTML lang attribute default."""
    return ""


_JS_CHALLENGE_INDICATORS = [
    "aes.js",
    "slowaes",
    "slowAES",
    "document.cookie",
    "__test",
    "This site requires Javascript",
    "javascript verification",
    "js verification",
    "verify you are human",
    "cloudflare",
    "cdn.optimizely.com",
]


def is_js_verification_page(
    html: str,
    headers: Optional[Dict[str, str]] = None,
    cookies: Optional[Dict[str, str]] = None,
    final_url: str = "",
) -> Dict:
    """Detect hosting-side JavaScript verification challenge pages.

    Returns a dict with:
      - is_challenge: bool
      - indicators: list of matched strings
      - reason: short description
      - sample: first 500 chars of HTML
      - final_url: URL after redirects
      - headers: provided headers (redacted of sensitive values)
      - cookies: provided cookie names only (values omitted)
    """
    html_lower = (html or "").lower()
    sample = (html or "")[:500]
    matched = []
    for ind in _JS_CHALLENGE_INDICATORS:
        if ind.lower() in html_lower:
            matched.append(ind)

    is_challenge = bool(matched)

    safe_headers = {}
    if headers:
        for k, v in headers.items():
            safe_headers[k] = v if k.lower() not in ("cookie", "set-cookie") else "[REDACTED]"

    safe_cookies = {}
    if cookies:
        for k in cookies:
            safe_cookies[k] = "[REDACTED]"

    reason = ""
    if is_challenge:
        reason = f"JS verification page detected: {', '.join(matched)}"

    return {
        "is_challenge": is_challenge,
        "indicators": matched,
        "reason": reason,
        "sample": sample,
        "final_url": final_url,
        "headers": safe_headers,
        "cookies": safe_cookies,
    }


def fetch_real_html(url: str, timeout: int = 20, user_agent: str = "AI-SEO-Autopilot/1.0") -> Dict:
    """Fetch real website HTML, bypassing JavaScript verification challenges.

    Strategy:
    1. Try raw HTTP GET.
    2. If response is a JS verification challenge AND Playwright is available,
       render the page with Playwright and extract the final DOM.
    3. Verify the rendered HTML is not itself a challenge page.
    4. Return the best available HTML with provenance metadata.

    Returns:
        {
            "ok": bool,
            "html": str,
            "status_code": int,
            "final_url": str,
            "source": "raw" | "rendered" | None,
            "challenge": dict | None,
            "error": str | None,
        }
    """
    import requests as _requests
    try:
        r = _requests.get(url, timeout=timeout, allow_redirects=True, headers={"User-Agent": user_agent})
        html = r.text or ""
        final_url = r.url
        challenge = is_js_verification_page(html=html, headers=dict(r.headers), cookies=dict(r.cookies), final_url=final_url)

        if not challenge.get("is_challenge"):
            return {
                "ok": True,
                "html": html,
                "status_code": r.status_code,
                "final_url": final_url,
                "source": "raw",
                "challenge": None,
                "error": None,
            }

        # Challenge detected. Try Playwright fallback.
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return {
                "ok": False,
                "html": html,
                "status_code": r.status_code,
                "final_url": final_url,
                "source": None,
                "challenge": challenge,
                "error": "JS verification challenge detected and Playwright not available",
            }

        rendered_html = ""
        rendered_url = final_url
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                ctx = browser.new_context(user_agent=user_agent, viewport={"width": 1280, "height": 800})
                page = ctx.new_page()
                page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    page.wait_for_timeout(2000)
                rendered_html = page.content()
                rendered_url = page.url
                browser.close()
        except Exception as e:
            return {
                "ok": False,
                "html": html,
                "status_code": r.status_code,
                "final_url": final_url,
                "source": None,
                "challenge": challenge,
                "error": f"Playwright render failed: {e}",
            }

        if not rendered_html or len(rendered_html) < 200:
            return {
                "ok": False,
                "html": rendered_html,
                "status_code": r.status_code,
                "final_url": rendered_url,
                "source": "rendered",
                "challenge": challenge,
                "error": "Rendered HTML too short",
            }

        rendered_challenge = is_js_verification_page(html=rendered_html, final_url=rendered_url)
        if rendered_challenge.get("is_challenge"):
            return {
                "ok": False,
                "html": rendered_html,
                "status_code": r.status_code,
                "final_url": rendered_url,
                "source": "rendered",
                "challenge": rendered_challenge,
                "error": "Rendered HTML is still a JS verification challenge",
            }

        return {
            "ok": True,
            "html": rendered_html,
            "status_code": r.status_code,
            "final_url": rendered_url,
            "source": "rendered",
            "challenge": None,
            "error": None,
        }
    except Exception as e:
        return {
            "ok": False,
            "html": "",
            "status_code": 0,
            "final_url": url,
            "source": None,
            "challenge": None,
            "error": str(e),
        }