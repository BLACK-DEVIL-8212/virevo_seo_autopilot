"""Website-level analysis - parses a page and extracts SEO fields.

Comprehensive HTML parsing and SEO metadata extraction including:
- Title, meta description, and meta tags
- Open Graph and Twitter Cards
- Structured data (JSON-LD)
- Headings (H1-H6)
- Images with alt text
- Internal and external links
- Word count and content analysis
- SEO score calculation
- Thin content detection
"""
from __future__ import annotations
import re
import json
import logging
from urllib.parse import urljoin, urlparse
from typing import Dict, List, Optional, Any, Tuple, Set
from collections import Counter
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

# Setup logging
logger = logging.getLogger(__name__)


# ============================================================================
# REGULAR EXPRESSIONS
# ============================================================================

META_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\']([^"\']+)["\'][^>]+content=["\']([^"\']*)["\']',
    flags=re.I,
)

URL_RE = re.compile(r'https?://[^\s<>"\'{}|\\^`\[\]]+', flags=re.I)

EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', flags=re.I)

PHONE_RE = re.compile(r'(\+\d{1,3}[-.]?)?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}', flags=re.I)

# ============================================================================
# META TAG EXTRACTION
# ============================================================================

def extract_meta_tags(soup: BeautifulSoup) -> Dict[str, str]:
    """Extract all meta tags from the document."""
    out: Dict[str, str] = {}
    for m in soup.find_all("meta"):
        key = m.get("name") or m.get("property") or m.get("http-equiv")
        content = m.get("content", "")
        if key:
            out[key.lower()] = content.strip()
    return out


def extract_open_graph(soup: BeautifulSoup) -> Dict[str, str]:
    """Extract Open Graph meta tags."""
    out = {}
    for m in soup.find_all("meta"):
        prop = m.get("property", "")
        if prop.startswith("og:"):
            out[prop] = m.get("content", "").strip()
    return out


def extract_twitter_cards(soup: BeautifulSoup) -> Dict[str, str]:
    """Extract Twitter Card meta tags."""
    out = {}
    for m in soup.find_all("meta"):
        name = m.get("name", "")
        if name.startswith("twitter:"):
            out[name] = m.get("content", "").strip()
    return out


def extract_structured_data(soup: BeautifulSoup) -> List[Dict]:
    """Extract JSON-LD structured data from the document."""
    out = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
            if isinstance(data, dict):
                out.append(data)
            elif isinstance(data, list):
                out.extend(data)
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse JSON-LD: {e}")
            continue
        except Exception as e:
            logger.debug(f"Error parsing JSON-LD: {e}")
            continue
    return out


def extract_headings(soup: BeautifulSoup) -> Dict[str, List[str]]:
    """Extract all heading tags (H1-H6)."""
    headings: Dict[str, List[str]] = {}
    for level in range(1, 7):
        tag = f"h{level}"
        headings[tag] = [h.get_text(" ", strip=True) for h in soup.find_all(tag)]
    return headings


def extract_images(soup: BeautifulSoup, base_url: str = "") -> Dict[str, Any]:
    """Extract image information including src, alt, title, etc."""
    imgs = []
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if base_url and src and not src.startswith(("http://", "https://", "data:", "//")):
            src = urljoin(base_url, src)
        
        imgs.append({
            "src": src,
            "alt": img.get("alt", "").strip(),
            "title": img.get("title", "").strip(),
            "width": img.get("width", ""),
            "height": img.get("height", ""),
            "loading": img.get("loading", ""),
            "sizes": img.get("sizes", ""),
            "srcset": img.get("srcset", ""),
        })
    
    images_with_alt = sum(1 for img in imgs if img.get("alt"))
    
    return {
        "count": len(imgs),
        "images": imgs,
        "images_with_alt": images_with_alt,
        "alt_ratio": round(images_with_alt / max(1, len(imgs)), 2)
    }


