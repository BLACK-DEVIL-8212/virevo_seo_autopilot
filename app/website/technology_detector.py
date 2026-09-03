"""Website technology detection based on signals."""
from __future__ import annotations
import re
from typing import List, Dict
from urllib.parse import urlparse


CMS_SIGNATURES = [
    ("wordpress", ["wp-content", "wp-includes", "wp-json", "/wp-login.php"]),
    ("drupal", ["drupal", "sites/default/files", "/core/misc/drupal.js"]),
    ("joomla", ["joomla", "/administrator/", "Joomla!"]),
    ("shopify", ["cdn.shopify.com", "shopify"]),
    ("magento", ["magento", "Mage.Cookies"]),
    ("ghost", ["ghost.css", "ghost.min.js", "ghost.org"]),
    ("squarespace", ["squarespace.com", "static.squarespace.com"]),
]


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
}


def detect_from_html(html: str, headers: Dict[str, str] | None = None) -> Dict:
    if html is None:
        html = ""
    h_lower = html.lower()
    detected: List[str] = []
    evidence: List[str] = []

    for tech, sigs in CMS_SIGNATURES:
        if any(s.lower() in h_lower for s in sigs):
            detected.append(tech)
            evidence.append(f"HTML contains: {sigs[0]}")

    meta_gen_match = re.search(
        r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)["\']',
        html, flags=re.I,
    )
    if meta_gen_match:
        gen = meta_gen_match.group(1).strip()
        evidence.append(f"meta generator: {gen}")
        for k, label in FRAMEWORK_META_GENERATORS.items():
            if label.lower() in gen.lower():
                detected.append(k)

    if headers:
        xpb = headers.get("X-Powered-By") or headers.get("x-powered-by") or ""
        if xpb:
            evidence.append(f"X-Powered-By: {xpb}")
        server = headers.get("Server") or headers.get("server") or ""
        if server:
            evidence.append(f"Server: {server}")
        if "PHP" in xpb or "PHP" in server:
            detected.append("php")

    if "/_next/" in h_lower or "__next_data__" in h_lower:
        if "next.js" not in detected:
            detected.append("next.js")
            evidence.append("Next.js markers present")
    if "/_nuxt/" in h_lower or "window.__NUXT__" in h_lower:
        if "nuxt" not in detected:
            detected.append("nuxt")
            evidence.append("Nuxt markers present")
    if "react" in h_lower and "data-reactroot" in h_lower:
        if "react" not in detected:
            detected.append("react")
    if "vue" in h_lower and "data-v-" in h_lower:
        if "vue" not in detected:
            detected.append("vue")

    if not detected:
        detected.append("static-html")
        evidence.append("No CMS/framework markers detected")

    return {
        "detected": detected,
        "primary": detected[0] if detected else "unknown",
        "evidence": evidence,
    }


def detect_from_files(file_list: List[str]) -> Dict:
    if not file_list:
        return {"detected": [], "primary": "unknown", "evidence": ["No files available"]}

    paths = " ".join(file_list).lower()
    detected: List[str] = []
    evidence: List[str] = []

    checks = [
        ("wordpress", ["wp-config.php", "wp-content/", "wp-includes/"]),
        ("drupal", ["sites/default/settings.php", "core/modules"]),
        ("laravel", ["artisan", "app/config", "vendor/laravel"]),
        ("django", ["manage.py", "settings.py"]),
        ("flask", ["app.py", "wsgi.py"]),
        ("next.js", [".next/", "next.config.js"]),
        ("nuxt", [".nuxt/", "nuxt.config.js"]),
        ("gatsby", ["gatsby-config.js"]),
        ("static-html", ["index.html"]),
    ]
    for tech, sigs in checks:
        for s in sigs:
            if s.lower() in paths:
                if tech not in detected:
                    detected.append(tech)
                evidence.append(f"Found: {s}")
                break

    if "dist/" in paths or "build/" in paths or "out/" in paths:
        if not detected:
            detected.append("static-build")
            evidence.append("Build output detected (dist/build/out)")

    if not detected:
        detected.append("unknown")
        evidence.append("Unable to identify technology from files")

    return {"detected": detected, "primary": detected[0], "evidence": evidence}