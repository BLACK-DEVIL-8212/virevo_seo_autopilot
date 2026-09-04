"""Website technology detection based on signals.

Detects CMS, frameworks, programming languages, and build tools
from HTML, headers, and file structures.
"""
from __future__ import annotations
import re
import json
import logging
from typing import List, Dict, Optional, Any, Tuple, Set
from urllib.parse import urlparse

# Setup logging
logger = logging.getLogger(__name__)


# ============================================================================
# CMS SIGNATURES
# ============================================================================

CMS_SIGNATURES = [
    # CMS Systems
    ("wordpress", ["wp-content", "wp-includes", "wp-json", "/wp-login.php", "wp-admin"]),
    ("drupal", ["drupal", "sites/default/files", "/core/misc/drupal.js", "Drupal.settings"]),
    ("joomla", ["joomla", "/administrator/", "Joomla!", "com_content"]),
    ("shopify", ["cdn.shopify.com", "shopify", "/shopify/", "Shopify.theme"]),
    ("magento", ["magento", "Mage.Cookies", "skin/frontend", "Magento"]),
    ("ghost", ["ghost.css", "ghost.min.js", "ghost.org", "ghost-theme"]),
    ("squarespace", ["squarespace.com", "static.squarespace.com", "squarespace"]),
    ("wix", ["wix.com", "static.wix", "wix-wix"]),
    ("webflow", ["webflow", "cdn.webflow.com", "webflow.io"]),
    ("hubspot", ["hs-scripts", "hubspot", "hubspot.com"]),
    ("typo3", ["typo3", "typo3conf", "t3lib"]),
    ("silverstripe", ["silverstripe", "framework"]),
    ("prestashop", ["prestashop", "ps_"]),
    ("opencart", ["opencart", "route=common/home"]),
    ("woocommerce", ["woocommerce", "wc-", "woo-"])  # WordPress plugin
]

# ============================================================================
# FRAMEWORK GENERATORS
# ============================================================================

FRAMEWORK_META_GENERATORS = {
    "wordpress": "WordPress",
    "drupal": "Drupal",
    "joomla": "Joomla!",
    "ghost": "Ghost",
    "hugo": "Hugo",
    "jekyll": "Jekyll",
    "next.js": "Next.js",
    "nuxt": "Nuxt",
    "gatsby": "Gatsby",
    "vue": "Vue",
    "react": "React",
    "angular": "Angular",
    "svelte": "Svelte",
    "laravel": "Laravel",
    "django": "Django",
    "flask": "Flask",
    "rails": "Ruby on Rails",
    "spring": "Spring",
    "asp.net": "ASP.NET",
    "statamic": "Statamic",
    "craft": "Craft CMS",
    "kirby": "Kirby",
    "grav": "Grav",
}

# ============================================================================
# HEADER SIGNATURES
# ============================================================================

HEADER_SIGNATURES = {
    "server": {
        "nginx": "nginx",
        "apache": "apache",
        "iis": "iis",
        "cloudflare": "cloudflare",
        "netlify": "netlify",
        "vercel": "vercel",
        "github pages": "github-pages",
        "heroku": "heroku",
        "aws": "aws",
        "gcp": "gcp",
        "azure": "azure",
        "firebase": "firebase",
        "nodejs": "nodejs",
        "php": "php",
        "python": "python",
        "ruby": "ruby",
        "java": "java",
        "go": "go",
    },
    "x-powered-by": {
        "php": "php",
        "asp.net": "asp.net",
        "express": "express",
        "next.js": "next.js",
        "nuxt": "nuxt",
        "laravel": "laravel",
        "django": "django",
        "flask": "flask",
        "rails": "rails",
        "spring": "spring",
        "node": "nodejs",
    },
    "x-drupal-cache": "drupal",
    "x-drupal-dynamic-cache": "drupal",
    "x-generator": "generator",
    "x-aspnet-version": "asp.net",
    "x-powered-by-plesk": "plesk",
    "x-varnish": "varnish",
    "x-vercel-id": "vercel",
    "x-nuxt-version": "nuxt",
    "x-nextjs-version": "next.js",
    "x-gatsby-version": "gatsby",
}

