"""Safe HTML modification engine.

Uses BeautifulSoup to make structured, surgical edits to HTML.
Never uses raw string replacement for SEO-critical changes.
Supports all SEO metadata updates including title, meta descriptions,
canonical URLs, Open Graph tags, structured data, and more.
"""
from __future__ import annotations
import json
import re
import logging
from copy import deepcopy
from typing import Dict, List, Optional, Tuple, Any, Union
from bs4 import BeautifulSoup, Doctype, Comment, NavigableString, Tag

# Setup logging
logger = logging.getLogger(__name__)


# ============================================================================
# HTML PARSING AND SERIALIZATION
# ============================================================================

def parse_html(html: str) -> Tuple[BeautifulSoup, bool]:
    """Parse HTML and detect doctype presence.

    Args:
        html: HTML string to parse

    Returns:
        Tuple of (BeautifulSoup object, had_doctype)
    """
    had_doctype = bool(re.search(r"<!doctype\s+html", html, flags=re.I)) if html else False
    
    try:
        soup = BeautifulSoup(html or "", "html.parser")
    except Exception as e:
        logger.warning(f"Failed to parse HTML: {e}")
        # Create minimal document if parsing fails
        soup = BeautifulSoup("<html><head></head><body></body></html>", "html.parser")
    
    # Ensure html tag exists
    if not soup.find("html"):
        html_tag = soup.new_tag("html")
        if soup.contents:
            # Move all contents into html tag
            for child in list(soup.contents):
                html_tag.append(child)
        soup = BeautifulSoup(str(html_tag), "html.parser")
    
    # Ensure head tag exists
    if not soup.find("head"):
        head_tag = soup.new_tag("head")
        if soup.html:
            soup.html.insert(0, head_tag)
    
    # Ensure body tag exists
    if not soup.find("body"):
        body_tag = soup.new_tag("body")
        if soup.html:
            soup.html.append(body_tag)
    
    return soup, had_doctype


def serialize_html(soup: BeautifulSoup, had_doctype: bool = True, pretty: bool = False) -> str:
    """Serialize BeautifulSoup back to HTML string.

    Args:
        soup: BeautifulSoup object
        had_doctype: Whether to include DOCTYPE declaration
        pretty: Whether to prettify output

    Returns:
        HTML string
    """
    if pretty:
        out = soup.prettify()
    else:
        out = str(soup)
    
    # Ensure DOCTYPE is present if it was originally
    if had_doctype and not out.lstrip().lower().startswith("<!doctype"):
        out = "<!DOCTYPE html>\n" + out
    
    return out


def get_html_metadata(soup: BeautifulSoup) -> Dict[str, Any]:
    """Extract all SEO metadata from parsed HTML.

    Args:
        soup: BeautifulSoup object

    Returns:
        Dictionary with all metadata
    """
    metadata = {}
    
    # Title
    title_tag = soup.find("title")
    metadata["title"] = title_tag.string.strip() if title_tag and title_tag.string else ""
    
    # Meta description
    meta_desc = soup.find("meta", attrs={"name": "description"})
    metadata["meta_description"] = meta_desc.get("content", "") if meta_desc else ""
    
    # Canonical URL
    canonical = soup.find("link", rel="canonical")
    metadata["canonical"] = canonical.get("href", "") if canonical else ""
    
    # Robots meta
    robots = soup.find("meta", attrs={"name": "robots"})
    metadata["robots_meta"] = robots.get("content", "") if robots else ""
    
    # Open Graph tags
    og_tags = {}
    for meta in soup.find_all("meta"):
        if meta.get("property", "").startswith("og:"):
            og_tags[meta["property"]] = meta.get("content", "")
    metadata["open_graph"] = og_tags
    
    # Twitter Cards
    twitter_tags = {}
    for meta in soup.find_all("meta"):
        if meta.get("name", "").startswith("twitter:"):
            twitter_tags[meta["name"]] = meta.get("content", "")
    metadata["twitter"] = twitter_tags
    
    # Structured data
    structured_data = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
            structured_data.append(data)
        except json.JSONDecodeError:
            structured_data.append({"error": "Invalid JSON"})
    metadata["structured_data"] = structured_data
    
    # Headings
    headings = {}
    for level in ["h1", "h2", "h3", "h4", "h5", "h6"]:
        headings[level] = [tag.text.strip() for tag in soup.find_all(level)]
    metadata["headings"] = headings
    
    # Images
    images = []
    for img in soup.find_all("img"):
        images.append({
            "src": img.get("src", ""),
            "alt": img.get("alt", ""),
            "width": img.get("width", ""),
            "height": img.get("height", "")
        })
    metadata["images"] = images
    
    # Links
    links = {"internal": [], "external": [], "nofollow": []}
    for a in soup.find_all("a"):
        href = a.get("href", "")
        rel = a.get("rel", [])
        if href and not href.startswith("#") and not href.startswith("javascript:"):
            if "nofollow" in rel:
                links["nofollow"].append(href)
            elif href.startswith(("http://", "https://")):
                links["external"].append(href)
            else:
                links["internal"].append(href)
    metadata["links"] = links
    
    # Word count
    for script in soup(["script", "style"]):
        script.decompose()
    text = soup.get_text(" ", strip=True)
    metadata["word_count"] = len(text.split())
    
    return metadata


