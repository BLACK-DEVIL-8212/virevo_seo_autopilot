"""Detect website architecture: static HTML vs SPA frameworks, hosting, and deployment strategy."""
from __future__ import annotations
import re
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlparse

# Setup logging
logger = logging.getLogger(__name__)


# ============================================================================
# MAIN ARCHITECTURE DETECTION
# ============================================================================

def detect_architecture(html: str, headers: Optional[Dict[str, str]] = None, 
                        url: str = "", cookies: Optional[Dict[str, str]] = None) -> Dict:
    """
    Detect whether a website is static HTML, SPA, SSR, or hybrid.
    
    Args:
        html: HTML content of the page
        headers: HTTP response headers
        url: URL of the page
        cookies: Cookies from the response
        
    Returns:
        Dictionary with architecture detection results
    """
    if html is None:
        html = ""
    
    h_lower = html.lower()
    evidence: List[str] = []
    
    # Initialize scores for different architectures
    scores = {
        "react_spa": 0,
        "vue_spa": 0,
        "angular_spa": 0,
        "svelte_spa": 0,
        "javascript_spa": 0,
        "ssr": 0,
        "static_html": 0,
        "hybrid": 0,
        "next_ssr": 0,
        "nuxt_ssr": 0,
        "gatsby_ssg": 0,
        "htmx": 0,
        "alpine": 0,
        "jquery": 0,
    }
    
    # =========================================================================
    # React Signals
    # =========================================================================
    react_patterns = [
        (r'data-reactroot', 3, "React DOM attributes found"),
        (r'data-reactid', 2, "React ID attributes found"),
        (r'reactdom', 2, "React DOM script reference"),
        (r'react-dom', 2, "React DOM script reference"),
        (r'__react_fiber', 2, "React internal fiber markers"),
        (r'__reactInternalInstance', 2, "React internal instance markers"),
        (r'react-helmet', 1, "React Helmet detected"),
        (r'react-router', 2, "React Router detected"),
        (r'window\.React', 1, "React global variable"),
        (r'React\.createElement', 2, "React.createElement usage"),
        (r'<script[^>]*src=["\'][^"\']*react[^"\']*\.js', 2, "React script import"),
        (r'_reactRoot', 2, "React root container"),
        (r'__REACT_DEVTOOLS_GLOBAL_HOOK__', 1, "React DevTools hook"),
    ]
    
    for pattern, weight, desc in react_patterns:
        if re.search(pattern, h_lower, re.IGNORECASE):
            scores["react_spa"] += weight
            evidence.append(desc)
    
    # =========================================================================
    # Vue Signals
    # =========================================================================
    vue_patterns = [
        (r'data-v-', 3, "Vue scoped CSS markers"),
        (r'window\.__vue__', 2, "Vue global marker"),
        (r'vue\.runtime', 2, "Vue runtime detected"),
        (r'vue\.js', 2, "Vue.js detected"),
        (r'vue-router', 2, "Vue Router detected"),
        (r'v-app', 2, "Vue app directive"),
        (r'v-html', 1, "Vue HTML directive"),
        (r'v-text', 1, "Vue text directive"),
        (r'v-for', 1, "Vue for directive"),
        (r'v-if', 1, "Vue if directive"),
        (r'v-bind', 1, "Vue bind directive"),
        (r'<script[^>]*src=["\'][^"\']*vue[^"\']*\.js', 2, "Vue script import"),
        (r'__VUE__', 2, "Vue global marker"),
        (r'Vue\.component', 2, "Vue component registration"),
    ]
    
    for pattern, weight, desc in vue_patterns:
        if re.search(pattern, h_lower, re.IGNORECASE):
            scores["vue_spa"] += weight
            evidence.append(desc)
    
    # =========================================================================
    # Angular Signals
    # =========================================================================
    angular_patterns = [
        (r'ng-app', 3, "Angular app directive"),
        (r'angular\.js', 2, "Angular.js detected"),
        (r'@angular', 2, "Angular package detected"),
        (r'ng-version', 2, "Angular version attribute"),
        (r'ng-controller', 2, "Angular controller"),
        (r'ng-model', 1, "Angular model directive"),
        (r'ng-repeat', 1, "Angular repeat directive"),
        (r'<script[^>]*src=["\'][^"\']*angular[^"\']*\.js', 2, "Angular script import"),
        (r'__NG__', 2, "Angular global marker"),
        (r'PlatformRef', 2, "Angular platform reference"),
    ]
    
    for pattern, weight, desc in angular_patterns:
        if re.search(pattern, h_lower, re.IGNORECASE):
            scores["angular_spa"] += weight
            evidence.append(desc)
    
    # =========================================================================
    # Svelte Signals
    # =========================================================================
    svelte_patterns = [
        (r'svelte', 3, "Svelte detected"),
        (r'__svelte', 2, "Svelte internal markers"),
        (r'<script[^>]*src=["\'][^"\']*svelte[^"\']*\.js', 2, "Svelte script import"),
    ]
    
    for pattern, weight, desc in svelte_patterns:
        if re.search(pattern, h_lower, re.IGNORECASE):
            scores["svelte_spa"] += weight
            evidence.append(desc)
    
    # =========================================================================
    # Generic SPA Signals
    # =========================================================================
    spa_patterns = [
        (r'<div[^>]*id=["\'](root|app|app-root|main)["\']', 2, "Single root div app shell"),
        (r'<div[^>]*id=["\'](root|app)["\'][^>]*>\s*</div>', 2, "Empty root div (JS-rendered)"),
        (r'bundle\.js', 1, "App bundle script"),
        (r'main\.js', 1, "Main script file"),
        (r'app\.js', 1, "App script file"),
        (r'chunk\.js', 1, "Webpack/Vite chunks"),
        (r'vendors', 1, "Vendor bundle"),
        (r'<script[^>]*type=["\']module["\'][^>]*>', 1, "ES module script"),
        (r'type=["\']text/javascript["\'][^>]*>', 1, "JavaScript module"),
        (r'manifest\.json', 1, "Web app manifest"),
        (r'__INITIAL_STATE__', 2, "Initial state variable (SPA)"),
        (r'__PRELOADED_STATE__', 2, "Preloaded state variable (SPA)"),
    ]
    
    for pattern, weight, desc in spa_patterns:
        if re.search(pattern, h_lower, re.IGNORECASE):
            scores["javascript_spa"] += weight
            evidence.append(desc)
    
    # =========================================================================
    # SSR / Hybrid Signals
    # =========================================================================
    ssr_patterns = [
        (r'__NEXT_DATA__', 3, "Next.js SSR/SSG data script"),
        (r'_next/', 2, "Next.js route"),
        (r'__NUXT__', 3, "Nuxt SSR/SSG data script"),
        (r'_nuxt/', 2, "Nuxt route"),
        (r'gatsby', 2, "Gatsby SSG markers"),
        (r'gatsby-', 2, "Gatsby route"),
        (r'__GATSBY__', 2, "Gatsby data script"),
        (r'<script[^>]*id=["\']__NEXT_DATA__["\']', 3, "Next.js data script"),
        (r'<script[^>]*id=["\']__NUXT_DATA__["\']', 3, "Nuxt data script"),
        (r'data-react-helmet', 1, "React Helmet SSR"),
        (r'server-side rendering', 2, "SSR marker"),
        (r'serverside rendered', 2, "SSR marker"),
        (r'<div id="__next"[^>]*>', 2, "Next.js root"),
        (r'<div id="__nuxt"[^>]*>', 2, "Nuxt root"),
    ]
    
    for pattern, weight, desc in ssr_patterns:
        if re.search(pattern, h_lower, re.IGNORECASE):
            scores["ssr"] += weight
            evidence.append(desc)
            if "next" in pattern:
                scores["next_ssr"] += weight
            elif "nuxt" in pattern:
                scores["nuxt_ssr"] += weight
            elif "gatsby" in pattern:
                scores["gatsby_ssg"] += weight
    
    # =========================================================================
    # HTMX Signals
    # =========================================================================
    htmx_patterns = [
        (r'htmx', 2, "HTMX detected"),
        (r'hx-', 2, "HTMX attributes"),
        (r'hx-get', 2, "HTMX get attribute"),
        (r'hx-post', 2, "HTMX post attribute"),
        (r'hx-put', 2, "HTMX put attribute"),
        (r'hx-delete', 2, "HTMX delete attribute"),
        (r'<script[^>]*src=["\'][^"\']*htmx[^"\']*\.js', 2, "HTMX script import"),
    ]
    
    for pattern, weight, desc in htmx_patterns:
        if re.search(pattern, h_lower, re.IGNORECASE):
            scores["htmx"] += weight
            evidence.append(desc)
    
    # =========================================================================
    # Alpine.js Signals
    # =========================================================================
    alpine_patterns = [
        (r'alpine', 2, "Alpine.js detected"),
        (r'x-data', 2, "Alpine data attribute"),
        (r'x-init', 2, "Alpine init attribute"),
        (r'x-show', 1, "Alpine show attribute"),
        (r'x-bind', 1, "Alpine bind attribute"),
        (r'x-on', 1, "Alpine on attribute"),
        (r'x-text', 1, "Alpine text attribute"),
        (r'x-html', 1, "Alpine HTML attribute"),
        (r'x-model', 1, "Alpine model attribute"),
        (r'<script[^>]*src=["\'][^"\']*alpine[^"\']*\.js', 2, "Alpine script import"),
    ]
    
    for pattern, weight, desc in alpine_patterns:
        if re.search(pattern, h_lower, re.IGNORECASE):
            scores["alpine"] += weight
            evidence.append(desc)
    
    # =========================================================================
    # jQuery Signals
    # =========================================================================
    jquery_patterns = [
        (r'jquery', 2, "jQuery detected"),
        (r'jQuery', 2, "jQuery detected"),
        (r'\$\(', 1, "jQuery selector"),
        (r'<script[^>]*src=["\'][^"\']*jquery[^"\']*\.js', 2, "jQuery script import"),
    ]
    
    for pattern, weight, desc in jquery_patterns:
        if re.search(pattern, h_lower, re.IGNORECASE):
            scores["jquery"] += weight
            evidence.append(desc)
    
    # =========================================================================
    # Hosting Detection
    # =========================================================================
    hosting = "unknown"
    hosting_evidence = []
    
    if headers:
        headers_lower = {k.lower(): v for k, v in headers.items()}
        
        # Firebase Hosting
        if headers_lower.get("x-firebase-version"):
            hosting = "firebase"
            hosting_evidence.append(f"Firebase Hosting header: {headers_lower.get('x-firebase-version')}")
            scores["javascript_spa"] += 1
        
        # Netlify
        server = headers_lower.get("server", "")
        if "netlify" in server.lower():
            hosting = "netlify"
            hosting_evidence.append(f"Netlify server: {server}")
        
        # Vercel
        if "vercel" in server.lower() or headers_lower.get("x-vercel-id"):
            hosting = "vercel"
            hosting_evidence.append("Vercel hosting detected")
        
        # Cloudflare
        if "cloudflare" in server.lower():
            hosting = "cloudflare"
            hosting_evidence.append(f"Cloudflare server: {server}")
        
        # AWS / CloudFront
        if "cloudfront" in server.lower() or headers_lower.get("x-amz-cf-id"):
            hosting = "aws_cloudfront"
            hosting_evidence.append("AWS CloudFront detected")
        
        # GitHub Pages
        if "github" in server.lower() and "pages" in server.lower():
            hosting = "github_pages"
            hosting_evidence.append("GitHub Pages detected")
        
        # Nginx / Apache (generic)
        if "nginx" in server.lower():
            hosting = "nginx"
            hosting_evidence.append("Nginx server")
        elif "apache" in server.lower():
            hosting = "apache"
            hosting_evidence.append("Apache server")
    
    # Domain-based hosting detection
    if url:
        parsed = urlparse(url)
        domain = parsed.hostname or ""
        
        if "firebaseapp.com" in domain or "web.app" in domain:
            hosting = "firebase"
            hosting_evidence.append("Firebase domain")
        elif "netlify.app" in domain or "netlify.com" in domain:
            hosting = "netlify"
            hosting_evidence.append("Netlify domain")
        elif "vercel.app" in domain:
            hosting = "vercel"
            hosting_evidence.append("Vercel domain")
        elif "github.io" in domain:
            hosting = "github_pages"
            hosting_evidence.append("GitHub Pages domain")
        elif "surge.sh" in domain:
            hosting = "surge"
            hosting_evidence.append("Surge domain")
        elif "herokuapp.com" in domain:
            hosting = "heroku"
            hosting_evidence.append("Heroku domain")
        elif "cloudfront.net" in domain:
            hosting = "aws_cloudfront"
            hosting_evidence.append("CloudFront domain")
    
    # =========================================================================
    # Determine Primary Architecture
    # =========================================================================
    max_score = max(scores.values())
    
    if max_score == 0:
        primary = "static_html"
        evidence.append("No SPA/SSR markers detected")
    else:
        # Get all architectures with max score
        candidates = [k for k, v in scores.items() if v == max_score]
        primary = candidates[0] if candidates else "static_html"
    
    # Special case: Firebase SPA
    if primary == "react_spa" and hosting == "firebase":
        primary = "firebase_spa"
        evidence.append("Firebase-hosted React SPA")
    
    # Special case: Hybrid detection
    if scores["ssr"] > 0 and (scores["react_spa"] > 0 or scores["javascript_spa"] > 0):
        primary = "hybrid"
        evidence.append("Hybrid SSR + SPA detected")
    
    # =========================================================================
    # Determine Rendering Mode
    # =========================================================================
    if primary == "static_html":
        rendering_mode = "raw"
    elif primary in ("ssr", "hybrid", "next_ssr", "nuxt_ssr", "gatsby_ssg"):
        rendering_mode = "server_rendered"
    elif primary in ("react_spa", "vue_spa", "angular_spa", "svelte_spa", "javascript_spa", "firebase_spa"):
        rendering_mode = "client_rendered"
    else:
        rendering_mode = "raw"
    
    # =========================================================================
    # Determine Deployment Strategy
    # =========================================================================
    deployment_strategy = "direct_html"
    
    if primary in ("react_spa", "vue_spa", "angular_spa", "svelte_spa", "javascript_spa", "firebase_spa"):
        if hosting == "firebase":
            deployment_strategy = "firebase_deploy"
        elif hosting in ("netlify", "vercel"):
            deployment_strategy = "git_deploy"
        else:
            deployment_strategy = "source_code_build"
    elif primary in ("next_ssr", "nuxt_ssr", "gatsby_ssg", "hybrid"):
        if hosting in ("netlify", "vercel", "firebase"):
            deployment_strategy = "git_deploy"
        else:
            deployment_strategy = "source_code_build"
    
    # =========================================================================
    # Detect Framework Version
    # =========================================================================
    framework_version = ""
    version_patterns = [
        (r'react[\-\.](\d+\.\d+\.\d+)', 'react'),
        (r'vue[\-\.](\d+\.\d+\.\d+)', 'vue'),
        (r'angular[\-\.](\d+\.\d+\.\d+)', 'angular'),
        (r'svelte[\-\.](\d+\.\d+\.\d+)', 'svelte'),
        (r'next[\-\.](\d+\.\d+\.\d+)', 'next'),
        (r'nuxt[\-\.](\d+\.\d+\.\d+)', 'nuxt'),
        (r'gatsby[\-\.](\d+\.\d+\.\d+)', 'gatsby'),
    ]
    
    for pattern, framework in version_patterns:
        match = re.search(pattern, h_lower, re.IGNORECASE)
        if match:
            framework_version = match.group(1)
            break
    
    # =========================================================================
    # Detect Build System
    # =========================================================================
    build_system = detect_from_js_bundle(html)
    
    # =========================================================================
    # Build Result
    # =========================================================================
    return {
        "architecture_type": primary,
        "rendering_mode": rendering_mode,
        "deployment_strategy": deployment_strategy,
        "hosting_provider": hosting,
        "hosting_evidence": hosting_evidence,
        "scores": scores,
        "evidence": evidence,
        "detected_spa_framework": primary,
        "detected_framework_version": framework_version,
        "is_spa": primary not in ("static_html", "ssr"),
        "build_system": build_system.get("build_system", "unknown"),
        "confidence": min(1.0, max_score / 10.0) if max_score > 0 else 0.0,
        "summary": {
            "type": primary,
            "hosting": hosting,
            "rendering": rendering_mode,
            "deployment": deployment_strategy,
            "is_spa": primary not in ("static_html", "ssr"),
            "framework": primary,
            "build_system": build_system.get("build_system", "unknown"),
        }
    }


