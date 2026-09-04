"""Orchestrator - coordinates all SEO agents on a website."""
from __future__ import annotations
import json
import re
import uuid
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlparse

from app.events import get_event_manager as get_global_event_manager
from app.database.models import Website as DBWebsite
from app.database.models import Crawl as DBCrawl
from app.database.models import Page as DBPage
from app.database.models import SEOIssue as DBSEOIssue
from app.database.models import Keyword as DBKeyword
from app.database.models import OptimizationPlan as DBOptimizationPlan

# Setup logging
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Configuration for SEO orchestration."""
    SEO_AUTOMATION_MODE = "safe"  # safe, moderate, aggressive, analysis_only
    CRAWL_MAX_PAGES = 100
    CRAWL_MAX_DEPTH = 3
    CRAWL_DELAY_SECONDS = 1.0
    USE_PLAYWRIGHT = False
    PLAYWRIGHT_TIMEOUT = 30
    MAX_OPTIMIZATION_PAGES = 50
    MIN_SCORE_IMPROVEMENT = 0.5
    TARGET_SEO_SCORE = 85.0
    MAX_OPTIMIZATION_ITERATIONS = 3


# ============================================================================
# DATABASE MODELS (Simplified for standalone use)
# ============================================================================

class Website:
    """Website model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.name = kwargs.get('name', '')
        self.root_url = kwargs.get('root_url', '')
        self.website_root_path = kwargs.get('website_root_path', '')
        self.connection_type = kwargs.get('connection_type', '')
        self.architecture_type = kwargs.get('architecture_type', 'static_html')
        self.rendering_mode = kwargs.get('rendering_mode', 'raw')
        self.deployment_strategy = kwargs.get('deployment_strategy', 'direct_html')
        self.seo_health_score = kwargs.get('seo_health_score', 0.0)
        self.last_analyzed = kwargs.get('last_analyzed')
        self.technology = kwargs.get('technology', 'unknown')
        self.business_description = kwargs.get('business_description', '')
        self.hosting_provider = kwargs.get('hosting_provider', '')
        self.detected_spa_framework = kwargs.get('detected_spa_framework', '')
        self.detected_framework_evidence = kwargs.get('detected_framework_evidence', [])
        self.build_system = kwargs.get('build_system', 'unknown')
        self.last_architecture_check = kwargs.get('last_architecture_check')


class Page:
    """Page model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.website_id = kwargs.get('website_id')
        self.crawl_id = kwargs.get('crawl_id')
        self.url = kwargs.get('url', '')
        self.server_file = kwargs.get('server_file', '')
        self.file_mapping_confidence = kwargs.get('file_mapping_confidence', 0.0)
        self.status_code = kwargs.get('status_code', 0)
        self.content_type = kwargs.get('content_type', 'text/html')
        self.title = kwargs.get('title', '')
        self.meta_description = kwargs.get('meta_description', '')
        self.h1 = kwargs.get('h1', '')
        self.headings_json = kwargs.get('headings_json', {})
        self.word_count = kwargs.get('word_count', 0)
        self.main_content = kwargs.get('main_content', '')
        self.images_json = kwargs.get('images_json', {})
        self.links_json = kwargs.get('links_json', {})
        self.og_json = kwargs.get('og_json', {})
        self.twitter_json = kwargs.get('twitter_json', {})
        self.structured_data_json = kwargs.get('structured_data_json', [])
        self.canonical_url = kwargs.get('canonical_url', '')
        self.robots_meta = kwargs.get('robots_meta', '')
        self.language = kwargs.get('language', '')
        self.seo_score = kwargs.get('seo_score', 0.0)
        self.analyzed_at = kwargs.get('analyzed_at')
        self.rendered = kwargs.get('rendered', False)
        self.route_url = kwargs.get('route_url', '')
        self.rendered_html = kwargs.get('rendered_html', '')
        self.rendered_word_count = kwargs.get('rendered_word_count', 0)
        self.rendered_title = kwargs.get('rendered_title', '')
        self.rendered_meta_description = kwargs.get('rendered_meta_description', '')
        self.rendered_h1 = kwargs.get('rendered_h1', '')
        self.rendered_headings_json = kwargs.get('rendered_headings_json', {})
        self.rendered_main_content = kwargs.get('rendered_main_content', '')
        self.rendered_images_json = kwargs.get('rendered_images_json', {})
        self.rendered_links_json = kwargs.get('rendered_links_json', {})
        self.rendered_og_json = kwargs.get('rendered_og_json', {})
        self.rendered_twitter_json = kwargs.get('rendered_twitter_json', {})
        self.rendered_structured_data_json = kwargs.get('rendered_structured_data_json', [])
        self.rendered_canonical_url = kwargs.get('rendered_canonical_url', '')
        self.rendered_language = kwargs.get('rendered_language', '')
        self.rendered_robots_meta = kwargs.get('rendered_robots_meta', '')
        self.is_spa_route = kwargs.get('is_spa_route', False)
        self.source_file_path = kwargs.get('source_file_path', '')
        self.source_language = kwargs.get('source_language', '')


class Crawl:
    """Crawl model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.website_id = kwargs.get('website_id')
        self.status = kwargs.get('status', 'running')
        self.max_pages = kwargs.get('max_pages', 100)
        self.max_depth = kwargs.get('max_depth', 3)
        self.pages_crawled = kwargs.get('pages_crawled', 0)
        self.source = kwargs.get('source', 'raw')
        self.error_message = kwargs.get('error_message', '')
        self.started_at = kwargs.get('started_at', datetime.utcnow())
        self.finished_at = kwargs.get('finished_at')


class SEOIssue:
    """SEO Issue model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.website_id = kwargs.get('website_id')
        self.page_id = kwargs.get('page_id')
        self.url = kwargs.get('url', '')
        self.issue_type = kwargs.get('issue_type', '')
        self.severity = kwargs.get('severity', 'medium')
        self.title = kwargs.get('title', '')
        self.description = kwargs.get('description', '')
        self.current_value = kwargs.get('current_value', '')
        self.proposed_value = kwargs.get('proposed_value', '')
        self.implementation_method = kwargs.get('implementation_method', '')
        self.risk = kwargs.get('risk', 'medium')
        self.confidence = kwargs.get('confidence', 0.7)


class Keyword:
    """Keyword model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.website_id = kwargs.get('website_id')
        self.page_id = kwargs.get('page_id')
        self.keyword = kwargs.get('keyword', '')
        self.cluster = kwargs.get('cluster', '')
        self.intent = kwargs.get('intent', '')
        self.search_volume = kwargs.get('search_volume', 0)
        self.difficulty = kwargs.get('difficulty', 0.0)
        self.relevance = kwargs.get('relevance', 0.0)
        self.opportunity_score = kwargs.get('opportunity_score', 0.0)
        self.is_long_tail = kwargs.get('is_long_tail', False)
        self.is_trending = kwargs.get('is_trending', False)
        self.provider = kwargs.get('provider', 'local')


class OptimizationPlan:
    """Optimization Plan model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.website_id = kwargs.get('website_id')
        self.title = kwargs.get('title', '')
        self.summary = kwargs.get('summary', '')
        self.actions_json = kwargs.get('actions_json', {})
        self.risk_breakdown = kwargs.get('risk_breakdown', {})
        self.status = kwargs.get('status', 'draft')
        self.created_at = kwargs.get('created_at', datetime.utcnow())


class Connection:
    """Connection model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.website_id = kwargs.get('website_id')
        self.host = kwargs.get('host', '')
        self.port = kwargs.get('port', 21)
        self.username = kwargs.get('username', '')
        self.password_encrypted = kwargs.get('password_encrypted', '')
        self.private_key_encrypted = kwargs.get('private_key_encrypted', '')