def extract_links(soup: BeautifulSoup, base_url: str) -> Dict[str, Any]:
    """Extract internal, external, and nofollow links."""
    from ..utils import is_internal
    
    internal, external, nofollow = [], [], []
    
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        
        anchor_text = a.get_text(" ", strip=True)
        rel = a.get("rel", [])
        if isinstance(rel, str):
            rel = rel.split()
        is_nofollow = "nofollow" in [r.lower() for r in rel] if rel else False
        
        link_data = {
            "href": href,
            "text": anchor_text[:100],
            "rel": " ".join(rel) if rel else "",
            "nofollow": is_nofollow,
            "target": a.get("target", ""),
        }
        
        # Determine if internal
        if base_url and is_internal(href, base_url):
            internal.append(link_data)
        else:
            external.append(link_data)
        
        if is_nofollow:
            nofollow.append(link_data)
    
    return {
        "internal_count": len(internal),
        "external_count": len(external),
        "nofollow_count": len(nofollow),
        "total_links": len(internal) + len(external),
        "internal": internal[:50],
        "external": external[:50],
        "internal_domains": list(set([urlparse(u["href"]).netloc for u in internal if u["href"].startswith("http")]))[:10],
        "external_domains": list(set([urlparse(u["href"]).netloc for u in external if u["href"].startswith("http")]))[:10],
    }


def extract_main_text(soup: BeautifulSoup) -> str:
    """Extract main text content from the document."""
    # Remove script, style, noscript, template elements
    for element in soup(["script", "style", "noscript", "template", "iframe"]):
        element.decompose()
    
    # Remove comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    
    # Get body content
    body = soup.body
    if not body:
        # If no body, use the whole document
        body = soup
    
    # Get text with spaces between elements
    text = body.get_text(" ", strip=True)
    
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)
    
    return text.strip()


def extract_canonical(soup: BeautifulSoup) -> str:
    """Extract canonical URL."""
    canon = soup.find("link", rel="canonical")
    return canon.get("href", "").strip() if canon else ""


def extract_robots_meta(soup: BeautifulSoup) -> str:
    """Extract robots meta tag."""
    robots = soup.find("meta", attrs={"name": "robots"})
    return robots.get("content", "").strip() if robots else ""


def extract_language(soup: BeautifulSoup) -> str:
    """Extract language from html tag."""
    html_tag = soup.find("html")
    return html_tag.get("lang", "").strip() if html_tag else ""


def extract_charset(soup: BeautifulSoup) -> str:
    """Extract character encoding."""
    # Check meta charset
    charset_meta = soup.find("meta", attrs={"charset": True})
    if charset_meta:
        return charset_meta.get("charset", "").strip()
    
    # Check http-equiv content-type
    content_type = soup.find("meta", attrs={"http-equiv": "Content-Type"})
    if content_type:
        content = content_type.get("content", "")
        match = re.search(r'charset=([^\s;]+)', content, re.I)
        if match:
            return match.group(1)
    
    return ""


def extract_keywords(soup: BeautifulSoup) -> List[str]:
    """Extract keywords from meta keywords tag."""
    keywords_meta = soup.find("meta", attrs={"name": "keywords"})
    if keywords_meta:
        content = keywords_meta.get("content", "")
        return [k.strip() for k in content.split(",") if k.strip()]
    return []