# ============================================================================
# JS BUNDLE ANALYSIS
# ============================================================================

def detect_from_js_bundle(html: str) -> Dict:
    """
    Inspect script tags and bundle references to infer build system.
    
    Args:
        html: HTML content
        
    Returns:
        Dictionary with build system detection results
    """
    if not html:
        return {"build_system": "unknown", "scripts": [], "signals": {}}
    
    # Find all script src attributes
    scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, flags=re.I)
    
    build_signals = {
        "webpack": [],
        "vite": [],
        "parcel": [],
        "rollup": [],
        "esbuild": [],
        "gatsby": [],
        "next": [],
        "nuxt": [],
        "angular_cli": [],
        "babel": [],
    }
    
    for src in scripts:
        s = src.lower()
        
        # Webpack signals
        if "webpack" in s or "/chunk." in s or "vendors" in s or "-chunk" in s:
            build_signals["webpack"].append(src)
        
        # Vite signals
        if "vite" in s or "/assets/" in s or "/@vite/" in s:
            build_signals["vite"].append(src)
        
        # Parcel signals
        if "parcel" in s:
            build_signals["parcel"].append(src)
        
        # Rollup signals
        if "rollup" in s:
            build_signals["rollup"].append(src)
        
        # ESBuild signals
        if "esbuild" in s:
            build_signals["esbuild"].append(src)
        
        # Gatsby signals
        if "gatsby" in s:
            build_signals["gatsby"].append(src)
        
        # Next.js signals
        if "_next" in s or "next/" in s:
            build_signals["next"].append(src)
        
        # Nuxt signals
        if "_nuxt" in s or "nuxt/" in s:
            build_signals["nuxt"].append(src)
        
        # Angular CLI signals
        if "angular-cli" in s or ".ng." in s:
            build_signals["angular_cli"].append(src)
        
        # Babel signals
        if "babel" in s:
            build_signals["babel"].append(src)
    
    # Determine primary build system
    build_system = "unknown"
    for system, hits in build_signals.items():
        if hits:
            build_system = system
            break
    
    return {
        "build_system": build_system,
        "scripts": scripts[:20],  # Limit to avoid excessive output
        "signals": {k: v[:10] for k, v in build_signals.items() if v},
        "total_scripts": len(scripts),
    }