# ============================================================================
# SEO METADATA UPDATE FUNCTIONS
# ============================================================================

def ensure_head(soup: BeautifulSoup) -> Tag:
    """Ensure head tag exists and return it."""
    head = soup.find("head")
    if not head:
        head = soup.new_tag("head")
        if soup.html:
            soup.html.insert(0, head)
        else:
            # If no html tag, create one
            html_tag = soup.new_tag("html")
            html_tag.append(head)
            soup.insert(0, html_tag)
    return head


def update_title(soup: BeautifulSoup, new_title: str) -> bool:
    """Update or add title tag.

    Args:
        soup: BeautifulSoup object
        new_title: New title text

    Returns:
        True if changed, False if unchanged
    """
    if not new_title:
        return False
    
    title_tag = soup.find("title")
    current_title = title_tag.string.strip() if title_tag and title_tag.string else ""
    
    if title_tag:
        if current_title == new_title:
            return False
        title_tag.string = new_title
        return True
    
    # Create new title tag
    head = ensure_head(soup)
    new_tag = soup.new_tag("title")
    new_tag.string = new_title
    head.append(new_tag)
    return True


def update_meta_description(soup: BeautifulSoup, new_desc: str) -> bool:
    """Update or add meta description.

    Args:
        soup: BeautifulSoup object
        new_desc: New meta description content

    Returns:
        True if changed, False if unchanged
    """
    if not new_desc:
        return False
    
    head = ensure_head(soup)
    existing = head.find("meta", attrs={"name": "description"})
    
    if existing:
        current = existing.get("content", "")
        if current == new_desc:
            return False
        existing["content"] = new_desc
        return True
    
    new_tag = soup.new_tag("meta", attrs={"name": "description", "content": new_desc})
    head.append(new_tag)
    return True


def update_canonical(soup: BeautifulSoup, url: str) -> bool:
    """Update or add canonical URL.

    Args:
        soup: BeautifulSoup object
        url: Canonical URL

    Returns:
        True if changed, False if unchanged
    """
    if not url:
        return False
    
    head = ensure_head(soup)
    existing = head.find("link", rel="canonical")
    
    if existing:
        current = existing.get("href", "")
        if current == url:
            return False
        existing["href"] = url
        return True
    
    new_tag = soup.new_tag("link", rel="canonical", href=url)
    head.append(new_tag)
    return True


