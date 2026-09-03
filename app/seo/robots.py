"""robots.txt parser and analyzer."""
from __future__ import annotations
import requests
from typing import Dict, List
from urllib.parse import urljoin


def fetch_robots(root_url: str, timeout: int = 10) -> str:
    try:
        r = requests.get(urljoin(root_url, "/robots.txt"), timeout=timeout,
                         headers={"User-Agent": "AI-SEO-Autopilot/1.0"})
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return ""


def parse_robots(text: str) -> Dict:
    groups: List[Dict] = []
    if not text:
        return {"groups": [], "sitemaps": [], "valid": True}
    current: Dict = {"user_agent": "*", "allow": [], "disallow": []}
    sitemaps: List[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if current["allow"] or current["disallow"] or current["user_agent"] != "*":
                groups.append(current)
            current = {"user_agent": value, "allow": [], "disallow": []}
        elif key == "allow":
            current["allow"].append(value)
        elif key == "disallow":
            current["disallow"].append(value)
        elif key == "sitemap":
            sitemaps.append(value)
    if current["allow"] or current["disallow"] or current["user_agent"]:
        groups.append(current)
    return {"groups": groups, "sitemaps": sitemaps, "valid": True}


def analyze_robots(text: str) -> Dict:
    parsed = parse_robots(text)
    blocking_all = any(
        "/" in g["disallow"] for g in parsed["groups"]
    )
    return {
        **parsed,
        "blocking_all": blocking_all,
        "has_sitemap_reference": bool(parsed["sitemaps"]),
        "issue_count": len(parsed["groups"]) if not parsed["valid"] else 0,
    }