# ============================================================================
# MANIFEST EXTRACTION
# ============================================================================

def extract_manifest_links(html: str) -> Dict:
    """
    Extract link tags for manifests, icons, and preloads.
    
    Args:
        html: HTML content
        
    Returns:
        Dictionary with extracted manifest information
    """
    if not html:
        return {"manifest": None, "icons": [], "preloads": [], "stylesheets": []}
    
    links = re.findall(r'<link[^>]+rel=["\']([^"\']+)["\'][^>]+href=["\']([^"\']+)["\']', html, flags=re.I)
    
    manifest = None
    icons = []
    preloads = []
    stylesheets = []
    precaches = []
    alternate = []
    
    for rel, href in links:
        r = rel.lower()
        
        if r == "manifest":
            manifest = href
        elif "icon" in r:
            icons.append(href)
        elif r in ("preload", "prefetch", "prerender"):
            preloads.append(href)
        elif r in ("stylesheet", "style"):
            stylesheets.append(href)
        elif r == "precache":
            precaches.append(href)
        elif r in ("alternate", "canonical"):
            alternate.append(href)
    
    return {
        "manifest": manifest,
        "icons": icons,
        "preloads": preloads,
        "stylesheets": stylesheets,
        "precaches": precaches,
        "alternate": alternate,
        "total_links": len(links),
    }


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def is_spa(html: str, headers: Optional[Dict[str, str]] = None, url: str = "") -> bool:
    """
    Quick check if a website is an SPA.
    
    Args:
        html: HTML content
        headers: HTTP headers
        url: URL
        
    Returns:
        True if SPA, False otherwise
    """
    result = detect_architecture(html, headers, url)
    return result.get("is_spa", False)


def get_framework(html: str, headers: Optional[Dict[str, str]] = None, url: str = "") -> str:
    """
    Get the detected framework name.
    
    Args:
        html: HTML content
        headers: HTTP headers
        url: URL
        
    Returns:
        Framework name or "unknown"
    """
    result = detect_architecture(html, headers, url)
    return result.get("detected_spa_framework", "unknown")


def get_hosting(html: str, headers: Optional[Dict[str, str]] = None, url: str = "") -> str:
    """
    Get the detected hosting provider.
    
    Args:
        html: HTML content
        headers: HTTP headers
        url: URL
        
    Returns:
        Hosting provider name or "unknown"
    """
    result = detect_architecture(html, headers, url)
    return result.get("hosting_provider", "unknown")

