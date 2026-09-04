"""Automatic SEO optimization engine.

Runs after a full analysis when the average SEO score is below target.
Iteratively optimizes the lowest-scoring pages, verifies score improvement,
and stops when the target is reached or no safe improvements remain.

Database sessions are opened only for brief reads/writes and are never
held open during HTTP requests, AI calls, or HTML modification.
"""
from __future__ import annotations
import os
import re
import logging
import requests
from datetime import datetime
from typing import Dict, List, Optional, Any, Set, Tuple
from urllib.parse import urlparse

# Setup logging
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Configuration for SEO optimization."""
    SEO_AUTOMATION_MODE = "safe"  # safe, moderate, aggressive
    CRAWL_MAX_PAGES = 100
    CRAWL_MAX_DEPTH = 3
    CRAWL_DELAY_SECONDS = 1.0
    USE_PLAYWRIGHT = False
    PLAYWRIGHT_TIMEOUT = 30
    MAX_OPTIMIZATION_PAGES = 50
    MIN_SCORE_IMPROVEMENT = 0.5


# ============================================================================
# DATABASE MODELS (Simplified for standalone use)
# ============================================================================

class DatabaseModels:
    """Placeholder for database models."""
    pass


class Website:
    """Website model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.name = kwargs.get('name', '')
        self.root_url = kwargs.get('root_url', '')
        self.website_root_path = kwargs.get('website_root_path', '')
        self.connection_type = kwargs.get('connection_type', '')
        self.architecture_type = kwargs.get('architecture_type', 'static_html')
        self.deployment_strategy = kwargs.get('deployment_strategy', 'direct_html')
        self.seo_health_score = kwargs.get('seo_health_score', 0.0)
        self.last_analyzed = kwargs.get('last_analyzed')


class Page:
    """Page model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.website_id = kwargs.get('website_id')
        self.crawl_id = kwargs.get('crawl_id')
        self.url = kwargs.get('url', '')
        self.server_file = kwargs.get('server_file', '')
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


class SEOIssue:
    """SEO Issue model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.website_id = kwargs.get('website_id')
        self.page_id = kwargs.get('page_id')
        self.issue_type = kwargs.get('issue_type', '')
        self.severity = kwargs.get('severity', 'medium')
        self.title = kwargs.get('title', '')
        self.description = kwargs.get('description', '')
        self.current_value = kwargs.get('current_value', '')
        self.proposed_value = kwargs.get('proposed_value', '')
        self.implementation_method = kwargs.get('implementation_method', '')
        self.risk = kwargs.get('risk', 'medium')
        self.confidence = kwargs.get('confidence', 0.7)
        self.resolved = kwargs.get('resolved', False)


class SEOChange:
    """SEO Change model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.website_id = kwargs.get('website_id')
        self.page_id = kwargs.get('page_id')
        self.change_type = kwargs.get('change_type', '')
        self.old_value = kwargs.get('old_value', '')
        self.new_value = kwargs.get('new_value', '')
        self.backup_id = kwargs.get('backup_id', '')
        self.created_at = kwargs.get('created_at', datetime.utcnow())


class SEOOptimization:
    """SEO Optimization record model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.website_id = kwargs.get('website_id')
        self.crawl_id = kwargs.get('crawl_id')
        self.status = kwargs.get('status', 'running')
        self.score_before = kwargs.get('score_before', 0.0)
        self.score_after = kwargs.get('score_after', 0.0)
        self.target_score = kwargs.get('target_score', 95.0)
        self.pages_optimized = kwargs.get('pages_optimized', 0)
        self.pages_remaining = kwargs.get('pages_remaining', 0)
        self.max_iterations = kwargs.get('max_iterations', 3)
        self.iteration = kwargs.get('iteration', 0)
        self.changes_applied = kwargs.get('changes_applied', 0)
        self.finished_at = kwargs.get('finished_at')
        self.created_at = kwargs.get('created_at', datetime.utcnow())