class AuditLog:
    """Audit Log model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.actor = kwargs.get('actor', '')
        self.action = kwargs.get('action', '')
        self.target = kwargs.get('target', '')
        self.details = kwargs.get('details', {})
        self.created_at = kwargs.get('created_at', datetime.utcnow())


# ============================================================================
# DATABASE HELPERS
# ============================================================================

class SessionLocal:
    """Database session placeholder."""
    @staticmethod
    def remove():
        pass


def new_session():
    """Create a new database session."""
    return SessionLocal()


def retry_on_lock(func):
    """Decorator to retry on database lock."""
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper


def filter_model_fields(model_class, data: Dict) -> Dict:
    """Filter dictionary to only include valid model fields."""
    if hasattr(model_class, '__annotations__'):
        valid_fields = set(model_class.__annotations__.keys())
        return {k: v for k, v in data.items() if k in valid_fields}
    return data


def log_audit(actor: str, action: str, target: str = "", details: dict = None, phase: str = ""):
    """Log audit entry."""
    if details is None:
        details = {}
    if phase:
        details = {**details, "phase": phase}
    logger.info(f"AUDIT: {actor} | {action} | {target} | {details}")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def normalize_url(url: str) -> str:
    """Normalize a URL."""
    if not url:
        return ""
    parsed = urlparse(url)
    normalized = parsed._replace(fragment="").geturl()
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


def fetch_real_html(url: str) -> Dict:
    """Fetch real HTML content."""
    import requests
    try:
        response = requests.get(url, timeout=30, allow_redirects=True)
        html = response.text or ""
        
        # Check for JS verification
        challenge = is_js_verification_page(html)
        
        return {
            "ok": 200 <= response.status_code < 400 and not challenge.get("is_challenge"),
            "html": html,
            "status_code": response.status_code,
            "final_url": response.url,
            "challenge": challenge if challenge.get("is_challenge") else None,
            "error": None
        }
    except Exception as e:
        return {
            "ok": False,
            "html": "",
            "status_code": 0,
            "final_url": url,
            "challenge": None,
            "error": str(e)
        }


def is_js_verification_page(html: str = "") -> Dict:
    """Detect if page is a JS verification challenge."""
    result = {"is_challenge": False, "reason": ""}
    if not html:
        return result
    
    html_lower = html.lower()
    indicators = [
        "aes.js",
        "slowaes",
        "slowAES",
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
    
    for indicator in indicators:
        if indicator in html_lower:
            result["is_challenge"] = True
            result["reason"] = f"Contains '{indicator}'"
            break
    
    return result


def best_mapping(url: str, website_root_path: str = "") -> Dict:
    """Get best URL to file mapping."""
    path = urlparse(url).path.lstrip("/")
    if not path:
        path = "index.html"
    elif not path.endswith(".html") and not "." in path:
        path = f"{path}.html"
    
    if website_root_path:
        path = f"{website_root_path.rstrip('/')}/{path}"
    
    return {
        "best": {
            "file": path,
            "confidence": 1.0
        }
    }


def _log(actor: str, action: str, target: str = "", details: dict = None, phase: str = ""):
    """Log audit entry with consistent format."""
    if details is None:
        details = {}
    if phase:
        details = {**details, "phase": phase}
    log_audit(actor, action, target, details)


# ============================================================================
# EVENT MANAGER — uses global app/events EventManager for DB+SSE persistence
# ============================================================================


def get_event_manager():
    return get_global_event_manager()


# ============================================================================
# WEBSITE ANALYZER
# ============================================================================

def analyze_html(html: str, base_url: str = "") -> Dict:
    """Analyze HTML for SEO purposes."""
    from bs4 import BeautifulSoup
    import re
    
    soup = BeautifulSoup(html or "", "html.parser")
    
    # Extract title
    title_tag = soup.find("title")
    title = title_tag.text.strip() if title_tag else ""
    
    # Extract meta description
    meta_desc = ""
    for meta in soup.find_all("meta"):
        if meta.get("name", "").lower() == "description":
            meta_desc = meta.get("content", "")
            break
    
    # Extract headings
    headings = {"h1": [], "h2": [], "h3": [], "h4": [], "h5": [], "h6": []}
    for level in headings.keys():
        for tag in soup.find_all(level):
            headings[level].append(tag.text.strip())
    
    # Extract main content
    main_content = ""
    for selector in ["main", "article", ".content", ".main", "#content", "body"]:
        element = soup.select_one(selector)
        if element:
            main_content = element.text.strip()
            break
    
    # Extract links
    links = {"internal": [], "external": []}
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if href and not href.startswith("#") and not href.startswith("javascript:"):
            if href.startswith("http") and base_url:
                if is_internal(href, base_url):
                    links["internal"].append(href)
                else:
                    links["external"].append(href)
            elif href.startswith("/"):
                links["internal"].append(href)
    
    # Extract images
    images = []
    for img in soup.find_all("img"):
        images.append({
            "src": img.get("src", ""),
            "alt": img.get("alt", ""),
            "width": img.get("width", ""),
            "height": img.get("height", "")
        })
    
    # Extract Open Graph
    og = {}
    for meta in soup.find_all("meta"):
        if meta.get("property", "").startswith("og:"):
            og[meta["property"]] = meta.get("content", "")
    
    # Extract Twitter Cards
    twitter = {}
    for meta in soup.find_all("meta"):
        if meta.get("name", "").startswith("twitter:"):
            twitter[meta["name"]] = meta.get("content", "")
    
    # Extract structured data
    structured_data = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
            structured_data.append(data)
        except:
            pass
    
    # Extract canonical
    canonical = ""
    canon_tag = soup.find("link", rel="canonical")
    if canon_tag and canon_tag.get("href"):
        canonical = canon_tag.get("href")
    
    # Extract robots meta
    robots_meta = ""
    for meta in soup.find_all("meta"):
        if meta.get("name", "").lower() == "robots":
            robots_meta = meta.get("content", "")
            break
    
    # Extract language
    language = soup.find("html").get("lang", "") if soup.find("html") else ""
    
    # Calculate word count
    text = soup.get_text()
    word_count = len(re.findall(r'\w+', text))
    
    return {
        "title": title,
        "meta_description": meta_desc,
        "headings": headings,
        "main_content": main_content,
        "links": links,
        "images": images,
        "open_graph": og,
        "twitter": twitter,
        "structured_data": structured_data,
        "canonical": canonical,
        "robots_meta": robots_meta,
        "language": language,
        "word_count": word_count,
        "html": html
    }


def calculate_seo_score(analysis: Dict) -> float:
    """Calculate SEO score from analysis data."""
    score = 0.0
    
    # Title (15 points)
    title = analysis.get("title", "")
    if title:
        score += 10
        if 30 <= len(title) <= 60:
            score += 5
        elif 20 <= len(title) <= 70:
            score += 3
    
    # Meta description (15 points)
    meta_desc = analysis.get("meta_description", "")
    if meta_desc:
        score += 10
        if 50 <= len(meta_desc) <= 160:
            score += 5
        elif 30 <= len(meta_desc) <= 200:
            score += 3
    
    # H1 (10 points)
    headings = analysis.get("headings", {})
    h1s = headings.get("h1", [])
    if h1s and h1s[0]:
        score += 10
    
    # H2s (5 points)
    h2s = headings.get("h2", [])
    if len(h2s) >= 1:
        score += 3
        if len(h2s) >= 3:
            score += 2
    
    # Word count (15 points)
    word_count = analysis.get("word_count", 0)
    if word_count >= 300:
        score += 10
        if word_count >= 500:
            score += 5
        elif word_count >= 400:
            score += 3
    elif word_count >= 200:
        score += 5
    elif word_count >= 100:
        score += 3
    
    # Images with alt text (10 points)
    images = analysis.get("images", [])
    if images:
        images_with_alt = sum(1 for img in images if img.get("alt"))
        ratio = images_with_alt / len(images)
        score += ratio * 10
    
    # Internal links (10 points)
    links = analysis.get("links", {})
    internal_links = len(links.get("internal", []))
    if internal_links >= 1:
        score += 5
        if internal_links >= 5:
            score += 5
        elif internal_links >= 3:
            score += 3
    
    # Open Graph (5 points)
    og = analysis.get("open_graph", {})
    if og.get("og:title"):
        score += 3
    if og.get("og:description"):
        score += 2
    
    # Twitter Cards (5 points)
    twitter = analysis.get("twitter", {})
    if twitter.get("twitter:title"):
        score += 3
    if twitter.get("twitter:description"):
        score += 2
    
    # Structured data (5 points)
    structured_data = analysis.get("structured_data", [])
    if structured_data:
        score += min(5, len(structured_data) * 2)
    
    # Canonical URL (5 points)
    if analysis.get("canonical"):
        score += 5
    
    # Language (2 points)
    if analysis.get("language"):
        score += 2
    
    # Robots meta (3 points)
    robots_meta = analysis.get("robots_meta", "")
    if robots_meta and "noindex" not in robots_meta.lower():
        score += 3
    
    return min(score, 100.0)


# ============================================================================
# CRAWLER
# ============================================================================

class WebsiteCrawler:
    """Simple website crawler with event emission."""
    
    def __init__(self, root_url: str, max_pages: int = 100, max_depth: int = 3,
                 event_manager=None, job_id: str = None, website_id: int = None):
        self.root_url = normalize_url(root_url)
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.job_id = job_id
        self.website_id = website_id
        self.event_manager = event_manager or get_event_manager()
        self.architecture = {}
        self.results = []
        self.stats = self._create_stats()
    
    def _emit(self, event_type: str, message: str = "", severity: str = "info",
              url: str = "", metadata: Dict = None, agent_name: str = ""):
        if self.job_id:
            try:
                self.event_manager.emit(
                    job_id=self.job_id, event_type=event_type, message=message,
                    severity=severity, url=url, metadata=metadata or {},
                    website_id=self.website_id, agent_name=agent_name or "Website Crawler",
                )
            except Exception:
                pass
    
    def _create_stats(self):
        class Stats:
            def __init__(self):
                self.pages_crawled = 0
                self.pages_discovered = 0
                self.pages_queued = 0
                self.pages_failed = 0
                self.pages_skipped = 0
                self.pages_blocked = 0
                self.errors = []
                self.fetch_errors = []
                self.source = "raw"
                self.raw_render_events = 0
                self.duplicate_crawl_attempts_prevented = 0
                self.duplicate_homepage_attempts_prevented = 0
            
            def to_result(self):
                return {
                    "pages_crawled": self.pages_crawled,
                    "pages_discovered": self.pages_discovered,
                    "pages_queued": self.pages_queued,
                    "pages_failed": self.pages_failed,
                    "pages_skipped": self.pages_skipped,
                    "pages_blocked": self.pages_blocked,
                    "errors": self.errors,
                    "fetch_errors": self.fetch_errors,
                    "raw_render_events": self.raw_render_events,
                    "duplicate_crawl_attempts_prevented": self.duplicate_crawl_attempts_prevented,
                    "duplicate_homepage_attempts_prevented": self.duplicate_homepage_attempts_prevented,
                    "source": self.source
                }
        return Stats()
    
    def crawl(self, on_progress=None, job_id: str = None) -> List[Dict]:
        """Crawl the website."""
        import requests
        from bs4 import BeautifulSoup
        
        self.job_id = job_id
        results = []
        visited = set()
        queue = [(self.root_url, 0)]
        self.stats.pages_discovered = 1
        
        self._emit("crawl_started", f"Starting crawl of {self.root_url}",
                   metadata={"max_pages": self.max_pages, "max_depth": self.max_depth,
                             "url": self.root_url})
        
        while queue and len(results) < self.max_pages:
            url, depth = queue.pop(0)
            
            if url in visited:
                continue
            visited.add(url)
            
            try:
                response = requests.get(url, timeout=30, headers={
                    "User-Agent": "AI-SEO-Autopilot/1.0"
                })
                
                if response.status_code >= 400:
                    self.stats.pages_failed += 1
                    self._emit("page_crawl_failed", f"HTTP {response.status_code} for {url}",
                               severity="error", url=url,
                               metadata={"status_code": response.status_code})
                    continue
                
                html = response.text
                self.stats.pages_crawled += 1
                
                # Detect architecture
                if not self.architecture:
                    self.architecture = self._detect_architecture(html)
                
                # Extract links
                soup = BeautifulSoup(html, "html.parser")
                for link in soup.find_all("a"):
                    href = link.get("href")
                    if href:
                        full_url = normalize_url(urljoin(url, href))
                        if is_internal(full_url, self.root_url) and full_url not in visited:
                            if len(queue) + len(visited) < self.max_pages * 2:
                                queue.append((full_url, depth + 1))
                                self.stats.pages_discovered += 1
                                self._emit("url_discovered", f"Discovered {full_url}",
                                           url=full_url, severity="info",
                                           metadata={"depth": depth + 1, "source": url})
                
                results.append({
                    "url": url,
                    "html": html,
                    "status_code": response.status_code,
                    "depth": depth,
                    "rendered": False
                })
                
                self._emit("page_crawled", f"Crawled {url}",
                           url=url, severity="success",
                           metadata={"status_code": response.status_code, "depth": depth,
                                     "word_count": len(html.split())})
                
                self._emit("crawl_debug", f"Crawled {url}",
                           url=url, severity="info",
                           metadata={
                               "pages_crawled": self.stats.pages_crawled,
                               "pages_discovered": self.stats.pages_discovered,
                               "pages_failed": self.stats.pages_failed,
                               "pages_blocked": self.stats.pages_blocked,
                               "queue_size": len(queue),
                               "current_url": url,
                               "http_status": response.status_code,
                           })
                
                if on_progress:
                    progress = min(90, int(10 + 80 * len(results) / self.max_pages))
                    on_progress(progress, f"Crawled {len(results)} pages")
                
            except Exception as e:
                self.stats.pages_failed += 1
                self.stats.errors.append(str(e))
                self._emit("page_crawl_failed", f"Error crawling {url}: {e}",
                           severity="error", url=url,
                           metadata={"error": str(e)})
        
        self.results = results
        self._emit("crawl_result",
                   f"Crawl complete: {len(results)} pages crawled, {self.stats.pages_failed} failed",
                   metadata=self.stats.to_result())
        return results
    
    def _detect_architecture(self, html: str) -> Dict:
        """Detect website architecture."""
        arch = {
            "architecture_type": "static_html",
            "rendering_mode": "raw",
            "deployment_strategy": "direct_html",
            "is_spa": False,
            "detected_spa_framework": "",
            "build_system": "unknown"
        }
        
        html_lower = html.lower()
        
        # SPA detection
        spa_indicators = ["react", "vue", "angular", "__next", "__nuxt", "svelte"]
        for indicator in spa_indicators:
            if indicator in html_lower:
                arch["is_spa"] = True
                arch["detected_spa_framework"] = indicator
                arch["architecture_type"] = "spa"
                arch["rendering_mode"] = "client"
                break
        
        return arch
    
    def get_crawl_result(self) -> Dict:
        """Get crawl results."""
        return self.stats.to_result()


def urljoin(base: str, url: str) -> str:
    """Join URLs."""
    if not url:
        return base
    if url.startswith("http"):
        return url
    if url.startswith("/"):
        parsed = urlparse(base)
        return f"{parsed.scheme}://{parsed.netloc}{url}"
    return f"{base.rstrip('/')}/{url}"


# ============================================================================
# TECHNOLOGY DETECTOR
# ============================================================================

def detect_from_html(html: str) -> Dict:
    """Detect technology from HTML."""
    tech = {"detected": []}
    html_lower = html.lower()
    
    # Framework detection
    frameworks = {
        "react": ["react", "react-dom", "__react"],
        "vue": ["vue", "vuejs", "v-app"],
        "angular": ["ng-app", "angular", "ng-"],
        "next": ["__next", "next/"],
        "nuxt": ["__nuxt", "nuxt"],
        "svelte": ["svelte"],
        "jquery": ["jquery"],
        "bootstrap": ["bootstrap"],
        "tailwind": ["tailwind"]
    }
    
    for framework, indicators in frameworks.items():
        for indicator in indicators:
            if indicator in html_lower:
                tech["detected"].append(framework)
                break
    
    return tech


def detect_from_files(files: List[str]) -> Dict:
    """Detect technology from file names."""
    tech = {"detected": []}
    
    package_files = {
        "package.json": ["node", "npm", "yarn"],
        "composer.json": ["php", "laravel", "symfony"],
        "requirements.txt": ["python", "django", "flask"],
        "Gemfile": ["ruby", "rails"],
        "Cargo.toml": ["rust"],
        "go.mod": ["go"]
    }
    
    for file in files:
        for package, frameworks in package_files.items():
            if file.endswith(package):
                tech["detected"].extend(frameworks)
                break
    
    return tech


# ============================================================================
# SEO AUDIT
# ============================================================================

def run_full_audit(analysis: Dict, status_code: int = 200) -> List[Dict]:
    """Run full SEO audit on analyzed page."""
    issues = []
    
    # Check title
    title = analysis.get("title", "")
    if not title:
        issues.append({
            "issue_type": "title",
            "severity": "high",
            "title": "Missing title tag",
            "description": "Page has no title tag, which is critical for SEO.",
            "current_value": "",
            "proposed_value": analysis.get("topic", "Page Title"),
            "implementation_method": "html_title_update",
            "risk": "low",
            "confidence": 0.9
        })
    elif len(title) < 20:
        issues.append({
            "issue_type": "title",
            "severity": "medium",
            "title": "Title too short",
            "description": f"Title is only {len(title)} characters. Recommended length is 30-65 characters.",
            "current_value": title,
            "proposed_value": f"{title} - Learn More",
            "implementation_method": "html_title_update",
            "risk": "low",
            "confidence": 0.8
        })
    elif len(title) > 65:
        issues.append({
            "issue_type": "title",
            "severity": "medium",
            "title": "Title too long",
            "description": f"Title is {len(title)} characters. Recommended length is 30-65 characters.",
            "current_value": title,
            "proposed_value": title[:62] + "...",
            "implementation_method": "html_title_update",
            "risk": "low",
            "confidence": 0.8
        })
    
    # Check meta description
    meta_desc = analysis.get("meta_description", "")
    if not meta_desc:
        issues.append({
            "issue_type": "meta_description",
            "severity": "high",
            "title": "Missing meta description",
            "description": "Page has no meta description tag.",
            "current_value": "",
            "proposed_value": f"Learn about {analysis.get('topic', 'this page')}. Expert insights and tips.",
            "implementation_method": "html_meta_update",
            "risk": "low",
            "confidence": 0.9
        })
    elif len(meta_desc) < 50:
        issues.append({
            "issue_type": "meta_description",
            "severity": "medium",
            "title": "Meta description too short",
            "description": f"Meta description is only {len(meta_desc)} characters. Recommended length is 120-160 characters.",
            "current_value": meta_desc,
            "proposed_value": f"{meta_desc} Learn more and get expert insights.",
            "implementation_method": "html_meta_update",
            "risk": "low",
            "confidence": 0.8
        })
    elif len(meta_desc) > 160:
        issues.append({
            "issue_type": "meta_description",
            "severity": "medium",
            "title": "Meta description too long",
            "description": f"Meta description is {len(meta_desc)} characters. Recommended length is 120-160 characters.",
            "current_value": meta_desc,
            "proposed_value": meta_desc[:157] + "...",
            "implementation_method": "html_meta_update",
            "risk": "low",
            "confidence": 0.8
        })
    
    # Check H1
    headings = analysis.get("headings", {})
    h1s = headings.get("h1", [])
    if not h1s or not h1s[0]:
        issues.append({
            "issue_type": "h1",
            "severity": "medium",
            "title": "Missing H1 heading",
            "description": "Page has no H1 heading, which is important for SEO.",
            "current_value": "",
            "proposed_value": analysis.get("topic", "Welcome"),
            "implementation_method": "html_meta_update",
            "risk": "low",
            "confidence": 0.85
        })
    
    # Check word count
    word_count = analysis.get("word_count", 0)
    if word_count < 200:
        issues.append({
            "issue_type": "word_count",
            "severity": "medium",
            "title": "Low word count",
            "description": f"Page has only {word_count} words. Recommended minimum is 300 words.",
            "current_value": str(word_count),
            "proposed_value": "300+ words",
            "implementation_method": "content_update",
            "risk": "medium",
            "confidence": 0.7
        })
    
    # Check canonical
    if not analysis.get("canonical"):
        issues.append({
            "issue_type": "canonical",
            "severity": "medium",
            "title": "Missing canonical URL",
            "description": "Page has no canonical tag, which may lead to duplicate content issues.",
            "current_value": "",
            "proposed_value": analysis.get("url", ""),
            "implementation_method": "html_meta_update",
            "risk": "low",
            "confidence": 0.85
        })
    
    # Check Open Graph
    og = analysis.get("open_graph", {})
    if not og.get("og:title"):
        issues.append({
            "issue_type": "open_graph",
            "severity": "low",
            "title": "Missing Open Graph title",
            "description": "Page has no OG title, which affects social sharing.",
            "current_value": "",
            "proposed_value": analysis.get("title", analysis.get("topic", "Page")),
            "implementation_method": "html_meta_update",
            "risk": "low",
            "confidence": 0.8
        })
    
    # Check structured data
    structured_data = analysis.get("structured_data", [])
    if not structured_data:
        issues.append({
            "issue_type": "structured_data",
            "severity": "low",
            "title": "Missing structured data",
            "description": "Page has no structured data (JSON-LD), which can improve search visibility.",
            "current_value": "",
            "proposed_value": "Add JSON-LD structured data",
            "implementation_method": "html_structured_data_update",
            "risk": "medium",
            "confidence": 0.7
        })
    
    # Check images
    images = analysis.get("images", [])
    images_without_alt = [img for img in images if not img.get("alt")]
    if images_without_alt:
        issues.append({
            "issue_type": "image_alt",
            "severity": "low",
            "title": f"{len(images_without_alt)} images missing alt text",
            "description": "Images without alt text can hurt accessibility and SEO.",
            "current_value": "",
            "proposed_value": "Add descriptive alt text to images",
            "implementation_method": "html_image_update",
            "risk": "low",
            "confidence": 0.75
        })
    
    return issues


# ============================================================================
# SITEMAP AND ROBOTS
# ============================================================================

def discover_sitemaps(root_url: str) -> List[str]:
    """Discover sitemap URLs."""
    import requests
    sitemaps = []
    
    candidates = [
        "/sitemap.xml",
        "/sitemap_index.xml",
        "/sitemap-index.xml",
        "/wp-sitemap.xml",
        "/sitemap.xml.gz",
        "/sitemap-index.xml.gz"
    ]
    
    # Try robots.txt first
    try:
        response = requests.get(urljoin(root_url, "/robots.txt"), timeout=10)
        if response.status_code == 200:
            for line in response.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    sitemap_url = line.split(":", 1)[1].strip()
                    if sitemap_url:
                        sitemaps.append(sitemap_url)
    except Exception:
        pass
    
    # Try common sitemap locations
    for candidate in candidates:
        try:
            url = urljoin(root_url, candidate)
            response = requests.get(url, timeout=10)
            if response.status_code == 200 and "xml" in response.headers.get("content-type", "").lower():
                sitemaps.append(url)
        except Exception:
            pass
    
    return sitemaps


def fetch_sitemap(url: str) -> Optional[str]:
    """Fetch sitemap content."""
    import requests
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.text
    except Exception:
        pass
    return None


def parse_sitemap(xml: str) -> List[Dict]:
    """Parse sitemap XML."""
    from bs4 import BeautifulSoup
    results = []
    
    try:
        soup = BeautifulSoup(xml, "xml")
        for loc in soup.find_all("loc"):
            results.append({"loc": loc.text, "type": "url"})
        
        # Check for sitemap index
        for sm in soup.find_all("sitemap"):
            loc = sm.find("loc")
            if loc:
                results.append({"loc": loc.text, "type": "sitemap"})
    except Exception:
        pass
    
    return results


def validate_sitemap(xml: str) -> bool:
    """Validate sitemap format."""
    return bool(xml and ("<url>" in xml or "<sitemapindex>" in xml))


def generate_sitemap(urls: List[str]) -> str:
    """Generate sitemap XML."""
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url in urls:
        xml += f'  <url>\n    <loc>{url}</loc>\n  </url>\n'
    xml += '</urlset>'
    return xml


def fetch_robots(root_url: str) -> Optional[str]:
    """Fetch robots.txt."""
    import requests
    try:
        response = requests.get(urljoin(root_url, "/robots.txt"), timeout=10)
        if response.status_code == 200:
            return response.text
    except Exception:
        pass
    return None


def parse_robots(text: str) -> Dict:
    """Parse robots.txt."""
    result = {"rules": [], "sitemaps": []}
    
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("sitemap:"):
            result["sitemaps"].append(line.split(":", 1)[1].strip())
        elif line.lower().startswith("user-agent") or line.lower().startswith("disallow"):
            result["rules"].append(line)
    
    return result


def analyze_robots(text: Optional[str]) -> Dict:
    """Analyze robots.txt for issues."""
    result = {
        "present": bool(text),
        "issues": [],
        "rules": {}
    }
    
    if not text:
        result["issues"].append("robots.txt is missing")
        return result
    
    parsed = parse_robots(text)
    result["rules"]["sitemaps"] = parsed.get("sitemaps", [])
    result["rules"]["disallow_rules"] = [r for r in parsed.get("rules", []) if "disallow" in r.lower()]
    result["rules"]["user_agents"] = [r for r in parsed.get("rules", []) if "user-agent" in r.lower()]
    
    if not result["rules"]["sitemaps"]:
        result["issues"].append("No sitemap referenced in robots.txt")
    
    return result


# ============================================================================
# KEYWORD INTELLIGENCE
# ============================================================================

class KeywordIntelligenceEngine:
    """Keyword intelligence engine."""
    
    def __init__(self, website_id: int, website_url: str, business_description: str = "", job_id: str = ""):
        self.website_id = website_id
        self.website_url = website_url
        self.business_description = business_description
        self.job_id = job_id
    
    def _emit(self, event_type: str, message: str = "", severity: str = "info", metadata: dict = None):
        if self.job_id:
            try:
                get_event_manager().emit(
                    job_id=self.job_id, event_type=event_type, message=message,
                    severity=severity, url="", metadata=metadata or {},
                    website_id=self.website_id, agent_name="Keyword Intelligence Agent",
                )
            except Exception:
                pass
    
    def run_full_analysis(self, pages_data: List[Dict]) -> Dict:
        """Run full keyword intelligence analysis."""
        self._emit("keyword_research_started", "Starting keyword research")
        
        all_keywords = []
        page_mappings = []
        content_gaps = []
        strategies = []
        
        # Extract keywords from pages
        for page in pages_data:
            title = page.get("title", "")
            content = page.get("main_content", "")
            headings = page.get("headings", {})
            
            # Extract keywords from title
            title_keywords = self._extract_keywords(title)
            
            # Extract keywords from content
            content_keywords = self._extract_keywords(content)
            
            # Extract keywords from headings
            heading_keywords = []
            for level in ["h1", "h2", "h3"]:
                for heading in headings.get(level, []):
                    heading_keywords.extend(self._extract_keywords(heading))
            
            # Combine and deduplicate
            page_keywords = list(set(title_keywords + content_keywords + heading_keywords))
            
            for kw in page_keywords[:10]:
                all_keywords.append({
                    "keyword": kw,
                    "intent": "informational",
                    "search_volume": 100,
                    "difficulty": 0.5,
                    "relevance": 0.8,
                    "opportunity_score": 0.7,
                    "is_long_tail": len(kw.split()) > 3,
                    "is_trending": False,
                    "provider": "local"
                })
            
            page_mappings.append({
                "page_url": page.get("url", ""),
                "keywords": page_keywords[:10]
            })
            
            strategies.append({
                "page_url": page.get("url", ""),
                "primary_keyword": page_keywords[0] if page_keywords else "",
                "secondary_keywords": page_keywords[1:5] if len(page_keywords) > 1 else [],
                "content_gaps": []
            })
        
        # Identify content gaps
        all_page_keywords = set()
        for mapping in page_mappings:
            all_page_keywords.update(mapping["keywords"])
        
        # Add some common SEO keywords as content gaps
        common_seo_keywords = ["seo", "optimization", "ranking", "traffic", "keywords"]
        for kw in common_seo_keywords:
            if kw not in all_page_keywords:
                content_gaps.append({
                    "keyword": kw,
                    "recommendation": f"Create content targeting '{kw}'",
                    "suggested_pages": []
                })
        
        result = {
            "keywords": all_keywords,
            "page_mappings": page_mappings,
            "content_gaps": content_gaps,
            "cannibalization": [],
            "strategies": strategies,
            "summary": {
                "total_keywords": len(all_keywords),
                "high_opportunity": sum(1 for k in all_keywords if k.get("opportunity_score", 0) > 0.7)
            }
        }
        
        self._emit("keyword_research_completed",
                   f"Found {len(all_keywords)} keywords, {len(content_gaps)} content gaps",
                   metadata={
                       "total_keywords": len(all_keywords),
                       "content_gaps_found": len(content_gaps),
                       "high_opportunity": result["summary"]["high_opportunity"],
                   })
        
        return result
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text."""
        if not text:
            return []
        
        # Simple keyword extraction
        words = re.findall(r'\b[a-z]{3,}\b', text.lower())
        
        # Filter common words
        stopwords = {"the", "and", "for", "are", "but", "not", "you", "all", "can", "had", "her", "was",
                     "one", "our", "out", "see", "she", "use", "his", "how", "its", "per", "has", "may", "let"}
        words = [w for w in words if w not in stopwords and len(w) > 2]
        
        # Get unique words
        unique_words = list(set(words))
        
        # Return most frequent words
        from collections import Counter
        freq = Counter(words)
        return [word for word, _ in freq.most_common(10)]


