"""SPA-aware crawler and route discovery.

Discovers routes in JavaScript-rendered applications, renders pages
with a headless browser when available, and extracts SEO data from
the rendered DOM.
"""
from __future__ import annotations
import re
import json
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from .spa_detector import detect_architecture, detect_from_js_bundle, extract_manifest_links
from .renderer import PageRenderer
from .website_analyzer import analyze_html, calculate_seo_score


class SpaRouteDiscovery:
    """Discover routes in SPAs using multiple strategies."""

    def __init__(self, base_url: str, html: str, renderer: Optional[PageRenderer] = None):
        self.base_url = base_url.rstrip("/")
        self.raw_html = html or ""
        self.renderer = renderer or PageRenderer()
        self.routes: List[str] = []
        self.rendered_html: str = ""
        self.architecture: Dict = {}

    def discover(self, max_routes: int = 50) -> List[str]:
        """Discover SPA routes using all available strategies."""
        arch = detect_architecture(self.raw_html, url=self.base_url)
        self.architecture = arch

        if not arch.get("is_spa"):
            return []

        routes: List[str] = []

        # Strategy 1: Extract from rendered DOM links
        rendered = self._render_home()
        if rendered:
            self.rendered_html = rendered
            routes.extend(self._extract_links_from_html(rendered))

        # Strategy 2: Extract from raw HTML script tags / router configs
        routes.extend(self._extract_from_scripts(self.raw_html))

        # Strategy 3: Extract from sitemap.xml
        routes.extend(self._fetch_sitemap_routes())

        # Strategy 4: Extract from robots.txt
        routes.extend(self._fetch_robots_routes())

        # Strategy 5: Common SPA routes heuristic
        routes.extend(self._common_spa_routes())

        # Deduplicate and normalize
        seen = set()
        unique = []
        for r in routes:
            normalized = self._normalize_route(r)
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique.append(normalized)
            if len(unique) >= max_routes:
                break

        self.routes = unique
        return unique

    def _render_home(self) -> Optional[str]:
        """Render the home page with headless browser if available."""
        result = self.renderer.render(self.base_url)
        if result.get("ok") and result.get("html"):
            return result["html"]
        return None

    def _extract_links_from_html(self, html: str) -> List[str]:
        """Extract internal links from rendered DOM."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html or "", "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            absolute = urljoin(self.base_url, href)
            parsed = urlparse(absolute)
            if parsed.netloc == urlparse(self.base_url).netloc:
                links.append(absolute)
        return links

    def _extract_from_scripts(self, html: str) -> List[str]:
        """Extract route definitions from inline/script tags."""
        routes = []
        # React Router patterns in bundled JS
        react_patterns = [
            r'path:\s*["\']([^"\']+)["\']',
            r'route:\s*["\']([^"\']+)["\']',
            r'<Route[^>]+path=["\']([^"\']+)["\']',
            r'/pages/[^"\']+',
            r'/routes/[^"\']+',
        ]
        for pattern in react_patterns:
            matches = re.findall(pattern, html, flags=re.I)
            routes.extend(matches)

        # Vue Router patterns
        vue_patterns = [
            r'path:\s*["\']([^"\']+)["\']',
            r'component:\s*["\']([^"\']+)["\']',
        ]
        for pattern in vue_patterns:
            matches = re.findall(pattern, html, flags=re.I)
            routes.extend(matches)

        return [r for r in routes if r and not r.startswith("http")]

    def _fetch_sitemap_routes(self) -> List[str]:
        """Fetch sitemap.xml and extract URLs."""
        import requests
        sitemap_url = urljoin(self.base_url, "/sitemap.xml")
        try:
            r = requests.get(sitemap_url, timeout=10, headers={"User-Agent": "AI-SEO-Autopilot/1.0"})
            if r.status_code == 200:
                urls = re.findall(r'<loc[^>]*>([^<]+)</loc>', r.text)
                return [u.strip() for u in urls if u.strip()]
        except Exception:
            pass
        return []

    def _fetch_robots_routes(self) -> List[str]:
        """Fetch robots.txt and extract sitemap/allow entries."""
        import requests
        robots_url = urljoin(self.base_url, "/robots.txt")
        try:
            r = requests.get(robots_url, timeout=10, headers={"User-Agent": "AI-SEO-Autopilot/1.0"})
            if r.status_code == 200:
                lines = r.text.splitlines()
                routes = []
                for line in lines:
                    line = line.strip()
                    if line.lower().startswith("allow:") or line.lower().startswith("disallow:"):
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            path = parts[1].strip()
                            if path and path != "/":
                                routes.append(urljoin(self.base_url, path))
                return routes
        except Exception:
            pass
        return []

    def _common_spa_routes(self) -> List[str]:
        """Return common SPA routes as fallback."""
        common = ["/about", "/about-us", "/contact", "/pricing", "/features", "/services", "/blog", "/faq"]
        return [urljoin(self.base_url, r) for r in common]

    def _normalize_route(self, route: str) -> str:
        """Normalize a route to a full URL."""
        if not route:
            return ""
        if route.startswith("http"):
            return route
        if route.startswith("/"):
            return urljoin(self.base_url, route)
        return urljoin(self.base_url, "/" + route)


class SpaCrawler:
    """Crawl SPA routes with headless browser rendering."""

    def __init__(self, base_url: str, timeout: int = 30, renderer: Optional[PageRenderer] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.renderer = renderer or PageRenderer(timeout=timeout)

    def crawl_route(self, url: str, wait_for_selector: str = "", wait_timeout: int = 5000) -> Dict:
        """Crawl a single SPA route and extract SEO data from rendered DOM."""
        result = {
            "url": url,
            "rendered": False,
            "status_code": 0,
            "html": "",
            "title": "",
            "meta_description": "",
            "canonical_url": "",
            "h1": "",
            "headings": {},
            "word_count": 0,
            "main_content": "",
            "images": {"count": 0, "images": []},
            "links": {"internal_count": 0, "external_count": 0, "nofollow_count": 0, "internal": [], "external": []},
            "open_graph": {},
            "twitter": {},
            "structured_data": [],
            "language": "",
            "robots_meta": "",
            "content_type": "text/html",
            "error": "",
        }

        if not self.renderer.use_playwright:
            result["error"] = "Playwright not installed; cannot render SPA routes"
            return result

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                ctx = browser.new_context(
                    user_agent="AI-SEO-Autopilot/1.0",
                    viewport={"width": 1280, "height": 800},
                )
                page = ctx.new_page()
                page.goto(url, timeout=self.timeout * 1000, wait_until="domcontentloaded")

                # Wait for app root if specified
                if wait_for_selector:
                    try:
                        page.wait_for_selector(wait_for_selector, timeout=wait_timeout)
                    except Exception:
                        pass

                # Wait for network idle
                try:
                    page.wait_for_load_state("networkidle", timeout=wait_timeout)
                except Exception:
                    page.wait_for_timeout(2000)

                html = page.content()
                result["html"] = html
                result["status_code"] = 200
                result["rendered"] = True

                # Extract SEO data from rendered DOM
                analyzed = analyze_html(html, base_url=url)
                result.update(analyzed)
                result["title"] = analyzed.get("title", "")
                result["meta_description"] = analyzed.get("meta_description", "")
                result["canonical_url"] = analyzed.get("canonical", "")
                result["h1"] = (analyzed.get("headings", {}).get("h1") or [""])[0]
                result["headings"] = analyzed.get("headings", {})
                result["word_count"] = analyzed.get("word_count", 0)
                result["main_content"] = analyzed.get("main_content", "")
                result["images"] = analyzed.get("images", {})
                result["links"] = analyzed.get("links", {})
                result["open_graph"] = analyzed.get("open_graph", {})
                result["twitter"] = analyzed.get("twitter", {})
                result["structured_data"] = analyzed.get("structured_data", [])
                result["language"] = analyzed.get("language", "")
                result["robots_meta"] = analyzed.get("robots_meta", "")

                browser.close()
        except Exception as e:
            result["error"] = str(e)

        return result

    def crawl_routes(self, urls: List[str], wait_for_selector: str = "", wait_timeout: int = 5000) -> Dict[str, Dict]:
        """Crawl multiple SPA routes reusing a single browser instance."""
        results = {}
        if not self.renderer.use_playwright:
            for url in urls:
                results[url] = {"url": url, "rendered": False, "error": "Playwright not installed"}
            return results

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                ctx = browser.new_context(
                    user_agent="AI-SEO-Autopilot/1.0",
                    viewport={"width": 1280, "height": 800},
                )
                page = ctx.new_page()
                for url in urls:
                    try:
                        page.goto(url, timeout=self.timeout * 1000, wait_until="domcontentloaded")
                        if wait_for_selector:
                            try:
                                page.wait_for_selector(wait_for_selector, timeout=wait_timeout)
                            except Exception:
                                pass
                        try:
                            page.wait_for_load_state("networkidle", timeout=wait_timeout)
                        except Exception:
                            page.wait_for_timeout(2000)

                        html = page.content()
                        analyzed = analyze_html(html, base_url=url)
                        results[url] = {
                            "url": url,
                            "rendered": True,
                            "status_code": 200,
                            "html": html,
                            **analyzed,
                        }
                    except Exception as e:
                        results[url] = {"url": url, "rendered": False, "error": str(e)}
                browser.close()
        except Exception as e:
            for url in urls:
                results.setdefault(url, {"url": url, "rendered": False, "error": str(e)})
        return results
