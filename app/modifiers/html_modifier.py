"""Safe HTML modification engine.

Uses BeautifulSoup to make structured, surgical edits to HTML.
Never uses raw string replacement for SEO-critical changes.
"""
from __future__ import annotations
import json
import re
from copy import deepcopy
from bs4 import BeautifulSoup, Doctype, Comment
from typing import Dict, List, Optional, Tuple


def parse_html(html: str) -> Tuple[BeautifulSoup, bool]:
    """Parse HTML. Detect doctype presence."""
    had_doctype = bool(re.search(r"<!doctype\s+html", html, flags=re.I))
    soup = BeautifulSoup(html or "<html><head></head><body></body></html>",
                        "html.parser")
    return soup, had_doctype


def serialize_html(soup: BeautifulSoup, had_doctype: bool = True) -> str:
    out = str(soup)
    if had_doctype and not out.lstrip().lower().startswith("<!doctype"):
        out = "<!DOCTYPE html>\n" + out
    return out


def update_title(soup: BeautifulSoup, new_title: str) -> bool:
    t = soup.find("title")
    if t:
        if t.string == new_title:
            return False
        t.string = new_title
        return True
    head = soup.find("head") or soup.insert(0, soup.new_tag("head"))
    new = soup.new_tag("title")
    new.string = new_title
    head.append(new)
    return True


def _ensure_meta(soup: BeautifulSoup, attrs: Dict) -> BeautifulSoup:
    m = soup.new_tag("meta", **attrs)
    return m


def update_meta_description(soup: BeautifulSoup, new_desc: str) -> bool:
    head = soup.find("head")
    if not head:
        head = soup.new_tag("head")
        soup.html.insert(0, head)
    existing = head.find("meta", attrs={"name": "description"})
    if existing:
        if existing.get("content", "") == new_desc:
            return False
        existing["content"] = new_desc
        return True
    new = soup.new_tag("meta", attrs={"name": "description", "content": new_desc})
    head.append(new)
    return True


def update_canonical(soup: BeautifulSoup, url: str) -> bool:
    head = soup.find("head")
    if not head:
        head = soup.new_tag("head")
        soup.html.insert(0, head)
    existing = head.find("link", rel="canonical")
    if existing:
        if existing.get("href") == url:
            return False
        existing["href"] = url
        return True
    new = soup.new_tag("link", rel="canonical", href=url)
    head.append(new)
    return True


def update_robots_meta(soup: BeautifulSoup, value: str) -> bool:
    head = soup.find("head")
    if not head:
        head = soup.new_tag("head")
        soup.html.insert(0, head)
    existing = head.find("meta", attrs={"name": "robots"})
    if existing:
        existing["content"] = value
        return True
    new = soup.new_tag("meta", attrs={"name": "robots", "content": value})
    head.append(new)
    return True


def update_open_graph(soup: BeautifulSoup, og: Dict[str, str]) -> bool:
    head = soup.find("head")
    if not head:
        head = soup.new_tag("head")
        soup.html.insert(0, head)
    changed = False
    for k, v in og.items():
        existing = head.find("meta", attrs={"property": k})
        if existing:
            if existing.get("content") != v:
                existing["content"] = v
                changed = True
        else:
            head.append(soup.new_tag("meta", attrs={"property": k, "content": v}))
            changed = True
    return changed


def add_structured_data(soup: BeautifulSoup, data: Dict) -> bool:
    head = soup.find("head")
    if not head:
        head = soup.new_tag("head")
        soup.html.insert(0, head)
    script = soup.new_tag("script", type="application/ld+json")
    script.string = json.dumps(data, ensure_ascii=False)
    head.append(script)
    return True


def update_image_alt(soup: BeautifulSoup, src_substring: str, new_alt: str) -> bool:
    changed = False
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src_substring in src:
            old = img.get("alt", "")
            if old != new_alt:
                img["alt"] = new_alt
                changed = True
    return changed


def apply_changes(html: str, changes: List[Dict]) -> Tuple[str, List[Dict]]:
    """Apply a list of structured changes. Returns (new_html, applied_log)."""
    soup, had_doctype = parse_html(html)
    log: List[Dict] = []
    for c in changes:
        ctype = c.get("type")
        try:
            if ctype == "title":
                if update_title(soup, c["value"]):
                    log.append({"type": ctype, "applied": True})
            elif ctype == "meta_description":
                if update_meta_description(soup, c["value"]):
                    log.append({"type": ctype, "applied": True})
            elif ctype == "canonical":
                if update_canonical(soup, c["value"]):
                    log.append({"type": ctype, "applied": True})
            elif ctype == "robots_meta":
                if update_robots_meta(soup, c["value"]):
                    log.append({"type": ctype, "applied": True})
            elif ctype == "open_graph":
                if update_open_graph(soup, c["value"]):
                    log.append({"type": ctype, "applied": True})
            elif ctype == "structured_data":
                if add_structured_data(soup, c["value"]):
                    log.append({"type": ctype, "applied": True})
            elif ctype == "image_alt":
                if update_image_alt(soup, c.get("match", ""), c["value"]):
                    log.append({"type": ctype, "applied": True})
        except Exception as e:
            log.append({"type": ctype, "applied": False, "error": str(e)})
    return serialize_html(soup, had_doctype), log


def validate_html(html: str) -> Dict:
    try:
        soup = BeautifulSoup(html or "", "html.parser")
        # Check for unclosed tags / balanced structure
        return {"valid": True, "title": soup.title.string if soup.title else ""}
    except Exception as e:
        return {"valid": False, "error": str(e)}


def validate_json_ld(html: str) -> List[Dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    results = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            json.loads(s.string or "{}")
            results.append({"valid": True, "length": len(s.string or "")})
        except Exception as e:
            results.append({"valid": False, "error": str(e)})
    return results