class PageOptimization:
    """Page Optimization record model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.optimization_id = kwargs.get('optimization_id')
        self.page_id = kwargs.get('page_id')
        self.page_url = kwargs.get('page_url', '')
        self.original_score = kwargs.get('original_score', 0.0)
        self.optimized_score = kwargs.get('optimized_score', 0.0)
        self.status = kwargs.get('status', 'pending')
        self.issues_detected = kwargs.get('issues_detected', [])
        self.changes_proposed = kwargs.get('changes_proposed', [])
        self.changes_applied = kwargs.get('changes_applied', [])
        self.change_reasons = kwargs.get('change_reasons', [])
        self.expected_benefit = kwargs.get('expected_benefit', {})
        self.failure_details = kwargs.get('failure_details', {})
        self.deploy_result = kwargs.get('deploy_result', {})
        self.optimization_timestamp = kwargs.get('optimization_timestamp', datetime.utcnow())


class OptimizationPlan:
    """Optimization Plan model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.website_id = kwargs.get('website_id')
        self.actions_json = kwargs.get('actions_json', {})
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


class Crawl:
    """Crawl model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.website_id = kwargs.get('website_id')
        self.status = kwargs.get('status', 'pending')
        self.started_at = kwargs.get('started_at', datetime.utcnow())
        self.completed_at = kwargs.get('completed_at')


class ProviderConfiguration:
    """Provider Configuration model."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.provider_type = kwargs.get('provider_type', '')
        self.provider_name = kwargs.get('provider_name', '')
        self.enabled = kwargs.get('enabled', False)


# ============================================================================
# DATABASE SESSION HELPERS
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


def log_audit(action_type: str, action_name: str, entity_id: str, data: Dict):
    """Log audit entry."""
    logger.info(f"AUDIT: {action_type} {action_name} {entity_id} {data}")


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


def _is_valid_html_page(url: str, html: str, status_code: int) -> bool:
    """Return True only if the URL and response look like a real HTML page."""
    if status_code < 200 or status_code >= 400:
        return False
    if not html or not html.strip():
        return False
    path = urlparse(url).path.lower()
    
    non_html_paths = {
        "/sitemap.xml", "/sitemap-index.xml", "/sitemap_index.xml",
        "/robots.txt", "/favicon.ico", "/site.webmanifest",
        "/manifest.json", "/service-worker.js",
    }
    if path in non_html_paths:
        return False
    
    non_html_extensions = {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif",
        ".pdf", ".zip", ".mp4", ".mp3", ".wav", ".css", ".js", ".mjs",
        ".map", ".woff", ".woff2", ".ttf", ".eot", ".json", ".xml",
        ".txt", ".rss", ".atom", ".webmanifest", ".manifest",
        ".cur", ".wasm", ".swf",
    }
    if any(path.endswith(ext) for ext in non_html_extensions):
        return False
    
    lowered = html.lstrip().lower()
    if lowered.startswith("<!doctype") or lowered.startswith("<html"):
        return True
    if "<html" in lowered[:400].lower():
        return True
    return len(html) > 200


# ============================================================================
# WEBSITE ANALYSIS FUNCTIONS
# ============================================================================

def analyze_html(html: str, base_url: str = "") -> Dict:
    """Analyze HTML for SEO purposes."""
    from bs4 import BeautifulSoup
    
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
            import json
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
    max_score = 100.0
    
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
    
    return min(score, max_score)


# ============================================================================
# EVENT MANAGER
# ============================================================================

class EventManager:
    """Event manager for emitting events."""
    
    def __init__(self):
        self._handlers = {}
        self._control_signals = {}
    
    def emit(self, job_id: str = None, event_type: str = "", message: str = "",
             agent_name: str = "", severity: str = "info", url: str = "",
             metadata: Dict = None, website_id: int = None):
        """Emit an event."""
        event = {
            "event_type": event_type,
            "message": message,
            "agent_name": agent_name or "Optimization Engine",
            "severity": severity,
            "url": url,
            "metadata": metadata or {},
            "website_id": website_id,
            "timestamp": datetime.utcnow().isoformat()
        }
        if job_id and job_id in self._handlers:
            for handler in self._handlers.get(job_id, []):
                try:
                    handler(event)
                except Exception:
                    pass
        
        # Log to console
        if severity in ("error", "warning"):
            logger.warning(f"{severity.upper()}: {message}")
        else:
            logger.info(f"{message}")
    
    def register_handler(self, job_id: str, handler):
        if job_id not in self._handlers:
            self._handlers[job_id] = []
        self._handlers[job_id].append(handler)
    
    def check_control_signal(self, job_id: str) -> str:
        return self._control_signals.get(job_id, "continue")
    
    def set_control_signal(self, job_id: str, signal: str):
        self._control_signals[job_id] = signal


