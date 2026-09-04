"""URL-to-server-file mapping engine.

Maps public URLs to potential server files based on common conventions.
Returns confidence levels so we never modify files we're unsure about.
Supports various web server configurations and SPA routing patterns.
"""
from __future__ import annotations
import re
import os
import logging
from typing import Optional, Dict, List, Set, Tuple, Any
from urllib.parse import urlparse, unquote

# Setup logging
logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

INDEX_FILES = ["index.html", "index.htm", "default.html", "default.htm", "index.php", "index.asp", "index.aspx"]
ROOT_INDEX_FILES = ["index.html", "index.htm", "default.html", "default.htm", "index.php"]

STATIC_EXTENSIONS = {
    ".html", ".htm", ".php", ".asp", ".aspx", ".jsp", ".do", ".action",
    ".css", ".js", ".json", ".xml", ".txt", ".csv",
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico", ".webp",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".mp4", ".mp3", ".wav", ".avi", ".mov"
}

STATIC_ROUTES = [
    "/static/", "/assets/", "/dist/", "/build/", "/public/",
    "/images/", "/img/", "/css/", "/js/", "/fonts/", "/media/"
]

SPA_FRAMEWORKS = {
    "react": ["index.html", "asset-manifest.json", "manifest.json"],
    "vue": ["index.html", "manifest.json"],
    "angular": ["index.html", "main.js", "polyfills.js", "runtime.js"],
    "next": ["index.html", "_next/"],
    "nuxt": ["index.html", "_nuxt/"],
    "gatsby": ["index.html", "gatsby-"],
}


# ============================================================================
# MAPPING STRATEGIES
# ============================================================================