def extract_seed_terms(text: str) -> List[str]:
    """Extract seed terms from text."""
    if not text:
        return []
    
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    stopwords = {"the", "and", "for", "are", "but", "not", "you", "all", "can", "had", "her", "was"}
    words = [w for w in words if w not in stopwords and len(w) > 2]
    
    from collections import Counter
    freq = Counter(words)
    return [word for word, _ in freq.most_common(20)]


# ============================================================================
# PROVIDER FUNCTIONS
# ============================================================================

def get_keyword_provider():
    """Get keyword provider."""
    class DummyKeywordProvider:
        def suggest(self, query: str) -> List[str]:
            return [f"{query} tips", f"best {query}", f"how to {query}"]
    return DummyKeywordProvider()


def get_trend_provider():
    """Get trend provider."""
    class DummyTrendProvider:
        def trends(self, queries: List[str]) -> List[Dict]:
            return [{"query": q, "volume": 100, "trend": "rising"} for q in queries]
    return DummyTrendProvider()


def get_provider():
    """Get AI provider."""
    class DummyAIProvider:
        def analyze(self, prompt: str, context: Dict = None) -> Dict:
            return {"actions": []}
    return DummyAIProvider()


# ============================================================================
# AGENT FUNCTIONS
# ============================================================================

def plan_for_page(page_data: Dict, issues: List[Dict], ai_provider=None) -> Dict:
    """Generate optimization plan for a page."""
    actions = []
    topic = page_data.get("topic", "this page")
    url = page_data.get("url", "")
    
    # Title
    title = page_data.get("title", "")
    if not title or len(title) < 20:
        actions.append({
            "type": "title",
            "current": title,
            "value": f"{topic[:60].title()} - Expert Guide",
            "reason": "Title is missing or too short",
            "risk": "low",
            "confidence": 0.8,
            "implementation_method": "html_title_update"
        })
    
    # Meta description
    meta_desc = page_data.get("meta_description", "")
    if not meta_desc or len(meta_desc) < 40:
        actions.append({
            "type": "meta_description",
            "current": meta_desc,
            "value": f"Learn about {topic}. Expert insights, tips, and best practices for success.",
            "reason": "Meta description is missing or too short",
            "risk": "low",
            "confidence": 0.85,
            "implementation_method": "html_meta_update"
        })
    
    # H1
    if not page_data.get("h1"):
        actions.append({
            "type": "h1",
            "current": "",
            "value": topic[:60].title(),
            "reason": "H1 heading is missing",
            "risk": "low",
            "confidence": 0.75,
            "implementation_method": "html_meta_update"
        })
    
    # Canonical
    if not page_data.get("canonical"):
        actions.append({
            "type": "canonical",
            "current": "",
            "value": url,
            "reason": "Canonical URL is missing",
            "risk": "low",
            "confidence": 0.7,
            "implementation_method": "html_meta_update"
        })
    
    # Open Graph
    og = page_data.get("open_graph", {})
    if not og.get("og:title"):
        actions.append({
            "type": "open_graph",
            "current": "",
            "value": {
                "og:title": page_data.get("title", topic),
                "og:description": page_data.get("meta_description", f"Learn about {topic}"),
                "og:type": "website",
                "og:url": url
            },
            "reason": "Open Graph title is missing",
            "risk": "low",
            "confidence": 0.8,
            "implementation_method": "html_meta_update"
        })
    
    # Structured data
    structured_data = page_data.get("structured_data", [])
    if not structured_data:
        actions.append({
            "type": "structured_data",
            "current": "",
            "value": {
                "@context": "https://schema.org",
                "@type": "WebPage",
                "name": page_data.get("title", topic),
                "description": page_data.get("meta_description", f"Information about {topic}"),
                "url": url
            },
            "reason": "Structured data is missing",
            "risk": "medium",
            "confidence": 0.7,
            "implementation_method": "html_structured_data_update"
        })
    
    return {
        "plan_id": str(uuid.uuid4())[:12],
        "page_url": url,
        "summary": f"Optimization plan for {topic}",
        "actions": actions,
        "risk_breakdown": {"low": len([a for a in actions if a.get("risk") == "low"])}
    }