_event_manager = None

def get_event_manager() -> EventManager:
    global _event_manager
    if _event_manager is None:
        _event_manager = EventManager()
    return _event_manager


# ============================================================================
# DEPLOYMENT FUNCTIONS
# ============================================================================

def _safe_remote_root(website: Website, conn: Connection) -> str:
    """Get safe remote root path."""
    if website and website.website_root_path:
        return website.website_root_path.rstrip("/")
    return "/"


def _resolve_remote_path(url: str, website_root_path: str = "") -> str:
    """Resolve remote file path from URL."""
    path = urlparse(url).path.lstrip("/")
    if website_root_path:
        return f"{website_root_path.rstrip('/')}/{path}"
    return path or "index.html"


def deploy_change(website_id: int, server_file: str, content: bytes,
                  changes_payload: List[Dict], page_url: str = "") -> Dict:
    """Deploy a change to the server."""
    # Simulated deployment
    return {
        "ok": True,
        "change_id": f"change_{datetime.utcnow().timestamp()}",
        "status": "deployed",
        "message": "Change deployed successfully"
    }


def rollback_change(change_id: str) -> Dict:
    """Rollback a change."""
    return {
        "ok": True,
        "message": "Rollback successful"
    }


# ============================================================================
# PROVIDER FUNCTIONS
# ============================================================================

def get_trend_provider():
    """Get trend provider."""
    class DummyTrendProvider:
        def trends(self, queries: List[str]) -> List[Dict]:
            return [{"query": q, "volume": 100, "trend": "rising"} for q in queries]
    return DummyTrendProvider()


def _has_real_trend_provider(website_id: int) -> bool:
    """Check if a real trend provider is available."""
    return False  # Default to no trend provider


# ============================================================================
# URL MAPPING
# ============================================================================

def best_mapping(url: str, website_root_path: str) -> Dict:
    """Get best URL to file mapping."""
    path = urlparse(url).path.lstrip("/")
    if not path:
        path = "index.html"
    elif not path.endswith(".html") and not "." in path:
        path = f"{path}.html"
    
    return {
        "best": {
            "file": path,
            "confidence": 1.0
        }
    }


# ============================================================================
# AGENT FUNCTIONS
# ============================================================================

def plan_for_page(page_data: Dict, issues: List[Dict]) -> Dict:
    """Generate optimization plan for a page."""
    actions = []
    
    # Check title
    title = page_data.get("title", "")
    if not title or len(title) < 20:
        actions.append({
            "type": "title",
            "value": f"{page_data.get('topic', 'Page')} - SEO Optimized",
            "reason": "Title is missing or too short",
            "risk": "low",
            "confidence": 0.8,
            "implementation_method": "html_meta_update"
        })
    
    # Check meta description
    meta_desc = page_data.get("meta_description", "")
    if not meta_desc or len(meta_desc) < 40:
        primary = page_data.get("keywords", [""])[0] if page_data.get("keywords") else ""
        topic = page_data.get("topic", "")
        actions.append({
            "type": "meta_description",
            "value": f"Learn about {topic or primary or 'this page'} and improve your SEO with our expert tips.",
            "reason": "Meta description is missing or too short",
            "risk": "low",
            "confidence": 0.85,
            "implementation_method": "html_meta_update"
        })
    
    # Check h1
    if not page_data.get("h1"):
        actions.append({
            "type": "h1",
            "value": page_data.get("topic", "Welcome"),
            "reason": "H1 heading is missing",
            "risk": "low",
            "confidence": 0.75,
            "implementation_method": "html_meta_update"
        })
    
    # Check canonical
    if not page_data.get("canonical"):
        actions.append({
            "type": "canonical",
            "value": page_data.get("url", ""),
            "reason": "Canonical URL is missing",
            "risk": "low",
            "confidence": 0.7,
            "implementation_method": "html_meta_update"
        })
    
    # Check Open Graph
    og = page_data.get("open_graph", {})
    if not og.get("og:title"):
        actions.append({
            "type": "og_title",
            "value": page_data.get("title", page_data.get("topic", "")),
            "reason": "Open Graph title is missing",
            "risk": "low",
            "confidence": 0.8,
            "implementation_method": "html_meta_update"
        })
    
    if not og.get("og:description"):
        actions.append({
            "type": "og_description",
            "value": page_data.get("meta_description", f"Learn about {page_data.get('topic', 'this page')}"),
            "reason": "Open Graph description is missing",
            "risk": "low",
            "confidence": 0.8,
            "implementation_method": "html_meta_update"
        })
    
    return {"actions": actions}


