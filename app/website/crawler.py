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
from typing import Optional, Set, List, Dict, Any

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


# Utility functions
def normalize_url(url: str) -> str:
    """Normalize a URL by removing fragments and trailing slashes."""
    if not url:
        return ""
    parsed = urlparse(url)
    # Remove fragments
    normalized = parsed._replace(fragment="").geturl()
    # Remove trailing slash
    if normalized.endswith("/") and not normalized.endswith("//"):
        normalized = normalized[:-1]
    return normalized


def is_internal(url: str, root_url: str) -> bool:
    """Check if URL is internal to the root domain."""
    if not url or not root_url:
        return False
    parsed_url = urlparse(url)
    parsed_root = urlparse(root_url)
    if not parsed_url.netloc:
        return True
    return parsed_url.netloc == parsed_root.netloc


def is_js_verification_page(html: str = "", headers: dict = None, cookies: dict = None, final_url: str = "") -> dict:
    """Detect if a page is a JavaScript verification challenge page."""
    result = {"is_challenge": False, "reason": ""}
    
    if not html:
        return result
    
    html_lower = html.lower()
    
    # Specific challenge patterns that are unique to challenge pages
    # These are script names, function names, and text that appear in
    # Cloudflare/challenge pages but are unlikely in legitimate content
    specific_indicators = [
        "aes.js",
        "slowaes",
        "slowaes",
        "toNumbers",
        "toHex",
        "checkCookie",
        "__test",
        "cf_chl",
        "_cf_chl",
        "_cf_challenge",
        "enable javascript",
        "this site requires javascript",
        "checking your browser before",
        "attention required",
        "javascript is disabled",
        "please enable js",
        "ddos protection by",
        "cf-ray",
    ]
    
    matches = []
    for indicator in specific_indicators:
        if indicator in html_lower:
            matches.append(indicator)
    
    # Require at least one specific indicator that is unique to challenge pages
    if matches:
        result["is_challenge"] = True
        result["reason"] = f"Contains '{matches[0]}'"
    
    return result


def fetch_real_html(url: str, session: requests.Session = None) -> dict:
    """Fetch real HTML content with error handling."""
    session = session or requests.Session()
    try:
        response = session.get(url, timeout=30, allow_redirects=True)
        return {
            "status_code": response.status_code,
            "html": response.text,
            "final_url": response.url,
            "headers": dict(response.headers),
            "cookies": dict(response.cookies),
            "success": 200 <= response.status_code < 400
        }
    except Exception as e:
        return {
            "status_code": 0,
            "html": "",
            "final_url": url,
            "headers": {},
            "cookies": {},
            "success": False,
            "error": str(e)
        }


class Config:
    """Configuration class for crawl settings."""
    CRAWL_MAX_PAGES = 100
    CRAWL_MAX_DEPTH = 3
    CRAWL_DELAY_SECONDS = 1.0
    USE_PLAYWRIGHT = True
    PLAYWRIGHT_TIMEOUT = 30


class PageRenderer:
    """Page renderer using Playwright if available."""
    
    def __init__(self, use_playwright: bool = False, timeout: int = 30):
        self.use_playwright = use_playwright
        self.timeout = timeout
        self._playwright_available = False
        try:
            import playwright
            self._playwright_available = True
        except ImportError:
            pass
    
    def render(self, url: str, wait_for_selector: str = None) -> dict:
        """Render a page using Playwright."""
        if not self.use_playwright or not self._playwright_available:
            return {"ok": False, "rendered": False, "html": "", "error": "Playwright not available"}
        
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                context = browser.new_context(
                    user_agent="AI-SEO-Autopilot/1.0 (+https://example.com/bot)",
                    viewport={"width": 1280, "height": 800}
                )
                page = context.new_page()
                
                # Navigate and wait for network idle
                response = page.goto(url, timeout=self.timeout * 1000, wait_until="networkidle")
                status_code = response.status if response else 0
                
                # Wait for selector if provided
                if wait_for_selector:
                    try:
                        page.wait_for_selector(wait_for_selector, timeout=5000)
                    except Exception:
                        pass
                
                html = page.content()
                title = page.title()
                final_url = page.url
                
                browser.close()
                return {
                    "ok": True,
                    "rendered": True,
                    "html": html,
                    "status_code": status_code,
                    "final_url": final_url,
                    "page_title": title
                }
        except Exception as e:
            return {"ok": False, "rendered": False, "html": "", "error": str(e)}