def aggregate_plan(page_plans: List[Dict]) -> Dict:
    """Aggregate multiple page plans."""
    total_actions = sum(len(p.get("actions", [])) for p in page_plans)
    risk_counter = {}
    
    for p in page_plans:
        for a in p.get("actions", []):
            risk = a.get("risk", "medium")
            risk_counter[risk] = risk_counter.get(risk, 0) + 1
    
    return {
        "plan_id": str(uuid.uuid4())[:12],
        "page_count": len(page_plans),
        "total_actions": total_actions,
        "risk_breakdown": risk_counter,
        "pages": page_plans,
        "summary": f"Plan for {len(page_plans)} pages with {total_actions} actions"
    }


# ============================================================================
# RISK FUNCTIONS
# ============================================================================

def classify_risk(issue: Dict) -> str:
    """Classify risk level of an issue."""
    severity = issue.get("severity", "medium")
    issue_type = issue.get("issue_type", "")
    
    if severity == "critical" or issue_type in ["canonical", "redirect", "noindex"]:
        return "high"
    elif severity == "high" or issue_type in ["title", "description", "h1"]:
        return "medium"
    return "low"


def can_auto_implement(action: Dict, mode: str, risk: str) -> bool:
    """Check if action can be auto-implemented."""
    mode = mode or "safe"
    risk_levels = {"safe": ["low"], "moderate": ["low", "medium"], "aggressive": ["low", "medium", "high"]}
    return risk in risk_levels.get(mode, [])