def extract_breadcrumbs(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """Extract breadcrumb navigation."""
    breadcrumbs = []
    
    # Look for common breadcrumb patterns
    selectors = [
        '.breadcrumb',
        '.breadcrumbs',
        '[aria-label="breadcrumb"]',
        'nav[aria-label="breadcrumb"]',
        '.woocommerce-breadcrumb',
        '#breadcrumbs',
        'ul.breadcrumb',
    ]
    
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            for item in element.find_all(['a', 'span']):
                if item.name == 'a':
                    breadcrumbs.append({
                        "text": item.get_text(strip=True),
                        "url": item.get("href", ""),
                        "is_current": False
                    })
                elif item.name == 'span' and 'current' in item.get('class', []):
                    breadcrumbs.append({
                        "text": item.get_text(strip=True),
                        "url": "",
                        "is_current": True
                    })
            if breadcrumbs:
                break
    
    return breadcrumbs


def extract_favicon(soup: BeautifulSoup) -> Optional[str]:
    """Extract favicon URL."""
    # Check for link rel icon
    for rel in ["icon", "shortcut icon", "apple-touch-icon"]:
        link = soup.find("link", rel=rel)
        if link and link.get("href"):
            return link.get("href")
    
    return None


def extract_manifest(soup: BeautifulSoup) -> Optional[str]:
    """Extract web app manifest URL."""
    link = soup.find("link", rel="manifest")
    if link and link.get("href"):
        return link.get("href")
    return None


def extract_social_links(soup: BeautifulSoup) -> Dict[str, str]:
    """Extract social media links."""
    social = {}
    
    # Common social media patterns
    social_patterns = {
        "facebook": ["facebook.com", "fb.com"],
        "twitter": ["twitter.com", "x.com"],
        "instagram": ["instagram.com"],
        "linkedin": ["linkedin.com"],
        "youtube": ["youtube.com", "youtu.be"],
        "pinterest": ["pinterest.com"],
        "github": ["github.com"],
        "tiktok": ["tiktok.com"],
        "reddit": ["reddit.com"],
        "medium": ["medium.com"],
    }
    
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").lower()
        for platform, domains in social_patterns.items():
            if any(domain in href for domain in domains):
                if platform not in social:
                    social[platform] = href
                break
    
    return social


def extract_contact_info(soup: BeautifulSoup) -> Dict[str, Any]:
    """Extract contact information."""
    text = extract_main_text(soup)
    
    contact = {}
    
    # Email addresses
    emails = EMAIL_RE.findall(text)
    if emails:
        contact["emails"] = list(set(emails))[:5]
    
    # Phone numbers
    phones = PHONE_RE.findall(text)
    if phones:
        contact["phones"] = list(set(phones))[:5]
    
    # Check for contact links
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").lower()
        if "mailto:" in href:
            email = href.split("mailto:")[-1].split("?")[0]
            if email and email not in contact.get("emails", []):
                contact.setdefault("emails", []).append(email)
        elif "tel:" in href:
            phone = href.split("tel:")[-1]
            if phone and phone not in contact.get("phones", []):
                contact.setdefault("phones", []).append(phone)
    
    return contact


def extract_schema_types(soup: BeautifulSoup) -> List[str]:
    """Extract schema.org types from structured data."""
    types = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
            if isinstance(data, dict):
                if "@type" in data:
                    types.append(data["@type"])
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "@type" in item:
                        types.append(item["@type"])
        except Exception:
            continue
    return types


# ============================================================================
# WORD COUNT AND TEXT ANALYSIS
# ============================================================================

def word_count(text: str) -> int:
    """Count words in text."""
    if not text:
        return 0
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def character_count(text: str) -> int:
    """Count characters in text."""
    return len(text) if text else 0


def reading_time(text: str, words_per_minute: int = 200) -> float:
    """Estimate reading time in minutes."""
    wc = word_count(text)
    return round(wc / words_per_minute, 1)


def keyword_density(text: str, keyword: str) -> float:
    """Calculate keyword density as percentage."""
    if not text or not keyword:
        return 0.0
    wc = word_count(text)
    if wc == 0:
        return 0.0
    keyword_lower = keyword.lower()
    text_lower = text.lower()
    count = text_lower.count(keyword_lower)
    return round(count / wc * 100, 2)


def extract_keywords_from_text(text: str, max_keywords: int = 20) -> List[Dict[str, Any]]:
    """Extract keywords from text with frequency."""
    if not text:
        return []
    
    # Clean text
    text = re.sub(r'[^a-zA-Z\s]', ' ', text.lower())
    words = text.split()
    
    # Stop words
    stop_words = {
        "the", "and", "for", "with", "this", "that", "from", "have", "been",
        "were", "was", "are", "not", "but", "they", "their", "what", "when",
        "where", "which", "while", "about", "your", "more", "other", "some",
        "into", "than", "them", "then", "these", "through", "over", "such",
        "after", "also", "just", "most", "very", "every", "should", "could",
        "would", "there", "here", "where", "being", "because", "between",
        "both", "during", "before", "after", "under", "again", "further",
        "once", "without", "within", "along", "across", "behind", "beyond",
        "toward", "towards", "upon", "whether", "either", "neither", "though",
        "although", "even", "only", "many", "much", "well", "back", "still",
        "way", "take", "come", "make", "like", "long", "look", "right", "used",
        "know", "get", "got", "let", "say", "said", "see", "two", "one", "new",
        "first", "last", "good", "great", "best", "better"
    }
    
    # Filter words
    filtered = [w for w in words if w not in stop_words and len(w) > 2]
    
    # Count frequencies
    freq = Counter(filtered)
    
    # Return top keywords
    return [
        {"keyword": word, "count": count, "frequency": round(count / len(filtered) * 100, 2)}
        for word, count in freq.most_common(max_keywords)
    ]


def analyze_content_quality(text: str) -> Dict[str, Any]:
    """Analyze content quality metrics."""
    if not text:
        return {"word_count": 0, "quality_score": 0}
    
    wc = word_count(text)
    
    # Calculate basic quality metrics
    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
    avg_sentence_length = sum(word_count(s) for s in sentences) / max(1, len(sentences))
    avg_word_length = sum(len(w) for w in text.split()) / max(1, word_count(text))
    
    # Quality scoring
    quality_score = 0
    if wc >= 300:
        quality_score += 30
    elif wc >= 200:
        quality_score += 20
    elif wc >= 100:
        quality_score += 10
    
    if 15 <= avg_sentence_length <= 25:
        quality_score += 20
    elif 10 <= avg_sentence_length <= 35:
        quality_score += 10
    
    if 4.5 <= avg_word_length <= 6.5:
        quality_score += 20
    elif 4 <= avg_word_length <= 7:
        quality_score += 10
    
    if len(sentences) >= 5:
        quality_score += 15
    elif len(sentences) >= 3:
        quality_score += 8
    
    # Check for proper formatting (paragraphs)
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    if len(paragraphs) >= 3:
        quality_score += 15
    
    return {
        "word_count": wc,
        "sentence_count": len(sentences),
        "avg_sentence_length": round(avg_sentence_length, 1),
        "avg_word_length": round(avg_word_length, 2),
        "paragraph_count": len(paragraphs),
        "quality_score": min(100, quality_score),
        "reading_time_minutes": reading_time(text),
    }


# ============================================================================
# MAIN ANALYZE FUNCTION
# ============================================================================

def analyze_html(html: str, base_url: str = "") -> Dict[str, Any]:
    """
    Comprehensive HTML analysis for SEO purposes.
    
    Args:
        html: HTML content to analyze
        base_url: Base URL for resolving relative URLs
        
    Returns:
        Dictionary with all extracted SEO data
    """
    if not html:
        return {
            "title": "",
            "meta_description": "",
            "meta_tags": {},
            "headings": {},
            "main_content": "",
            "word_count": 0,
            "images": {"count": 0, "images": []},
            "links": {"internal_count": 0, "external_count": 0, "total_links": 0},
            "open_graph": {},
            "twitter": {},
            "structured_data": [],
            "canonical": "",
            "robots_meta": "",
            "language": "",
            "charset": "",
            "keywords": [],
            "breadcrumbs": [],
            "favicon": None,
            "manifest": None,
            "social_links": {},
            "contact_info": {},
            "schema_types": [],
            "content_quality": {},
            "error": "Empty HTML provided"
        }
    
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        logger.error(f"Failed to parse HTML: {e}")
        return {
            "title": "",
            "meta_description": "",
            "meta_tags": {},
            "headings": {},
            "main_content": "",
            "word_count": 0,
            "images": {"count": 0, "images": []},
            "links": {"internal_count": 0, "external_count": 0, "total_links": 0},
            "open_graph": {},
            "twitter": {},
            "structured_data": [],
            "canonical": "",
            "robots_meta": "",
            "language": "",
            "charset": "",
            "keywords": [],
            "breadcrumbs": [],
            "favicon": None,
            "manifest": None,
            "social_links": {},
            "contact_info": {},
            "schema_types": [],
            "content_quality": {},
            "error": f"Parse error: {str(e)}"
        }
    
    # Extract all metadata
    meta_tags = extract_meta_tags(soup)
    title = (soup.title.string or "").strip() if soup.title else ""
    description = meta_tags.get("description", "")
    
    headings = extract_headings(soup)
    main_text = extract_main_text(soup)
    images = extract_images(soup, base_url)
    links = extract_links(soup, base_url)
    og = extract_open_graph(soup)
    twitter = extract_twitter_cards(soup)
    structured_data = extract_structured_data(soup)
    
    canonical = extract_canonical(soup)
    robots_meta = extract_robots_meta(soup)
    language = extract_language(soup)
    charset = extract_charset(soup)
    keywords = extract_keywords(soup)
    
    breadcrumbs = extract_breadcrumbs(soup)
    favicon = extract_favicon(soup)
    manifest = extract_manifest(soup)
    social_links = extract_social_links(soup)
    contact_info = extract_contact_info(soup)
    schema_types = extract_schema_types(soup)
    
    # Content quality analysis
    content_quality = analyze_content_quality(main_text)
    
    # Extract keywords from content
    content_keywords = extract_keywords_from_text(main_text)
    
    # Detect duplicate canonical if any
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
        "twitter": twitter,
        "structured_data": structured_data,
        "canonical": canonical,
        "robots_meta": robots_meta,
        "language": language,
        "charset": charset,
        "keywords": keywords,
        "breadcrumbs": breadcrumbs,
        "favicon": favicon,
        "manifest": manifest,
        "social_links": social_links,
        "contact_info": contact_info,
        "schema_types": schema_types,
        "content_quality": content_quality,
        "content_keywords": content_keywords,
        "has_duplicate_meta": canonical_info.get("has_duplicate", False),
        "canonical_info": canonical_info,
        "error": None
    }