def update_robots_meta(soup: BeautifulSoup, value: str) -> bool:
    """Update or add robots meta tag.

    Args:
        soup: BeautifulSoup object
        value: Robots meta content (e.g., "index, follow")

    Returns:
        True if changed, False if unchanged
    """
    if not value:
        return False
    
    head = ensure_head(soup)
    existing = head.find("meta", attrs={"name": "robots"})
    
    if existing:
        current = existing.get("content", "")
        if current == value:
            return False
        existing["content"] = value
        return True
    
    new_tag = soup.new_tag("meta", attrs={"name": "robots", "content": value})
    head.append(new_tag)
    return True


def update_viewport(soup: BeautifulSoup, value: str = "width=device-width, initial-scale=1.0") -> bool:
    """Update or add viewport meta tag.

    Args:
        soup: BeautifulSoup object
        value: Viewport content

    Returns:
        True if changed, False if unchanged
    """
    head = ensure_head(soup)
    existing = head.find("meta", attrs={"name": "viewport"})
    
    if existing:
        current = existing.get("content", "")
        if current == value:
            return False
        existing["content"] = value
        return True
    
    new_tag = soup.new_tag("meta", attrs={"name": "viewport", "content": value})
    head.append(new_tag)
    return True


def update_charset(soup: BeautifulSoup, charset: str = "UTF-8") -> bool:
    """Update or add charset meta tag.

    Args:
        soup: BeautifulSoup object
        charset: Character encoding

    Returns:
        True if changed, False if unchanged
    """
    head = ensure_head(soup)
    
    # Check for existing charset meta tag
    existing = head.find("meta", attrs={"charset": True})
    if existing:
        current = existing.get("charset", "")
        if current == charset:
            return False
        existing["charset"] = charset
        return True
    
    # Also check for http-equiv content-type
    existing = head.find("meta", attrs={"http-equiv": "Content-Type"})
    if existing:
        current = existing.get("content", "")
        new_content = f"text/html; charset={charset}"
        if current == new_content:
            return False
        existing["content"] = new_content
        return True
    
    new_tag = soup.new_tag("meta", attrs={"charset": charset})
    head.append(new_tag)
    return True


def update_open_graph(soup: BeautifulSoup, og_data: Dict[str, str]) -> bool:
    """Update or add Open Graph meta tags.

    Args:
        soup: BeautifulSoup object
        og_data: Dictionary of og:property -> content

    Returns:
        True if any changes were made
    """
    if not og_data:
        return False
    
    head = ensure_head(soup)
    changed = False
    
    for prop, content in og_data.items():
        if not content:
            continue
        
        # Ensure property starts with og:
        if not prop.startswith("og:"):
            prop = f"og:{prop}"
        
        existing = head.find("meta", attrs={"property": prop})
        if existing:
            if existing.get("content", "") != content:
                existing["content"] = content
                changed = True
        else:
            new_tag = soup.new_tag("meta", attrs={"property": prop, "content": content})
            head.append(new_tag)
            changed = True
    
    return changed


def update_twitter_cards(soup: BeautifulSoup, twitter_data: Dict[str, str]) -> bool:
    """Update or add Twitter Card meta tags.

    Args:
        soup: BeautifulSoup object
        twitter_data: Dictionary of twitter:name -> content

    Returns:
        True if any changes were made
    """
    if not twitter_data:
        return False
    
    head = ensure_head(soup)
    changed = False
    
    for name, content in twitter_data.items():
        if not content:
            continue
        
        # Ensure name starts with twitter:
        if not name.startswith("twitter:"):
            name = f"twitter:{name}"
        
        existing = head.find("meta", attrs={"name": name})
        if existing:
            if existing.get("content", "") != content:
                existing["content"] = content
                changed = True
        else:
            new_tag = soup.new_tag("meta", attrs={"name": name, "content": content})
            head.append(new_tag)
            changed = True
    
    return changed