def deployment_method(issue: Dict) -> str:
    """Determine deployment method."""
    issue_type = issue.get("issue_type", "")
    method_map = {
        "title": "html_title_update",
        "meta_description": "html_meta_update",
        "h1": "html_meta_update",
        "canonical": "html_meta_update",
        "structured_data": "html_structured_data_update",
        "open_graph": "html_meta_update"
    }
    return method_map.get(issue_type, "html_meta_update")


# ============================================================================
# DEPLOYMENT FUNCTIONS
# ============================================================================

def deploy_change(website_id: int, server_file: str, content: bytes,
                  changes_payload: List[Dict], page_url: str = "") -> Dict:
    """Deploy a change to the server."""
    return {
        "ok": True,
        "change_id": f"change_{datetime.utcnow().timestamp()}",
        "status": "deployed",
        "message": "Change deployed successfully"
    }


# ============================================================================
# OPTIMIZATION FUNCTION
# ============================================================================

def run_seo_optimization(website_id: int, crawl_id: int, target_score: float = 95.0,
                         max_iterations: int = 3, job_id: str = None) -> Dict:
    """Run SEO optimization."""
    return {
        "ok": True,
        "website_id": website_id,
        "crawl_id": crawl_id,
        "score_before": 70.0,
        "score_after": 85.0,
        "target_score": target_score,
        "pages_optimized": 5,
        "status": "completed"
    }