# ============================================================================
# RISK ASSESSMENT
# ============================================================================

def can_auto_implement(action: Dict, mode: str, risk: str) -> bool:
    """Check if action can be auto-implemented based on risk and mode."""
    mode = mode or "safe"
    risk_levels = {"safe": ["low"], "moderate": ["low", "medium"], "aggressive": ["low", "medium", "high"]}
    return risk in risk_levels.get(mode, [])


# ============================================================================
# MODIFIER FUNCTIONS
# ============================================================================

def apply_changes(html: str, changes: List[Dict]) -> Tuple[str, List[Dict]]:
    """Apply SEO changes to HTML."""
    from bs4 import BeautifulSoup
    
    soup = BeautifulSoup(html, "html.parser")
    applied_log = []
    
    for change in changes:
        change_type = change.get("type", "")
        value = change.get("value", "")
        
        if change_type == "title":
            if soup.title:
                soup.title.string = value
            else:
                title_tag = soup.new_tag("title")
                title_tag.string = value
                if soup.head:
                    soup.head.append(title_tag)
            applied_log.append({"type": change_type, "status": "applied"})
        
        elif change_type == "meta_description":
            meta_tag = soup.find("meta", attrs={"name": "description"})
            if meta_tag:
                meta_tag["content"] = value
            else:
                meta_tag = soup.new_tag("meta")
                meta_tag["name"] = "description"
                meta_tag["content"] = value
                if soup.head:
                    soup.head.append(meta_tag)
            applied_log.append({"type": change_type, "status": "applied"})
        
        elif change_type == "h1":
            h1_tag = soup.find("h1")
            if h1_tag:
                h1_tag.string = value
            else:
                h1_tag = soup.new_tag("h1")
                h1_tag.string = value
                body = soup.find("body")
                if body:
                    body.insert(0, h1_tag)
            applied_log.append({"type": change_type, "status": "applied"})
        
        elif change_type in ["og_title", "og_description"]:
            prop = "og:title" if change_type == "og_title" else "og:description"
            meta_tag = soup.find("meta", attrs={"property": prop})
            if meta_tag:
                meta_tag["content"] = value
            else:
                meta_tag = soup.new_tag("meta")
                meta_tag["property"] = prop
                meta_tag["content"] = value
                if soup.head:
                    soup.head.append(meta_tag)
            applied_log.append({"type": change_type, "status": "applied"})
        
        elif change_type == "canonical":
            link_tag = soup.find("link", attrs={"rel": "canonical"})
            if link_tag:
                link_tag["href"] = value
            else:
                link_tag = soup.new_tag("link")
                link_tag["rel"] = "canonical"
                link_tag["href"] = value
                if soup.head:
                    soup.head.append(link_tag)
            applied_log.append({"type": change_type, "status": "applied"})
    
    return str(soup), applied_log


# ============================================================================
# SPA DEPLOYMENT RESOLUTION
# ============================================================================

def _resolve_spa_deployment_target(website_id: int, url: str,
                                   changes: List[Dict], conn_obj) -> Optional[Dict]:
    """Determine deployment target for SPA SEO changes."""
    # Default to index.html for SPA
    return {
        "strategy": "spa_index_html",
        "server_file": "index.html",
        "reason": "SPA detected, using index.html",
        "ftp_files_inspected": ["index.html"]
    }


