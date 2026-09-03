"""Pre-deployment validation engine."""
from __future__ import annotations
import json
from xml.etree import ElementTree as ET
from typing import Dict, List
from bs4 import BeautifulSoup

from ..modifiers import validate_html, validate_json_ld


def validate_change_payload(before_html: str, after_html: str, changes: List[Dict]) -> Dict:
    result = {"ok": True, "checks": []}
    # 1. HTML well-formed enough
    vb = validate_html(before_html or "")
    va = validate_html(after_html or "")
    result["checks"].append({"name": "html_wellformed", "ok": va["valid"], "detail": va.get("error", "")})
    if not va["valid"]:
        result["ok"] = False

    # 2. JSON-LD validity
    jld = validate_json_ld(after_html or "")
    if jld:
        bad = [j for j in jld if not j.get("valid")]
        result["checks"].append({"name": "json_ld_valid", "ok": not bad, "detail": bad})
        if bad:
            result["ok"] = False

    # 3. No title regression - only one <title>
    soup = BeautifulSoup(after_html or "", "html.parser")
    titles = soup.find_all("title")
    if len(titles) > 1:
        result["checks"].append({"name": "single_title", "ok": False, "detail": f"Found {len(titles)} titles"})
        result["ok"] = False
    else:
        result["checks"].append({"name": "single_title", "ok": True})

    # 4. Word count shouldn't massively decrease
    for s in soup(["script", "style"]):
        s.decompose()
    text = soup.get_text(" ", strip=True)
    words_after = len(text.split())
    soup_b = BeautifulSoup(before_html or "", "html.parser")
    for s in soup_b(["script", "style"]):
        s.decompose()
    text_b = soup_b.get_text(" ", strip=True)
    words_before = len(text_b.split())
    if words_before > 0 and (words_before - words_after) / max(1, words_before) > 0.5:
        result["checks"].append({
            "name": "no_massive_content_loss",
            "ok": False,
            "detail": f"Before: {words_before} words, After: {words_after} words",
        })
        result["ok"] = False
    else:
        result["checks"].append({"name": "no_massive_content_loss", "ok": True})

    # 5. Sitemap XML validity if a sitemap change is included
    sitemap_changes = [c for c in changes if c.get("type") == "sitemap_update"]
    for sc in sitemap_changes:
        try:
            ET.fromstring(sc.get("value", ""))
            result["checks"].append({"name": "sitemap_valid", "ok": True})
        except Exception as e:
            result["checks"].append({"name": "sitemap_valid", "ok": False, "detail": str(e)})
            result["ok"] = False

    return result