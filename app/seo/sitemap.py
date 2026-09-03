"""Sitemap discovery, validation and generation."""
from __future__ import annotations
import requests
import re
from xml.etree import ElementTree as ET
from typing import List, Dict, Optional
from urllib.parse import urljoin, urlparse
from datetime import datetime


def discover_sitemaps(root_url: str, timeout: int = 10) -> List[str]:
    """Try common sitemap paths."""
    candidates = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml"]
    found: List[str] = []
    for path in candidates:
        url = urljoin(root_url, path)
        try:
            r = requests.head(url, timeout=timeout, allow_redirects=True,
                              headers={"User-Agent": "AI-SEO-Autopilot/1.0"})
            if r.status_code == 200:
                found.append(url)
        except Exception:
            continue
    return found


def fetch_sitemap(url: str, timeout: int = 10) -> Optional[str]:
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "AI-SEO-Autopilot/1.0"})
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return None


def parse_sitemap(xml_text: str) -> List[Dict]:
    if not xml_text:
        return []
    urls: List[Dict] = []
    try:
        root = ET.fromstring(xml_text)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        if root.tag.endswith("sitemapindex"):
            for child in root.findall("sm:sitemap", ns):
                loc = child.find("sm:loc", ns)
                if loc is not None and loc.text:
                    urls.append({"loc": loc.text.strip(), "type": "sitemap"})
        else:
            for child in root.findall("sm:url", ns):
                loc = child.find("sm:loc", ns)
                if loc is not None and loc.text:
                    lastmod = child.find("sm:lastmod", ns)
                    urls.append({
                        "loc": loc.text.strip(),
                        "lastmod": lastmod.text.strip() if lastmod is not None and lastmod.text else "",
                        "type": "url",
                    })
    except Exception:
        # try without namespace
        try:
            root = ET.fromstring(xml_text)
            for child in root:
                if child.tag.lower().endswith("loc") and child.text:
                    urls.append({"loc": child.text.strip(), "type": "url"})
        except Exception:
            pass
    return urls


def validate_sitemap(xml_text: str) -> Dict:
    try:
        ET.fromstring(xml_text)
        return {"valid": True, "error": ""}
    except Exception as e:
        return {"valid": False, "error": str(e)}


def generate_sitemap(urls: List[str], base_url: str = "") -> str:
    urlset = ET.Element("urlset", {
        "xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9",
    })
    today = datetime.utcnow().strftime("%Y-%m-%d")
    for u in urls:
        url_el = ET.SubElement(urlset, "url")
        loc = ET.SubElement(url_el, "loc")
        loc.text = u
        lastmod = ET.SubElement(url_el, "lastmod")
        lastmod.text = today
        ET.SubElement(url_el, "changefreq")
        ET.SubElement(url_el, "priority").text = "0.5"
    ET.indent(urlset, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(urlset, encoding="unicode")