# ============================================================================
# PROGRESS RECORDING
# ============================================================================

def _record_progress(job_id: str, progress: int, message: str):
    """Record progress for a job."""
    logger.info(f"Progress {job_id}: {progress}% - {message}")


# ============================================================================
# CORE OPTIMIZATION FUNCTIONS
# ============================================================================

def _compute_valid_pages_average(website_id: int, crawl_id: int) -> Tuple[float, int, int]:
    """Compute average score across valid HTML pages only."""
    # Placeholder - in real implementation, this queries the database
    return 70.0, 10, 15


def _get_keyword_strategy(website_id: int, page_url: str) -> Dict:
    """Get keyword strategy for a page."""
    return {
        "primary_keyword": "seo optimization",
        "secondary_keywords": ["website seo", "seo tips", "search engine optimization"],
        "content_gaps": ["technical seo", "on-page seo"]
    }


def _snapshot_page(page: Page) -> Dict:
    """Capture a complete snapshot of a page's analysis state."""
    return {
        "page_id": page.id,
        "seo_score": page.seo_score,
        "word_count": page.word_count,
        "title": page.title,
        "meta_description": page.meta_description,
        "canonical_url": page.canonical_url,
        "h1": page.h1,
        "headings_json": page.headings_json,
        "main_content": page.main_content,
        "images_json": page.images_json,
        "links_json": page.links_json,
        "og_json": page.og_json,
        "twitter_json": page.twitter_json,
        "structured_data_json": page.structured_data_json,
        "robots_meta": page.robots_meta,
        "language": page.language,
        "analyzed_at": page.analyzed_at.isoformat() if page.analyzed_at else None,
    }


def _restore_page_snapshot(page_id: int, snapshot: Dict, crawl_id: int) -> None:
    """Restore a page's analysis state from a saved snapshot."""
    logger.info(f"Restored page {page_id} from snapshot")


def _update_page_analysis(page_id: int, analyzed: Dict, new_score: float, crawl_id: int) -> None:
    """Update a Page record with fresh analysis results."""
    logger.info(f"Updated page {page_id} with score {new_score}")


def _page_already_optimized(website_id: int, page_id: int, change_type: str, optimization_id: int) -> bool:
    """Check if this page/change_type combo was already attempted."""
    return False


def _fetch_page_html(url: str) -> Optional[Tuple[str, int, str]]:
    """Fetch current HTML for a page."""
    result = fetch_real_html(url)
    if result.get("ok"):
        return result["html"], result.get("status_code", 200), "text/html"
    return None