def add_structured_data(soup: BeautifulSoup, data: Union[Dict, List]) -> bool:
    """Add structured data (JSON-LD) to the page.

    Args:
        soup: BeautifulSoup object
        data: JSON-LD data as dict or list

    Returns:
        True if added, False if failed
    """
    if not data:
        return False
    
    head = ensure_head(soup)
    
    # Ensure data is a list
    if not isinstance(data, list):
        data = [data]
    
    for item in data:
        if not isinstance(item, dict):
            continue
        
        # Validate basic schema structure
        if "@context" not in item:
            item["@context"] = "https://schema.org"
        
        script_tag = soup.new_tag("script", type="application/ld+json")
        try:
            script_tag.string = json.dumps(item, ensure_ascii=False, indent=2)
            head.append(script_tag)
        except (TypeError, ValueError) as e:
            logger.warning(f"Failed to serialize structured data: {e}")
            return False
    
    return True


def update_image_alt(soup: BeautifulSoup, src_substring: str, new_alt: str) -> bool:
    """Update alt text for images matching a src pattern.

    Args:
        soup: BeautifulSoup object
        src_substring: Substring to match in src attribute
        new_alt: New alt text

    Returns:
        True if any changes were made
    """
    if not src_substring or not new_alt:
        return False
    
    changed = False
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src_substring in src:
            old_alt = img.get("alt", "")
            if old_alt != new_alt:
                img["alt"] = new_alt
                changed = True
    
    return changed


def update_all_images_alt(soup: BeautifulSoup, alt_generator: callable) -> bool:
    """Update alt text for all images using a generator function.

    Args:
        soup: BeautifulSoup object
        alt_generator: Function that takes img tag and returns alt text

    Returns:
        True if any changes were made
    """
    changed = False
    for img in soup.find_all("img"):
        current_alt = img.get("alt", "")
        new_alt = alt_generator(img)
        if new_alt and new_alt != current_alt:
            img["alt"] = new_alt
            changed = True
    
    return changed


def update_h1(soup: BeautifulSoup, new_h1: str) -> bool:
    """Update or add H1 heading.

    Args:
        soup: BeautifulSoup object
        new_h1: New H1 text

    Returns:
        True if changed, False if unchanged
    """
    if not new_h1:
        return False
    
    h1_tag = soup.find("h1")
    if h1_tag:
        if h1_tag.text.strip() == new_h1:
            return False
        h1_tag.string = new_h1
        return True
    
    # Create new H1
    body = soup.find("body")
    if not body:
        body = soup.new_tag("body")
        if soup.html:
            soup.html.append(body)
    
    new_tag = soup.new_tag("h1")
    new_tag.string = new_h1
    body.insert(0, new_tag)
    return True


def update_headings(soup: BeautifulSoup, headings_data: Dict[str, List[str]]) -> bool:
    """Update multiple heading levels.

    Args:
        soup: BeautifulSoup object
        headings_data: Dict mapping heading level to list of text values

    Returns:
        True if any changes were made
    """
    changed = False
    
    for level, texts in headings_data.items():
        if not level.startswith("h"):
            level = f"h{level}"
        
        tags = soup.find_all(level)
        for i, text in enumerate(texts):
            if i < len(tags):
                if tags[i].string != text:
                    tags[i].string = text
                    changed = True
            else:
                # Add new heading
                body = soup.find("body")
                if body:
                    new_tag = soup.new_tag(level)
                    new_tag.string = text
                    body.append(new_tag)
                    changed = True
    
    return changed


def remove_element(soup: BeautifulSoup, selector: str) -> bool:
    """Remove elements matching a CSS selector.

    Args:
        soup: BeautifulSoup object
        selector: CSS selector

    Returns:
        True if any elements were removed
    """
    elements = soup.select(selector)
    if not elements:
        return False
    
    for element in elements:
        element.decompose()
    
    return True


def add_element(soup: BeautifulSoup, tag: str, content: str, parent_selector: str = "body", position: str = "append") -> bool:
    """Add a new element to the page.

    Args:
        soup: BeautifulSoup object
        tag: HTML tag name
        content: Text content
        parent_selector: CSS selector for parent element
        position: "append", "prepend", or "after"

    Returns:
        True if added
    """
    parent = soup.select_one(parent_selector)
    if not parent:
        return False
    
    new_tag = soup.new_tag(tag)
    new_tag.string = content
    
    if position == "prepend":
        parent.insert(0, new_tag)
    elif position == "after":
        parent.insert_after(new_tag)
    else:
        parent.append(new_tag)
    
    return True


# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_html(html: str) -> Dict[str, Any]:
    """Validate HTML structure.

    Args:
        html: HTML string to validate

    Returns:
        Dictionary with validation results
    """
    result = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "metadata": {}
    }
    
    if not html or not html.strip():
        result["valid"] = False
        result["errors"].append("HTML is empty")
        return result
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        
        # Check for html tag
        if not soup.find("html"):
            result["valid"] = False
            result["errors"].append("Missing <html> tag")
        
        # Check for head tag
        if not soup.find("head"):
            result["warnings"].append("Missing <head> tag")
        
        # Check for body tag
        if not soup.find("body"):
            result["warnings"].append("Missing <body> tag")
        
        # Check for title
        if not soup.find("title"):
            result["warnings"].append("Missing <title> tag")
        
        # Check for doctype
        if not re.search(r"<!doctype\s+html", html, flags=re.I):
            result["warnings"].append("Missing DOCTYPE declaration")
        
        # Check for meta description
        if not soup.find("meta", attrs={"name": "description"}):
            result["warnings"].append("Missing meta description")
        
        # Check for charset
        has_charset = False
        if soup.find("meta", attrs={"charset": True}):
            has_charset = True
        elif soup.find("meta", attrs={"http-equiv": "Content-Type"}):
            has_charset = True
        if not has_charset:
            result["warnings"].append("Missing charset meta tag")
        
        # Extract metadata for additional validation
        result["metadata"] = get_html_metadata(soup)
        
        # Check for unclosed tags
        html_str = str(soup)
        if html_str.count("<") != html_str.count(">"):
            result["warnings"].append("Potential unclosed tags detected")
        
    except Exception as e:
        result["valid"] = False
        result["errors"].append(f"Parse error: {str(e)}")
    
    return result


def validate_json_ld(html: str) -> List[Dict[str, Any]]:
    """Validate JSON-LD structured data in HTML.

    Args:
        html: HTML string

    Returns:
        List of validation results for each script
    """
    results = []
    
    if not html:
        return results
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        scripts = soup.find_all("script", type="application/ld+json")
        
        if not scripts:
            results.append({
                "valid": False,
                "error": "No JSON-LD structured data found"
            })
            return results
        
        for i, script in enumerate(scripts):
            script_content = script.string or "{}"
            try:
                data = json.loads(script_content)
                
                # Basic validation
                valid = True
                issues = []
                
                if "@context" not in data:
                    issues.append("Missing @context")
                    valid = False
                
                if "@type" not in data:
                    issues.append("Missing @type")
                    valid = False
                
                if "@context" in data and data["@context"] != "https://schema.org":
                    issues.append(f"Invalid @context: {data['@context']}")
                    valid = False
                
                results.append({
                    "index": i,
                    "valid": valid,
                    "issues": issues,
                    "type": data.get("@type", "unknown"),
                    "data": data if valid else None
                })
                
            except json.JSONDecodeError as e:
                results.append({
                    "index": i,
                    "valid": False,
                    "issues": [f"Invalid JSON: {str(e)}"],
                    "type": "invalid"
                })
    
    except Exception as e:
        results.append({
            "valid": False,
            "error": f"Parse error: {str(e)}"
        })
    
    return results