def is_static_asset_url(url: str) -> bool:
    """Check if URL is likely a static asset."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    
    # Check extension
    if any(path.endswith(ext) for ext in STATIC_EXTENSIONS):
        return True
    
    # Check static route patterns
    if any(route in path for route in STATIC_ROUTES):
        return True
    
    return False


def is_spa_route(url: str, architecture_type: str = "") -> bool:
    """Check if URL is likely an SPA route."""
    if is_static_asset_url(url):
        return False
    
    parsed = urlparse(url)
    path = parsed.path
    
    # SPA routes typically don't have file extensions
    if "." in path.split("/")[-1]:
        return False
    
    # Common SPA route patterns
    if architecture_type in ["react_spa", "vue_spa", "angular_spa", "javascript_spa"]:
        return True
    
    return True


def get_file_extension(path: str) -> str:
    """Get file extension from path."""
    filename = path.split("/")[-1]
    if "." in filename:
        return "." + filename.split(".")[-1].lower()
    return ""


def normalize_path(path: str) -> str:
    """Normalize a file path."""
    # Remove leading/trailing slashes
    path = path.strip("/")
    # Replace backslashes with forward slashes
    path = path.replace("\\", "/")
    # Remove double slashes
    while "//" in path:
        path = path.replace("//", "/")
    return path


# ============================================================================
# CANDIDATE GENERATION
# ============================================================================

def candidate_files_for_url(public_url: str, web_root: str = "", 
                           architecture_type: str = "") -> List[Dict]:
    """
    Return candidate server file paths for a given URL with confidence scores.
    
    Args:
        public_url: Public URL to map
        web_root: Web root path on server
        architecture_type: Architecture type (static_html, react_spa, etc.)
        
    Returns:
        List of candidate file paths with confidence scores
    """
    parsed = urlparse(public_url)
    path = parsed.path or "/"
    path = unquote(path)  # Decode URL-encoded characters
    
    # Remove query string and fragment
    path = path.split("?")[0].split("#")[0]
    
    # Normalize path
    path = normalize_path(path)
    
    candidates: List[Dict] = []
    base = (web_root or "").rstrip("/")
    base = normalize_path(base)
    
    # =========================================================================
    # Strategy 1: Direct file match
    # =========================================================================
    if "." in path.split("/")[-1] and not path.endswith("/"):
        # Has file extension
        file_path = path
        if base and not file_path.startswith(base):
            file_path = f"{base}/{file_path}" if base else file_path
        candidates.append({
            "file": file_path,
            "confidence": 0.95,
            "reason": "explicit file extension",
            "strategy": "direct_file"
        })
        return candidates  # Direct file is most likely, return early
    
    # =========================================================================
    # Strategy 2: Index file in directory
    # =========================================================================
    if path.endswith("/") or not path:
        dir_path = path.rstrip("/")
        for idx in INDEX_FILES:
            file_path = f"{dir_path}/{idx}" if dir_path else idx
            if base and not file_path.startswith(base):
                file_path = f"{base}/{file_path}" if base else file_path
            candidates.append({
                "file": file_path,
                "confidence": 0.85 if idx in ROOT_INDEX_FILES else 0.75,
                "reason": f"directory index file: {idx}",
                "strategy": "index_file"
            })
        return candidates
    
    # =========================================================================
    # Strategy 3: HTML file without extension
    # =========================================================================
    # Common patterns: /about -> about.html, about/index.html, about.php
    segments = [s for s in path.split("/") if s]
    rel_path = "/".join(segments)
    
    # 3a: Named HTML file
    file_path = f"{rel_path}.html"
    if base and not file_path.startswith(base):
        file_path = f"{base}/{file_path}" if base else file_path
    candidates.append({
        "file": file_path,
        "confidence": 0.70,
        "reason": "named .html file",
        "strategy": "html_file"
    })
    
    # 3b: PHP file (common for PHP sites)
    file_path = f"{rel_path}.php"
    if base and not file_path.startswith(base):
        file_path = f"{base}/{file_path}" if base else file_path
    candidates.append({
        "file": file_path,
        "confidence": 0.45,
        "reason": "named .php file",
        "strategy": "php_file"
    })
    
    # 3c: Directory with index.html
    for idx in INDEX_FILES[:2]:
        file_path = f"{rel_path}/{idx}"
        if base and not file_path.startswith(base):
            file_path = f"{base}/{file_path}" if base else file_path
        candidates.append({
            "file": file_path,
            "confidence": 0.55,
            "reason": f"directory with {idx}",
            "strategy": "directory_index"
        })
    
    # =========================================================================
    # Strategy 4: SPA routing
    # =========================================================================
    if is_spa_route(public_url, architecture_type):
        # SPA routes typically serve the same HTML file
        spa_index = "index.html"
        if base:
            spa_index = f"{base}/{spa_index}" if base else spa_index
        
        candidates.append({
            "file": spa_index,
            "confidence": 0.50,
            "reason": "SPA route (served from index.html)",
            "strategy": "spa_route"
        })
    
    # =========================================================================
    # Strategy 5: Clean URL patterns (WordPress, etc.)
    # =========================================================================
    # WordPress: /category/page -> /category/page.php
    if len(segments) == 2:
        file_path = f"{segments[0]}/{segments[1]}.php"
        if base and not file_path.startswith(base):
            file_path = f"{base}/{file_path}" if base else file_path
        candidates.append({
            "file": file_path,
            "confidence": 0.40,
            "reason": "WordPress-style rewrite",
            "strategy": "wordpress_rewrite"
        })
    
    # =========================================================================
    # Strategy 6: API routes
    # =========================================================================
    if "/api/" in path:
        # API routes often map to dedicated API handlers
        file_path = f"{rel_path}.php"
        if base and not file_path.startswith(base):
            file_path = f"{base}/{file_path}" if base else file_path
        candidates.append({
            "file": file_path,
            "confidence": 0.35,
            "reason": "API route",
            "strategy": "api_route"
        })
        
        # Also try JSON endpoint
        file_path = f"{rel_path}.json"
        if base and not file_path.startswith(base):
            file_path = f"{base}/{file_path}" if base else file_path
        candidates.append({
            "file": file_path,
            "confidence": 0.30,
            "reason": "API JSON endpoint",
            "strategy": "api_json"
        })
    
    # =========================================================================
    # Strategy 7: Trailing slash variants
    # =========================================================================
    # Try with trailing slash
    dir_path = path
    for idx in INDEX_FILES[:2]:
        file_path = f"{dir_path}/{idx}"
        if base and not file_path.startswith(base):
            file_path = f"{base}/{file_path}" if base else file_path
        candidates.append({
            "file": file_path,
            "confidence": 0.50,
            "reason": f"directory with trailing slash and {idx}",
            "strategy": "trailing_slash"
        })
    
    # =========================================================================
    # Strategy 8: Upper/lower case variants
    # =========================================================================
    # Some servers are case-sensitive
    if any(c.isupper() for c in path):
        lower_path = path.lower()
        file_path = f"{lower_path}.html"
        if base and not file_path.startswith(base):
            file_path = f"{base}/{file_path}" if base else file_path
        candidates.append({
            "file": file_path,
            "confidence": 0.35,
            "reason": "lowercase variant",
            "strategy": "case_variant"
        })
    
    # =========================================================================
    # Strategy 9: Common aliases
    # =========================================================================
    common_aliases = {
        "/about-us": "/about",
        "/contact-us": "/contact",
        "/home": "/",
        "/blog": "/articles",
    }
    
    for alias, target in common_aliases.items():
        if path == alias.lstrip("/"):
            file_path = target.lstrip("/")
            if not file_path:
                file_path = "index.html"
            elif not "." in file_path:
                file_path = f"{file_path}.html"
            
            if base and not file_path.startswith(base):
                file_path = f"{base}/{file_path}" if base else file_path
            
            candidates.append({
                "file": file_path,
                "confidence": 0.35,
                "reason": f"common alias: {alias} -> {target}",
                "strategy": "alias"
            })
            break
    
    # =========================================================================
    # Deduplicate candidates
    # =========================================================================
    seen = set()
    unique_candidates = []
    for c in candidates:
        file_key = c["file"].replace("\\", "/")
        if file_key not in seen:
            seen.add(file_key)
            unique_candidates.append(c)
    
    # Sort by confidence descending
    unique_candidates.sort(key=lambda x: x["confidence"], reverse=True)
    
    return unique_candidates


# ============================================================================
# BEST MAPPING
# ============================================================================

def best_mapping(public_url: str, web_root: str = "",
                 available_files: Optional[List[str]] = None,
                 architecture_type: str = "",
                 existing_mappings: Optional[List[Dict]] = None) -> Dict:
    """
    Find the best mapping for a URL to a server file.
    
    Args:
        public_url: Public URL to map
        web_root: Web root path on server
        available_files: List of available files on server
        architecture_type: Architecture type for SPA detection
        existing_mappings: Existing mappings for reference
        
    Returns:
        Dictionary with best mapping and all candidates
    """
    candidates = candidate_files_for_url(public_url, web_root, architecture_type)
    
    # Verify against available files
    if available_files:
        avail_norm = set()
        for f in available_files:
            f_norm = normalize_path(f)
            avail_norm.add(f_norm)
            # Also add without web_root if present
            if web_root and f_norm.startswith(normalize_path(web_root)):
                avail_norm.add(f_norm[len(normalize_path(web_root)):].lstrip("/"))
        
        for c in candidates:
            cf = normalize_path(c["file"])
            # Check exact match
            if cf in avail_norm or ("/" + cf) in avail_norm or cf.lstrip("/") in avail_norm:
                c["confidence"] = min(0.99, c["confidence"] + 0.2)
                c["verified"] = True
            
            # Check if any index file in directory exists
            elif "index" in c.get("reason", "").lower():
                dir_path = "/".join(cf.split("/")[:-1])
                for idx in INDEX_FILES:
                    idx_path = f"{dir_path}/{idx}".replace("//", "/")
                    if idx_path in avail_norm or idx_path.lstrip("/") in avail_norm:
                        c["confidence"] = min(0.99, c["confidence"] + 0.15)
                        c["verified"] = True
                        c["verified_file"] = idx_path
                        break
    
    # Sort by confidence descending
    candidates.sort(key=lambda x: x["confidence"], reverse=True)
    
    # Get best candidate
    best = candidates[0] if candidates else None
    
    # If no good confidence, log warning
    if best and best["confidence"] < 0.5:
        logger.warning(f"Low confidence mapping for {public_url}: {best['file']} ({best['confidence']})")
    
    return {
        "url": public_url,
        "best": best,
        "all_candidates": candidates,
        "has_good_match": best and best["confidence"] >= 0.6,
        "verified": best and best.get("verified", False),
        "architecture_type": architecture_type,
    }


def verify_mapping(mapping: Dict, available_files: List[str]) -> Dict:
    """
    Verify a mapping against available files.
    
    Args:
        mapping: Mapping dictionary from best_mapping
        available_files: List of available files
        
    Returns:
        Updated mapping with verification results
    """
    if not mapping or not mapping.get("best"):
        return mapping
    
    best = mapping["best"]
    file_path = normalize_path(best["file"])
    avail_norm = {normalize_path(f) for f in available_files}
    
    # Check if file exists
    if file_path in avail_norm or file_path.lstrip("/") in avail_norm:
        best["exists"] = True
        best["verified"] = True
        best["confidence"] = min(0.99, best["confidence"] + 0.1)
    else:
        best["exists"] = False
    
    mapping["best"] = best
    mapping["verified"] = best.get("verified", False)
    
    return mapping


# ============================================================================
# BATCH MAPPING
# ============================================================================

def batch_mapping(urls: List[str], web_root: str = "",
                  available_files: Optional[List[str]] = None,
                  architecture_type: str = "") -> Dict[str, Dict]:
    """
    Map multiple URLs to server files.
    
    Args:
        urls: List of public URLs
        web_root: Web root path
        available_files: Available files on server
        architecture_type: Architecture type
        
    Returns:
        Dictionary mapping URL to mapping result
    """
    results = {}
    
    for url in urls:
        result = best_mapping(url, web_root, available_files, architecture_type)
        results[url] = result
    
    return results


def find_unmapped_urls(urls: List[str], web_root: str = "",
                       available_files: Optional[List[str]] = None,
                       architecture_type: str = "",
                       min_confidence: float = 0.6) -> List[str]:
    """
    Find URLs that cannot be mapped with sufficient confidence.
    
    Args:
        urls: List of URLs
        web_root: Web root path
        available_files: Available files
        architecture_type: Architecture type
        min_confidence: Minimum confidence threshold
        
    Returns:
        List of unmapped URLs
    """
    unmapped = []
    
    for url in urls:
        result = best_mapping(url, web_root, available_files, architecture_type)
        if not result.get("has_good_match") or result.get("best", {}).get("confidence", 0) < min_confidence:
            unmapped.append(url)
    
    return unmapped


# ============================================================================
# MAPPING CACHE
# ============================================================================

class MappingCache:
    """Cache for URL to file mappings."""
    
    def __init__(self):
        self._cache = {}
        self._stats = {
            "hits": 0,
            "misses": 0,
            "total": 0
        }
    
    def get(self, url: str, web_root: str = "", architecture_type: str = "") -> Optional[Dict]:
        """Get cached mapping if available."""
        key = f"{url}|{web_root}|{architecture_type}"
        self._stats["total"] += 1
        
        if key in self._cache:
            self._stats["hits"] += 1
            return self._cache[key]
        
        self._stats["misses"] += 1
        return None
    
    def set(self, url: str, mapping: Dict, web_root: str = "", architecture_type: str = "") -> None:
        """Cache a mapping."""
        key = f"{url}|{web_root}|{architecture_type}"
        self._cache[key] = mapping
    
    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()
        self._stats = {"hits": 0, "misses": 0, "total": 0}
    
    def get_stats(self) -> Dict:
        """Get cache statistics."""
        return {
            **self._stats,
            "hit_rate": round(self._stats["hits"] / max(1, self._stats["total"]) * 100, 1)
        }


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def normalize_url_for_mapping(url: str) -> str:
    """Normalize URL for mapping purposes."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    path = unquote(path)
    path = normalize_path(path)
    
    # Remove trailing slash for consistency (except root)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    
    return path


def is_mappable(url: str) -> bool:
    """Check if a URL is mappable to a server file."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    
    # Always mappable
    return True


def get_common_route_patterns() -> Dict[str, str]:
    """Get common route patterns for mapping."""
    return {
        "/": "index.html",
        "/home": "index.html",
        "/about-us": "about.html",
        "/contact-us": "contact.html",
        "/pricing": "pricing.html",
        "/features": "features.html",
        "/services": "services.html",
        "/blog": "blog.html",
        "/faq": "faq.html",
        "/terms": "terms.html",
        "/privacy": "privacy.html",
    }
