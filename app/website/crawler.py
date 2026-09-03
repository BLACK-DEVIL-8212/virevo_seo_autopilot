"""Website crawler with rendering support."""
from __future__ import annotations
import time
import json
import os
import re
import threading
import warnings
from collections import deque
from datetime import datetime
from urllib.parse import urljoin, urlparse
from typing import Optional, Set, List, Dict

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from ..utils import normalize_url, is_internal, is_js_verification_page, fetch_real_html
from ..config import Config
from ..events import get_event_manager
from ..website.renderer import PageRenderer
from ..website.spa_detector import detect_architecture, detect_from_js_bundle
from ..website.spa_crawler import SpaRouteDiscovery, SpaCrawler

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


class CrawlStats:
    def __init__(self):
        self.pages_crawled = 0
        self.pages_discovered = 0
        self.pages_queued = 0
        self.pages_failed = 0
        self.pages_skipped = 0
        self.pages_blocked = 0
        self.errors: List[str] = []
        self.fetch_errors: List[Dict] = []
        self.source = "raw"
        self._stop = False
        self._pause = False
        self._lock = threading.Lock()

    def to_result(self) -> Dict:
        """Return the authoritative crawl result dict.

        Both the Live Activity UI and the Background Job result must use
        this same object so the counters can never disagree.
        """
        return {
            "pages_crawled": self.pages_crawled,
            "pages_discovered": self.pages_discovered,
            "pages_queued": self.pages_queued,
            "pages_failed": self.pages_failed,
            "pages_skipped": self.pages_skipped,
            "pages_blocked": self.pages_blocked,
            "errors": list(self.errors),
            "fetch_errors": list(self.fetch_errors),
        }