class EventManager:
    """Simple event manager for crawl events."""
    
    def __init__(self):
        self._handlers = {}
        self._control_signals = {}
    
    def emit(self, job_id: str, event_type: str, message: str = "", 
             agent_name: str = "Crawler", severity: str = "info", 
             url: str = "", metadata: dict = None):
        """Emit an event."""
        event = {
            "job_id": job_id,
            "event_type": event_type,
            "message": message,
            "agent_name": agent_name,
            "severity": severity,
            "url": url,
            "metadata": metadata or {},
            "timestamp": datetime.utcnow().isoformat()
        }
        if job_id in self._handlers:
            for handler in self._handlers[job_id]:
                try:
                    handler(event)
                except Exception:
                    pass
    
    def check_control_signal(self, job_id: str) -> str:
        """Check for control signals (stop, pause, resume)."""
        return self._control_signals.get(job_id, "continue")
    
    def set_control_signal(self, job_id: str, signal: str):
        """Set a control signal."""
        self._control_signals[job_id] = signal
    
    def register_handler(self, job_id: str, handler):
        """Register an event handler."""
        if job_id not in self._handlers:
            self._handlers[job_id] = []
        self._handlers[job_id].append(handler)


# Singleton event manager
_event_manager = None

def get_event_manager():
    """Get the singleton event manager."""
    global _event_manager
    if _event_manager is None:
        _event_manager = EventManager()
    return _event_manager


class SpaRouteDiscovery:
    """Discover routes in Single Page Applications."""
    
    def __init__(self, root_url: str, html: str, renderer: PageRenderer):
        self.root_url = normalize_url(root_url)
        self.html = html
        self.renderer = renderer
    
    def discover(self, max_routes: int = 30) -> Set[str]:
        """Discover SPA routes."""
        routes = set()
        
        # Look for router configuration in JavaScript
        route_patterns = [
            r'path\s*:\s*["\']([^"\']+)["\']',
            r'route\s*:\s*["\']([^"\']+)["\']',
            r'to\s*:\s*["\']([^"\']+)["\']',
            r'href\s*:\s*["\']([^"\']+)["\']',
            r'url\s*:\s*["\']([^"\']+)["\']',
        ]
        
        # Extract routes from HTML and inline JavaScript
        for pattern in route_patterns:
            matches = re.findall(pattern, self.html, re.IGNORECASE)
            for match in matches:
                if match.startswith("/") and len(match) > 1 and not match.startswith("//"):
                    full_url = normalize_url(urljoin(self.root_url, match))
                    if is_internal(full_url, self.root_url):
                        routes.add(full_url)
        
        # Look for React Router routes
        react_router_pattern = r'<Route[^>]*path=["\']([^"\']+)["\']'
        matches = re.findall(react_router_pattern, self.html, re.IGNORECASE)
        for match in matches:
            if match.startswith("/"):
                full_url = normalize_url(urljoin(self.root_url, match))
                if is_internal(full_url, self.root_url):
                    routes.add(full_url)
        
        # Common SPA routes
        common_routes = ["/about", "/contact", "/pricing", "/features", "/blog", "/faq", "/services"]
        for route in common_routes:
            full_url = normalize_url(urljoin(self.root_url, route))
            if is_internal(full_url, self.root_url):
                routes.add(full_url)
        
        return routes


class SpaCrawler:
    """Specialized crawler for Single Page Applications."""
    
    def __init__(self, root_url: str, renderer: PageRenderer):
        self.root_url = normalize_url(root_url)
        self.renderer = renderer
        self.crawled = set()
    
    def crawl(self, max_pages: int = 50) -> List[Dict]:
        """Crawl SPA pages."""
        results = []
        queue = deque([(self.root_url, 0)])
        seen = {self.root_url}
        
        while queue and len(results) < max_pages:
            url, depth = queue.popleft()
            if url in self.crawled:
                continue
            
            result = self.renderer.render(url)
            if not result.get("ok") or not result.get("rendered"):
                continue
            
            self.crawled.add(url)
            html = result.get("html", "")
            
            # Extract links from rendered page
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a"):
                href = link.get("href")
                if href:
                    full_url = normalize_url(urljoin(url, href))
                    if is_internal(full_url, self.root_url) and full_url not in seen:
                        seen.add(full_url)
                        queue.append((full_url, depth + 1))
            
            results.append({
                "url": url,
                "html": html,
                "status_code": result.get("status_code", 200),
                "final_url": result.get("final_url", url),
                "depth": depth,
                "crawled_at": datetime.utcnow().isoformat()
            })
        
        return results


