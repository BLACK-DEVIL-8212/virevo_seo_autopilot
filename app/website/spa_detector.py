"""Detect website architecture: static HTML vs SPA frameworks, hosting, and deployment strategy."""
from __future__ import annotations
import re
import json
from typing import Dict, List, Optional
from urllib.parse import urlparse


def detect_architecture(html: str, headers: Dict[str, str] | None = None, url: str = "") -> Dict:
    """Detect whether a website is static HTML, SPA, SSR, or hybrid."""
    if html is None:
        html = ""
    h_lower = html.lower()
    evidence: List[str] = []
    scores = {
        "react_spa": 0,
        "vue_spa": 0,
        "angular_spa": 0,
        "javascript_spa": 0,
        "ssr": 0,
        "static_html": 0,
        "hybrid": 0,
    }

    # React signals
    if "data-reactroot" in h_lower or "data-reactid" in h_lower:
        scores["react_spa"] += 3
        evidence.append("React DOM attributes found")
    if "reactdom" in h_lower or "react-dom" in h_lower:
        scores["react_spa"] += 2
        evidence.append("React DOM script reference")
    if "__react_fiber" in h_lower or "__reactInternalInstance" in h_lower:
        scores["react_spa"] += 2
        evidence.append("React internal markers")
    if "react-helmet" in h_lower or "helmet" in h_lower:
        scores["react_spa"] += 1
        evidence.append("React Helmet detected")

    # Vue signals
    if "data-v-" in h_lower:
        scores["vue_spa"] += 3
        evidence.append("Vue scoped CSS markers")
    if "window.__vue__" in h_lower or "vue.runtime" in h_lower or "vue.js" in h_lower:
        scores["vue_spa"] += 2
        evidence.append("Vue runtime detected")
    if "vue-router" in h_lower:
        scores["vue_spa"] += 2
        evidence.append("Vue Router detected")

    # Angular signals
    if "ng-app" in h_lower or "angular.js" in h_lower or "@angular" in h_lower:
        scores["angular_spa"] += 3
        evidence.append("Angular markers")
    if "ng-version" in h_lower:
        scores["angular_spa"] += 2
        evidence.append("Angular version attribute")

    # Generic JS app shell / SPA
    if re.search(r'<div[^>]*id=["\'](root|app|app-root|main)["\']', h_lower):
        scores["javascript_spa"] += 2
        evidence.append("Single root div app shell")
    if re.search(r'<div[^>]*id=["\'](root|app)["\'][^>]*>\s*</div>', h_lower):
        scores["javascript_spa"] += 2
        evidence.append("Empty root div (JS-rendered)")
    if "bundle.js" in h_lower or "main.js" in h_lower or "app.js" in h_lower:
        scores["javascript_spa"] += 1
        evidence.append("App bundle script")
    if "chunk.js" in h_lower or "vendors" in h_lower:
        scores["javascript_spa"] += 1
        evidence.append("Webpack/Vite chunks")

    # SSR / Hybrid signals
    if "__next_data__" in h_lower or "_next/" in h_lower:
        scores["ssr"] += 2
        evidence.append("Next.js SSR/SSG markers")
    if "__NUXT__" in h_lower or "_nuxt/" in h_lower:
        scores["ssr"] += 2
        evidence.append("Nuxt SSR/SSG markers")
    if "gatsby" in h_lower or "gatsby-" in h_lower:
        scores["ssr"] += 2
        evidence.append("Gatsby SSG markers")
    if "rendered by" in h_lower and "express" in h_lower:
        scores["ssr"] += 1
        evidence.append("Express rendering marker")

    # Firebase Hosting
    is_firebase = False
    if headers:
        x_fb = headers.get("X-Firebase-Version") or headers.get("x-firebase-version") or ""
        if x_fb:
            scores["react_spa"] += 1
            scores["javascript_spa"] += 1
            evidence.append(f"Firebase Hosting header: {x_fb}")
            is_firebase = True

    hosting = "unknown"
    if is_firebase or urlparse(url).hostname and "web.app" in url or "firebaseapp.com" in url:
        hosting = "firebase"
        evidence.append("Firebase Hosting domain")

    if headers:
        server = headers.get("Server") or headers.get("server") or ""
        if "Netlify" in server:
            hosting = "netlify"
            evidence.append(f"Server header: {server}")
        elif "Vercel" in server:
            hosting = "vercel"
            evidence.append(f"Server header: {server}")
        elif "cloudflare" in server.lower():
            hosting = "cloudflare"
            evidence.append(f"Server header: {server}")

    # Determine primary architecture
    max_score = max(scores.values())
    if max_score == 0:
        primary = "static_html"
        evidence.append("No SPA/SSR markers detected")
    else:
        candidates = [k for k, v in scores.items() if v == max_score]
        primary = candidates[0] if candidates else "static_html"

    if primary == "react_spa" and is_firebase:
        primary = "firebase_spa"

    if scores["ssr"] > 0 and (scores["react_spa"] > 0 or scores["javascript_spa"] > 0):
        primary = "hybrid"
        evidence.append("Hybrid SSR + SPA detected")

    # Deployment strategy
    deployment_strategy = "direct_html"
    if primary in ("react_spa", "vue_spa", "angular_spa", "javascript_spa", "firebase_spa"):
        if hosting == "firebase":
            deployment_strategy = "firebase_deploy"
        elif "github" in (headers.get("Server", "") if headers else "").lower():
            deployment_strategy = "git_deploy"
        else:
            deployment_strategy = "source_code_build"

    return {
        "architecture_type": primary,
        "rendering_mode": "rendered" if primary not in ("static_html",) else "raw",
        "deployment_strategy": deployment_strategy,
        "hosting_provider": hosting,
        "scores": scores,
        "evidence": evidence,
        "detected_spa_framework": primary,
        "is_spa": primary not in ("static_html",),
    }


def detect_from_js_bundle(html: str) -> Dict:
    """Inspect script tags and bundle references to infer build system."""
    scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, flags=re.I)
    build_signals = {
        "webpack": [],
        "vite": [],
        "parcel": [],
        "rollup": [],
        "gatsby": [],
    }
    for src in scripts:
        s = src.lower()
        if "webpack" in s or "/chunk." in s or "vendors" in s:
            build_signals["webpack"].append(src)
        if "vite" in s or "/assets/" in s:
            build_signals["vite"].append(src)
        if "parcel" in s:
            build_signals["parcel"].append(src)
        if "rollup" in s:
            build_signals["rollup"].append(src)
        if "gatsby" in s:
            build_signals["gatsby"].append(src)

    build_system = "unknown"
    for system, hits in build_signals.items():
        if hits:
            build_system = system
            break
    return {"build_system": build_system, "scripts": scripts, "signals": build_signals}


def extract_manifest_links(html: str) -> Dict:
    """Extract link tags for manifests, icons, and preloads."""
    links = re.findall(r'<link[^>]+rel=["\']([^"\']+)["\'][^>]+href=["\']([^"\']+)["\']', html, flags=re.I)
    manifest = None
    icons = []
    preloads = []
    for rel, href in links:
        r = rel.lower()
        if r == "manifest":
            manifest = href
        if "icon" in r:
            icons.append(href)
        if r in ("preload", "prefetch"):
            preloads.append(href)
    return {"manifest": manifest, "icons": icons, "preloads": preloads}
