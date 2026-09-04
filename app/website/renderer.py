"""Rendered page analysis.

Provides a lightweight rendered-page fetcher that doesn't depend on heavy
browser automation when not available. Falls back to raw HTML when no
renderer is installed. Supports both single and batch rendering with
configurable options.
"""
from __future__ import annotations
import time
import logging
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlparse

# Setup logging
logger = logging.getLogger(__name__)


# ============================================================================
# AVAILABILITY CHECKS
# ============================================================================

def has_playwright() -> bool:
    """Check if Playwright is installed."""
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False
    except Exception:
        return False


def has_requests() -> bool:
    """Check if requests is installed."""
    try:
        import requests  # noqa: F401
        return True
    except ImportError:
        return False
    except Exception:
        return False


def has_beautifulsoup() -> bool:
    """Check if BeautifulSoup is installed."""
    try:
        import bs4  # noqa: F401
        return True
    except ImportError:
        return False
    except Exception:
        return False


# ============================================================================
# HTTP FETCHER (Fallback)
# ============================================================================

class HttpFetcher:
    """Simple HTTP fetcher for raw HTML."""
    
    def __init__(self, timeout: int = 30, user_agent: str = "AI-SEO-Autopilot/1.0"):
        self.timeout = timeout
        self.user_agent = user_agent
        self._session = None
    
    def _get_session(self):
        """Get or create requests session."""
        if not has_requests():
            raise RuntimeError("requests library is not installed")
        
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": self.user_agent})
            self._session.timeout = self.timeout
        return self._session
    
    def fetch(self, url: str, allow_redirects: bool = True) -> Dict[str, Any]:
        """Fetch a URL and return the response."""
        try:
            session = self._get_session()
            response = session.get(url, allow_redirects=allow_redirects)
            
            return {
                "ok": 200 <= response.status_code < 400,
                "status_code": response.status_code,
                "html": response.text or "",
                "final_url": response.url,
                "headers": dict(response.headers),
                "error": None
            }
        except Exception as e:
            return {
                "ok": False,
                "status_code": 0,
                "html": "",
                "final_url": url,
                "headers": {},
                "error": str(e)
            }
    
    def fetch_batch(self, urls: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch multiple URLs."""
        results = {}
        for url in urls:
            results[url] = self.fetch(url)
        return results


# ============================================================================
# PAGE RENDERER
# ============================================================================

class PageRenderer:
    """Try Playwright if available, otherwise fall back to raw HTTP."""

    def __init__(self, timeout: int = 20, user_agent: str = "AI-SEO-Autopilot/1.0",
                 headless: bool = True, viewport_width: int = 1280,
                 viewport_height: int = 800, use_playwright: bool = None):
        """
        Initialize the page renderer.
        
        Args:
            timeout: Timeout in seconds for page loading
            user_agent: User agent string
            headless: Whether to run browser in headless mode
            viewport_width: Viewport width in pixels
            viewport_height: Viewport height in pixels
            use_playwright: Whether to use Playwright. If None, auto-detect.
        """
        self.timeout = timeout
        self.user_agent = user_agent
        self.headless = headless
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        if use_playwright is None:
            self.use_playwright = has_playwright()
        else:
            self.use_playwright = use_playwright
        self.http_fetcher = HttpFetcher(timeout=timeout, user_agent=user_agent)
        
        logger.info(f"PageRenderer initialized with playwright={self.use_playwright}")

    def render(self, url: str, wait_for_selector: str = "",
               wait_timeout: int = 5000, wait_until: str = "networkidle",
               capture_screenshot: bool = False, capture_console: bool = False) -> Dict[str, Any]:
        """
        Render a page with Playwright or fall back to HTTP.
        
        Args:
            url: URL to render.
            wait_for_selector: CSS selector to wait for before capturing HTML.
            wait_timeout: Max wait time in ms for selector/network idle.
            wait_until: Playwright wait condition ('networkidle', 'domcontentloaded', 'load').
            capture_screenshot: Whether to capture a screenshot.
            capture_console: Whether to capture console logs.
            
        Returns:
            Dictionary with rendering results:
                - ok: bool
                - rendered: bool
                - html: str
                - final_url: str
                - status_code: int
                - screenshot: bytes (optional)
                - console_logs: list (optional)
                - error: str (optional)
        """
        if not self.use_playwright:
            # Fall back to HTTP
            logger.debug(f"Falling back to HTTP for {url}")
            result = self.http_fetcher.fetch(url)
            return {
                "ok": result.get("ok", False),
                "rendered": False,
                "html": result.get("html", ""),
                "final_url": result.get("final_url", url),
                "status_code": result.get("status_code", 0),
                "error": result.get("error"),
                "reason": "Playwright not installed, using HTTP fallback"
            }
        
        try:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                # Launch browser
                browser = p.chromium.launch(
                    headless=self.headless,
                    args=["--no-sandbox", "--disable-dev-shm-usage"]
                )
                
                # Create context
                ctx = browser.new_context(
                    user_agent=self.user_agent,
                    viewport={"width": self.viewport_width, "height": self.viewport_height},
                    java_script_enabled=True,
                    ignore_https_errors=True
                )
                
                page = ctx.new_page()
                
                # Collect console logs if requested
                console_logs = []
                if capture_console:
                    def on_console(msg):
                        console_logs.append({
                            "type": msg.type,
                            "text": msg.text,
                            "location": msg.location
                        })
                    page.on("console", on_console)
                
                # Navigate to URL
                try:
                    response = page.goto(
                        url,
                        timeout=self.timeout * 1000,
                        wait_until=wait_until if wait_until != "networkidle" else "domcontentloaded"
                    )
                    status_code = response.status if response else 0
                    final_url = page.url
                except Exception as e:
                    browser.close()
                    return {
                        "ok": False,
                        "rendered": False,
                        "html": "",
                        "final_url": url,
                        "status_code": 0,
                        "error": str(e),
                        "reason": "Navigation failed"
                    }
                
                # Wait for specific selector if provided
                if wait_for_selector:
                    try:
                        page.wait_for_selector(wait_for_selector, timeout=wait_timeout)
                    except Exception as e:
                        logger.debug(f"Selector '{wait_for_selector}' not found: {e}")
                
                # Wait for network idle if requested
                if wait_until == "networkidle":
                    try:
                        page.wait_for_load_state("networkidle", timeout=min(wait_timeout, 10000))
                    except Exception:
                        page.wait_for_timeout(2000)
                
                # Get page content
                html = page.content()
                
                # Capture screenshot if requested
                screenshot = None
                if capture_screenshot:
                    try:
                        screenshot = page.screenshot(full_page=True)
                    except Exception as e:
                        logger.warning(f"Failed to capture screenshot: {e}")
                
                browser.close()
                
                result = {
                    "ok": True,
                    "rendered": True,
                    "html": html,
                    "final_url": final_url,
                    "status_code": status_code,
                    "console_logs": console_logs if capture_console else None,
                    "screenshot": screenshot if capture_screenshot else None,
                }
                
                if console_logs:
                    errors = [log for log in console_logs if log.get("type") == "error"]
                    if errors:
                        result["console_errors"] = errors
                
                return result
                
        except ImportError as e:
            logger.warning(f"Playwright import error: {e}")
            self.use_playwright = False
            return self.render(url, wait_for_selector, wait_timeout, wait_until)
            
        except Exception as e:
            logger.error(f"Playwright rendering failed for {url}: {e}")
            return {
                "ok": False,
                "rendered": False,
                "html": "",
                "final_url": url,
                "status_code": 0,
                "error": str(e),
                "reason": "Playwright rendering failed"
            }

    def render_batch(self, urls: List[str], wait_for_selector: str = "",
                     wait_timeout: int = 3000, wait_until: str = "networkidle",
                     max_concurrent: int = 5) -> Dict[str, Dict[str, Any]]:
        """
        Render multiple URLs reusing a single browser instance.
        
        Args:
            urls: List of URLs to render.
            wait_for_selector: CSS selector to wait for.
            wait_timeout: Wait timeout in ms.
            wait_until: Wait condition.
            max_concurrent: Maximum concurrent pages (limited by browser).
            
        Returns:
            Dictionary mapping URL to render result.
        """
        results = {}
        
        if not urls:
            return results
        
        if not self.use_playwright:
            # Fall back to HTTP for all URLs
            logger.debug(f"Falling back to HTTP batch for {len(urls)} URLs")
            http_results = self.http_fetcher.fetch_batch(urls)
            for url, result in http_results.items():
                results[url] = {
                    "ok": result.get("ok", False),
                    "rendered": False,
                    "html": result.get("html", ""),
                    "final_url": result.get("final_url", url),
                    "status_code": result.get("status_code", 0),
                    "error": result.get("error"),
                    "reason": "Playwright not installed, using HTTP fallback"
                }
            return results
        
        try:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=self.headless,
                    args=["--no-sandbox", "--disable-dev-shm-usage"]
                )
                
                ctx = browser.new_context(
                    user_agent=self.user_agent,
                    viewport={"width": self.viewport_width, "height": self.viewport_height},
                    java_script_enabled=True,
                    ignore_https_errors=True
                )
                
                # Process URLs in batches
                for i in range(0, len(urls), max_concurrent):
                    batch = urls[i:i + max_concurrent]
                    pages = []
                    
                    for url in batch:
                        page = ctx.new_page()
                        pages.append((url, page))
                    
                    for url, page in pages:
                        try:
                            response = page.goto(
                                url,
                                timeout=self.timeout * 1000,
                                wait_until="domcontentloaded"
                            )
                            status_code = response.status if response else 0
                            final_url = page.url
                            
                            if wait_for_selector:
                                try:
                                    page.wait_for_selector(wait_for_selector, timeout=wait_timeout)
                                except Exception:
                                    pass
                            
                            try:
                                page.wait_for_load_state("networkidle", timeout=min(wait_timeout, 10000))
                            except Exception:
                                page.wait_for_timeout(2000)
                            
                            html = page.content()
                            
                            results[url] = {
                                "ok": True,
                                "rendered": True,
                                "html": html,
                                "final_url": final_url,
                                "status_code": status_code
                            }
                            
                        except Exception as e:
                            results[url] = {
                                "ok": False,
                                "rendered": False,
                                "html": "",
                                "final_url": url,
                                "status_code": 0,
                                "error": str(e)
                            }
                        
                        # Close page to free resources
                        try:
                            page.close()
                        except Exception:
                            pass
                
                browser.close()
                
        except ImportError as e:
            logger.warning(f"Playwright import error: {e}")
            self.use_playwright = False
            return self.render_batch(urls, wait_for_selector, wait_timeout, wait_until, max_concurrent)
            
        except Exception as e:
            logger.error(f"Batch rendering failed: {e}")
            # Fill in any missing results
            for url in urls:
                if url not in results:
                    results[url] = {
                        "ok": False,
                        "rendered": False,
                        "html": "",
                        "final_url": url,
                        "status_code": 0,
                        "error": str(e)
                    }
        
        return results

    def render_with_retry(self, url: str, max_retries: int = 3, retry_delay: float = 1.0,
                          **kwargs) -> Dict[str, Any]:
        """
        Render a page with retry logic.
        
        Args:
            url: URL to render.
            max_retries: Maximum number of retry attempts.
            retry_delay: Delay between retries in seconds.
            **kwargs: Additional arguments passed to render().
            
        Returns:
            Dictionary with rendering results.
        """
        last_error = None
        
        for attempt in range(max_retries):
            result = self.render(url, **kwargs)
            
            if result.get("ok"):
                return result
            
            last_error = result.get("error") or result.get("reason")
            
            if attempt < max_retries - 1:
                logger.debug(f"Retry {attempt + 1}/{max_retries} for {url}: {last_error}")
                time.sleep(retry_delay * (attempt + 1))
        
        return {
            "ok": False,
            "rendered": False,
            "html": "",
            "final_url": url,
            "status_code": 0,
            "error": last_error or "Max retries exceeded",
            "reason": "Max retries exceeded"
        }


# ============================================================================
# RENDERED PAGE ANALYZER
# ============================================================================

class RenderedPageAnalyzer:
    """Analyzes rendered pages for SEO metrics."""
    
    def __init__(self, renderer: Optional[PageRenderer] = None):
        self.renderer = renderer or PageRenderer()
    
    def analyze(self, url: str, wait_for_selector: str = "",
                wait_timeout: int = 5000) -> Dict[str, Any]:
        """
        Render and analyze a page.
        
        Args:
            url: URL to analyze.
            wait_for_selector: Selector to wait for.
            wait_timeout: Wait timeout in ms.
            
        Returns:
            Dictionary with rendering and analysis results.
        """
        # Render the page
        render_result = self.renderer.render(
            url,
            wait_for_selector=wait_for_selector,
            wait_timeout=wait_timeout
        )
        
        if not render_result.get("ok"):
            return render_result
        
        # Analyze the rendered HTML
        html = render_result.get("html", "")
        if not html:
            return {
                **render_result,
                "analysis": {"error": "No HTML content"}
            }
        
        try:
            analysis = self._analyze_html(html, url)
            return {
                **render_result,
                "analysis": analysis
            }
        except Exception as e:
            return {
                **render_result,
                "analysis": {"error": str(e)}
            }
    
    def _analyze_html(self, html: str, url: str) -> Dict[str, Any]:
        """Analyze HTML for SEO metrics."""
        if not has_beautifulsoup():
            return {"error": "BeautifulSoup not installed"}
        
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(html, "html.parser")
        
        # Extract basic metadata
        title_tag = soup.find("title")
        title = title_tag.string.strip() if title_tag and title_tag.string else ""
        
        meta_desc = soup.find("meta", attrs={"name": "description"})
        description = meta_desc.get("content", "") if meta_desc else ""
        
        # Headings
        headings = {}
        for level in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            headings[level] = [tag.text.strip() for tag in soup.find_all(level)]
        
        # Links
        internal_links = []
        external_links = []
        for a in soup.find_all("a"):
            href = a.get("href", "")
            if href and not href.startswith("#") and not href.startswith("javascript:"):
                if href.startswith(("http://", "https://")):
                    if url and href.startswith(url):
                        internal_links.append(href)
                    else:
                        external_links.append(href)
                else:
                    internal_links.append(href)
        
        # Images
        images = []
        for img in soup.find_all("img"):
            src = img.get("src", "")
            alt = img.get("alt", "")
            images.append({"src": src, "alt": alt})
        
        # Word count
        for script in soup(["script", "style"]):
            script.decompose()
        text = soup.get_text(" ", strip=True)
        word_count = len(text.split())
        
        # Open Graph
        og = {}
        for meta in soup.find_all("meta"):
            prop = meta.get("property", "")
            if prop.startswith("og:"):
                og[prop] = meta.get("content", "")
        
        # Canonical
        canonical = ""
        link = soup.find("link", rel="canonical")
        if link and link.get("href"):
            canonical = link.get("href")
        
        return {
            "title": title,
            "meta_description": description,
            "headings": headings,
            "internal_links": len(internal_links),
            "external_links": len(external_links),
            "total_links": len(internal_links) + len(external_links),
            "images": len(images),
            "images_with_alt": sum(1 for img in images if img.get("alt")),
            "word_count": word_count,
            "open_graph": og,
            "canonical": canonical,
            "has_json_ld": bool(soup.find("script", type="application/ld+json")),
        }


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_page_renderer(timeout: int = 20) -> PageRenderer:
    """Get a page renderer instance."""
    return PageRenderer(timeout=timeout)


def render_page(url: str, **kwargs) -> Dict[str, Any]:
    """Convenience function to render a single page."""
    renderer = PageRenderer()
    return renderer.render(url, **kwargs)


def render_pages(urls: List[str], **kwargs) -> Dict[str, Dict[str, Any]]:
    """Convenience function to render multiple pages."""
    renderer = PageRenderer()
    return renderer.render_batch(urls, **kwargs)