# ============================================================================
# LANGUAGE AND FRAMEWORK SIGNATURES
# ============================================================================

LANGUAGE_SIGNATURES = {
    "php": [
        r'\.php', r'<script[^>]*php', r'php.ini', r'phpinfo', r'<\?php',
        r'wp-content', r'wp-includes', r'?php'
    ],
    "python": [r'\.py', r'wsgi', r'django', r'flask', r'python'],
    "ruby": [r'\.rb', r'rails', r'ruby', r'gem'],
    "java": [r'\.jsp', r'\.do', r'\.action', r'java', r'servlet', r'weblogic', r'websphere', r'tomcat'],
    "javascript": [r'\.js', r'\.jsx', r'react', r'vue', r'angular', r'node', r'express'],
    "typescript": [r'\.ts', r'\.tsx', r'typescript'],
    "csharp": [r'\.aspx', r'\.ashx', r'asp.net', r'c#'],
    "golang": [r'\.go', r'golang'],
    "rust": [r'\.rs', r'rust'],
    "perl": [r'\.pl', r'\.cgi', r'perl'],
}

# ============================================================================
# CDN SIGNATURES
# ============================================================================

CDN_SIGNATURES = {
    "cloudflare": ["cloudflare", "cf-ray", "cf-cache-status", "cf-"],
    "akamai": ["akamai", "akamaitech"],
    "fastly": ["fastly", "x-fastly"],
    "cloudfront": ["cloudfront", "x-amz-cf"],
    "incapsula": ["incapsula"],
    "keycdn": ["keycdn"],
    "bunnycdn": ["bunnycdn"],
    "stackpath": ["stackpath"],
    "google": ["googleusercontent", "gstatic"],
    "microsoft": ["azure-edge", "ms-"],
    "verizon": ["verizon", "edgecast"],
}

# ============================================================================
# MAIN DETECTION FUNCTION
# ============================================================================