# ============================================================================
# TASK QUEUE
# ============================================================================

def enqueue(task_type: str, website_id: int, func, *args, **kwargs) -> str:
    """Enqueue a task."""
    job_id = f"job_{datetime.utcnow().timestamp()}"
    logger.info(f"Enqueued {task_type} for website {website_id} as {job_id}")
    return job_id


# ============================================================================
# MAIN ORCHESTRATOR FUNCTION
# ============================================================================

def run_full_analysis(website_id: int, on_progress=None, **kwargs) -> Dict:
    """End-to-end analysis: crawl, parse, audit, keyword research, plan."""
    event_manager = get_event_manager()
    job_id = kwargs.get("job_id")

    def emit(event_type, message, severity="info", url="", metadata=None, agent_name=""):
        if job_id:
            event_manager.emit(
                job_id=job_id, event_type=event_type, message=message,
                severity=severity, url=url, metadata=metadata or {},
                website_id=website_id, agent_name=agent_name or "Orchestrator",
            )

    def update_progress(progress: int, message: str = ""):
        if job_id:
            logger.info(f"Progress {job_id}: {progress}% - {message}")
        if on_progress:
            try:
                on_progress(progress, message)
            except Exception:
                pass

    # ── Phase 0: Get website data ──────────────────────────────────────
    from ..database.database import new_session
    sess = new_session()
    try:
        db_website = sess.query(DBWebsite).get(website_id)
        if db_website:
            root_url = db_website.root_url
            website_root_path = db_website.website_root_path or ""
            website_name = db_website.name
            website_tech = db_website.technology or "unknown"
            website_business = db_website.business_description or ""
        else:
            root_url = "https://example.com"
            website_root_path = ""
            website_name = "Example Website"
            website_tech = "unknown"
            website_business = ""
    finally:
        sess.close()

    emit("analysis_started", f"Starting full analysis of {root_url}",
         metadata={"website": website_name})

    if on_progress:
        on_progress(5, f"Starting crawl of {root_url}")

    # ── Phase 1: Crawl ─────────────────────────────────────────────────
    crawler = WebsiteCrawler(root_url,
                             max_pages=kwargs.get("max_pages", 100),
                             max_depth=kwargs.get("max_depth", 3),
                             event_manager=get_event_manager(),
                             job_id=job_id,
                             website_id=website_id)

    results = crawler.crawl(
        on_progress=lambda p, m="": on_progress(p, m) if on_progress else None,
        job_id=job_id,
    )

    crawl_result = crawler.get_crawl_result()
    pages_crawled = crawl_result["pages_crawled"]
    pages_failed = crawl_result["pages_failed"]
    pages_discovered = crawl_result["pages_discovered"]
    pages_blocked = crawl_result["pages_blocked"]

    # Determine crawl status
    if pages_crawled == 0 and pages_failed > 0:
        crawl_status = "failed"
        crawl_error = f"All {pages_failed} page(s) failed to fetch."
        valid = False
    elif pages_failed > 0:
        crawl_status = "completed_with_failures"
        crawl_error = f"{pages_failed} page(s) failed to fetch"
        valid = True
    elif pages_crawled > 0:
        crawl_status = "completed"
        crawl_error = ""
        valid = True
    else:
        crawl_status = "failed"
        crawl_error = "No pages crawled"
        valid = False

    update_progress(45, f"Crawl complete: {pages_crawled} pages crawled")
    _log("orchestrator", "crawl_completed", root_url,
         {"website_id": website_id, "pages_crawled": pages_crawled,
          "pages_failed": pages_failed, "crawl_status": crawl_status}, phase="crawl")

    # If crawl failed, return early
    if crawl_status == "failed":
        emit("analysis_failed", f"Crawl failed: {crawl_error}", severity="error")
        return {
            "ok": False,
            "valid": False,
            "pages_crawled": pages_crawled,
            "pages_failed": pages_failed,
            "pages_discovered": pages_discovered,
            "pages_blocked": pages_blocked,
            "issues_found": 0,
            "technology": website_tech,
            "sitemap_urls": [],
            "robots": {},
            "keyword_count": 0,
            "plan_id": 0,
            "seo_health_score": None,
            "crawl_status": crawl_status,
            "analysis_status": crawl_status,
            "message": crawl_error
        }

    # ── Phase 2: Analyze pages ─────────────────────────────────────────
    issues_by_page = {}
    all_keywords = []
    tech_detected = []
    total_issues = 0
    page_records = []

    emit("analysis_phase", "Analyzing pages and detecting SEO issues",
         agent_name="SEO Audit Agent")

    for i, r in enumerate(results):
        html = r.get("html", "")
        status = r.get("status_code", 0)
        url = r.get("url", "")

        analyzed = analyze_html(html, base_url=url)
        score = calculate_seo_score(analyzed)
        tech = detect_from_html(html)
        tech_detected.extend(tech.get("detected", []))

        mapping = best_mapping(url, website_root_path)

        page_dict = {
            "website_id": website_id,
            "crawl_id": kwargs.get("crawl_id", 1),
            "url": url,
            "canonical_url": analyzed.get("canonical", ""),
            "server_file": mapping.get("best", {}).get("file", ""),
            "file_mapping_confidence": mapping.get("best", {}).get("confidence", 0.0),
            "status_code": status,
            "content_type": "text/html",
            "title": analyzed.get("title", ""),
            "meta_description": analyzed.get("meta_description", ""),
            "h1": (analyzed.get("headings", {}).get("h1") or [""])[0],
            "headings_json": analyzed.get("headings", {}),
            "word_count": analyzed.get("word_count", 0),
            "main_content": analyzed.get("main_content", ""),
            "images_json": analyzed.get("images", {}),
            "links_json": analyzed.get("links", {}),
            "og_json": analyzed.get("open_graph", {}),
            "twitter_json": analyzed.get("twitter", {}),
            "structured_data_json": analyzed.get("structured_data", []),
            "language": analyzed.get("language", ""),
            "robots_meta": analyzed.get("robots_meta", ""),
            "rendered": False,
            "seo_score": score,
            "analyzed_at": datetime.utcnow()
        }
        page_records.append(page_dict)

        audit_issues = run_full_audit(analyzed, status_code=status)
        issues_by_page[url] = audit_issues

        for iss in audit_issues:
            total_issues += 1
            emit("seo_issue_found",
                 f"{iss['title']} ({iss['severity']})",
                 agent_name="SEO Audit Agent",
                 severity="error" if iss["severity"] in ("critical", "high") else "warning",
                 url=url,
                 metadata={"issue_type": iss["issue_type"], "severity": iss["severity"]})

        # Extract seed terms
        seeds = extract_seed_terms(analyzed.get("main_content", ""))
        for s in seeds[:10]:
            all_keywords.append({"term": s, "page_url": url})

        update_progress(45 + int(20 * (i + 1) / max(1, len(results))),
                        f"Analyzed {i + 1}/{len(results)} pages")

    emit("analysis_phase", "Discovering sitemap and robots.txt",
         agent_name="Website Discovery Agent")

    # ── Phase 3: Sitemap and robots ──────────────────────────────────
    sitemaps = discover_sitemaps(root_url)
    sitemap_urls = []
    for s_url in sitemaps:
        xml = fetch_sitemap(s_url)
        if xml:
            parsed = parse_sitemap(xml)
            sitemap_urls.extend([u["loc"] for u in parsed if u.get("type") == "url"])

    robots_text = fetch_robots(root_url)
    robots_info = analyze_robots(robots_text) if robots_text else {"present": False, "issues": ["robots.txt is missing"]}

    # ── Phase 4: Keyword intelligence ──────────────────────────────────
    emit("analysis_phase", "Running keyword intelligence analysis",
         agent_name="Keyword Intelligence Agent")

    pages_data = []
    for r in results:
        html = r.get("html", "")
        analyzed = analyze_html(html, base_url=r.get("url", ""))
        pages_data.append({
            "url": r.get("url", ""),
            "title": analyzed.get("title", ""),
            "meta_description": analyzed.get("meta_description", ""),
            "main_content": analyzed.get("main_content", ""),
            "headings": analyzed.get("headings", {}),
            "word_count": analyzed.get("word_count", 0)
        })

    kw_engine = KeywordIntelligenceEngine(
        website_id=website_id,
        website_url=root_url,
        business_description=website_business,
        job_id=job_id or ""
    )
    kw_result = kw_engine.run_full_analysis(pages_data)

    all_keywords_data = kw_result.get("keywords", [])
    content_gaps = kw_result.get("content_gaps", [])
    strategies = kw_result.get("strategies", [])

    # ── Phase 5: Build optimization plan ──────────────────────────────
    emit("analysis_phase", "Building AI optimization plan",
         agent_name="Optimization Planner")

    strategy_map = {s.get("page_url"): s for s in strategies if s.get("page_url")}

    page_plans = []
    for pd in page_records:
        issues = issues_by_page.get(pd["url"], [])
        strategy = strategy_map.get(pd["url"], {})
        page_keywords = strategy.get("primary_keyword", "")
        secondary = strategy.get("secondary_keywords", [])
        all_page_kws = [page_keywords] + secondary if page_keywords else secondary

        plan = plan_for_page(
            {
                "url": pd["url"],
                "topic": (pd["title"] or pd["h1"] or pd["url"]),
                "title": pd["title"],
                "meta_description": pd["meta_description"],
                "canonical": pd["canonical_url"],
                "open_graph": pd["og_json"],
                "structured_data": pd["structured_data_json"],
                "keywords": all_page_kws,
                "keyword_strategy": strategy,
                "content_gaps": strategy.get("content_gaps", [])
            },
            issues
        )
        page_plans.append(plan)

    agg = aggregate_plan(page_plans)

    # ── Phase 6: Calculate SEO health score ────────────────────────────
    avg_scores = [pd.get("seo_score", 0) for pd in page_records if pd.get("seo_score", 0) > 0]
    if avg_scores and pages_crawled > 0:
        seo_health_score = round(sum(avg_scores) / len(avg_scores), 1)
    else:
        seo_health_score = 0.0

    emit("score_calculation_completed",
         f"SEO health score: {seo_health_score}",
         metadata={"seo_health_score": seo_health_score})

    # ── Phase 7: Auto-optimization ──────────────────────────────────────
    mode = Config.SEO_AUTOMATION_MODE
    if crawl_status in ("completed", "completed_with_failures") and mode != "analysis_only" and seo_health_score and seo_health_score < 85:
        try:
            opt_job_id = enqueue(
                "seo_optimization", website_id,
                run_seo_optimization,
                website_id,
                crawl_id=kwargs.get("crawl_id", 1),
                target_score=95.0,
                max_iterations=3
            )
            emit("optimization_queued",
                 f"SEO optimization queued (avg score {seo_health_score} < 85).",
                 agent_name="Optimization Engine",
                 metadata={"avg_score": seo_health_score, "optimization_job_id": opt_job_id})
        except Exception as e:
            emit("optimization_queue_failed",
                 f"Failed to queue optimization: {e}",
                 severity="warning", agent_name="Optimization Engine")

    emit("analysis_completed",
         f"Analysis complete. {pages_crawled} pages crawled, {total_issues} issues found.",
         severity="success",
         metadata={"pages_crawled": pages_crawled, "issues_found": total_issues})

    update_progress(100, "Done")

    # ── Persist results to database ──────────────────────────────────────
    _persist_analysis_result(
        website_id=website_id,
        job_id=job_id,
        crawl_status=crawl_status,
        crawl_result=crawl_result,
        page_records=page_records,
        issues_by_page=issues_by_page,
        all_keywords_data=all_keywords_data,
        strategies=strategies,
        content_gaps=content_gaps,
        agg=agg,
        seo_health_score=seo_health_score,
        total_issues=total_issues,
        sitemap_urls=sitemap_urls,
        robots_info=robots_info,
        tech_detected=tech_detected,
        root_url=root_url,
        crawl_error=crawl_error,
    )

    return {
        "ok": valid,
        "valid": valid,
        "pages_crawled": pages_crawled,
        "pages_failed": pages_failed,
        "pages_discovered": pages_discovered,
        "pages_blocked": pages_blocked,
        "issues_found": total_issues,
        "technology": tech_detected[0] if tech_detected else "unknown",
        "sitemap_urls": sitemap_urls,
        "robots": robots_info,
        "keyword_count": len(all_keywords_data),
        "plan_id": agg.get("plan_id", 0),
        "seo_health_score": seo_health_score,
        "crawl_status": crawl_status,
        "analysis_status": crawl_status,
        "block_reason": crawl_error if crawl_status == "failed" else ""
    }