def _optimize_single_page(
    website_id: int,
    page: Page,
    issues: List[Dict],
    keyword_strategy: Dict,
    mode: str,
    job_id: str,
    optimization_run_id: str,
    optimization_id: int,
    real_trend_available: bool,
    website_root_path: str = "",
) -> Dict:
    """Optimize a single page and return results."""
    event_manager = get_event_manager()
    url = page.url
    
    def emit(event_type, message, severity="info", url="", metadata=None, agent_name=""):
        if job_id:
            event_manager.emit(
                job_id=job_id, event_type=event_type, message=message,
                severity=severity, url=url, metadata=metadata or {},
                website_id=website_id, agent_name=agent_name or "Optimization Engine",
            )
    
    # 1. Fetch current HTML
    fetched = _fetch_page_html(url)
    if not fetched:
        emit("page_optimize_skipped", f"Could not fetch {url}", severity="warning", url=url,
             metadata={"reason": "fetch_failed"})
        return {
            "page_id": page.id, "page_url": url, "original_score": page.seo_score or 0,
            "optimized_score": page.seo_score or 0, "status": "skipped",
            "changes_applied": [], "change_reasons": [], "reason": "fetch_failed",
        }
    
    current_html, status_code, content_type = fetched
    
    # 2. Validate it's actually HTML
    if not _is_valid_html_page(url, current_html, status_code):
        emit("page_optimize_skipped", f"Skipped non-HTML resource: {url}", severity="warning", url=url,
             metadata={"reason": "non_html", "content_type": content_type})
        return {
            "page_id": page.id, "page_url": url, "original_score": page.seo_score or 0,
            "optimized_score": page.seo_score or 0, "status": "skipped",
            "changes_applied": [], "change_reasons": [], "reason": "non_html",
        }
    
    # 3. Analyze current state
    analyzed = analyze_html(current_html, base_url=url)
    original_score = calculate_seo_score(analyzed)
    
    # Save original snapshot
    original_snapshot = _snapshot_page(page)
    
    # 4. Generate optimization plan
    page_keywords = []
    primary = keyword_strategy.get("primary_keyword", "")
    secondary = keyword_strategy.get("secondary_keywords", [])
    if primary:
        page_keywords.append(primary)
    page_keywords.extend(secondary[:3])
    
    plan = plan_for_page(
        {
            "url": url,
            "topic": page.title or page.h1 or url,
            "title": page.title,
            "meta_description": page.meta_description,
            "canonical": page.canonical_url,
            "open_graph": page.og_json,
            "structured_data": page.structured_data_json,
            "keywords": page_keywords,
            "keyword_strategy": keyword_strategy,
            "content_gaps": keyword_strategy.get("content_gaps", []),
        },
        issues,
    )
    
    # 5. Filter actions by risk/mode
    safe_actions = []
    seen_change_types = set()
    for action in plan.get("actions", []):
        risk = action.get("risk", "medium")
        if not can_auto_implement({"risk": risk}, mode, risk):
            continue
        change_type = action.get("type", "meta_description")
        if change_type in seen_change_types:
            continue
        if _page_already_optimized(website_id, page.id, change_type, optimization_id):
            continue
        seen_change_types.add(change_type)
        safe_actions.append(action)
    
    if not safe_actions:
        emit("page_optimize_skipped", f"No safe actions for {url}", severity="info", url=url,
             metadata={"reason": "no_safe_actions"})
        return {
            "page_id": page.id, "page_url": url, "original_score": original_score,
            "optimized_score": original_score, "status": "skipped",
            "changes_applied": [], "change_reasons": [], "reason": "no_safe_actions",
        }
    
    # 6. Apply changes locally
    changes_payload = []
    change_reasons = []
    for a in safe_actions:
        changes_payload.append({
            "type": a.get("type", "meta_description"),
            "value": a.get("value", ""),
            "match": "",
            "reason": a.get("reason", ""),
            "risk": a.get("risk", "low"),
            "confidence": a.get("confidence", 0.7),
            "implementation_method": a.get("implementation_method", "html_meta_update"),
            "optimization_run_id": optimization_run_id,
        })
        change_reasons.append(a.get("reason", ""))
    
    new_html, applied_log = apply_changes(current_html, changes_payload)
    
    # 7. Re-analyze modified HTML
    modified_analyzed = analyze_html(new_html, base_url=url)
    proposed_score = calculate_seo_score(modified_analyzed)
    
    # 8. Only proceed if local score improved
    if proposed_score <= original_score:
        emit("page_optimize_skipped",
             f"Proposed change would not improve score {original_score} -> {proposed_score} for {url}",
             severity="warning", url=url,
             metadata={"original_score": original_score, "proposed_score": proposed_score})
        return {
            "page_id": page.id, "page_url": url, "original_score": original_score,
            "optimized_score": original_score, "status": "skipped",
            "changes_applied": [], "change_reasons": [], "reason": "score_not_improved",
            "proposed_score": proposed_score,
        }
    
    # 9. Deploy the change
    server_file = page.server_file or urlparse(url).path.lstrip("/") or "index.html"
    
    try:
        emit("deploy_started", f"Deploying {len(changes_payload)} change(s) for {url}",
             url=url, metadata={"server_file": server_file, "changes": len(changes_payload)})
        
        result = deploy_change(
            website_id,
            server_file,
            current_html.encode("utf-8"),
            changes_payload,
            page_url=url,
        )
        
        if not result.get("ok"):
            emit("page_optimize_failed",
                 f"Deploy failed for {url}: {result.get('message', 'Unknown error')}",
                 severity="error", url=url,
                 metadata={"error": result.get("message")})
            return {
                "page_id": page.id, "page_url": url, "original_score": original_score,
                "optimized_score": original_score, "status": "failed",
                "changes_applied": [], "change_reasons": [], "reason": "deploy_failed",
                "deploy_result": result,
            }
        
        emit("deploy_completed", f"Deployment succeeded for {url}",
             url=url, metadata={"change_id": result.get("change_id")})
        
        # 10. Update page with new analysis
        _update_page_analysis(page.id, modified_analyzed, proposed_score, page.crawl_id)
        
        emit("page_optimize_improved",
             f"SEO score improved from {original_score} to {proposed_score} for {url}",
             severity="success", url=url,
             metadata={
                 "original_score": original_score,
                 "proposed_score": proposed_score,
                 "changes_count": len(changes_payload),
             })
        
        return {
            "page_id": page.id, "page_url": url,
            "original_score": original_score, "optimized_score": proposed_score,
            "status": "improved",
            "changes_applied": changes_payload,
            "change_reasons": change_reasons,
            "reason": "score_improved",
            "proposed_score": proposed_score,
        }
    
    except Exception as e:
        emit("page_optimize_failed",
             f"Exception optimizing {url}: {e}",
             severity="error", url=url)
        return {
            "page_id": page.id, "page_url": url, "original_score": original_score,
            "optimized_score": original_score, "status": "failed",
            "changes_applied": [], "change_reasons": [], "reason": str(e),
        }


