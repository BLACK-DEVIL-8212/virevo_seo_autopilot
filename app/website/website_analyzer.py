"""Website-level analysis - parses a page and extracts SEO fields."""
from __future__ import annotations
import re
import json
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from typing import Dict, List


META_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\']([^"\']+)["\'][^>]+content=["\']([^"\']*)["\']',
    flags=re.I,
)


def extract_meta_tags(soup: BeautifulSoup) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in soup.find_all("meta"):
        key = m.get("name") or m.get("property") or m.get("http-equiv")
        content = m.get("content", "")
        if key:
            out[key.lower()] = content
    return out


def extract_open_graph(soup: BeautifulSoup) -> Dict[str, str]:
    out = {}
    for m in soup.find_all("meta"):
        prop = m.get("property", "")
        if prop.startswith("og:"):
            out[prop] = m.get("content", "")
    return out


def extract_twitter(soup: BeautifulSoup) -> Dict[str, str]:
    out = {}
    for m in soup.find_all("meta"):
        name = m.get("name", "")
        if name.startswith("twitter:"):
            out[name] = m.get("content", "")
    return out


def extract_structured_data(soup: BeautifulSoup) -> List[Dict]:
    out = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "{}")
            if isinstance(data, dict):
                out.append(data)
            elif isinstance(data, list):
                out.extend(data)
        except Exception:
            continue
    return out


def extract_headings(soup: BeautifulSoup) -> Dict:
    headings: Dict[str, List[str]] = {}
    for level in range(1, 7):
        tag = f"h{level}"
        headings[tag] = [h.get_text(" ", strip=True) for h in soup.find_all(tag)]
    return headings


def extract_images(soup: BeautifulSoup, base_url: str = "") -> Dict:
    imgs = []
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if base_url and src and not src.startswith(("http://", "https://", "data:")):
            src = urljoin(base_url, src)
        imgs.append({
            "src": src,
            "alt": img.get("alt", "").strip(),
            "title": img.get("title", "").strip(),
            "width": img.get("width", ""),
            "height": img.get("height", ""),
            "loading": img.get("loading", ""),
        })
    return {"count": len(imgs), "images": imgs}


def extract_links(soup: BeautifulSoup, base_url: str) -> Dict:
    from ..utils import is_internal
    internal, external, nofollow = [], [], []
    for a in soup.find_all("a"):
        href = a.get("href", "").strip()
        if not href:
            continue
        anchor_text = a.get_text(" ", strip=True)
        rel = (a.get("rel") or [])
        if isinstance(rel, str):
            rel = rel.split()
        is_nofollow = "nofollow" in [r.lower() for r in rel]
        item = {"href": href, "text": anchor_text}
        if base_url and is_internal(href, base_url):
            internal.append(item)
        else:
            external.append(item)
        if is_nofollow:
            nofollow.append(item)
    return {
        "internal_count": len(internal),
        "external_count": len(external),
        "nofollow_count": len(nofollow),
        "internal": internal[:50],
        "external": external[:50],
    }


def extract_main_text(soup: BeautifulSoup) -> str:
    for s in soup(["script", "style", "noscript", "template"]):
        s.decompose()
    body = soup.body or soup
    text = body.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", text or "") if w])


def detect_duplicate_canonical(soup: BeautifulSoup) -> Dict:
    canon = soup.find("link", rel="canonical")
    robots = soup.find("meta", attrs={"name": "robots"})
    return {
        "canonical": canon.get("href", "") if canon else "",
        "robots": robots.get("content", "") if robots else "",
    }


def analyze_html(html: str, base_url: str = "") -> Dict:
    soup = BeautifulSoup(html or "", "html.parser")
    html_tag = soup.find("html")
    lang = html_tag.get("lang", "") if html_tag else ""

    title = (soup.title.string or "").strip() if soup.title else ""
    meta_tags = extract_meta_tags(soup)
    description = meta_tags.get("description", "")

    headings = extract_headings(soup)
    main_text = extract_main_text(soup)
    images = extract_images(soup, base_url)
    links = extract_links(soup, base_url)
    og = extract_open_graph(soup)
    tw = extract_twitter(soup)
    sd = extract_structured_data(soup)
    canonical_info = detect_duplicate_canonical(soup)

    return {
        "title": title,
        "meta_description": description,
        "meta_tags": meta_tags,
        "headings": headings,
        "main_content": main_text[:5000],
        "word_count": word_count(main_text),
        "images": images,
        "links": links,
        "open_graph": og,
        "twitter": tw,
        "structured_data": sd,
        "canonical": canonical_info["canonical"],
        "robots_meta": canonical_info["robots"],
        "language": lang,
    }


def detect_thin_content(analyzed: Dict, threshold: int = 250) -> bool:
    return analyzed.get("word_count", 0) < threshold


def calculate_seo_score(analyzed: Dict) -> float:
    """Compute a simple 0-100 SEO score."""
    score = 0.0
    weights = {
        "has_title": 15,
        "title_length_ok": 10,
        "has_description": 15,
        "description_length_ok": 10,
        "has_h1": 10,
        "single_h1": 5,
        "has_canonical": 5,
        "has_og": 5,
        "has_structured_data": 10,
        "good_word_count": 5,
        "images_have_alt": 5,
        "has_internal_links": 5,
    }
    title = analyzed.get("title", "")
    desc = analyzed.get("meta_description", "")
    headings = analyzed.get("headings", {})
    images = analyzed.get("images", {})
    canonical = analyzed.get("canonical", "")
    og = analyzed.get("open_graph", {})
    sd = analyzed.get("structured_data", [])
    wc = analyzed.get("word_count", 0)
    links = analyzed.get("links", {})

    if title:
        score += weights["has_title"]
        if 30 <= len(title) <= 65:
            score += weights["title_length_ok"]
    if desc:
        score += weights["has_description"]
        if 70 <= len(desc) <= 170:
            score += weights["description_length_ok"]
    h1s = headings.get("h1", [])
    if h1s:
        score += weights["has_h1"]
        if len(h1s) == 1:
            score += weights["single_h1"]
    if canonical:
        score += weights["has_canonical"]
    if og:
        score += weights["has_og"]
    if sd:
        score += weights["has_structured_data"]
    if wc >= 250:
        score += weights["good_word_count"]
    imgs = images.get("images", [])
    if imgs and all(img.get("alt") for img in imgs):
        score += weights["images_have_alt"]
    if links.get("internal_count", 0) > 0:
        score += weights["has_internal_links"]
    return min(100.0, score)