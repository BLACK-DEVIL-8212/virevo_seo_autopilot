"""SPA-aware crawler and route discovery.

Discovers routes in JavaScript-rendered applications, renders pages
with a headless browser when available, and extracts SEO data from
the rendered DOM.
"""
from __future__ import annotations
import re
import json
import time
import logging
from typing import Dict, List, Optional, Tuple, Set, Any
from urllib.parse import urljoin, urlparse, parse_qs

from .spa_detector import detect_architecture, detect_from_js_bundle, extract_manifest_links
from .renderer import PageRenderer
from .website_analyzer import analyze_html, calculate_seo_score

# Setup logging
logger = logging.getLogger(__name__)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def normalize_url(url: str) -> str:
    """Normalize a URL by removing fragments and trailing slashes."""
    if not url:
        return ""
    parsed = urlparse(url)
    normalized = parsed._replace(fragment="").geturl()
    if normalized.endswith("/") and not normalized.endswith("//"):
        normalized = normalized[:-1]
    return normalized


def is_internal(url: str, base_url: str) -> bool:
    """Check if URL is internal to the base domain."""
    if not url or not base_url:
        return False
    parsed_url = urlparse(url)
    parsed_base = urlparse(base_url)
    if not parsed_url.netloc:
        return True
    return parsed_url.netloc == parsed_base.netloc


def urljoin_safe(base: str, url: str) -> str:
    """Safely join URLs."""
    if not url:
        return base
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("/"):
        parsed = urlparse(base)
        return f"{parsed.scheme}://{parsed.netloc}{url}"
    return f"{base.rstrip('/')}/{url}"


# ============================================================================
# SPA ROUTE DISCOVERY
# ============================================================================