def detect_from_html(html: str, headers: Optional[Dict[str, str]] = None, 
                     url: str = "") -> Dict:
    """
    Detect technologies from HTML and headers.
    
    Args:
        html: HTML content
        headers: HTTP response headers
        url: URL for domain-based detection
        
    Returns:
        Dictionary with detection results
    """
    if html is None:
        html = ""
    
    h_lower = html.lower()
    detected: List[str] = []
    evidence: List[str] = []
    confidence: Dict[str, float] = {}
    
    # =========================================================================
    # CMS Detection
    # =========================================================================
    for tech, sigs in CMS_SIGNATURES:
        for sig in sigs:
            if sig.lower() in h_lower:
                if tech not in detected:
                    detected.append(tech)
                evidence.append(f"HTML contains CMS signature: {sig}")
                confidence[tech] = confidence.get(tech, 0) + 0.3
                break
    
    # =========================================================================
    # Meta Generator Detection
    # =========================================================================
    meta_gen_match = re.search(
        r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)["\']',
        html, flags=re.I
    )
    if meta_gen_match:
        gen = meta_gen_match.group(1).strip()
        evidence.append(f"meta generator: {gen}")
        
        # Try to map to known frameworks
        for framework, label in FRAMEWORK_META_GENERATORS.items():
            if label.lower() in gen.lower():
                if framework not in detected:
                    detected.append(framework)
                confidence[framework] = confidence.get(framework, 0) + 0.5
                evidence.append(f"Framework from meta generator: {framework}")
                break
    
    # =========================================================================
    # Framework Detection from HTML
    # =========================================================================
    framework_patterns = [
        # React
        (r'data-reactroot', "react", 0.4),
        (r'data-reactid', "react", 0.3),
        (r'react-dom', "react", 0.3),
        (r'__react_fiber', "react", 0.3),
        (r'react-helmet', "react", 0.2),
        (r'react-router', "react", 0.2),
        (r'<script[^>]*react[^>]*\.js', "react", 0.3),
        
        # Vue
        (r'data-v-', "vue", 0.4),
        (r'__vue__', "vue", 0.3),
        (r'vue\.runtime', "vue", 0.3),
        (r'vue\.js', "vue", 0.3),
        (r'v-app', "vue", 0.2),
        (r'vue-router', "vue", 0.2),
        (r'<script[^>]*vue[^>]*\.js', "vue", 0.3),
        
        # Angular
        (r'ng-app', "angular", 0.4),
        (r'ng-version', "angular", 0.3),
        (r'angular\.js', "angular", 0.3),
        (r'@angular', "angular", 0.3),
        (r'ng-controller', "angular", 0.2),
        (r'<script[^>]*angular[^>]*\.js', "angular", 0.3),
        
        # Next.js
        (r'__NEXT_DATA__', "next.js", 0.5),
        (r'_next/', "next.js", 0.4),
        (r'<div id="__next"', "next.js", 0.4),
        (r'next/head', "next.js", 0.3),
        (r'next/image', "next.js", 0.3),
        
        # Nuxt
        (r'__NUXT__', "nuxt", 0.5),
        (r'_nuxt/', "nuxt", 0.4),
        (r'<div id="__nuxt"', "nuxt", 0.4),
        
        # Gatsby
        (r'gatsby', "gatsby", 0.3),
        (r'__GATSBY__', "gatsby", 0.4),
        (r'gatsby-', "gatsby", 0.3),
        (r'___gatsby', "gatsby", 0.3),
        
        # Svelte
        (r'svelte', "svelte", 0.3),
        (r'__svelte', "svelte", 0.3),
        
        # Bootstrap
        (r'bootstrap', "bootstrap", 0.3),
        (r'bootstrap\.css', "bootstrap", 0.3),
        (r'bootstrap\.min\.css', "bootstrap", 0.3),
        (r'bootstrap\.js', "bootstrap", 0.3),
        
        # Tailwind
        (r'tailwind', "tailwindcss", 0.3),
        (r'tailwind\.css', "tailwindcss", 0.3),
        (r'tw-', "tailwindcss", 0.2),
        
        # HTMX
        (r'htmx', "htmx", 0.3),
        (r'hx-', "htmx", 0.2),
        
        # Alpine.js
        (r'alpine', "alpinejs", 0.3),
        (r'x-data', "alpinejs", 0.2),
        (r'x-init', "alpinejs", 0.2),
        
        # jQuery
        (r'jquery', "jquery", 0.3),
        (r'jQuery', "jquery", 0.3),
        (r'\$\(', "jquery", 0.1),
    ]
    
    for pattern, framework, weight in framework_patterns:
        if re.search(pattern, h_lower, re.IGNORECASE):
            if framework not in detected:
                detected.append(framework)
            confidence[framework] = confidence.get(framework, 0) + weight
            evidence.append(f"Framework marker: {framework}")
    
    # =========================================================================
    # Header Detection
    # =========================================================================
    if headers:
        headers_lower = {k.lower(): v for k, v in headers.items()}
        
        # Server header
        server = headers_lower.get("server", "")
        if server:
            evidence.append(f"Server: {server}")
            for key, value in HEADER_SIGNATURES.get("server", {}).items():
                if key.lower() in server.lower():
                    if value not in detected:
                        detected.append(value)
                    confidence[value] = confidence.get(value, 0) + 0.3
                    break
        
        # X-Powered-By
        xpb = headers_lower.get("x-powered-by", "")
        if xpb:
            evidence.append(f"X-Powered-By: {xpb}")
            for key, value in HEADER_SIGNATURES.get("x-powered-by", {}).items():
                if key.lower() in xpb.lower():
                    if value not in detected:
                        detected.append(value)
                    confidence[value] = confidence.get(value, 0) + 0.3
                    break
        
        # Other headers
        for header, tech in HEADER_SIGNATURES.items():
            if header in headers_lower and header not in ["server", "x-powered-by"]:
                if isinstance(tech, str):
                    if tech not in detected:
                        detected.append(tech)
                    confidence[tech] = confidence.get(tech, 0) + 0.3
                    evidence.append(f"Header {header}: {headers_lower[header]}")
    
    # =========================================================================
    # CDN Detection
    # =========================================================================
    cdn_headers = []
    if headers:
        for header, value in headers.items():
            header_lower = header.lower()
            for cdn, sigs in CDN_SIGNATURES.items():
                for sig in sigs:
                    if sig in header_lower or (value and sig in value.lower()):
                        if cdn not in detected:
                            detected.append(f"cdn_{cdn}")
                        confidence[f"cdn_{cdn}"] = confidence.get(f"cdn_{cdn}", 0) + 0.3
                        evidence.append(f"CDN detected: {cdn}")
                        cdn_headers.append(f"{header}: {value}")
                        break
    
    # CDN detection from URLs
    cdn_url_patterns = {
        "cloudflare": [r'cdn\.cloudflare\.com', r'cloudflare'],
        "google": [r'googleapis\.com', r'gstatic\.com'],
        "microsoft": [r'azureedge\.net', r'microsoft'],
        "cloudfront": [r'cloudfront\.net'],
        "fastly": [r'fastly\.net'],
        "bunny": [r'bunnycdn\.com', r'bunnycdn\.net'],
        "jsdelivr": [r'cdn\.jsdelivr\.net', r'jsdelivr'],
        "unpkg": [r'unpkg\.com'],
        "cdnjs": [r'cdnjs\.cloudflare\.com'],
    }
    
    for cdn, patterns in cdn_url_patterns.items():
        for pattern in patterns:
            if re.search(pattern, h_lower, re.IGNORECASE):
                if f"cdn_{cdn}" not in detected:
                    detected.append(f"cdn_{cdn}")
                confidence[f"cdn_{cdn}"] = confidence.get(f"cdn_{cdn}", 0) + 0.2
                evidence.append(f"CDN URL detected: {cdn}")
                break
    
    # =========================================================================
    # Language Detection
    # =========================================================================
    for language, patterns in LANGUAGE_SIGNATURES.items():
        for pattern in patterns:
            if re.search(pattern, h_lower, re.IGNORECASE):
                if language not in detected:
                    detected.append(language)
                confidence[language] = confidence.get(language, 0) + 0.2
                evidence.append(f"Language signal: {language}")
                break
    
    # =========================================================================
    # Generic SPA detection
    # =========================================================================
    if "react" in detected or "vue" in detected or "angular" in detected:
        if "spa" not in detected:
            detected.append("spa")
        confidence["spa"] = confidence.get("spa", 0) + 0.3
        evidence.append("SPA detected from framework")
    
    # =========================================================================
    # Build tools
    # =========================================================================
    build_tools = {
        "webpack": [r'webpack', r'chunk-', r'vendors~', r'manifest\.js'],
        "vite": [r'vite', r'@vite', r'/assets/'],
        "parcel": [r'parcel'],
        "rollup": [r'rollup'],
        "esbuild": [r'esbuild'],
        "babel": [r'babel'],
    }
    
    for tool, patterns in build_tools.items():
        for pattern in patterns:
            if re.search(pattern, h_lower, re.IGNORECASE):
                if tool not in detected:
                    detected.append(tool)
                confidence[tool] = confidence.get(tool, 0) + 0.2
                evidence.append(f"Build tool: {tool}")
                break
    
    # =========================================================================
    # Domain-based detection
    # =========================================================================
    if url:
        parsed = urlparse(url)
        domain = parsed.hostname or ""
        
        # WordPress.com
        if "wordpress.com" in domain:
            if "wordpress" not in detected:
                detected.append("wordpress")
            confidence["wordpress"] = confidence.get("wordpress", 0) + 0.5
            evidence.append("WordPress.com domain")
        
        # Shopify
        if "shopify.com" in domain or "myshopify.com" in domain:
            if "shopify" not in detected:
                detected.append("shopify")
            confidence["shopify"] = confidence.get("shopify", 0) + 0.5
            evidence.append("Shopify domain")
        
        # Squarespace
        if "squarespace.com" in domain:
            if "squarespace" not in detected:
                detected.append("squarespace")
            confidence["squarespace"] = confidence.get("squarespace", 0) + 0.5
            evidence.append("Squarespace domain")
    
    # =========================================================================
    # Deduplicate and sort
    # =========================================================================
    detected = list(dict.fromkeys(detected))
    
    # Calculate overall confidence for each tech
    for tech in detected:
        confidence[tech] = min(1.0, confidence.get(tech, 0))
    
    # Determine primary technology
    primary = "unknown"
    if detected:
        # Prioritize certain technologies
        priority = ["wordpress", "drupal", "joomla", "shopify", "next.js", "react", "vue", "angular", "laravel", "django"]
        for p in priority:
            if p in detected:
                primary = p
                break
        if primary == "unknown":
            primary = detected[0]
    
    # =========================================================================
    # Build result
    # =========================================================================
    return {
        "detected": detected,
        "primary": primary,
        "confidence": confidence,
        "evidence": evidence,
        "headers": cdn_headers,
        "has_cdn": bool(cdn_headers),
        "is_cms": any(t in detected for t in ["wordpress", "drupal", "joomla", "shopify", "magento", "ghost", "squarespace", "wix", "webflow"]),
        "is_framework": any(t in detected for t in ["react", "vue", "angular", "svelte", "next.js", "nuxt", "gatsby"]),
        "is_spa": "spa" in detected or any(t in detected for t in ["react", "vue", "angular", "svelte"]),
        "backend_language": next((t for t in detected if t in LANGUAGE_SIGNATURES), None),
        "summary": {
            "primary_technology": primary,
            "all_technologies": detected,
            "has_cms": any(t in ["wordpress", "drupal", "joomla", "shopify", "magento", "ghost", "squarespace", "wix", "webflow"] for t in detected),
            "has_framework": any(t in ["react", "vue", "angular", "svelte", "next.js", "nuxt", "gatsby"] for t in detected),
            "uses_cdn": bool(cdn_headers),
            "language": next((t for t in detected if t in LANGUAGE_SIGNATURES), "unknown")
        }
    }