# ============================================================================
# DUPLICATE CANONICAL DETECTION
# ============================================================================

def detect_duplicate_canonical(soup: BeautifulSoup) -> Dict[str, Any]:
    """Detect duplicate canonical issues."""
    canonicals = soup.find_all("link", rel="canonical")
    
    result = {
        "canonical": "",
        "robots": "",
        "has_duplicate": False,
        "count": len(canonicals),
        "canonical_values": []
    }
    
    if canonicals:
        result["canonical"] = canonicals[0].get("href", "")
        result["canonical_values"] = [c.get("href", "") for c in canonicals]
        if len(canonicals) > 1:
            result["has_duplicate"] = True
            result["message"] = f"Multiple canonical tags found ({len(canonicals)})"
    
    robots = soup.find("meta", attrs={"name": "robots"})
    if robots:
        result["robots"] = robots.get("content", "")
        if "noindex" in result["robots"].lower():
            result["message"] = "Page has noindex directive"
    
    return result


# ============================================================================
# THIN CONTENT DETECTION
# ============================================================================

def detect_thin_content(analyzed: Dict, threshold: int = 250) -> bool:
    """Detect thin content based on word count."""
    word_count = analyzed.get("word_count", 0)
    return word_count < threshold


def detect_thin_content_detailed(analyzed: Dict) -> Dict[str, Any]:
    """Detailed thin content detection with reasons."""
    result = {
        "is_thin": False,
        "reasons": [],
        "metrics": {}
    }
    
    wc = analyzed.get("word_count", 0)
    result["metrics"]["word_count"] = wc
    
    if wc < 250:
        result["reasons"].append(f"Low word count: {wc} words (threshold: 250)")
        result["is_thin"] = True
    
    if wc < 100:
        result["reasons"].append(f"Very low word count: {wc} words (threshold: 100)")
        result["is_thin"] = True
    
    # Check for images
    images = analyzed.get("images", {})
    img_count = images.get("count", 0)
    result["metrics"]["image_count"] = img_count
    
    if img_count == 0 and wc < 300:
        result["reasons"].append("No images and low word count")
        result["is_thin"] = True
    
    # Check for links
    links = analyzed.get("links", {})
    internal_links = links.get("internal_count", 0)
    result["metrics"]["internal_links"] = internal_links
    
    if internal_links == 0 and wc < 250:
        result["reasons"].append("No internal links and low word count")
        result["is_thin"] = True
    
    return result