class SpaRouteDiscovery:
    """Discover routes in SPAs using multiple strategies."""

    def __init__(self, base_url: str, html: str, renderer: Optional[PageRenderer] = None):
        self.base_url = base_url.rstrip("/")
        self.raw_html = html or ""
        self.renderer = renderer or PageRenderer()
        self.routes: List[str] = []
        self.rendered_html: str = ""
        self.architecture: Dict = {}
        self._discovered_from = {}

    def discover(self, max_routes: int = 50, include_querystring: bool = False) -> List[str]:
        """Discover SPA routes using all available strategies."""
        arch = detect_architecture(self.raw_html, url=self.base_url)
        self.architecture = arch

        if not arch.get("is_spa"):
            logger.debug(f"Not an SPA: {self.base_url}")
            return []

        routes: List[str] = []
        discovery_sources = {}

        # Strategy 1: Extract from rendered DOM links
        rendered = self._render_home()
        if rendered:
            self.rendered_html = rendered
            dom_routes = self._extract_links_from_html(rendered)
            routes.extend(dom_routes)
            discovery_sources["dom"] = dom_routes

        # Strategy 2: Extract from raw HTML script tags / router configs
        script_routes = self._extract_from_scripts(self.raw_html)
        routes.extend(script_routes)
        discovery_sources["scripts"] = script_routes

        # Strategy 3: Extract from JavaScript bundle
        bundle_routes = self._extract_from_js_bundle(self.raw_html)
        routes.extend(bundle_routes)
        discovery_sources["bundle"] = bundle_routes

        # Strategy 4: Extract from manifest files
        manifest_routes = self._extract_from_manifest(self.raw_html)
        routes.extend(manifest_routes)
        discovery_sources["manifest"] = manifest_routes

        # Strategy 5: Extract from sitemap.xml
        sitemap_routes = self._fetch_sitemap_routes()
        routes.extend(sitemap_routes)
        discovery_sources["sitemap"] = sitemap_routes

        # Strategy 6: Extract from robots.txt
        robots_routes = self._fetch_robots_routes()
        routes.extend(robots_routes)
        discovery_sources["robots"] = robots_routes

        # Strategy 7: Common SPA routes heuristic
        common_routes = self._common_spa_routes()
        routes.extend(common_routes)
        discovery_sources["common"] = common_routes

        # Strategy 8: Extract from navigation elements
        nav_routes = self._extract_navigation_routes(self.raw_html)
        routes.extend(nav_routes)
        discovery_sources["navigation"] = nav_routes

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
        self._discovered_from = discovery_sources

        logger.info(f"Discovered {len(unique)} routes from {len(discovery_sources)} sources")
        return unique

    def _render_home(self) -> Optional[str]:
        """Render the home page with headless browser if available."""
        if not self.renderer.use_playwright:
            return None
        
        result = self.renderer.render(self.base_url, wait_for_selector="#app, #root, #__next, #__nuxt")
        if result.get("ok") and result.get("html"):
            return result["html"]
        return None

    def _extract_links_from_html(self, html: str) -> List[str]:
        """Extract internal links from rendered DOM."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []
        
        soup = BeautifulSoup(html or "", "html.parser")
        links = []
        
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            
            # Skip empty or self-referential links
            if href in ("", "/", "#", "./", "../"):
                continue
            
            absolute = urljoin(self.base_url + "/", href)
            parsed = urlparse(absolute)
            
            # Check if internal
            if is_internal(absolute, self.base_url):
                normalized = normalize_url(absolute)
                if normalized and normalized != self.base_url.rstrip("/"):
                    links.append(normalized)
        
        return links

    def _extract_from_scripts(self, html: str) -> List[str]:
        """Extract route definitions from inline/script tags."""
        routes = []
        
        # React Router patterns
        react_patterns = [
            r'path:\s*["\']([^"\']+)["\']',
            r'route:\s*["\']([^"\']+)["\']',
            r'<Route[^>]+path=["\']([^"\']+)["\']',
            r'to=["\']([^"\']+)["\']',
            r'href=["\']([^"\']+)["\']',
        ]
        for pattern in react_patterns:
            matches = re.findall(pattern, html, flags=re.I)
            routes.extend([m for m in matches if m and not m.startswith("http")])

        # Vue Router patterns
        vue_patterns = [
            r'path:\s*["\']([^"\']+)["\']',
            r'component:\s*["\']([^"\']+)["\']',
            r'<router-link[^>]+to=["\']([^"\']+)["\']',
            r':to=["\']([^"\']+)["\']',
        ]
        for pattern in vue_patterns:
            matches = re.findall(pattern, html, flags=re.I)
            routes.extend([m for m in matches if m and not m.startswith("http")])

        # Angular Router patterns
        angular_patterns = [
            r'path:\s*["\']([^"\']+)["\']',
            r'routerLink=["\']([^"\']+)["\']',
        ]
        for pattern in angular_patterns:
            matches = re.findall(pattern, html, flags=re.I)
            routes.extend([m for m in matches if m and not m.startswith("http")])

        # Next.js patterns
        next_patterns = [
            r'<Link[^>]+href=["\']([^"\']+)["\']',
            r'href=["\']([^"\']+)["\']',
            r'pathname:\s*["\']([^"\']+)["\']',
        ]
        for pattern in next_patterns:
            matches = re.findall(pattern, html, flags=re.I)
            routes.extend([m for m in matches if m and not m.startswith("http")])

        # Clean up routes
        cleaned = []
        for r in routes:
            # Remove query parameters and fragments
            r = r.split("?")[0].split("#")[0]
            if r and len(r) > 1:
                cleaned.append(r)

        return cleaned

    def _extract_from_js_bundle(self, html: str) -> List[str]:
        """Extract routes from JavaScript bundles."""
        routes = []
        
        # Look for route definitions in JS
        bundle_patterns = [
            r'/api/[^"\']+',
            r'/pages/[^"\']+',
            r'/routes/[^"\']+',
            r'/views/[^"\']+',
            r'/components/[^"\']+',
            r'"/[a-z][a-z0-9\-/]+"',
            r"'/[a-z][a-z0-9\-/]+'",
        ]
        
        for pattern in bundle_patterns:
            matches = re.findall(pattern, html, flags=re.I)
            for match in matches:
                # Clean up
                route = match.strip('"\'')
                if route and route.startswith("/") and len(route) > 1:
                    routes.append(route)

        return routes

    def _extract_from_manifest(self, html: str) -> List[str]:
        """Extract routes from manifest files."""
        try:
            manifest_links = extract_manifest_links(html)
            routes = []
            for link in manifest_links:
                if link.startswith("/"):
                    routes.append(link)
            return routes
        except Exception:
            return []

    def _extract_navigation_routes(self, html: str) -> List[str]:
        """Extract routes from navigation elements."""
        routes = []
        
        # Look for nav elements
        nav_patterns = [
            r'<nav[^>]*>.*?</nav>',
            r'<ul[^>]*class="[^"]*nav[^"]*"[^>]*>.*?</ul>',
            r'<div[^>]*class="[^"]*menu[^"]*"[^>]*>.*?</div>',
        ]
        
        for pattern in nav_patterns:
            matches = re.findall(pattern, html, flags=re.I | re.DOTALL)
            for match in matches:
                # Extract hrefs from nav
                hrefs = re.findall(r'href=["\']([^"\']+)["\']', match, flags=re.I)
                routes.extend([h for h in hrefs if h and not h.startswith(("http", "#", "javascript:"))])

        return routes

    def _fetch_sitemap_routes(self) -> List[str]:
        """Fetch sitemap.xml and extract URLs."""
        try:
            import requests
        except ImportError:
            return []
        
        sitemap_url = urljoin(self.base_url, "/sitemap.xml")
        try:
            response = requests.get(sitemap_url, timeout=10, headers={"User-Agent": "AI-SEO-Autopilot/1.0"})
            if response.status_code == 200:
                urls = re.findall(r'<loc[^>]*>([^<]+)</loc>', response.text, flags=re.I)
                return [u.strip() for u in urls if u.strip()]
        except Exception as e:
            logger.debug(f"Failed to fetch sitemap: {e}")
        
        return []

    def _fetch_robots_routes(self) -> List[str]:
        """Fetch robots.txt and extract sitemap/allow entries."""
        try:
            import requests
        except ImportError:
            return []
        
        robots_url = urljoin(self.base_url, "/robots.txt")
        try:
            response = requests.get(robots_url, timeout=10, headers={"User-Agent": "AI-SEO-Autopilot/1.0"})
            if response.status_code == 200:
                lines = response.text.splitlines()
                routes = []
                for line in lines:
                    line = line.strip()
                    if line.lower().startswith("allow:") or line.lower().startswith("disallow:"):
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            path = parts[1].strip()
                            if path and path != "/":
                                routes.append(urljoin(self.base_url, path))
                    elif line.lower().startswith("sitemap:"):
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            sitemap_url = parts[1].strip()
                            routes.append(sitemap_url)
                return routes
        except Exception as e:
            logger.debug(f"Failed to fetch robots.txt: {e}")
        
        return []

    def _common_spa_routes(self) -> List[str]:
        """Return common SPA routes as fallback."""
        common = [
            "/about", "/about-us", "/contact", "/pricing", "/features",
            "/services", "/blog", "/faq", "/help", "/support", "/terms",
            "/privacy", "/careers", "/team", "/portfolio", "/gallery",
            "/testimonials", "/reviews", "/case-studies", "/resources",
            "/download", "/signup", "/login", "/register", "/dashboard"
        ]
        return [urljoin(self.base_url, r) for r in common]

    def _normalize_route(self, route: str) -> str:
        """Normalize a route to a full URL."""
        if not route:
            return ""
        
        # Clean up route
        route = route.split("?")[0].split("#")[0]
        route = route.strip()
        
        if not route:
            return ""
        
        if route.startswith(("http://", "https://")):
            return normalize_url(route)
        
        if route.startswith("/"):
            return normalize_url(urljoin(self.base_url, route))
        
        # If route doesn't start with /, add it
        return normalize_url(urljoin(self.base_url, "/" + route))

    def get_discovery_summary(self) -> Dict[str, int]:
        """Get summary of routes discovered from each source."""
        return {source: len(routes) for source, routes in self._discovered_from.items()}


# ============================================================================
# SPA CRAWLER
# ============================================================================

class SpaCrawler:
    """Crawl SPA routes with headless browser rendering."""

    def __init__(self, base_url: str, timeout: int = 30, renderer: Optional[PageRenderer] = None,
                 max_pages: int = 100):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_pages = max_pages
        self.renderer = renderer or PageRenderer(timeout=timeout)
        self._crawled = set()
        self._results = {}
        self._discovered = set()

    def crawl_route(self, url: str, wait_for_selector: str = "", 
                    wait_timeout: int = 5000, capture_screenshot: bool = False) -> Dict:
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
            "links": {"internal_count": 0, "external_count": 0, "nofollow_count": 0},
            "open_graph": {},
            "twitter": {},
            "structured_data": [],
            "language": "",
            "robots_meta": "",
            "content_type": "text/html",
            "error": "",
            "screenshot": None,
            "console_errors": [],
        }

        if not self.renderer.use_playwright:
            result["error"] = "Playwright not installed; cannot render SPA routes"
            return result

        try:
            render_result = self.renderer.render(
                url,
                wait_for_selector=wait_for_selector or "#app, #root, #__next, #__nuxt",
                wait_timeout=wait_timeout,
                wait_until="networkidle",
                capture_screenshot=capture_screenshot,
                capture_console=True
            )

            if not render_result.get("ok"):
                result["error"] = render_result.get("error", "Render failed")
                return result

            html = render_result.get("html", "")
            result["html"] = html
            result["status_code"] = render_result.get("status_code", 200)
            result["rendered"] = True
            result["final_url"] = render_result.get("final_url", url)
            
            if render_result.get("screenshot"):
                result["screenshot"] = render_result.get("screenshot")
            
            if render_result.get("console_errors"):
                result["console_errors"] = render_result.get("console_errors")

            # Extract SEO data from rendered DOM
            analyzed = analyze_html(html, base_url=url)
            
            # Update result with analysis
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
            
            # Calculate SEO score
            result["seo_score"] = calculate_seo_score(analyzed)

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Error crawling {url}: {e}")

        return result

    def crawl_routes(self, urls: List[str], wait_for_selector: str = "",
                     wait_timeout: int = 5000, max_concurrent: int = 5) -> Dict[str, Dict]:
        """Crawl multiple SPA routes reusing a single browser instance."""
        results = {}
        
        if not self.renderer.use_playwright:
            for url in urls:
                results[url] = {"url": url, "rendered": False, "error": "Playwright not installed"}
            return results

        # Process in batches
        for i in range(0, len(urls), max_concurrent):
            batch = urls[i:i + max_concurrent]
            
            try:
                from playwright.sync_api import sync_playwright
                
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                    ctx = browser.new_context(
                        user_agent="AI-SEO-Autopilot/1.0",
                        viewport={"width": 1280, "height": 800},
                    )
                    
                    pages = []
                    for url in batch:
                        page = ctx.new_page()
                        pages.append((url, page))
                    
                    for url, page in pages:
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
                                "title": analyzed.get("title", ""),
                                "meta_description": analyzed.get("meta_description", ""),
                                "canonical_url": analyzed.get("canonical", ""),
                                "h1": (analyzed.get("headings", {}).get("h1") or [""])[0],
                                "headings": analyzed.get("headings", {}),
                                "word_count": analyzed.get("word_count", 0),
                                "main_content": analyzed.get("main_content", ""),
                                "images": analyzed.get("images", {}),
                                "links": analyzed.get("links", {}),
                                "open_graph": analyzed.get("open_graph", {}),
                                "twitter": analyzed.get("twitter", {}),
                                "structured_data": analyzed.get("structured_data", []),
                                "language": analyzed.get("language", ""),
                                "robots_meta": analyzed.get("robots_meta", ""),
                                "seo_score": calculate_seo_score(analyzed),
                                "error": "",
                            }
                            
                        except Exception as e:
                            results[url] = {"url": url, "rendered": False, "error": str(e)}
                        
                        try:
                            page.close()
                        except Exception:
                            pass
                    
                    browser.close()
                    
            except Exception as e:
                for url in batch:
                    if url not in results:
                        results[url] = {"url": url, "rendered": False, "error": str(e)}
        
        self._results.update(results)
        self._crawled.update(urls)
        return results

    def crawl_site(self, max_routes: int = 50, wait_for_selector: str = "",
                   wait_timeout: int = 5000, discover_routes: bool = True) -> Dict[str, Dict]:
        """
        Crawl an entire SPA site by discovering routes first.
        
        Args:
            max_routes: Maximum number of routes to crawl
            wait_for_selector: Selector to wait for
            wait_timeout: Wait timeout in ms
            discover_routes: Whether to discover routes first
            
        Returns:
            Dictionary mapping URL to crawl results
        """
        urls_to_crawl = [self.base_url]
        
        if discover_routes:
            # Get initial HTML
            try:
                import requests
                response = requests.get(self.base_url, timeout=10)
                html = response.text
                
                # Discover routes
                discovery = SpaRouteDiscovery(self.base_url, html, self.renderer)
                routes = discovery.discover(max_routes=max_routes)
                urls_to_crawl = [self.base_url] + routes
                
                logger.info(f"Discovered {len(routes)} routes for crawling")
            except Exception as e:
                logger.error(f"Failed to discover routes: {e}")
        
        # Limit total pages
        urls_to_crawl = urls_to_crawl[:self.max_pages]
        
        # Crawl routes
        results = self.crawl_routes(urls_to_crawl, wait_for_selector, wait_timeout)
        
        return results

    def get_summary(self) -> Dict:
        """Get summary of crawl results."""
        crawled_count = len(self._crawled)
        successful = sum(1 for r in self._results.values() if r.get("rendered"))
        failed = crawled_count - successful
        
        # Calculate average SEO score
        scores = [r.get("seo_score", 0) for r in self._results.values() if r.get("seo_score", 0) > 0]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        return {
            "total_crawled": crawled_count,
            "successful": successful,
            "failed": failed,
            "avg_seo_score": round(avg_score, 1),
            "min_seo_score": min(scores) if scores else 0,
            "max_seo_score": max(scores) if scores else 0,
        }


# ============================================================================
# SPA DETECTOR FUNCTIONS
# ============================================================================

def detect_architecture(html: str, url: str = "") -> Dict:
    """Detect SPA architecture from HTML."""
    result = {
        "is_spa": False,
        "architecture_type": "static_html",
        "rendering_mode": "raw",
        "deployment_strategy": "direct_html",
        "detected_spa_framework": "",
        "spa_indicators": [],
        "confidence": 0.0
    }
    
    if not html:
        return result
    
    html_lower = html.lower()
    
    # SPA framework detection
    spa_frameworks = {
        "react": ["react", "react-dom", "__react", "_react", "reactroot"],
        "vue": ["vue", "vuejs", "v-app", "v-html", "v-text"],
        "angular": ["ng-app", "ng-controller", "angular"],
        "next": ["__next", "next/"],
        "nuxt": ["__nuxt", "nuxt"],
        "svelte": ["svelte"],
        "gatsby": ["gatsby", "___gatsby"],
        "ember": ["ember"],
    }
    
    confidence = 0.0
    detected_framework = ""
    indicators = []
    
    for framework, keywords in spa_frameworks.items():
        for keyword in keywords:
            if keyword in html_lower:
                detected_framework = framework
                indicators.append(keyword)
                confidence += 0.2
                break
        if detected_framework:
            break
    
    # Check for SPA container elements
    spa_containers = ["#app", "#root", "#__next", "#__nuxt", "[data-reactroot]", "[data-v-app]"]
    for container in spa_containers:
        if container.replace("#", "").replace("[", "").replace("]", "") in html_lower:
            indicators.append(f"container:{container}")
            confidence += 0.15
    
    # Check for empty body (SPA shell)
    body_match = re.search(r"<body[^>]*>(.*?)</body>", html, re.IGNORECASE | re.DOTALL)
    if body_match:
        body_content = body_match.group(1).strip()
        if len(body_content) < 500 and not re.search(r"<h[1-6]", body_content, re.IGNORECASE):
            indicators.append("empty_body")
            confidence += 0.1
    
    # Determine SPA status
    result["is_spa"] = confidence >= 0.3
    result["spa_indicators"] = indicators
    result["confidence"] = min(confidence, 1.0)
    
    if result["is_spa"]:
        result["architecture_type"] = "spa"
        result["rendering_mode"] = "client"
        result["deployment_strategy"] = "client_side_rendering"
        result["detected_spa_framework"] = detected_framework
    
    return result


def detect_from_js_bundle(html: str) -> Dict:
    """Detect build system and framework from JS bundle references."""
    result = {
        "build_system": "unknown",
        "framework": "unknown",
        "bundle_files": []
    }
    
    if not html:
        return result
    
    # Look for JS bundle references
    bundle_patterns = [
        r'src=["\']([^"\']*\.js)["\']',
        r'src=["\']([^"\']*\.mjs)["\']',
        r'<script[^>]+src=["\']([^"\']+)["\']',
    ]
    
    bundles = []
    for pattern in bundle_patterns:
        matches = re.findall(pattern, html, flags=re.I)
        bundles.extend(matches)
    
    result["bundle_files"] = bundles
    
    # Detect build system
    build_systems = {
        "webpack": ["webpack", "chunk-", "vendors~", "main."],
        "vite": ["vite", "vitejs"],
        "rollup": ["rollup"],
        "esbuild": ["esbuild"],
        "parcel": ["parcel"],
        "babel": ["babel"],
        "next": ["_next/"],
        "nuxt": ["_nuxt/"],
        "gatsby": ["gatsby"],
    }
    
    for bundle in bundles:
        for system, keywords in build_systems.items():
            if any(keyword in bundle for keyword in keywords):
                result["build_system"] = system
                break
        if result["build_system"] != "unknown":
            break
    
    return result


def extract_manifest_links(html: str) -> List[str]:
    """Extract manifest file links from HTML."""
    links = []
    
    # Look for manifest links
    manifest_patterns = [
        r'<link[^>]+rel=["\']manifest["\'][^>]+href=["\']([^"\']+)["\']',
        r'<link[^>]+href=["\']([^"\']+manifest[^"\']*)["\']',
    ]
    
    for pattern in manifest_patterns:
        matches = re.findall(pattern, html, flags=re.I)
        links.extend(matches)
    
    return links