# ============================================================================
# FILE-BASED DETECTION
# ============================================================================

def detect_from_files(file_list: List[str]) -> Dict:
    """
    Detect technologies from file structure.
    
    Args:
        file_list: List of file paths
        
    Returns:
        Dictionary with detection results
    """
    if not file_list:
        return {
            "detected": [],
            "primary": "unknown",
            "evidence": ["No files available"],
            "confidence": {}
        }
    
    paths = " ".join(file_list).lower()
    detected: List[str] = []
    evidence: List[str] = []
    confidence: Dict[str, float] = {}
    
    # =========================================================================
    # CMS file signatures
    # =========================================================================
    cms_file_checks = [
        ("wordpress", ["wp-config.php", "wp-content/", "wp-includes/", "wp-admin/", "wp-settings.php"]),
        ("drupal", ["sites/default/settings.php", "core/modules", "modules/", "themes/"]),
        ("joomla", ["configuration.php", "administrator/", "components/", "modules/"]),
        ("laravel", ["artisan", "app/config", "vendor/laravel", "app/Models/", "app/Http/"]),
        ("django", ["manage.py", "settings.py", "urls.py", "wsgi.py", "asgi.py"]),
        ("flask", ["app.py", "wsgi.py", "requirements.txt", "Procfile"]),
        ("rails", ["Gemfile", "config/routes.rb", "app/models/", "app/controllers/", "app/views/"]),
        ("next.js", [".next/", "next.config.js", "pages/", "app/", "components/"]),
        ("nuxt", [".nuxt/", "nuxt.config.js", "pages/", "store/", "layouts/"]),
        ("gatsby", ["gatsby-config.js", "gatsby-node.js", "src/pages/"]),
        ("express", ["app.js", "server.js", "routes/", "views/", "package.json"]),
        ("spring", ["pom.xml", "build.gradle", "src/main/java/", "application.properties"]),
        ("symfony", ["composer.json", "src/", "config/", "public/index.php"]),
        ("shopify", ["theme.liquid", "sections/", "templates/", "config/settings_schema.json"]),
        ("magento", ["app/etc/config.xml", "Mage.php", "vendor/magento/"]),
    ]
    
    for tech, sigs in cms_file_checks:
        for sig in sigs:
            if sig in paths:
                if tech not in detected:
                    detected.append(tech)
                evidence.append(f"Found file signature: {sig}")
                confidence[tech] = confidence.get(tech, 0) + 0.3
                break
    
    # =========================================================================
    # Framework file signatures
    # =========================================================================
    framework_file_checks = [
        ("react", ["react", "jsx", "components/", "node_modules/react"]),
        ("vue", ["vue", "components/", "node_modules/vue", ".vue"]),
        ("angular", ["angular", "node_modules/@angular", ".ts", "angular.json"]),
        ("svelte", ["svelte", ".svelte"]),
        ("htmx", ["htmx"]),
        ("alpinejs", ["alpine"]),
    ]
    
    for tech, sigs in framework_file_checks:
        for sig in sigs:
            if sig in paths:
                if tech not in detected:
                    detected.append(tech)
                evidence.append(f"Found framework file: {sig}")
                confidence[tech] = confidence.get(tech, 0) + 0.2
                break
    
    # =========================================================================
    # Build tool file signatures
    # =========================================================================
    build_file_checks = [
        ("webpack", ["webpack.config", "webpack."]),
        ("vite", ["vite.config", "vite."]),
        ("parcel", ["parcel.", ".parcel"]),
        ("rollup", ["rollup.config"]),
        ("esbuild", ["esbuild."]),
        ("babel", [".babelrc", "babel.config"]),
        ("grunt", ["Gruntfile", "grunt."]),
        ("gulp", ["Gulpfile", "gulpfile"]),
    ]
    
    for tech, sigs in build_file_checks:
        for sig in sigs:
            if sig in paths:
                if tech not in detected:
                    detected.append(tech)
                evidence.append(f"Found build tool: {sig}")
                confidence[tech] = confidence.get(tech, 0) + 0.2
                break
    
    # =========================================================================
    # Package manager detection
    # =========================================================================
    package_managers = {
        "npm": ["package.json", "node_modules/", "package-lock.json"],
        "yarn": ["yarn.lock", ".yarn"],
        "composer": ["composer.json", "composer.lock", "vendor/"],
        "pip": ["requirements.txt", "setup.py", "Pipfile", "pipenv"],
        "gem": ["Gemfile", "Gemfile.lock"],
        "bundle": ["Gemfile", "Gemfile.lock"],
        "cargo": ["Cargo.toml", "Cargo.lock"],
        "go": ["go.mod", "go.sum"],
        "maven": ["pom.xml"],
        "gradle": ["build.gradle", "settings.gradle"],
    }
    
    for manager, sigs in package_managers.items():
        for sig in sigs:
            if sig in paths:
                if manager not in detected:
                    detected.append(manager)
                evidence.append(f"Found package manager: {sig}")
                confidence[manager] = confidence.get(manager, 0) + 0.2
                break
    
    # =========================================================================
    # Static site generators
    # =========================================================================
    ssg_checks = {
        "hugo": ["hugo.", "layouts/", "content/", "themes/"],
        "jekyll": ["_config.yml", "_layouts/", "_posts/", "_includes/"],
        "eleventy": [".eleventy.js", "_site/", "eleventy."],
        "mkdocs": ["mkdocs.yml", "docs/"],
        "sphinx": ["conf.py", "docs/", "source/"],
        "vuepress": ["vuepress", ".vuepress/"],
    }
    
    for tech, sigs in ssg_checks.items():
        for sig in sigs:
            if sig in paths:
                if tech not in detected:
                    detected.append(tech)
                evidence.append(f"Found SSG: {sig}")
                confidence[tech] = confidence.get(tech, 0) + 0.2
                break
    
    # =========================================================================
    # Deduplicate and sort
    # =========================================================================
    detected = list(dict.fromkeys(detected))
    
    for tech in detected:
        confidence[tech] = min(1.0, confidence.get(tech, 0))
    
    primary = detected[0] if detected else "unknown"
    
    return {
        "detected": detected,
        "primary": primary,
        "confidence": confidence,
        "evidence": evidence,
        "summary": {
            "primary_technology": primary,
            "all_technologies": detected,
            "has_cms": any(t in ["wordpress", "drupal", "joomla", "shopify", "magento", "ghost"] for t in detected),
            "has_framework": any(t in ["react", "vue", "angular", "svelte", "next.js", "nuxt", "gatsby", "laravel", "django", "rails"] for t in detected),
            "has_build_tool": any(t in ["webpack", "vite", "parcel", "rollup", "esbuild", "babel"] for t in detected),
            "has_package_manager": any(t in ["npm", "yarn", "composer", "pip", "gem", "cargo", "go", "maven", "gradle"] for t in detected),
            "is_static_site": any(t in ["hugo", "jekyll", "eleventy", "mkdocs", "sphinx", "vuepress", "gatsby"] for t in detected),
        }
    }


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def detect_technology(html: str = "", headers: Optional[Dict[str, str]] = None, 
                      url: str = "", files: Optional[List[str]] = None) -> Dict:
    """
    Detect technologies from all available sources.
    
    Args:
        html: HTML content
        headers: HTTP headers
        url: URL
        files: List of file paths
        
    Returns:
        Combined detection results
    """
    result = {
        "html_detection": detect_from_html(html, headers, url),
        "file_detection": detect_from_files(files) if files else {"detected": [], "primary": "unknown", "evidence": []},
        "combined": {}
    }
    
    # Combine results
    all_techs = set(result["html_detection"]["detected"] + result["file_detection"]["detected"])
    
    # Calculate combined confidence
    combined_confidence = {}
    for tech in all_techs:
        html_conf = result["html_detection"]["confidence"].get(tech, 0)
        file_conf = result["file_detection"]["confidence"].get(tech, 0)
        combined_confidence[tech] = min(1.0, html_conf + file_conf * 0.5)
    
    result["combined"] = {
        "detected": list(all_techs),
        "primary": result["html_detection"]["primary"] if result["html_detection"]["primary"] != "unknown" else result["file_detection"]["primary"],
        "confidence": combined_confidence,
        "evidence": result["html_detection"]["evidence"] + result["file_detection"]["evidence"],
        "summary": {
            **result["html_detection"]["summary"],
            **result["file_detection"]["summary"]
        }
    }
    
    return result


def get_primary_technology(html: str = "", headers: Optional[Dict[str, str]] = None,
                           url: str = "", files: Optional[List[str]] = None) -> str:
    """Get the primary technology detected."""
    result = detect_technology(html, headers, url, files)
    return result["combined"].get("primary", "unknown")


def get_all_technologies(html: str = "", headers: Optional[Dict[str, str]] = None,
                         url: str = "", files: Optional[List[str]] = None) -> List[str]:
    """Get all detected technologies."""
    result = detect_technology(html, headers, url, files)
    return result["combined"].get("detected", [])