class WebsiteCrawler:
    """Crawl a public website starting from a root URL."""

    USER_AGENT = "AI-SEO-Autopilot/1.0 (+https://example.com/bot)"

    def __init__(self, root_url: str, max_pages: int = None, max_depth: int = None,
                 delay: float = None, respect_robots: bool = True):
        self.root_url = normalize_url(root_url)
        self.max_pages = int(max_pages or Config.CRAWL_MAX_PAGES)
        self.max_depth = int(max_depth or Config.CRAWL_MAX_DEPTH)
        self.delay = float(delay if delay is not None else Config.CRAWL_DELAY_SECONDS)
        self.respect_robots = respect_robots
        self.robots_disallow: Set[str] = set()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.USER_AGENT})
        self.stats = CrawlStats()
        self.results: List[Dict] = []
        self._seen: Set[str] = set()
        self._queued: Set[str] = set()
        self._failed: Set[str] = set()
        self._skipped: Set[str] = set()
        self._skip_reasons: Dict[str, str] = {}
        self._discovery_sources: Dict[str, str] = {}
        self._crawled: Set[str] = set()
        self.job_id: Optional[str] = None
        self.event_manager = get_event_manager()
        self.renderer = PageRenderer()
        self.architecture: Dict = {}
        self.spa_discovery: Optional[SpaRouteDiscovery] = None
        self._blocked: Dict[str, Dict] = {}

    def _emit(self, event_type: str, message: str = "", severity: str = "info",
              url: str = "", metadata: dict = None):
        """Emit an event if job_id is set."""
        if self.job_id:
            self.event_manager.emit(
                job_id=self.job_id,
                event_type=event_type,
                message=message,
                agent_name="Website Crawler",
                severity=severity,
                url=url,
                metadata=metadata or {},
            )

    def _check_control(self) -> bool:
        """Check for control signals. Returns True if should continue."""
        if not self.job_id:
            return True
        signal = self.event_manager.check_control_signal(self.job_id)
        if signal == "stop":
            self.stats._stop = True
            return False
        elif signal == "pause":
            self.stats._pause = True
            self._emit("crawl_paused", "Crawl paused by user", severity="warning")
            while self.stats._pause and not self.stats._stop:
                time.sleep(0.5)
                sig = self.event_manager.check_control_signal(self.job_id)
                if sig == "resume":
                    self.stats._pause = False
                    self._emit("crawl_resumed", "Crawl resumed by user", severity="info")
                    break
                elif sig == "stop":
                    self.stats._stop = True
                    return False
        return not self.stats._stop

    def _load_robots(self):
        try:
            r = self.session.get(urljoin(self.root_url, "/robots.txt"), timeout=10)
            if r.status_code == 200:
                agent = None
                applies = True
                for line in r.text.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.lower().startswith("user-agent"):
                        agent = line.split(":", 1)[1].strip()
                        applies = (agent == "*" or agent.lower() == "ai-seo-autopilot")
                    elif line.lower().startswith("disallow") and applies:
                        path = line.split(":", 1)[1].strip()
                        if path:
                            self.robots_disallow.add(path)
        except Exception as e:
            self._emit("robots_fetch_failed",
                       f"Failed to fetch robots.txt: {type(e).__name__}: {e}",
                       severity="warning", url=self.root_url)

    def _allowed(self, url: str) -> bool:
        if not self.respect_robots or not self.robots_disallow:
            return True
        path = urlparse(url).path or "/"
        for rule in self.robots_disallow:
            if rule == "/":
                return False
            if path.startswith(rule):
                return False
        return True

    def _classify_exception(self, exc: Exception, url: str) -> Dict:
        """Classify a network/HTTP exception into structured error info.

        Preserves the real exception type and message instead of collapsing
        every failure into a generic HTTP 0.
        """
        from urllib.parse import urlparse
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        error_type = type(exc).__name__
        error_message = str(exc)
        exc_msg_lower = error_message.lower()

        if isinstance(exc, requests.exceptions.SSLError):
            error_type = "SSLError"
        elif isinstance(exc, requests.exceptions.ConnectionError):
            if any(tok in exc_msg_lower for tok in (
                "name or service not known", "getaddrinfo", "nodename nor servname",
                "temporary failure in name resolution",
            )):
                error_type = "DNSResolutionError"
            elif "connection refused" in exc_msg_lower:
                error_type = "ConnectionRefusedError"
            elif "ssl" in exc_msg_lower:
                error_type = "SSLError"
            else:
                error_type = "ConnectionError"
        elif isinstance(exc, requests.exceptions.Timeout):
            error_type = "TimeoutError"
        elif isinstance(exc, requests.exceptions.TooManyRedirects):
            error_type = "TooManyRedirectsError"
        elif isinstance(exc, requests.exceptions.RequestException):
            error_type = "RequestException"

        return {
            "error_type": error_type,
            "error_message": error_message,
            "url": url,
            "hostname": hostname,
            "port": port,
            "scheme": parsed.scheme,
        }

    def _diagnose_connectivity(self, url: str) -> Dict:
        """Run pre-crawl connectivity diagnostics.

        Tests DNS resolution, TCP connection, SSL/TLS handshake, basic HTTP
        GET, and redirect chain.  Logs the exact failure stage so the real
        root cause of an HTTP 0 is never hidden.
        """
        from urllib.parse import urlparse
        import socket
        import ssl as _ssl

        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        diag: Dict = {
            "url": url,
            "hostname": hostname,
            "port": port,
            "dns": "unknown",
            "tcp": "unknown",
            "tls": "unknown",
            "http": "unknown",
            "status_code": None,
            "resolved_ips": [],
            "redirects": [],
            "final_url": None,
            "error_type": None,
            "error_message": None,
        }

        # Stage 1: DNS resolution
        try:
            addr_info = socket.getaddrinfo(
                hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM
            )
            diag["resolved_ips"] = sorted(set(a[4][0] for a in addr_info))
            diag["dns"] = "success"
        except socket.gaierror as e:
            diag["dns"] = "failed"
            diag["error_type"] = "DNSResolutionError"
            diag["error_message"] = str(e)
            self._emit("connectivity_diagnostic",
                       f"DNS failed for {hostname}: {e}",
                       severity="error", url=url,
                       metadata={"stage": "dns", **diag})
            return diag
        except Exception as e:
            diag["dns"] = "failed"
            diag["error_type"] = type(e).__name__
            diag["error_message"] = str(e)
            self._emit("connectivity_diagnostic",
                       f"DNS failed for {hostname}: {e}",
                       severity="error", url=url,
                       metadata={"stage": "dns", **diag})
            return diag

        if not diag["resolved_ips"]:
            diag["dns"] = "failed"
            diag["error_type"] = "DNSResolutionError"
            diag["error_message"] = f"No A/AAAA records found for {hostname}"
            self._emit("connectivity_diagnostic",
                       diag["error_message"], severity="error", url=url,
                       metadata={"stage": "dns", **diag})
            return diag

        # Stage 2: TCP connection
        sock = None
        try:
            sock = socket.create_connection((hostname, port), timeout=10)
            diag["tcp"] = "success"
        except socket.timeout:
            diag["tcp"] = "failed"
            diag["error_type"] = "TimeoutError"
            diag["error_message"] = f"TCP connection to {hostname}:{port} timed out"
        except ConnectionRefusedError:
            diag["tcp"] = "failed"
            diag["error_type"] = "ConnectionRefusedError"
            diag["error_message"] = f"Connection refused by {hostname}:{port}"
        except Exception as e:
            diag["tcp"] = "failed"
            diag["error_type"] = type(e).__name__
            diag["error_message"] = str(e)
        if sock:
            try:
                sock.close()
            except Exception:
                pass

        if diag["tcp"] == "failed":
            self._emit("connectivity_diagnostic",
                       diag["error_message"], severity="error", url=url,
                       metadata={"stage": "tcp", **diag})
            return diag

        # Stage 3: SSL/TLS handshake (HTTPS only)
        if parsed.scheme == "https":
            try:
                context = _ssl.create_default_context()
                with socket.create_connection((hostname, port), timeout=10) as tls_sock:
                    with context.wrap_socket(tls_sock, server_hostname=hostname) as ssock:
                        cert = ssock.getpeercert()
                diag["tls"] = "success"
                if cert:
                    diag["tls_cert"] = {
                        "not_after": cert.get("notAfter", ""),
                        "subject": dict(x[0] for x in cert.get("subject", [])) if cert.get("subject") else {},
                    }
            except _ssl.SSLError as e:
                diag["tls"] = "failed"
                diag["error_type"] = "SSLError"
                diag["error_message"] = str(e)
                self._emit("connectivity_diagnostic",
                           diag["error_message"], severity="error", url=url,
                           metadata={"stage": "tls", **diag})
                return diag
            except Exception as e:
                diag["tls"] = "failed"
                diag["error_type"] = type(e).__name__
                diag["error_message"] = str(e)
                self._emit("connectivity_diagnostic",
                           diag["error_message"], severity="error", url=url,
                           metadata={"stage": "tls", **diag})
                return diag
        else:
            diag["tls"] = "n/a"

        # Stage 4: Basic HTTP GET
        try:
            r = self.session.get(url, timeout=15, allow_redirects=True)
            diag["http"] = "success"
            diag["status_code"] = r.status_code
            diag["final_url"] = r.url
            # Stage 5: Redirect chain
            diag["redirects"] = [
                {"status_code": h.status_code, "url": h.url}
                for h in r.history
            ]
            self._emit("connectivity_diagnostic",
                       f"Connectivity OK: DNS={diag['dns']}, TCP={diag['tcp']}, "
                       f"TLS={diag['tls']}, HTTP={r.status_code}",
                       severity="info", url=url,
                       metadata={"stage": "all", **diag})
        except requests.exceptions.ConnectionError as e:
            diag["http"] = "failed"
            err_info = self._classify_exception(e, url)
            diag["error_type"] = err_info["error_type"]
            diag["error_message"] = err_info["error_message"]
            self._emit("connectivity_diagnostic",
                       diag["error_message"], severity="error", url=url,
                       metadata={"stage": "http", **diag})
        except requests.exceptions.Timeout:
            diag["http"] = "failed"
            diag["error_type"] = "TimeoutError"
            diag["error_message"] = f"HTTP GET to {url} timed out"
            self._emit("connectivity_diagnostic",
                       diag["error_message"], severity="error", url=url,
                       metadata={"stage": "http", **diag})
        except Exception as e:
            diag["http"] = "failed"
            diag["error_type"] = type(e).__name__
            diag["error_message"] = str(e)
            self._emit("connectivity_diagnostic",
                       diag["error_message"], severity="error", url=url,
                       metadata={"stage": "http", **diag})

        return diag

    def _render_with_browser(self, url: str,
                             app_root_selector: str = "#app, #root, #__next, #__nuxt, [id*='app']") -> Dict:
        """Render a page with a headless browser (Stage 2 fallback).

        Used when normal HTTP fetching fails or the page is
        JavaScript-rendered.  Implements the full two-stage browser pipeline:

        1. Navigate to the URL.
        2. Wait for DOM content loaded.
        3. Wait for application root element.
        4. Wait for network idle with a timeout.
        5. Capture final URL.
        6. Capture page title.
        7. Capture rendered HTML.
        8. Capture visible text.
        9. Capture browser console errors.
        10. Capture failed network requests.

        Browser errors are never silently converted into HTTP 0.
        """
        if not getattr(self.renderer, 'use_playwright', False):
            return {
                "ok": False,
                "rendered": False,
                "html": "",
                "error_type": "PlaywrightNotAvailable",
                "error_message": "Playwright is not installed; cannot render JavaScript-rendered pages.",
            }

        result: Dict = {
            "ok": False,
            "rendered": False,
            "html": "",
            "final_url": url,
            "status_code": 0,
            "page_title": "",
            "visible_text": "",
            "console_errors": [],
            "failed_requests": [],
            "error_type": None,
            "error_message": None,
        }

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                ctx = browser.new_context(
                    user_agent=self.USER_AGENT,
                    viewport={"width": 1280, "height": 800},
                )
                page = ctx.new_page()

                console_errors: List[Dict] = []
                failed_requests: List[Dict] = []

                page.on("console", lambda msg: console_errors.append({
                    "type": msg.type,
                    "text": msg.text,
                }) if msg.type == "error" else None)

                page.on("requestfailed", lambda req: failed_requests.append({
                    "url": req.url,
                    "method": req.method,
                    "failure": (req.failure or {}).get("error_description", ""),
                }))

                try:
                    # 1. Navigate to URL, 2. wait for DOMContentLoaded
                    response = page.goto(
                        url, timeout=self.renderer.timeout * 1000,
                        wait_until="domcontentloaded",
                    )
                    if response:
                        result["status_code"] = response.status
                    else:
                        result["status_code"] = 0
                        result["error_type"] = "NoResponse"
                        result["error_message"] = "Browser received no response for the initial navigation."

                    # 3. Wait for application root element
                    try:
                        page.wait_for_selector(app_root_selector, timeout=5000)
                    except Exception:
                        pass  # Root element may not exist; proceed anyway

                    # 4. Wait for network idle with timeout
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        page.wait_for_timeout(2000)

                    # 5. Capture final URL
                    result["final_url"] = page.url
                    # 6. Capture page title
                    try:
                        result["page_title"] = page.title()
                    except Exception:
                        pass
                    # 7. Capture rendered HTML
                    result["html"] = page.content()
                    # 8. Capture visible text
                    try:
                        result["visible_text"] = page.inner_text("body")
                    except Exception:
                        pass
                    # 9 & 10. Console errors and failed requests already collected
                    result["console_errors"] = console_errors
                    result["failed_requests"] = failed_requests
                    result["ok"] = True
                    result["rendered"] = True

                except Exception as e:
                    result["error_type"] = type(e).__name__
                    result["error_message"] = str(e)

                browser.close()
        except Exception as e:
            result["error_type"] = type(e).__name__
            result["error_message"] = str(e)

        return result

    def _fetch(self, url: str) -> Dict:
        """Fetch a URL with retry logic (Stage 1: HTTP fetch).

        Returns a dict with:
        - status_code: int — HTTP status code, or 0 if no response was received
        - html: str — response body (may contain error text on failure)
        - final_url: str — final URL after redirects
        - error_type: str | None — exception class name if fetch failed
        - error_message: str | None — exception message if fetch failed
        - is_challenge: bool — JS verification challenge detected
        - challenge: dict | None — challenge details if detected
        - diagnostics: dict | None — connectivity diagnostics
        - retries_exhausted: bool — whether all retries were used

        HTTP status 0 means no valid HTTP response was received (DNS failure,
        connection refused, SSL/TLS error, timeout, etc.).  It must never be
        treated as a valid HTTP response.
        """
        transient_errors = (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.TooManyRedirects,
        )
        last_exc = None
        last_error_info: Optional[Dict] = None
        last_final_url = url

        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=15, allow_redirects=True)
                html = r.text or ""
                final_url = r.url

                challenge = is_js_verification_page(
                    html=html,
                    headers=dict(r.headers),
                    cookies=dict(r.cookies),
                    final_url=final_url,
                )
                if challenge.get("is_challenge"):
                    self._blocked[url] = challenge
                    # Do NOT emit here; crawl() will emit page_crawl_blocked
                    # after it has full context (fetch_time, pages_crawled, etc.)
                    # Try Playwright fallback for JS verification pages
                    if getattr(self.renderer, 'use_playwright', False):
                        rendered = self.renderer.render(final_url or url)
                        if rendered.get("ok") and rendered.get("rendered") and rendered.get("html"):
                            rendered_html = rendered["html"]
                            rendered_challenge = is_js_verification_page(
                                html=rendered_html,
                                final_url=final_url,
                            )
                            if not rendered_challenge.get("is_challenge"):
                                self._blocked.pop(url, None)
                                return {
                                    "status_code": r.status_code,
                                    "html": rendered_html,
                                    "final_url": final_url,
                                    "error_type": None,
                                    "error_message": None,
                                    "is_challenge": False,
                                    "challenge": None,
                                }
                    # Challenge detected but could not bypass — preserve
                    # the real HTTP status code instead of returning 0.
                    return {
                        "status_code": r.status_code,
                        "html": html,
                        "final_url": final_url,
                        "error_type": "JSVerificationChallenge",
                        "error_message": challenge.get("reason", "JS verification page"),
                        "is_challenge": True,
                        "challenge": challenge,
                    }

                return {
                    "status_code": r.status_code,
                    "html": html,
                    "final_url": final_url,
                    "error_type": None,
                    "error_message": None,
                    "is_challenge": False,
                    "challenge": None,
                }
            except transient_errors as e:
                last_exc = e
                last_error_info = self._classify_exception(e, url)
                last_final_url = url
                if attempt < 2:
                    time.sleep(2 ** attempt)
            except Exception as e:
                error_info = self._classify_exception(e, url)
                diags = self._diagnose_connectivity(url)
                return {
                    "status_code": 0,
                    "html": "",
                    "final_url": url,
                    "error_type": error_info["error_type"],
                    "error_message": error_info["error_message"],
                    "is_challenge": False,
                    "challenge": None,
                    "diagnostics": diags,
                }

        # All retries exhausted for transient errors
        diags = self._diagnose_connectivity(url) if last_error_info else None
        return {
            "status_code": 0,
            "html": "",
            "final_url": last_final_url,
            "error_type": last_error_info["error_type"] if last_error_info else type(last_exc).__name__,
            "error_message": last_error_info["error_message"] if last_error_info else str(last_exc),
            "is_challenge": False,
            "challenge": None,
            "diagnostics": diags,
            "retries_exhausted": True,
        }

    def _is_html_content(self, url: str, html: str, status_code: int) -> bool:
        if status_code < 200 or status_code >= 400:
            return False
        if not html or not html.strip():
            return False
        path = urlparse(url).path.lower()
        if any(path.endswith(ext) for ext in self.ASSET_EXTENSIONS):
            return False
        lowered = html.lstrip().lower()
        if lowered.startswith("<!doctype") or lowered.startswith("<html"):
            return True
        if "<html" in lowered[:200].lower():
            return True
        return len(html) > 200

    def _extract_links(self, html: str, current_url: str) -> Set[str]:
        soup = BeautifulSoup(html or "", "html.parser")
        found: Set[str] = set()
        for tag in soup.find_all(["a", "link"]):
            href = tag.get("href")
            if not href:
                continue
            if tag.name == "link" and tag.get("rel"):
                rel = " ".join(tag.get("rel")).lower()
                if "stylesheet" in rel or "alternate" in rel:
                    continue
            abs_url = urljoin(current_url, href)
            norm = normalize_url(abs_url)
            if is_internal(norm, self.root_url):
                found.add(norm)
        return found

    def _extract_structured_data_urls(self, html: str, current_url: str) -> Set[str]:
        urls: Set[str] = set()
        soup = BeautifulSoup(html or "", "html.parser")
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(s.string or "{}")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    urls.update(self._walk_json_for_urls(item, current_url))
            except Exception:
                continue
        return urls

    def _walk_json_for_urls(self, obj, current_url: str) -> Set[str]:
        found: Set[str] = set()
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("url", "@id", "url", "sameAs", "image") and isinstance(v, str):
                    candidate = v.strip()
                    if candidate.startswith("http"):
                        norm = normalize_url(candidate)
                        if is_internal(norm, self.root_url):
                            found.add(norm)
                elif isinstance(v, (dict, list)):
                    found.update(self._walk_json_for_urls(v, current_url))
        elif isinstance(obj, list):
            for item in obj:
                found.update(self._walk_json_for_urls(item, current_url))
        return found

    def _extract_canonical(self, html: str, current_url: str) -> Set[str]:
        urls: Set[str] = set()
        soup = BeautifulSoup(html or "", "html.parser")
        canon = soup.find("link", rel="canonical")
        if canon and canon.get("href"):
            href = canon.get("href")
            if href.startswith("http"):
                urls.add(normalize_url(href))
            else:
                urls.add(normalize_url(urljoin(current_url, href)))
        return urls

    def _render_and_extract(self, url: str) -> Set[str]:
        if not getattr(self.renderer, 'use_playwright', False):
            return set()
        try:
            result = self.renderer.render(url)
            if not result.get("ok") or not result.get("rendered"):
                return set()
            return self._extract_links(result.get("html", ""), url)
        except Exception:
            return set()

    def _discover_urls_from_sitemap(self, root_url: str) -> Set[str]:
        from ..seo.sitemap import discover_sitemaps, fetch_sitemap, parse_sitemap
        from ..seo.robots import fetch_robots, parse_robots
        found: Set[str] = set()

        sitemap_candidates = [
            "/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml",
            "/wp-sitemap.xml", "/sitemap-index.xml",
        ]
        robots_text = fetch_robots(root_url)
        if robots_text:
            parsed_robots = parse_robots(robots_text)
            for sm in parsed_robots.get("sitemaps", []):
                if sm not in sitemap_candidates:
                    sitemap_candidates.append(sm)

        for path in sitemap_candidates:
            url = urljoin(root_url, path)
            try:
                xml = fetch_sitemap(url)
                if not xml and getattr(self.renderer, 'use_playwright', False):
                    rendered = self.renderer.render(url)
                    if rendered.get("ok") and rendered.get("rendered"):
                        xml = rendered.get("html", "")
                if xml:
                    parsed = parse_sitemap(xml)
                    for entry in parsed:
                        loc = entry.get("loc", "")
                        if loc and is_internal(loc, self.root_url):
                            found.add(normalize_url(loc))
                        elif loc and not is_internal(loc, self.root_url):
                            other = urlparse(loc)
                            here = urlparse(self.root_url)
                            if other.path and other.netloc == "":
                                found.add(normalize_url(urljoin(self.root_url, other.path)))
                            elif other.netloc and other.netloc != here.netloc:
                                found.add(normalize_url(urljoin(self.root_url, other.path)))
                        if entry.get("type") == "sitemap":
                            sub_xml = fetch_sitemap(loc)
                            if not sub_xml and getattr(self.renderer, 'use_playwright', False):
                                rendered = self.renderer.render(loc)
                                if rendered.get("ok") and rendered.get("rendered"):
                                    sub_xml = rendered.get("html", "")
                            if sub_xml:
                                for sub_entry in parse_sitemap(sub_xml):
                                    sub_loc = sub_entry.get("loc", "")
                                    if sub_loc and is_internal(sub_loc, self.root_url):
                                        found.add(normalize_url(sub_loc))
                                    elif sub_loc:
                                        other = urlparse(sub_loc)
                                        if other.path:
                                            found.add(normalize_url(urljoin(self.root_url, other.path)))
            except Exception:
                continue
        return found

    def _discover_common_spa_routes(self) -> Set[str]:
        if not getattr(self.renderer, 'use_playwright', False):
            return set()
        common = [
            "/about", "/about-us", "/contact", "/pricing", "/features",
        ]
        found: Set[str] = set()
        for path in common:
            url = urljoin(self.root_url, path)
            if url in self._seen or url in self._queued:
                continue
            try:
                result = self.renderer.render(url)
                if result.get("ok") and result.get("rendered") and len(result.get("html", "") or "") > 500:
                    found.add(url)
                    self._emit("url_discovered", f"Discovered SPA route: {url}",
                               url=url, metadata={"source": "spa_route", "depth": 1})
            except Exception:
                continue
        return found

    ASSET_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif",
        ".pdf", ".zip", ".mp4", ".mp3", ".wav", ".css", ".js", ".mjs",
        ".map", ".woff", ".woff2", ".ttf", ".eot", ".json", ".xml",
        ".txt", ".rss", ".atom", ".webmanifest", ".manifest",
        ".cur", ".ico", ".wasm", ".swf",
    }

    def _is_asset_url(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        if any(path.endswith(ext) for ext in self.ASSET_EXTENSIONS):
            return True
        if "/assets/" in path or "/static/" in path or "/dist/" in path or "/build/" in path:
            if any(path.endswith(ext) for ext in self.ASSET_EXTENSIONS):
                return True
        return False

    def _add_url(self, url: str, source: str, depth: int = 0) -> bool:
        norm = normalize_url(url)
        if not is_internal(norm, self.root_url):
            if norm not in self._skipped:
                self._skipped.add(norm)
                self._skip_reasons[norm] = "external"
            return False
        if self._is_asset_url(norm):
            if norm not in self._skipped:
                self._skipped.add(norm)
                self._skip_reasons[norm] = "asset"
            return False
        if not self._allowed(norm):
            if norm not in self._skipped:
                self._skipped.add(norm)
                self._skip_reasons[norm] = "blocked by robots.txt"
            return False
        if norm in self._seen or norm in self._queued:
            if norm not in self._skipped:
                self._skipped.add(norm)
                self._skip_reasons[norm] = "duplicate"
            return False

        self._seen.add(norm)
        self._queued.add(norm)
        self.stats.pages_discovered += 1
        self.stats.pages_queued += 1
        self._discovery_sources[norm] = source
        self._emit("url_discovered", f"Discovered: {norm}",
                   url=norm, metadata={"source": source, "depth": depth})
        self._emit("page_queued", f"Queued: {norm}",
                   url=norm, metadata={"source": source, "depth": depth})
        return True

    def crawl(self, on_progress=None, job_id: str = None) -> List[Dict]:
        if job_id:
            self.job_id = job_id
        self._load_robots()

        self._emit("crawl_started", f"Starting crawl of {self.root_url}",
                   metadata={"max_pages": self.max_pages, "max_depth": self.max_depth})

        # ── Connectivity diagnostics (Task 7) ──
        self._diagnose_connectivity(self.root_url)

        # Pre-discover from sitemap
        sitemap_urls = self._discover_urls_from_sitemap(self.root_url)
        for u in sitemap_urls:
            self._add_url(u, "sitemap", depth=0)

        # Seed queue with homepage
        self._add_url(self.root_url, "homepage", depth=0)

        queue: deque = deque([(self.root_url, 0)])
        architecture_detected = False

        while queue and self.stats.pages_crawled < self.max_pages:
            if not self._check_control():
                break

            url, depth = queue.popleft()
            if url in self._failed or url in self._skipped or url in self._crawled:
                continue
            if not self._allowed(url):
                continue

            self._queued.discard(url)
            self.stats.pages_queued = max(0, self.stats.pages_queued - 1)

            self._emit("page_crawl_started", f"Crawling {url}",
                       url=url, metadata={"depth": depth, "source": self._discovery_sources.get(url, "unknown")})

            start_time = time.time()
            fetch_result = self._fetch(url)
            fetch_time = round(time.time() - start_time, 2)
            status = fetch_result["status_code"]
            html = fetch_result["html"]
            final_url = fetch_result["final_url"] or url
            error_type = fetch_result.get("error_type")
            error_message = fetch_result.get("error_message")
            is_challenge = fetch_result.get("is_challenge", False)
            challenge = fetch_result.get("challenge")
            diagnostics = fetch_result.get("diagnostics")
            norm = normalize_url(final_url)

            # If a JS verification challenge was detected but could not be
            # bypassed by the browser renderer, mark as blocked.
            if url in self._blocked:
                self.stats.pages_blocked += 1
                self._failed.add(url)
                self._crawled.add(url)
                self._emit("page_crawl_blocked",
                           f"Blocked {norm} (JS verification): {error_message}",
                           severity="warning", url=norm,
                           metadata={"status_code": status,
                                     "fetch_time": fetch_time,
                                     "pages_crawled": self.stats.pages_crawled,
                                     "pages_blocked": self.stats.pages_blocked,
                                     "blocked": True,
                                     "block_reason": "js_verification",
                                     "block_details": self._blocked.get(url, {})})
                self.results.append({
                    "url": norm,
                    "status_code": status,
                    "html": html,
                    "depth": depth,
                    "rendered": False,
                    "fetched_at": datetime.utcnow().isoformat(),
                    "fetch_time": fetch_time,
                    "discovery_source": self._discovery_sources.get(norm, "homepage"),
                    "architecture_type": self.architecture.get("architecture_type", "static_html"),
                    "rendering_mode": self.architecture.get("rendering_mode", "raw"),
                    "deployment_strategy": self.architecture.get("deployment_strategy", "direct_html"),
                    "is_spa": self.architecture.get("is_spa", False),
                    "spa_framework": self.architecture.get("detected_spa_framework", ""),
                    "blocked": True,
                    "block_reason": "js_verification",
                    "block_details": self._blocked.get(url, {}),
                    "error_type": error_type,
                    "error_message": error_message,
                })
                if self.delay:
                    time.sleep(self.delay)
                continue

            # Detect architecture on first successful HTML response
            if not architecture_detected and html and 200 <= status < 400:
                arch = detect_architecture(html, url=norm)
                build_info = detect_from_js_bundle(html)
                self.architecture = arch
                self.architecture["build_system"] = build_info.get("build_system", "unknown")
                self.stats.source = "rendered" if arch.get("is_spa") else "raw"
                architecture_detected = True
                self._emit("architecture_detected",
                           f"Detected architecture: {arch.get('architecture_type')}",
                           url=norm,
                           metadata={"architecture": arch, "build_system": build_info})

                # If SPA, discover additional routes
                if arch.get("is_spa") and depth == 0:
                    self.spa_discovery = SpaRouteDiscovery(norm, html, self.renderer)
                    spa_routes = self.spa_discovery.discover(max_routes=30)
                    for route_url in spa_routes:
                        if route_url != norm:
                            self._add_url(route_url, "spa_discovery", depth=1)
                    # Queue newly discovered SPA routes
                    for discovered in list(self._seen - self._failed - self._skipped - self._crawled - set(q[0] for q in queue)):
                        if discovered not in [q[0] for q in queue] and discovered != norm:
                            queue.append((discovered, depth + 1))

            # HTTP status 0 means no valid HTTP response was received — this
            # is NOT a valid HTTP status and must be treated as a failure.
            if status == 0 or status >= 400:
                self.stats.pages_failed += 1
                self._failed.add(url)
                self._crawled.add(url)
                fetch_error = {
                    "url": url,
                    "status_code": status,
                    "error_type": error_type or (f"HTTP{status}" if status != 0 else "HTTPZero"),
                    "error_message": error_message or f"HTTP {status}",
                    "fetch_time": fetch_time,
                    "diagnostics": diagnostics,
                }
                self.stats.fetch_errors.append(fetch_error)
                self._emit("page_crawl_failed",
                           f"Failed to fetch {url}: {error_message or f'HTTP {status}'}",
                           severity="error", url=url,
                           metadata={
                               "status_code": status,
                               "error_type": error_type,
                               "error_message": error_message,
                               "fetch_time": fetch_time,
                               "diagnostics": diagnostics,
                               "retries_exhausted": fetch_result.get("retries_exhausted", False),
                           })
                self.stats.errors.append(
                    f"{url}: {error_type or f'HTTP {status}'} - "
                    f"{error_message or 'No HTTP response received'}"
                )
                if self.delay:
                    time.sleep(self.delay)
                continue

            if not self._is_html_content(norm, html, status):
                self.stats.pages_skipped += 1
                self._skipped.add(norm)
                self._skip_reasons[norm] = "non_html_asset"
                self._crawled.add(url)
                self._emit("page_crawl_skipped",
                           f"Skipped non-HTML resource: {norm}",
                           severity="warning", url=norm,
                           metadata={"status_code": status, "fetch_time": fetch_time, "reason": "non_html_asset"})
                if self.delay:
                    time.sleep(self.delay)
                continue

            # Stage 2: If normal HTTP fetch returned content but the page is
            # JavaScript-rendered (small HTML shell or known SPA), attempt
            # browser rendering to get the real DOM.  This supports SPAs
            # without breaking basic HTTP fetching.
            browser_rendered = False
            if (getattr(self.renderer, 'use_playwright', False)
                    and (self.architecture.get("is_spa") or len(html) < 1200)):
                rendered = self._render_with_browser(url)
                if rendered.get("ok") and rendered.get("html"):
                    browser_rendered = True
                    html = rendered["html"]
                    final_url = rendered.get("final_url", final_url)
                    page_title = rendered.get("page_title", "")
                    norm = normalize_url(final_url)
                    self._emit("page_rendered",
                               f"Rendered {norm} with headless browser in {fetch_time}s",
                               severity="info", url=norm,
                               metadata={
                                   "status_code": rendered.get("status_code"),
                                   "page_title": page_title,
                                   "console_errors": len(rendered.get("console_errors", [])),
                                   "failed_requests": len(rendered.get("failed_requests", [])),
                               })

            # Extract links from raw HTML
            raw_links = self._extract_links(html, final_url or url)
            for link in raw_links:
                self._add_url(link, "homepage_link", depth=depth + 1)

            # Extract links from rendered DOM (only for shallow pages to keep crawl fast)
            if depth <= 0 and getattr(self.renderer, 'use_playwright', False) and not browser_rendered:
                rendered_links = self._render_and_extract(final_url or url)
                for link in rendered_links:
                    self._add_url(link, "rendered_dom", depth=depth + 1)

            # Extract structured data URLs
            sd_urls = self._extract_structured_data_urls(html, final_url or url)
            for u in sd_urls:
                self._add_url(u, "structured_data", depth=depth + 1)

            # Extract canonical
            canon_urls = self._extract_canonical(html, final_url or url)
            for u in canon_urls:
                self._add_url(u, "canonical", depth=depth + 1)

            # Queue newly discovered URLs
            for discovered in list(self._seen - self._failed - self._skipped - self._crawled - set(q[0] for q in queue)):
                if discovered not in [q[0] for q in queue] and discovered != norm:
                    queue.append((discovered, depth + 1))

            page = {
                "url": norm,
                "status_code": status,
                "html": html,
                "depth": depth,
                "rendered": browser_rendered,
                "fetched_at": datetime.utcnow().isoformat(),
                "fetch_time": fetch_time,
                "discovery_source": self._discovery_sources.get(norm, "homepage"),
                "architecture_type": self.architecture.get("architecture_type", "static_html"),
                "rendering_mode": self.architecture.get("rendering_mode", "raw"),
                "deployment_strategy": self.architecture.get("deployment_strategy", "direct_html"),
                "is_spa": self.architecture.get("is_spa", False),
                "spa_framework": self.architecture.get("detected_spa_framework", ""),
            }

            if browser_rendered:
                page["rendered_html"] = html
                page["rendered"] = True

            self.results.append(page)
            self.stats.pages_crawled += 1
            self._crawled.add(norm)

            self._emit("page_crawl_completed",
                       f"Crawled {norm} ({status}) in {fetch_time}s",
                       severity="success", url=norm,
                       metadata={"status_code": status, "fetch_time": fetch_time,
                                 "pages_crawled": self.stats.pages_crawled,
                                 "source": self._discovery_sources.get(norm, "homepage")})

            total_known = max(1, self.stats.pages_discovered)
            progress = min(90, int(5 + 85 * self.stats.pages_crawled / total_known))
            if on_progress:
                try:
                    on_progress(progress, f"Crawled {self.stats.pages_crawled} of {total_known} discovered pages")
                except Exception as e:
                    self._emit("progress_callback_error",
                               f"Progress callback failed: {type(e).__name__}: {e}",
                               severity="warning", url=norm)

            self._emit("crawl_progress",
                       f"Crawled {self.stats.pages_crawled} of {total_known} discovered pages",
                       metadata={"progress": progress,
                                 "pages_crawled": self.stats.pages_crawled,
                                 "pages_discovered": total_known,
                                 "pages_failed": self.stats.pages_failed,
                                 "pages_blocked": self.stats.pages_blocked,
                                 "pages_skipped": len(self._skipped)})

            if self.delay:
                time.sleep(self.delay)

        if self.stats._stop:
            self._emit("crawl_stopped", "Crawl stopped by user", severity="warning")
        else:
            self._emit("crawl_completed",
                       f"Crawl finished. {self.stats.pages_crawled} pages crawled, {self.stats.pages_discovered} discovered.",
                       metadata={
                           "pages_crawled": self.stats.pages_crawled,
                           "pages_discovered": self.stats.pages_discovered,
                           "pages_failed": self.stats.pages_failed,
                           "pages_skipped": self.stats.pages_skipped,
                           "errors": self.stats.errors,
                       })

        self._emit_crawl_debug()

        # Emit authoritative crawl result so UI and Background Job agree
        crawl_result = self.stats.to_result()
        self._emit("crawl_result",
                   f"Crawl result: {crawl_result['pages_crawled']} crawled, "
                   f"{crawl_result['pages_failed']} failed",
                   severity="info" if crawl_result["pages_failed"] == 0 else "error",
                   metadata=crawl_result)

        return self.results

    def get_crawl_result(self) -> Dict:
        """Return the authoritative crawl result dict.

        Both the Live Activity UI and the Background Job ``result_json``
        must use this same object so the counters can never disagree.
        """
        return self.stats.to_result()

    def _emit_crawl_debug(self):
        self._emit("crawl_debug", "Crawl debug summary", severity="info",
                   metadata={
                       "pages_crawled": self.stats.pages_crawled,
                       "pages_discovered": self.stats.pages_discovered,
                       "pages_queued": self.stats.pages_queued,
                       "pages_failed": self.stats.pages_failed,
                       "pages_skipped": len(self._skipped),
                       "pages_blocked": self.stats.pages_blocked,
                       "skip_reasons": dict(list(self._skip_reasons.items())[:20]),
                       "discovery_sources": dict(list(self._discovery_sources.items())[:20]),
                       "fetch_errors": self.stats.fetch_errors,
                   })