class CrawlStats:
    """Statistics tracker for crawling."""
    
    def __init__(self):
        self.pages_crawled = 0
        self.pages_discovered = 0
        self.pages_queued = 0
        self.pages_failed = 0
        self.pages_skipped = 0
        self.pages_blocked = 0
        self.ssl_warnings = 0
        self.errors: List[str] = []
        self.fetch_errors: List[Dict] = []
        self.source = "raw"
        self._stop = False
        self._pause = False
        self._lock = threading.Lock()
        self.raw_render_events = 0
        self.duplicate_crawl_attempts_prevented = 0
        self.duplicate_homepage_attempts_prevented = 0

    def to_result(self) -> Dict:
        """Convert stats to result dictionary."""
        return {
            "pages_crawled": self.pages_crawled,
            "pages_discovered": self.pages_discovered,
            "pages_queued": self.pages_queued,
            "pages_failed": self.pages_failed,
            "pages_skipped": self.pages_skipped,
            "pages_blocked": self.pages_blocked,
            "ssl_warnings": self.ssl_warnings,
            "errors": self.errors[:100],  # Limit to prevent overflow
            "fetch_errors": self.fetch_errors[:100],
            "raw_render_events": self.raw_render_events,
            "duplicate_crawl_attempts_prevented": self.duplicate_crawl_attempts_prevented,
            "duplicate_homepage_attempts_prevented": self.duplicate_homepage_attempts_prevented,
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
        self.session.timeout = 30
        self.stats = CrawlStats()
        self.results: List[Dict] = []
        self._seen: Set[str] = set()
        self._queued: Set[str] = set()
        self._failed: Set[str] = set()
        self._skipped: Set[str] = set()
        self._skip_reasons: Dict[str, str] = {}
        self._discovery_sources: Dict[str, str] = {}
        self._crawled: Set[str] = set()
        self.url_states: Dict[str, Dict] = {}
        self._queue_set: Set[str] = set()
        self.job_id: Optional[str] = None
        self.event_manager = get_event_manager()
        self.renderer = PageRenderer(use_playwright=Config.USE_PLAYWRIGHT, timeout=Config.PLAYWRIGHT_TIMEOUT)
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
        """Load robots.txt for the website."""
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
        """Check if URL is allowed by robots.txt."""
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
        """Classify a network/HTTP exception into structured error info."""
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
        """Run pre-crawl connectivity diagnostics."""
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
                             app_root_selector: str = "#app, #root, #__next, #__nuxt, [id*='app']",
                             ignore_https_errors: bool = False) -> Dict:
        """Render a page with a headless browser."""
        if not self.renderer.use_playwright:
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
            "ssl_warning": False,
        }

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                ctx = browser.new_context(
                    user_agent=self.USER_AGENT,
                    viewport={"width": 1280, "height": 800},
                    ignore_https_errors=ignore_https_errors,
                )
                page = ctx.new_page()

                console_errors: List[Dict] = []
                failed_requests: List[Dict] = []

                def _on_console(msg):
                    try:
                        if msg.type == "error":
                            console_errors.append({
                                "type": msg.type,
                                "text": msg.text,
                            })
                    except Exception:
                        pass

                page.on("console", _on_console)

                def _on_request_failed(req):
                    try:
                        failure = req.failure
                        if isinstance(failure, dict):
                            err_desc = failure.get("error_description", str(failure))
                        elif isinstance(failure, str):
                            err_desc = failure
                        elif failure is None:
                            err_desc = ""
                        else:
                            err_desc = str(failure)
                    except Exception:
                        err_desc = ""
                    failed_requests.append({
                        "url": req.url,
                        "method": req.method,
                        "failure": err_desc,
                    })

                page.on("requestfailed", _on_request_failed)

                try:
                    # Navigate to URL, wait for DOMContentLoaded
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

                    # Wait for application root element
                    try:
                        page.wait_for_selector(app_root_selector, timeout=5000)
                    except Exception:
                        pass

                    # Wait for network idle with timeout
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        page.wait_for_timeout(2000)

                    # Capture final URL
                    result["final_url"] = page.url
                    # Capture page title
                    try:
                        result["page_title"] = page.title()
                    except Exception:
                        pass
                    # Capture rendered HTML
                    result["html"] = page.content()
                    # Capture visible text
                    try:
                        result["visible_text"] = page.inner_text("body")
                    except Exception:
                        pass
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

    def _try_browser_fallback(self, url: str, error_info: Dict) -> Dict:
        """Attempt browser rendering fallback for SSL/connection errors."""
        if not self.renderer.use_playwright:
            return {}

        self._emit("browser_fallback_attempt",
                   f"Attempting browser rendering fallback for {url}",
                   severity="warning", url=url,
                   metadata={"error_type": error_info.get("error_type"),
                             "error_message": error_info.get("error_message")})

        rendered = self._render_with_browser(url, ignore_https_errors=True)
        if rendered.get("ok") and rendered.get("rendered") and rendered.get("html"):
            self.stats.raw_render_events += 1
            self._emit("browser_fallback_success",
                       f"Browser rendered {url} despite strict HTTP failure",
                       severity="success", url=url,
                       metadata={"status_code": rendered.get("status_code"),
                                 "page_title": rendered.get("page_title", ""),
                                 "ssl_warning": True})
            return {
                "status_code": rendered.get("status_code", 200),
                "html": rendered["html"],
                "final_url": rendered.get("final_url", url),
                "error_type": None,
                "error_message": None,
                "is_challenge": False,
                "challenge": None,
                "ssl_warning": True,
                "browser_rendered": True,
            }

        self._emit("browser_fallback_failed",
                   f"Browser fallback also failed for {url}: {rendered.get('error_message', 'unknown')}",
                   severity="error", url=url,
                   metadata={"error_type": rendered.get("error_type"),
                             "error_message": rendered.get("error_message")})
        return {}

    def _fetch(self, url: str) -> Dict:
        """Fetch a URL with retry logic."""
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
                    # Try Playwright fallback for JS verification pages
                    if self.renderer.use_playwright:
                        self.stats.raw_render_events += 1
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
                
                # Try browser fallback for SSL errors
                if error_info.get("error_type") == "SSLError" and self.renderer.use_playwright:
                    fallback = self._try_browser_fallback(url, error_info)
                    if fallback:
                        return fallback
                
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

        # All retries exhausted
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
        """Check if content is HTML."""
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
        """Extract links from HTML."""
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
        """Extract URLs from structured data."""
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
        """Walk JSON object to find URLs."""
        found: Set[str] = set()
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("url", "@id", "sameAs", "image") and isinstance(v, str):
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
        """Extract canonical URL."""
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
        """Render page and extract links."""
        if not self.renderer.use_playwright:
            return set()
        try:
            result = self.renderer.render(url)
            if not result.get("ok") or not result.get("rendered"):
                return set()
            return self._extract_links(result.get("html", ""), url)
        except Exception:
            return set()

    def _discover_urls_from_sitemap(self, root_url: str) -> Set[str]:
        """Discover URLs from sitemap."""
        found: Set[str] = set()
        
        sitemap_candidates = [
            "/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml",
            "/wp-sitemap.xml", "/sitemap-index.xml",
        ]
        
        # Try to get sitemap from robots.txt
        try:
            robots_url = urljoin(root_url, "/robots.txt")
            r = self.session.get(robots_url, timeout=10)
            if r.status_code == 200:
                for line in r.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sitemap_url = line.split(":", 1)[1].strip()
                        if sitemap_url:
                            sitemap_candidates.insert(0, sitemap_url)
        except Exception:
            pass
        
        for path in sitemap_candidates:
            url = urljoin(root_url, path)
            try:
                r = self.session.get(url, timeout=10)
                if r.status_code == 200:
                    xml = r.text
                    # Parse sitemap
                    soup = BeautifulSoup(xml, "xml")
                    for loc in soup.find_all("loc"):
                        if loc.text:
                            found.add(normalize_url(loc.text))
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
        """Check if URL points to an asset file."""
        path = urlparse(url).path.lower()
        if any(path.endswith(ext) for ext in self.ASSET_EXTENSIONS):
            return True
        if "/assets/" in path or "/static/" in path or "/dist/" in path or "/build/" in path:
            if any(path.endswith(ext) for ext in self.ASSET_EXTENSIONS):
                return True
        return False

    def claim_url_for_crawl(self, url: str, source: str = "unknown", depth: int = 0) -> bool:
        """Atomically claim a URL for crawling."""
        norm = normalize_url(url)
        with self.stats._lock:
            state = self.url_states.get(norm)
            if state is None:
                self.url_states[norm] = {
                    "status": "crawling",
                "attempts": 1,
                    "discovered_from": source,
                    "crawl_started": True,
                    "crawl_completed": False,
                    "depth": depth,
                }
                return True
            if state["status"] in ("crawling", "crawled"):
                self.stats.duplicate_crawl_attempts_prevented += 1
                if norm == self.root_url:
                    self.stats.duplicate_homepage_attempts_prevented += 1
                return False
            if state["status"] == "queued":
                state["status"] = "crawling"
                state["attempts"] = state.get("attempts", 0) + 1
                state["crawl_started"] = True
                return True
        return True

    def _mark_crawled(self, normalized_url: str):
        """Mark a URL as fully crawled."""
        state = self.url_states.get(normalized_url)
        if state is not None:
            state["status"] = "crawled"
            state["crawl_started"] = True
            state["crawl_completed"] = True

    def _mark_failed(self, url: str):
        """Mark a URL as failed/blocked/skipped and prevent re-crawling."""
        norm = normalize_url(url)
        self._failed.add(norm)
        self._crawled.add(norm)
        self.stats.duplicate_crawl_attempts_prevented += 0
        state = self.url_states.get(norm)
        if state is not None:
            state["status"] = "failed"
            state["crawl_started"] = True
            state["crawl_completed"] = True

    def _add_url(self, url: str, source: str, depth: int = 0) -> bool:
        """Add a URL to the crawl queue."""
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
        if norm not in self.url_states:
            self.url_states[norm] = {
                "status": "queued",
                "attempts": 0,
                "discovered_from": source,
                "crawl_started": False,
                "crawl_completed": False,
                "depth": depth,
            }
        self.stats.pages_discovered += 1
        self.stats.pages_queued += 1
        self._discovery_sources[norm] = source
        self._emit("url_discovered", f"Discovered: {norm}",
                   url=norm, metadata={"source": source, "depth": depth})
        self._emit("page_queued", f"Queued: {norm}",
                   url=norm, metadata={"source": source, "depth": depth})
        return True

    def crawl(self, on_progress=None, job_id: str = None) -> List[Dict]:
        """Crawl the website starting from the root URL."""
        if job_id:
            self.job_id = job_id
        
        # Load robots.txt
        self._load_robots()

        self._emit("crawl_started", f"Starting crawl of {self.root_url}",
                   metadata={"max_pages": self.max_pages, "max_depth": self.max_depth})

        # Connectivity diagnostics
        self._diagnose_connectivity(self.root_url)

        # Pre-discover from sitemap
        sitemap_urls = self._discover_urls_from_sitemap(self.root_url)
        for u in sitemap_urls:
            self._add_url(u, "sitemap", depth=0)

        # Seed queue with homepage
        self._add_url(self.root_url, "homepage", depth=0)

        queue: deque = deque([(self.root_url, 0)])
        self._queue_set = {self.root_url}
        architecture_detected = False

        while queue and self.stats.pages_crawled < self.max_pages:
            if not self._check_control():
                break

            url, depth = queue.popleft()
            self._queue_set.discard(url)
            norm_url = normalize_url(url)

            if not self.claim_url_for_crawl(url, self._discovery_sources.get(norm_url, "unknown"), depth):
                continue
            if not self._allowed(url):
                self._mark_failed(url)
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
            diagnostics = fetch_result.get("diagnostics")
            ssl_warning = fetch_result.get("ssl_warning", False)
            browser_rendered = fetch_result.get("browser_rendered", False)
            # norm is the original normalized URL from the queue — it must NEVER
            # be overwritten by the browser's final URL, because a SPA route
            # may cause the browser to navigate back to the homepage, which
            # would make norm == homepage_url and break deduplication.

            # Track SSL warnings
            if ssl_warning:
                self.stats.ssl_warnings += 1
                self._emit("ssl_warning",
                           f"SSL warning for {norm_url}: {error_message or 'TLS certificate issue'}",
                           severity="warning", url=norm_url,
                           metadata={"error_type": error_type,
                                     "error_message": error_message,
                                     "diagnostics": diagnostics})

            # Handle blocked pages (JS verification)
            if url in self._blocked:
                self.stats.pages_blocked += 1
                self._mark_failed(url)
                self._emit("page_crawl_blocked",
                           f"Blocked {norm_url} (JS verification): {error_message}",
                           severity="warning", url=norm_url,
                           metadata={"status_code": status,
                                     "fetch_time": fetch_time,
                                     "pages_crawled": self.stats.pages_crawled,
                                     "pages_blocked": self.stats.pages_blocked,
                                     "blocked": True,
                                     "block_reason": "js_verification",
                                     "block_details": self._blocked.get(url, {})})
                self.results.append({
                    "url": norm_url,
                    "status_code": status,
                    "html": html,
                    "depth": depth,
                    "rendered": False,
                    "fetched_at": datetime.utcnow().isoformat(),
                    "fetch_time": fetch_time,
                    "discovery_source": self._discovery_sources.get(norm_url, "homepage"),
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
                arch = self._detect_architecture(html, url=norm_url)
                self.architecture = arch
                self.stats.source = "rendered" if arch.get("is_spa") else "raw"
                architecture_detected = True
                self._emit("architecture_detected",
                           f"Detected architecture: {arch.get('architecture_type')}",
                           url=norm_url,
                           metadata={"architecture": arch})

                # If SPA, discover additional routes.
                # The homepage is rendered ONCE here for route discovery.
                # Individual SPA routes are navigated to directly in the
                # crawl loop below — never via the homepage renderer.
                if arch.get("is_spa") and norm_url == self.root_url:
                    self.spa_discovery = SpaRouteDiscovery(norm_url, html, self.renderer)
                    spa_routes = self.spa_discovery.discover(max_routes=30)
                    for route_url in spa_routes:
                        if normalize_url(route_url) != norm_url:
                            self._add_url(route_url, "spa_discovery", depth=1)

            # Handle HTTP errors
            if status == 0 or status >= 400:
                self.stats.pages_failed += 1
                self._mark_failed(url)
                fetch_error = {
                    "url": norm_url,
                    "status_code": status,
                    "error_type": error_type or (f"HTTP{status}" if status != 0 else "HTTPZero"),
                    "error_message": error_message or f"HTTP {status}",
                    "fetch_time": fetch_time,
                    "diagnostics": diagnostics,
                }
                self.stats.fetch_errors.append(fetch_error)
                self._emit("page_crawl_failed",
                           f"Failed to fetch {norm_url}: {error_message or f'HTTP {status}'}",
                           severity="error", url=norm_url,
                           metadata={
                               "status_code": status,
                               "error_type": error_type,
                               "error_message": error_message,
                               "fetch_time": fetch_time,
                               "diagnostics": diagnostics,
                               "retries_exhausted": fetch_result.get("retries_exhausted", False),
                           })
                self.stats.errors.append(
                    f"{norm_url}: {error_type or f'HTTP {status}'} - "
                    f"{error_message or 'No HTTP response received'}"
                )
                if self.delay:
                    time.sleep(self.delay)
                continue

            # Skip non-HTML content
            if not self._is_html_content(norm_url, html, status):
                self.stats.pages_skipped += 1
                self._skipped.add(norm_url)
                self._skip_reasons[norm_url] = "non_html_asset"
                self._mark_failed(url)
                self._emit("page_crawl_skipped",
                           f"Skipped non-HTML resource: {norm_url}",
                           severity="warning", url=norm_url,
                           metadata={"status_code": status, "fetch_time": fetch_time, "reason": "non_html_asset"})
                if self.delay:
                    time.sleep(self.delay)
                continue

            # Browser rendering for SPA or small pages.
            # The browser navigates DIRECTLY to the route URL — it never
            # re-renders the homepage as a prerequisite.
            # NOTE: browser_final_url is tracked separately and must NOT
            # overwrite norm_url or final_url used for crawl tracking.
            # Skip if _fetch already rendered via browser fallback.
            if not browser_rendered:
                if (getattr(self.renderer, 'use_playwright', False)
                        and (self.architecture.get("is_spa") or len(html) < 1200)):
                    rendered = self._render_with_browser(url)
                    if rendered.get("ok") and rendered.get("html"):
                        browser_rendered = True
                        self.stats.raw_render_events += 1
                        html = rendered["html"]
                        browser_final_url = rendered.get("final_url", final_url)
                        page_title = rendered.get("page_title", "")
                        self._emit("page_rendered",
                                   f"Rendered {norm_url} with headless browser in {fetch_time}s",
                                   severity="info", url=norm_url,
                                   metadata={
                                       "status_code": rendered.get("status_code"),
                                       "page_title": page_title,
                                       "console_errors": len(rendered.get("console_errors", [])),
                                       "failed_requests": len(rendered.get("failed_requests", [])),
                                       "browser_final_url": browser_final_url,
                                   })

            # Extract links from HTML (use norm_url as base, not the browser
            # final URL, so SPA fallback doesn't corrupt link extraction)
            raw_links = self._extract_links(html, norm_url)
            for link in raw_links:
                self._add_url(link, "page_link", depth=depth + 1)

            # Extract links from rendered DOM (only for shallow pages)
            if depth <= 0 and getattr(self.renderer, 'use_playwright', False) and not browser_rendered:
                rendered_links = self._render_and_extract(norm_url)
                for link in rendered_links:
                    self._add_url(link, "rendered_dom", depth=depth + 1)

            # Extract structured data URLs
            sd_urls = self._extract_structured_data_urls(html, norm_url)
            for u in sd_urls:
                self._add_url(u, "structured_data", depth=depth + 1)

            # Extract canonical
            canon_urls = self._extract_canonical(html, norm_url)
            for u in canon_urls:
                self._add_url(u, "canonical", depth=depth + 1)

            # Sync newly discovered queued URLs into the crawl deque.
            # Only URLs in _queued (added by _add_url above) that are not
            # already in the deque or already crawled get added.
            # This replaces the old buggy "re-queue everything in _seen"
            # logic that re-queued the homepage on every iteration.
            if self._queued:
                deque_urls = set(q[0] for q in queue)
                for queued_url in list(self._queued):
                    if queued_url not in deque_urls and queued_url not in self._crawled:
                        queue.append((queued_url, depth + 1))
                        self._queue_set.add(queued_url)
                        self._queued.discard(queued_url)

            page = {
                "url": norm_url,
                "status_code": status,
                "html": html,
                "depth": depth,
                "rendered": browser_rendered,
                "fetched_at": datetime.utcnow().isoformat(),
                "fetch_time": fetch_time,
                "discovery_source": self._discovery_sources.get(norm_url, "homepage"),
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
            self._crawled.add(norm_url)
            self._mark_crawled(norm_url)

            self._emit("page_crawl_completed",
                       f"Crawled {norm_url} ({status}) in {fetch_time}s",
                       severity="success", url=norm_url,
                       metadata={"status_code": status, "fetch_time": fetch_time,
                                 "pages_crawled": self.stats.pages_crawled,
                                 "source": self._discovery_sources.get(norm_url, "homepage")})

            total_known = max(1, self.stats.pages_discovered)
            progress = min(90, int(5 + 85 * self.stats.pages_crawled / total_known))
            if on_progress:
                try:
                    on_progress(progress, f"Crawled {self.stats.pages_crawled} of {total_known} discovered pages")
                except Exception as e:
                    self._emit("progress_callback_error",
                               f"Progress callback failed: {type(e).__name__}: {e}",
                               severity="warning", url=norm_url)

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
                           "diagnostics": self.get_crawl_diagnostics(),
                       })

        # Emit authoritative crawl result
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
        result = self.stats.to_result()
        result["diagnostics"] = self.get_crawl_diagnostics()
        return result

    def get_crawl_diagnostics(self) -> Dict:
        """Return final diagnostic report with authoritative counts.

        Distinguishes raw_render_events (every Playwright navigation)
        from unique_pages_crawled (pages successfully analyzed once).
        """
        unique_crawled_urls = {
            u for u, s in self.url_states.items() if s.get("status") == "crawled"
        }
        unique_queued_urls = {
            u for u, s in self.url_states.items() if s.get("status") == "queued"
        }
        unique_discovered = len(self.url_states)
        return {
            "unique_discovered": unique_discovered,
            "unique_queued": len(unique_queued_urls),
            "unique_crawled": len(unique_crawled_urls),
            "duplicate_crawl_attempts_prevented": self.stats.duplicate_crawl_attempts_prevented,
            "duplicate_homepage_attempts_prevented": self.stats.duplicate_homepage_attempts_prevented,
            "raw_render_events": self.stats.raw_render_events,
        }

    def _detect_architecture(self, html: str, url: str) -> Dict:
        """Detect website architecture (SPA vs static)."""
        arch = {
            "architecture_type": "static_html",
            "rendering_mode": "raw",
            "deployment_strategy": "direct_html",
            "is_spa": False,
            "detected_spa_framework": "",
            "spa_indicators": [],
            "build_system": "unknown",
            "confidence": 0.0
        }

        html_lower = html.lower()
        confidence = 0.0

        # SPA Framework detection
        spa_frameworks = {
            "react": ["react", "react-dom", "__react", "_react", "reactroot", "reactapp", "reactjs"],
            "vue": ["vue", "vuejs", "vue-app", "vue_", "v-app", "v-html", "v-text"],
            "angular": ["ng-app", "ng-controller", "angular", "ng-", "ngversion"],
            "next": ["__next", "next/", "nextjs", "next.js"],
            "nuxt": ["__nuxt", "nuxt", "nuxtjs"],
            "svelte": ["svelte", "sveltejs", "app.svelte"],
            "gatsby": ["gatsby", "gatsbyjs", "___gatsby"],
            "ember": ["ember", "emberjs"],
            "backbone": ["backbone"],
            "jquery": ["jquery"],
            "alpine": ["alpine", "x-data", "x-init"],
            "htmx": ["htmx", "hx-"],
            "livewire": ["livewire", "wire:"],
            "alpinejs": ["alpinejs", "x-data"],
        }

        for framework, keywords in spa_frameworks.items():
            for keyword in keywords:
                if keyword in html_lower:
                    arch["detected_spa_framework"] = framework
                    arch["spa_indicators"].append(keyword)
                    confidence += 0.15
                    break
            if arch["detected_spa_framework"]:
                break

        # Build system detection
        build_indicators = {
            "webpack": ["webpack", "chunk-", "vendors~", "main."],
            "vite": ["vite", "vitejs", "vite_"],
            "rollup": ["rollup"],
            "esbuild": ["esbuild"],
            "parcel": ["parcel"],
            "babel": ["babel"],
            "next": ["next/", "_next/"],
            "nuxt": ["_nuxt/"],
            "gatsby": ["gatsby"],
            "angular-cli": ["angular-cli", "ng build"],
        }

        for build_system, indicators in build_indicators.items():
            for indicator in indicators:
                if indicator in html_lower:
                    arch["build_system"] = build_system
                    break
            if arch["build_system"] != "unknown":
                break

        # Check for SPA characteristics
        spa_patterns = [
            ("container", "#app", 0.1),
            ("container", "#root", 0.1),
            ("container", "#__next", 0.15),
            ("container", "#__nuxt", 0.15),
            ("container", "[data-reactroot]", 0.15),
            ("container", "[data-v-app]", 0.1),
            ("container", "ng-view", 0.1),
            ("container", "ui-view", 0.1),
            ("router", "react-router", 0.2),
            ("router", "vue-router", 0.2),
            ("router", "angular-router", 0.2),
            ("state", "__NEXT_DATA__", 0.2),
            ("state", "__NUXT__", 0.2),
            ("state", "__INITIAL_STATE__", 0.15),
            ("state", "__PRELOADED_STATE__", 0.15),
            ("state", "window.APP_STATE", 0.15),
            ("js_bundle", "chunk", 0.05),
            ("js_bundle", "bundle", 0.05),
            ("js_bundle", "main.js", 0.05),
            ("empty_body", "html shell", 0.2),
        ]

        for pattern_type, pattern, weight in spa_patterns:
            if pattern in html_lower:
                arch["spa_indicators"].append(f"{pattern_type}:{pattern}")
                confidence += weight

        # Check if body is mostly empty
        body_match = re.search(r"<body[^>]*>(.*?)</body>", html, re.IGNORECASE | re.DOTALL)
        if body_match:
            body_content = body_match.group(1).strip()
            if len(body_content) < 1000 and not re.search(r"<h[1-6]", body_content, re.IGNORECASE):
                confidence += 0.1
                arch["spa_indicators"].append("empty_body")

        # Determine architecture type
        arch["confidence"] = min(confidence, 1.0)
        if confidence >= 0.3:
            arch["is_spa"] = True
            arch["architecture_type"] = "spa"
            arch["rendering_mode"] = "client"
            arch["deployment_strategy"] = "client_side_rendering"
        elif arch["detected_spa_framework"]:
            arch["is_spa"] = True
            arch["architecture_type"] = "spa"
            arch["rendering_mode"] = "client"
        else:
            arch["is_spa"] = False
            arch["architecture_type"] = "static_html"
            arch["rendering_mode"] = "raw"

        return arch