def validate_seo_metadata(html: str) -> Dict[str, Any]:
    """Validate SEO metadata in HTML.

    Args:
        html: HTML string

    Returns:
        Dictionary with validation results
    """
    result = {
        "valid": True,
        "issues": [],
        "warnings": [],
        "metadata": {}
    }
    
    if not html:
        result["valid"] = False
        result["issues"].append("HTML is empty")
        return result
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        metadata = get_html_metadata(soup)
        result["metadata"] = metadata
        
        # Validate title
        title = metadata.get("title", "")
        if not title:
            result["valid"] = False
            result["issues"].append("Title is missing")
        elif len(title) < 20:
            result["warnings"].append(f"Title is too short: {len(title)} chars (recommended 30-65)")
        elif len(title) > 65:
            result["warnings"].append(f"Title is too long: {len(title)} chars (recommended 30-65)")
        
        # Validate meta description
        desc = metadata.get("meta_description", "")
        if not desc:
            result["valid"] = False
            result["issues"].append("Meta description is missing")
        elif len(desc) < 50:
            result["warnings"].append(f"Meta description is too short: {len(desc)} chars (recommended 120-160)")
        elif len(desc) > 160:
            result["warnings"].append(f"Meta description is too long: {len(desc)} chars (recommended 120-160)")
        
        # Validate canonical
        canonical = metadata.get("canonical", "")
        if not canonical:
            result["warnings"].append("Canonical URL is missing")
        
        # Validate Open Graph
        og = metadata.get("open_graph", {})
        if not og:
            result["warnings"].append("Open Graph tags are missing")
        else:
            if "og:title" not in og:
                result["warnings"].append("og:title is missing")
            if "og:description" not in og:
                result["warnings"].append("og:description is missing")
            if "og:type" not in og:
                result["warnings"].append("og:type is missing")
        
        # Validate H1
        h1s = metadata.get("headings", {}).get("h1", [])
        if not h1s:
            result["warnings"].append("H1 heading is missing")
        elif len(h1s) > 1:
            result["warnings"].append(f"Multiple H1 tags found: {len(h1s)}")
        
        # Validate word count
        word_count = metadata.get("word_count", 0)
        if word_count < 100:
            result["warnings"].append(f"Low word count: {word_count} words (recommended 300+)")
        
        # Validate images
        images = metadata.get("images", [])
        images_without_alt = [img for img in images if not img.get("alt")]
        if images_without_alt:
            result["warnings"].append(f"{len(images_without_alt)} images missing alt text")
        
    except Exception as e:
        result["valid"] = False
        result["issues"].append(f"Validation error: {str(e)}")
    
    return result


# ============================================================================
# MAIN APPLY CHANGES FUNCTION
# ============================================================================