# ============================================================================
# MAIN OPTIMIZATION ENGINE
# ============================================================================

def run_seo_optimization(
    website_id: int,
    crawl_id: int,
    target_score: float = 95.0,
    max_iterations: int = 3,
    min_page_score: float = 0.0,
    on_progress=None,
    **kwargs,
) -> Dict:
    """Run automatic SEO optimization for a website."""
    event_manager = get_event_manager()
    job_id = kwargs.get("job_id")
    mode = Config.SEO_AUTOMATION_MODE
    optimization_run_id = f"OPT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{website_id}"
    
    def emit(event_type, message, severity="info", url="", metadata=None, agent_name=""):
        if job_id:
            event_manager.emit(
                job_id=job_id, event_type=event_type, message=message,
                severity=severity, url=url, metadata=metadata or {},
                website_id=website_id, agent_name=agent_name or "Optimization Engine",
            )
    
    def update_progress(progress: int, message: str = ""):
        if job_id:
            _record_progress(job_id, progress, message)
        if on_progress:
            try:
                on_progress(progress, message)
            except Exception:
                pass
    
    # Get website info
    website = Website(id=website_id, root_url="https://example.com", name="Example Website")
    website_root_path = ""
    
    # Compute initial average
    initial_avg, valid_count, total_count = _compute_valid_pages_average(website_id, crawl_id)
    current_avg = initial_avg
    
    emit("optimization_started",
         f"Average SEO score is {current_avg}. Starting optimization.",
         metadata={
             "target_score": target_score,
             "mode": mode,
             "valid_pages": valid_count,
             "total_pages": total_count,
         })
    
    # Create sample pages
    pages = []
    for i in range(5):
        page = Page(
            id=i+1,
            website_id=website_id,
            crawl_id=crawl_id,
            url=f"https://example.com/page{i+1}",
            seo_score=50.0 + i * 5,
            title=f"Page {i+1}",
            meta_description=f"Description for page {i+1}",
            h1=f"Page {i+1} Heading",
            word_count=200 + i * 50,
            main_content=f"Content for page {i+1}",
        )
        pages.append(page)
    
    # Create optimization record
    opt_id = 1
    opt = SEOOptimization(
        id=opt_id,
        website_id=website_id,
        crawl_id=crawl_id,
        status="running",
        score_before=current_avg,
        target_score=target_score
    )
    
    total_changes_applied = 0
    pages_optimized_count = 0
    pages_failed_count = 0
    pages_rolled_back_count = 0
    stop_reason = "target_reached"
    all_iter_results = []
    
    real_trend_available = _has_real_trend_provider(website_id)
    
    for iteration in range(max_iterations):
        update_progress(10 + int(80 * iteration / max(1, max_iterations)),
                        f"Iteration {iteration + 1}/{max_iterations}")
        emit("optimization_iteration_started",
             f"Starting optimization iteration {iteration + 1}",
             metadata={"iteration": iteration + 1, "max_iterations": max_iterations})
        
        pages_optimized_this_iter = 0
        pages_failed_this_iter = 0
        pages_rolled_back_this_iter = 0
        iter_results = []
        
        for page in pages:
            if page.seo_score is None or page.seo_score >= target_score:
                continue
            
            page_issues = []
            keyword_strategy = _get_keyword_strategy(website_id, page.url)
            
            result = _optimize_single_page(
                website_id=website_id,
                page=page,
                issues=page_issues,
                keyword_strategy=keyword_strategy,
                mode=mode,
                job_id=job_id,
                optimization_run_id=optimization_run_id,
                optimization_id=opt_id,
                real_trend_available=real_trend_available,
                website_root_path=website_root_path,
            )
            
            iter_results.append(result)
            if result.get("status") == "improved":
                pages_optimized_this_iter += 1
                total_changes_applied += len(result.get("changes_applied", []))
            elif result.get("status") == "failed":
                pages_failed_this_iter += 1
                pages_failed_count += 1
            elif result.get("status") == "rolled_back":
                pages_rolled_back_this_iter += 1
                pages_rolled_back_count += 1
        
        pages_optimized_count += pages_optimized_this_iter
        
        # Recalculate average
        new_avg, valid_count, total_count = _compute_valid_pages_average(website_id, crawl_id)
        
        # Check if score improved
        if new_avg < current_avg:
            emit("optimization_improvement",
                 f"Score dropped from {current_avg} to {new_avg}",
                 severity="warning")
            stop_reason = "score_dropped"
            break
        
        current_avg = new_avg
        all_iter_results.extend(iter_results)
        
        emit("optimization_iteration_completed",
             f"Iteration {iteration + 1} complete. Average score: {new_avg}",
             metadata={"iteration": iteration + 1, "avg_score": new_avg})
        
        # Stop conditions
        if new_avg >= target_score:
            stop_reason = "target_reached"
            break
        if pages_optimized_this_iter == 0:
            stop_reason = "no_improvements"
            break
        if iteration >= max_iterations - 1:
            stop_reason = "max_iterations_reached"
            break
    
    # Finalize
    final_avg, _, _ = _compute_valid_pages_average(website_id, crawl_id)
    
    total_improved = sum(1 for r in all_iter_results if r.get("status") == "improved")
    total_failed = sum(1 for r in all_iter_results if r.get("status") == "failed")
    total_rolled_back = sum(1 for r in all_iter_results if r.get("status") == "rolled_back")
    total_skipped = sum(1 for r in all_iter_results if r.get("status") == "skipped")
    
    if total_improved > 0:
        final_status = "completed"
    else:
        final_status = "completed_no_changes"
    
    emit("optimization_completed",
         f"Website average SEO score: {initial_avg} -> {final_avg}.",
         severity="success" if final_status == "completed" else "warning",
         metadata={
             "score_before": initial_avg,
             "score_after": final_avg,
             "target_score": target_score,
             "pages_optimized": total_improved,
             "pages_failed": total_failed,
             "pages_rolled_back": total_rolled_back,
             "pages_skipped": total_skipped,
             "changes_applied": total_changes_applied,
             "stop_reason": stop_reason,
             "iterations": iteration + 1,
             "status": final_status,
         })
    
    update_progress(100, "Optimization complete")
    
    return {
        "ok": final_status == "completed",
        "website_id": website_id,
        "crawl_id": crawl_id,
        "optimization_id": opt_id,
        "score_before": initial_avg,
        "score_after": final_avg,
        "target_score": target_score,
        "pages_optimized": total_improved,
        "pages_failed": total_failed,
        "pages_rolled_back": total_rolled_back,
        "pages_skipped": total_skipped,
        "changes_applied": total_changes_applied,
        "stop_reason": stop_reason,
        "iterations": iteration + 1,
        "status": final_status,
    }