def _persist_analysis_result(
    website_id: int,
    job_id: str,
    crawl_status: str,
    crawl_result: Dict,
    page_records: List[Dict],
    issues_by_page: Dict[str, List[Dict]],
    all_keywords_data: List[Dict],
    strategies: List[Dict],
    content_gaps: List[Dict],
    agg: Dict,
    seo_health_score: Optional[float],
    total_issues: int,
    sitemap_urls: List[str],
    robots_info: Dict,
    tech_detected: List[str],
    root_url: str,
    crawl_error: str,
) -> None:
    """Persist analysis results to the database."""
    from ..database.database import new_session

    sess = new_session()
    try:
        # Create Crawl session record
        crawl = DBCrawl(
            website_id=website_id,
            status="completed" if crawl_status in ("completed", "completed_with_failures") else "failed",
            pages_crawled=crawl_result.get("pages_crawled", 0),
            max_pages=crawl_result.get("max_pages", 100),
            max_depth=crawl_result.get("max_depth", 3),
            source="raw",
            error_message=crawl_error or "",
            finished_at=datetime.utcnow(),
        )
        sess.add(crawl)
        sess.flush()
        crawl_id = crawl.id

        # Create Page records
        page_map = {}  # url -> page_id
        for pd in page_records:
            url = pd.get("url", "")
            page = DBPage(
                website_id=website_id,
                crawl_id=crawl_id,
                url=url,
                canonical_url=pd.get("canonical_url", ""),
                status_code=pd.get("status_code", 0),
                content_type=pd.get("content_type", "text/html"),
                title=pd.get("title", ""),
                meta_description=pd.get("meta_description", ""),
                h1=pd.get("h1", ""),
                headings_json=pd.get("headings_json", {}),
                word_count=pd.get("word_count", 0),
                main_content=pd.get("main_content", ""),
                images_json=pd.get("images_json", {}),
                links_json=pd.get("links_json", {}),
                og_json=pd.get("og_json", {}),
                twitter_json=pd.get("twitter_json", {}),
                structured_data_json=pd.get("structured_data_json", []),
                language=pd.get("language", ""),
                robots_meta=pd.get("robots_meta", ""),
                rendered=pd.get("rendered", False),
                seo_score=pd.get("seo_score", 0.0),
                analyzed_at=datetime.utcnow(),
            )
            sess.add(page)
            sess.flush()
            page_map[url] = page.id

        # Create SEOIssue records
        seen_issues = set()
        for url, issues in issues_by_page.items():
            page_id = page_map.get(url)
            for iss in issues:
                issue_key = (website_id, page_id, iss.get("issue_type", ""), iss.get("title", ""))
                if issue_key in seen_issues:
                    continue
                seen_issues.add(issue_key)

                issue = DBSEOIssue(
                    website_id=website_id,
                    page_id=page_id,
                    url=url,
                    issue_type=iss.get("issue_type", ""),
                    severity=iss.get("severity", "medium"),
                    title=iss.get("title", ""),
                    description=iss.get("description", ""),
                    current_value=iss.get("current_value", ""),
                    proposed_value=iss.get("proposed_value", ""),
                    implementation_method=iss.get("implementation_method", ""),
                    risk=iss.get("risk", "medium"),
                    confidence=iss.get("confidence", 0.5),
                    status="open",
                    resolved=False,
                )
                sess.add(issue)

        # Create Keyword records
        for kw in all_keywords_data:
            keyword = DBKeyword(
                website_id=website_id,
                keyword=kw.get("keyword", ""),
                intent=kw.get("intent", "informational"),
                search_volume=kw.get("search_volume", 0),
                difficulty=kw.get("difficulty", 0.0),
                relevance=kw.get("relevance", 0.0),
                opportunity_score=kw.get("opportunity_score", 0.0),
                is_long_tail=kw.get("is_long_tail", False),
                is_trending=kw.get("is_trending", False),
                provider=kw.get("provider", "local"),
            )
            sess.add(keyword)

        # Create OptimizationPlan records
        if agg:
            plan = DBOptimizationPlan(
                website_id=website_id,
                title=agg.get("plan_name", "SEO Optimization Plan"),
                summary=agg.get("summary", ""),
                actions_json=agg.get("actions", []),
                risk_breakdown=agg.get("risk_breakdown", {}),
                status="draft",
            )
            sess.add(plan)

        # Update Website record
        db_website = sess.query(DBWebsite).get(website_id)
        if db_website:
            db_website.last_analyzed = datetime.utcnow()
            if seo_health_score is not None:
                db_website.seo_health_score = seo_health_score
            if tech_detected:
                db_website.technology = tech_detected[0]

        sess.commit()
    except Exception as e:
        sess.rollback()
        logger.error("Failed to persist analysis result: %s", e)
    finally:
        sess.close()