def apply_changes(html: str, changes: List[Dict]) -> Tuple[str, List[Dict]]:
    """Apply a list of structured changes to HTML.

    Args:
        html: Original HTML string
        changes: List of change dictionaries with 'type' and 'value' keys

    Returns:
        Tuple of (new_html, applied_log)
    """
    soup, had_doctype = parse_html(html)
    log: List[Dict] = []
    
    # Group changes by type to avoid conflicts
    change_types = {}
    for c in changes:
        ctype = c.get("type")
        if ctype not in change_types:
            change_types[ctype] = []
        change_types[ctype].append(c)
    
    try:
        # Process title
        if "title" in change_types:
            for c in change_types["title"]:
                try:
                    if update_title(soup, c.get("value", "")):
                        log.append({"type": "title", "applied": True, "value": c.get("value", "")})
                except Exception as e:
                    log.append({"type": "title", "applied": False, "error": str(e)})
        
        # Process meta_description
        if "meta_description" in change_types:
            for c in change_types["meta_description"]:
                try:
                    if update_meta_description(soup, c.get("value", "")):
                        log.append({"type": "meta_description", "applied": True, "value": c.get("value", "")[:50] + "..."})
                except Exception as e:
                    log.append({"type": "meta_description", "applied": False, "error": str(e)})
        
        # Process canonical
        if "canonical" in change_types:
            for c in change_types["canonical"]:
                try:
                    if update_canonical(soup, c.get("value", "")):
                        log.append({"type": "canonical", "applied": True, "value": c.get("value", "")})
                except Exception as e:
                    log.append({"type": "canonical", "applied": False, "error": str(e)})
        
        # Process robots_meta
        if "robots_meta" in change_types:
            for c in change_types["robots_meta"]:
                try:
                    if update_robots_meta(soup, c.get("value", "")):
                        log.append({"type": "robots_meta", "applied": True, "value": c.get("value", "")})
                except Exception as e:
                    log.append({"type": "robots_meta", "applied": False, "error": str(e)})
        
        # Process open_graph
        if "open_graph" in change_types:
            for c in change_types["open_graph"]:
                try:
                    if update_open_graph(soup, c.get("value", {})):
                        log.append({"type": "open_graph", "applied": True})
                except Exception as e:
                    log.append({"type": "open_graph", "applied": False, "error": str(e)})
        
        # Process structured_data
        if "structured_data" in change_types:
            for c in change_types["structured_data"]:
                try:
                    if add_structured_data(soup, c.get("value", {})):
                        log.append({"type": "structured_data", "applied": True})
                except Exception as e:
                    log.append({"type": "structured_data", "applied": False, "error": str(e)})
        
        # Process image_alt
        if "image_alt" in change_types:
            for c in change_types["image_alt"]:
                try:
                    if update_image_alt(soup, c.get("match", ""), c.get("value", "")):
                        log.append({"type": "image_alt", "applied": True, "match": c.get("match", "")})
                except Exception as e:
                    log.append({"type": "image_alt", "applied": False, "error": str(e)})
        
        # Process h1
        if "h1" in change_types:
            for c in change_types["h1"]:
                try:
                    if update_h1(soup, c.get("value", "")):
                        log.append({"type": "h1", "applied": True, "value": c.get("value", "")})
                except Exception as e:
                    log.append({"type": "h1", "applied": False, "error": str(e)})
        
        # Process viewport
        if "viewport" in change_types:
            for c in change_types["viewport"]:
                try:
                    if update_viewport(soup, c.get("value", "width=device-width, initial-scale=1.0")):
                        log.append({"type": "viewport", "applied": True})
                except Exception as e:
                    log.append({"type": "viewport", "applied": False, "error": str(e)})
        
        # Process charset
        if "charset" in change_types:
            for c in change_types["charset"]:
                try:
                    if update_charset(soup, c.get("value", "UTF-8")):
                        log.append({"type": "charset", "applied": True})
                except Exception as e:
                    log.append({"type": "charset", "applied": False, "error": str(e)})
        
        # Process twitter_cards
        if "twitter" in change_types or "twitter_cards" in change_types:
            key = "twitter" if "twitter" in change_types else "twitter_cards"
            for c in change_types[key]:
                try:
                    if update_twitter_cards(soup, c.get("value", {})):
                        log.append({"type": "twitter", "applied": True})
                except Exception as e:
                    log.append({"type": "twitter", "applied": False, "error": str(e)})
    
    except Exception as e:
        logger.error(f"Error applying changes: {e}")
        log.append({"type": "general", "applied": False, "error": str(e)})
    
    return serialize_html(soup, had_doctype), log


# ============================================================================
# BATCH OPERATIONS
# ============================================================================

def batch_apply_changes(html: str, changes: List[Dict], validate: bool = True) -> Dict[str, Any]:
    """Apply changes with validation and rollback on failure.

    Args:
        html: Original HTML
        changes: List of changes
        validate: Whether to validate after changes

    Returns:
        Dictionary with results, validation, and applied changes
    """
    result = {
        "ok": True,
        "new_html": html,
        "applied_log": [],
        "validation": {},
        "error": None
    }
    
    try:
        # Apply changes
        new_html, applied_log = apply_changes(html, changes)
        result["new_html"] = new_html
        result["applied_log"] = applied_log
        
        # Validate if requested
        if validate:
            validation = validate_html(new_html)
            result["validation"] = validation
            
            if not validation.get("valid", True):
                result["ok"] = False
                result["error"] = "Validation failed"
                # Return original HTML on validation failure
                result["new_html"] = html
        
    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)
        result["new_html"] = html
    
    return result