# ============================================================================
# SEO SCORE CALCULATION
# ============================================================================

def calculate_seo_score(analyzed: Dict) -> float:
    """
    Compute a comprehensive 0-100 SEO score.
    
    Scoring criteria:
    - Title: 15 points
    - Meta description: 15 points
    - H1 heading: 10 points
    - Headings structure: 5 points
    - Word count: 10 points
    - Images with alt: 10 points
    - Internal links: 10 points
    - Open Graph: 5 points
    - Twitter Cards: 5 points
    - Structured data: 10 points
    - Canonical: 5 points
    """
    score = 0.0
    
    # Title (15 points)
    title = analyzed.get("title", "")
    if title:
        score += 5
        title_len = len(title)
        if 30 <= title_len <= 65:
            score += 10
        elif 20 <= title_len <= 70:
            score += 7
        elif title_len > 0:
            score += 3
    
    # Meta description (15 points)
    desc = analyzed.get("meta_description", "")
    if desc:
        score += 5
        desc_len = len(desc)
        if 70 <= desc_len <= 170:
            score += 10
        elif 50 <= desc_len <= 200:
            score += 7
        elif desc_len > 0:
            score += 3
    
    # H1 heading (10 points)
    headings = analyzed.get("headings", {})
    h1s = headings.get("h1", [])
    if h1s:
        score += 5
        if len(h1s) == 1:
            score += 5
        elif len(h1s) > 1:
            score += 2
    
    # Headings structure (5 points)
    h2s = headings.get("h2", [])
    if h2s:
        score += 3
        if len(h2s) >= 3:
            score += 2
    
    # Word count (10 points)
    wc = analyzed.get("word_count", 0)
    if wc >= 500:
        score += 10
    elif wc >= 300:
        score += 8
    elif wc >= 200:
        score += 5
    elif wc >= 100:
        score += 3
    
    # Images with alt (10 points)
    images = analyzed.get("images", {})
    alt_ratio = images.get("alt_ratio", 0)
    if images.get("count", 0) > 0:
        score += alt_ratio * 10
    else:
        score += 3  # No images but not penalized
    
    # Internal links (10 points)
    links = analyzed.get("links", {})
    internal = links.get("internal_count", 0)
    if internal >= 5:
        score += 10
    elif internal >= 3:
        score += 7
    elif internal >= 1:
        score += 5
    
    # Open Graph (5 points)
    og = analyzed.get("open_graph", {})
    if og.get("og:title"):
        score += 3
    if og.get("og:description"):
        score += 2
    
    # Twitter Cards (5 points)
    twitter = analyzed.get("twitter", {})
    if twitter.get("twitter:title"):
        score += 3
    if twitter.get("twitter:description"):
        score += 2
    
    # Structured data (10 points)
    sd = analyzed.get("structured_data", [])
    if sd:
        score += min(10, len(sd) * 3)
    
    # Canonical (5 points)
    if analyzed.get("canonical"):
        score += 5
    
    # Language (bonus)
    if analyzed.get("language"):
        score += 2
    
    # Robots meta (bonus)
    robots = analyzed.get("robots_meta", "")
    if robots and "noindex" not in robots.lower():
        score += 3
    
    return min(100.0, score)
