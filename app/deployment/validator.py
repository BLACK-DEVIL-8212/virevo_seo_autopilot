"""Pre-deployment validation engine.

Comprehensive validation before deploying SEO changes to production.
Validates HTML structure, content quality, performance impact, and SEO metrics.
"""
from __future__ import annotations
import json
import re
import logging
from xml.etree import ElementTree as ET
from typing import Dict, List, Optional, Any, Tuple
from collections import Counter
from urllib.parse import urlparse

from bs4 import BeautifulSoup

# Setup logging
logger = logging.getLogger(__name__)


# ============================================================================
# HTML VALIDATION
# ============================================================================

def validate_html(html: str) -> Dict:
    """Validate HTML structure and well-formedness."""
    result = {
        "valid": True,
        "error": None,
        "warnings": [],
        "checks": []
    }
    
    if not html or not html.strip():
        result["valid"] = False
        result["error"] = "HTML is empty"
        return result
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        
        # Check for basic structure
        if not soup.find("html"):
            result["valid"] = False
            result["error"] = "Missing <html> tag"
            result["checks"].append({"name": "html_tag", "ok": False})
        else:
            result["checks"].append({"name": "html_tag", "ok": True})
        
        if not soup.find("head"):
            result["valid"] = False
            result["error"] = "Missing <head> tag"
            result["checks"].append({"name": "head_tag", "ok": False})
        else:
            result["checks"].append({"name": "head_tag", "ok": True})
        
        if not soup.find("body"):
            result["valid"] = False
            result["error"] = "Missing <body> tag"
            result["checks"].append({"name": "body_tag", "ok": False})
        else:
            result["checks"].append({"name": "body_tag", "ok": True})
        
        # Check for unclosed tags (basic)
        html_str = str(soup)
        if html_str.count("<") != html_str.count(">"):
            result["warnings"].append("Potential unclosed tags detected")
            result["checks"].append({"name": "tag_balance", "ok": False})
        else:
            result["checks"].append({"name": "tag_balance", "ok": True})
        
        # Check for DOCTYPE
        if not html.strip().lower().startswith("<!doctype"):
            result["warnings"].append("Missing DOCTYPE declaration")
            result["checks"].append({"name": "doctype", "ok": False})
        else:
            result["checks"].append({"name": "doctype", "ok": True})
        
        # Check for charset
        charset_found = False
        for meta in soup.find_all("meta"):
            if meta.get("charset") or (meta.get("http-equiv") and meta.get("http-equiv").lower() == "content-type"):
                charset_found = True
                break
        if not charset_found:
            result["warnings"].append("Missing charset meta tag")
            result["checks"].append({"name": "charset", "ok": False})
        else:
            result["checks"].append({"name": "charset", "ok": True})
        
    except Exception as e:
        result["valid"] = False
        result["error"] = f"Parse error: {str(e)}"
    
    return result


# ============================================================================
# JSON-LD VALIDATION
# ============================================================================

def validate_json_ld(html: str) -> List[Dict]:
    """Validate all JSON-LD structured data in HTML."""
    results = []
    
    if not html:
        return results
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        scripts = soup.find_all("script", type="application/ld+json")
        
        for i, script in enumerate(scripts):
            script_content = script.string or "{}"
            try:
                data = json.loads(script_content)
                
                # Basic schema validation
                valid = True
                issues = []
                
                # Check for @context
                if "@context" not in data:
                    valid = False
                    issues.append("Missing @context")
                
                # Check for @type
                if "@type" not in data:
                    valid = False
                    issues.append("Missing @type")
                
                # Check for valid @context value
                if "@context" in data and not isinstance(data["@context"], (str, dict)):
                    valid = False
                    issues.append("Invalid @context: must be string or object")
                
                # Check for valid @type value
                if "@type" in data and not isinstance(data["@type"], str):
                    valid = False
                    issues.append("Invalid @type: must be string")
                
                # Check for common required fields based on type
                type_value = data.get("@type", "").lower()
                if "article" in type_value or "blogposting" in type_value:
                    if "headline" not in data and "name" not in data:
                        valid = False
                        issues.append("Article missing headline or name")
                
                if "person" in type_value:
                    if "name" not in data:
                        valid = False
                        issues.append("Person missing name")
                
                if "organization" in type_value:
                    if "name" not in data:
                        valid = False
                        issues.append("Organization missing name")
                
                if "product" in type_value:
                    if "name" not in data:
                        valid = False
                        issues.append("Product missing name")
                
                results.append({
                    "index": i,
                    "valid": valid,
                    "issues": issues,
                    "type": data.get("@type", "unknown"),
                    "context": data.get("@context", "unknown")
                })
                
            except json.JSONDecodeError as e:
                results.append({
                    "index": i,
                    "valid": False,
                    "issues": [f"Invalid JSON: {str(e)}"],
                    "type": "invalid",
                    "context": "invalid"
                })
            except Exception as e:
                results.append({
                    "index": i,
                    "valid": False,
                    "issues": [f"Validation error: {str(e)}"],
                    "type": "error",
                    "context": "error"
                })
    
    except Exception as e:
        results.append({
            "index": 0,
            "valid": False,
            "issues": [f"Parse error: {str(e)}"],
            "type": "parse_error",
            "context": "parse_error"
        })
    
    return results


# ============================================================================
# SEO METRIC VALIDATION
# ============================================================================

def validate_seo_metrics(html: str, base_url: str = "") -> Dict:
    """Validate SEO metrics and return issues."""
    result = {
        "valid": True,
        "issues": [],
        "warnings": [],
        "metrics": {}
    }
    
    if not html:
        result["valid"] = False
        result["issues"].append("HTML is empty")
        return result
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        
        # Title validation
        titles = soup.find_all("title")
        if not titles:
            result["valid"] = False
            result["issues"].append("Missing title tag")
        elif len(titles) > 1:
            result["valid"] = False
            result["issues"].append(f"Multiple title tags found: {len(titles)}")
        else:
            title_text = titles[0].string or ""
            title_len = len(title_text)
            result["metrics"]["title_length"] = title_len
            if title_len < 20:
                result["warnings"].append(f"Title too short: {title_len} characters (recommended 30-65)")
            elif title_len > 65:
                result["warnings"].append(f"Title too long: {title_len} characters (recommended 30-65)")
            if not title_text.strip():
                result["valid"] = False
                result["issues"].append("Title tag is empty")
        
        # Meta description validation
        meta_desc = None
        for meta in soup.find_all("meta"):
            if meta.get("name", "").lower() == "description":
                meta_desc = meta.get("content", "")
                break
        
        if meta_desc is None:
            result["valid"] = False
            result["issues"].append("Missing meta description")
        else:
            desc_len = len(meta_desc)
            result["metrics"]["description_length"] = desc_len
            if desc_len < 50:
                result["warnings"].append(f"Meta description too short: {desc_len} characters (recommended 120-160)")
            elif desc_len > 160:
                result["warnings"].append(f"Meta description too long: {desc_len} characters (recommended 120-160)")
            if not meta_desc.strip():
                result["valid"] = False
                result["issues"].append("Meta description is empty")
        
        # H1 validation
        h1s = soup.find_all("h1")
        if not h1s:
            result["warnings"].append("Missing H1 heading")
        elif len(h1s) > 1:
            result["warnings"].append(f"Multiple H1 tags found: {len(h1s)}")
        elif not h1s[0].string or not h1s[0].string.strip():
            result["warnings"].append("H1 heading is empty")
        
        # H2 validation
        h2s = soup.find_all("h2")
        result["metrics"]["h2_count"] = len(h2s)
        if len(h2s) == 0:
            result["warnings"].append("No H2 headings found (recommended for content structure)")
        
        # Image alt validation
        images = soup.find_all("img")
        if images:
            images_without_alt = [img for img in images if not img.get("alt")]
            result["metrics"]["images_without_alt"] = len(images_without_alt)
            if images_without_alt:
                result["warnings"].append(f"{len(images_without_alt)} images missing alt text")
        
        # Word count validation
        for script in soup(["script", "style"]):
            script.decompose()
        text = soup.get_text(" ", strip=True)
        word_count = len(text.split())
        result["metrics"]["word_count"] = word_count
        if word_count < 100:
            result["warnings"].append(f"Low word count: {word_count} words (recommended 300+)")
        elif word_count < 300:
            result["warnings"].append(f"Word count could be improved: {word_count} words (recommended 300+)")
        
        # Canonical URL validation
        canonical = None
        for link in soup.find_all("link"):
            if link.get("rel") and "canonical" in link.get("rel", []):
                canonical = link.get("href")
                break
        
        if canonical is None:
            result["warnings"].append("Missing canonical URL")
        elif canonical and base_url:
            # Check if canonical is valid URL
            parsed = urlparse(canonical)
            if not parsed.netloc and base_url:
                result["warnings"].append("Canonical URL should be absolute")
        
        # Robots meta validation
        robots_meta = None
        for meta in soup.find_all("meta"):
            if meta.get("name", "").lower() == "robots":
                robots_meta = meta.get("content", "")
                break
        
        if robots_meta is not None:
            robots_lower = robots_meta.lower()
            if "noindex" in robots_lower:
                result["warnings"].append("Page has noindex directive")
            if "nofollow" in robots_lower:
                result["warnings"].append("Page has nofollow directive")
        
        # Open Graph validation
        og_props = {}
        for meta in soup.find_all("meta"):
            prop = meta.get("property", "")
            if prop and prop.startswith("og:"):
                og_props[prop] = meta.get("content", "")
        
        if not og_props:
            result["warnings"].append("Missing Open Graph tags")
        else:
            if not og_props.get("og:title"):
                result["warnings"].append("Missing og:title")
            if not og_props.get("og:description"):
                result["warnings"].append("Missing og:description")
            if not og_props.get("og:type"):
                result["warnings"].append("Missing og:type")
            if not og_props.get("og:url"):
                result["warnings"].append("Missing og:url")
        
        # Twitter Card validation
        twitter_cards = {}
        for meta in soup.find_all("meta"):
            name = meta.get("name", "")
            if name and name.startswith("twitter:"):
                twitter_cards[name] = meta.get("content", "")
        
        if not twitter_cards:
            result["warnings"].append("Missing Twitter Cards")
        else:
            if not twitter_cards.get("twitter:card"):
                result["warnings"].append("Missing twitter:card")
            if not twitter_cards.get("twitter:title"):
                result["warnings"].append("Missing twitter:title")
        
    except Exception as e:
        result["valid"] = False
        result["issues"].append(f"SEO validation error: {str(e)}")
    
    return result


# ============================================================================
# REGRESSION DETECTION
# ============================================================================

def detect_regressions(before_html: str, after_html: str, changes: List[Dict]) -> Dict:
    """Detect regressions between before and after HTML."""
    result = {
        "valid": True,
        "regressions": [],
        "warnings": []
    }
    
    if not before_html or not after_html:
        result["valid"] = False
        result["regressions"].append("Missing before or after HTML")
        return result
    
    try:
        soup_before = BeautifulSoup(before_html, "html.parser")
        soup_after = BeautifulSoup(after_html, "html.parser")
        
        # Remove scripts and styles for content comparison
        for script in soup_before(["script", "style"]):
            script.decompose()
        for script in soup_after(["script", "style"]):
            script.decompose()
        
        # Word count regression
        text_before = soup_before.get_text(" ", strip=True)
        text_after = soup_after.get_text(" ", strip=True)
        words_before = len(text_before.split())
        words_after = len(text_after.split())
        
        if words_before > 0:
            loss_ratio = (words_before - words_after) / words_before
            if loss_ratio > 0.5:
                result["valid"] = False
                result["regressions"].append({
                    "type": "word_count_loss",
                    "before": words_before,
                    "after": words_after,
                    "loss_ratio": loss_ratio,
                    "message": f"Massive content loss: {words_before} -> {words_after} words"
                })
            elif loss_ratio > 0.2:
                result["warnings"].append({
                    "type": "word_count_loss",
                    "before": words_before,
                    "after": words_after,
                    "loss_ratio": loss_ratio,
                    "message": f"Significant content loss: {words_before} -> {words_after} words"
                })
        
        # Title regression
        titles_before = soup_before.find_all("title")
        titles_after = soup_after.find_all("title")
        
        if titles_before and titles_after:
            title_before = titles_before[0].string or ""
            title_after = titles_after[0].string or ""
            if title_before and not title_after:
                result["valid"] = False
                result["regressions"].append({
                    "type": "title_removed",
                    "message": "Title tag was removed"
                })
            elif title_before and title_after and len(title_after) < len(title_before) / 2:
                result["warnings"].append({
                    "type": "title_truncated",
                    "before": len(title_before),
                    "after": len(title_after),
                    "message": f"Title significantly shortened: {len(title_before)} -> {len(title_after)} chars"
                })
        
        # H1 regression
        h1s_before = soup_before.find_all("h1")
        h1s_after = soup_after.find_all("h1")
        
        if h1s_before and not h1s_after:
            result["warnings"].append({
                "type": "h1_removed",
                "message": "H1 heading was removed"
            })
        
        # Key phrase presence
        for change in changes:
            if change.get("type") == "title" and change.get("value"):
                keyword = change.get("value")
                # Check if the new title appears in the after HTML body
                if keyword not in text_after:
                    result["warnings"].append({
                        "type": "keyword_not_found",
                        "keyword": keyword,
                        "message": f"New title keyword '{keyword[:30]}...' not found in page body"
                    })
        
        # Link count regression
        links_before = len(soup_before.find_all("a"))
        links_after = len(soup_after.find_all("a"))
        if links_before > 0 and links_after < links_before * 0.5:
            result["warnings"].append({
                "type": "link_count_loss",
                "before": links_before,
                "after": links_after,
                "message": f"Link count significantly decreased: {links_before} -> {links_after}"
            })
        
        # Image count regression
        images_before = len(soup_before.find_all("img"))
        images_after = len(soup_after.find_all("img"))
        if images_before > 0 and images_after < images_before * 0.5:
            result["warnings"].append({
                "type": "image_count_loss",
                "before": images_before,
                "after": images_after,
                "message": f"Image count significantly decreased: {images_before} -> {images_after}"
            })
        
    except Exception as e:
        result["valid"] = False
        result["regressions"].append({
            "type": "parse_error",
            "message": f"Regression detection error: {str(e)}"
        })
    
    return result


# ============================================================================
# SITEMAP VALIDATION
# ============================================================================

def validate_sitemap_xml(xml_content: str) -> Dict:
    """Validate sitemap XML content."""
    result = {
        "valid": True,
        "issues": [],
        "warnings": [],
        "urls": 0
    }
    
    if not xml_content or not xml_content.strip():
        result["valid"] = False
        result["issues"].append("Sitemap XML is empty")
        return result
    
    try:
        # Try to parse as XML
        root = ET.fromstring(xml_content)
        
        # Check if it's a sitemap or sitemap index
        is_sitemap = root.tag.endswith("urlset")
        is_sitemap_index = root.tag.endswith("sitemapindex")
        
        if not is_sitemap and not is_sitemap_index:
            result["valid"] = False
            result["issues"].append("Invalid sitemap: root element must be urlset or sitemapindex")
            return result
        
        # Count URLs
        if is_sitemap:
            urls = root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
            result["urls"] = len(urls)
            if len(urls) == 0:
                result["valid"] = False
                result["issues"].append("Sitemap contains no URLs")
            
            # Check for valid URLs
            for i, loc in enumerate(urls[:10]):  # Check first 10
                if loc.text and not loc.text.startswith(("http://", "https://")):
                    result["warnings"].append(f"Invalid URL at position {i+1}: {loc.text}")
        
        elif is_sitemap_index:
            sitemaps = root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
            result["urls"] = len(sitemaps)
            if len(sitemaps) == 0:
                result["valid"] = False
                result["issues"].append("Sitemap index contains no sitemaps")
        
        # Check for lastmod format
        for node in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}lastmod"):
            if node.text and not re.match(r"\d{4}-\d{2}-\d{2}", node.text):
                result["warnings"].append(f"Invalid lastmod format: {node.text}")
        
    except ET.ParseError as e:
        result["valid"] = False
        result["issues"].append(f"XML parse error: {str(e)}")
    except Exception as e:
        result["valid"] = False
        result["issues"].append(f"Validation error: {str(e)}")
    
    return result


# ============================================================================
# PERFORMANCE VALIDATION
# ============================================================================

def validate_performance_impact(before_html: str, after_html: str) -> Dict:
    """Validate performance impact of changes."""
    result = {
        "valid": True,
        "issues": [],
        "metrics": {}
    }
    
    if not before_html or not after_html:
        result["valid"] = False
        result["issues"].append("Missing HTML for performance comparison")
        return result
    
    try:
        # Size comparison
        before_size = len(before_html.encode("utf-8"))
        after_size = len(after_html.encode("utf-8"))
        result["metrics"]["size_before"] = before_size
        result["metrics"]["size_after"] = after_size
        
        size_increase = after_size - before_size
        size_ratio = after_size / max(1, before_size)
        
        if size_ratio > 1.5:
            result["valid"] = False
            result["issues"].append({
                "type": "size_increase",
                "message": f"Page size increased by {size_increase} bytes ({size_ratio:.1%})"
            })
        elif size_ratio > 1.2:
            result["warnings"].append({
                "type": "size_increase",
                "message": f"Page size increased by {size_increase} bytes ({size_ratio:.1%})"
            })
        
        # Image count comparison
        soup_before = BeautifulSoup(before_html, "html.parser")
        soup_after = BeautifulSoup(after_html, "html.parser")
        
        images_before = len(soup_before.find_all("img"))
        images_after = len(soup_after.find_all("img"))
        result["metrics"]["images_before"] = images_before
        result["metrics"]["images_after"] = images_after
        
        if images_after > images_before * 1.5:
            result["warnings"].append({
                "type": "image_count_increase",
                "message": f"Image count increased from {images_before} to {images_after}"
            })
        
        # External resources count
        external_links_before = 0
        external_links_after = 0
        
        for link in soup_before.find_all(["link", "script"]):
            src = link.get("href") or link.get("src") or ""
            if src and src.startswith(("http://", "https://")):
                external_links_before += 1
        
        for link in soup_after.find_all(["link", "script"]):
            src = link.get("href") or link.get("src") or ""
            if src and src.startswith(("http://", "https://")):
                external_links_after += 1
        
        result["metrics"]["external_links_before"] = external_links_before
        result["metrics"]["external_links_after"] = external_links_after
        
        if external_links_after > external_links_before * 1.5:
            result["warnings"].append({
                "type": "external_links_increase",
                "message": f"External resource count increased from {external_links_before} to {external_links_after}"
            })
        
    except Exception as e:
        result["valid"] = False
        result["issues"].append(f"Performance validation error: {str(e)}")
    
    return result


# ============================================================================
# MAIN VALIDATION FUNCTION
# ============================================================================

def validate_change_payload(before_html: str, after_html: str, changes: List[Dict]) -> Dict:
    """
    Comprehensive validation of change payload.
    
    Runs multiple validation checks including:
    - HTML well-formedness
    - JSON-LD validity
    - Title uniqueness
    - Content preservation
    - SEO metrics
    - Regression detection
    - Performance impact
    """
    result = {
        "ok": True,
        "checks": [],
        "warnings": [],
        "regressions": [],
        "metrics": {},
        "summary": {
            "total_checks": 0,
            "passed": 0,
            "failed": 0,
            "warnings_count": 0
        }
    }
    
    # 1. HTML well-formedness validation
    html_before = validate_html(before_html or "")
    html_after = validate_html(after_html or "")
    
    result["checks"].append({
        "name": "html_wellformed_before",
        "ok": html_before["valid"],
        "detail": html_before.get("error"),
        "warnings": html_before.get("warnings", [])
    })
    
    result["checks"].append({
        "name": "html_wellformed_after",
        "ok": html_after["valid"],
        "detail": html_after.get("error"),
        "warnings": html_after.get("warnings", [])
    })
    
    if not html_after["valid"]:
        result["ok"] = False
    
    # 2. JSON-LD validation
    json_ld_before = validate_json_ld(before_html or "")
    json_ld_after = validate_json_ld(after_html or "")
    
    invalid_before = [j for j in json_ld_before if not j.get("valid")]
    invalid_after = [j for j in json_ld_after if not j.get("valid")]
    
    result["checks"].append({
        "name": "json_ld_valid",
        "ok": len(invalid_after) == 0,
        "detail": {
            "before_count": len(json_ld_before),
            "after_count": len(json_ld_after),
            "invalid_after": invalid_after
        }
    })
    
    if invalid_after:
        result["ok"] = False
    
    # 3. Title uniqueness - only one <title>
    soup_after = BeautifulSoup(after_html or "", "html.parser")
    titles_after = soup_after.find_all("title")
    
    if len(titles_after) > 1:
        result["ok"] = False
        result["checks"].append({
            "name": "single_title",
            "ok": False,
            "detail": f"Found {len(titles_after)} title tags"
        })
    else:
        result["checks"].append({"name": "single_title", "ok": True})
    
    # 4. SEO metrics validation
    seo_metrics = validate_seo_metrics(after_html)
    result["metrics"]["seo"] = seo_metrics["metrics"]
    
    if not seo_metrics["valid"]:
        result["ok"] = False
        for issue in seo_metrics["issues"]:
            result["checks"].append({
                "name": "seo_metric",
                "ok": False,
                "detail": issue
            })
    
    for warning in seo_metrics.get("warnings", []):
        result["warnings"].append({
            "type": "seo",
            "message": warning
        })
    
    # 5. Regression detection
    regressions = detect_regressions(before_html, after_html, changes)
    if not regressions["valid"]:
        result["ok"] = False
        for regression in regressions["regressions"]:
            result["regressions"].append(regression)
            result["checks"].append({
                "name": "regression",
                "ok": False,
                "detail": regression.get("message")
            })
    
    for warning in regressions.get("warnings", []):
        result["warnings"].append({
            "type": "regression",
            "message": warning.get("message")
        })
    
    # 6. Performance impact
    performance = validate_performance_impact(before_html, after_html)
    result["metrics"]["performance"] = performance["metrics"]
    
    if not performance["valid"]:
        result["ok"] = False
        for issue in performance.get("issues", []):
            result["checks"].append({
                "name": "performance",
                "ok": False,
                "detail": issue.get("message") if isinstance(issue, dict) else issue
            })
    
    for warning in performance.get("warnings", []):
        result["warnings"].append({
            "type": "performance",
            "message": warning.get("message") if isinstance(warning, dict) else warning
        })
    
    # 7. Sitemap XML validation if applicable
    sitemap_changes = [c for c in changes if c.get("type") in ("sitemap_update", "sitemap")]
    for sc in sitemap_changes:
        sitemap_xml = sc.get("value", "")
        sitemap_result = validate_sitemap_xml(sitemap_xml)
        
        result["checks"].append({
            "name": "sitemap_valid",
            "ok": sitemap_result["valid"],
            "detail": {
                "urls": sitemap_result.get("urls", 0),
                "issues": sitemap_result.get("issues", []),
                "warnings": sitemap_result.get("warnings", [])
            }
        })
        
        if not sitemap_result["valid"]:
            result["ok"] = False
        
        for warning in sitemap_result.get("warnings", []):
            result["warnings"].append({
                "type": "sitemap",
                "message": warning
            })
    
    # 8. Check for JS verification page
    challenge = detect_js_verification(after_html)
    if challenge.get("is_challenge"):
        result["ok"] = False
        result["checks"].append({
            "name": "js_verification",
            "ok": False,
            "detail": f"JS verification detected: {challenge.get('reason')}"
        })
    
    # 9. Verify changes were actually applied
    for change in changes:
        change_type = change.get("type", "")
        expected_value = change.get("value", "")
        
        if change_type == "title":
            if titles_after and titles_after[0].string:
                actual_title = titles_after[0].string.strip()
                if expected_value and expected_value not in actual_title:
                    result["warnings"].append({
                        "type": "change_verification",
                        "message": f"Title change may not have been fully applied. Expected: '{expected_value[:30]}...', Found: '{actual_title[:30]}...'"
                    })
        
        elif change_type == "meta_description":
            meta_desc_after = None
            for meta in soup_after.find_all("meta"):
                if meta.get("name", "").lower() == "description":
                    meta_desc_after = meta.get("content", "")
                    break
            if expected_value and meta_desc_after and expected_value not in meta_desc_after:
                result["warnings"].append({
                    "type": "change_verification",
                    "message": f"Meta description may not have been fully applied. Expected: '{expected_value[:30]}...'"
                })
    
    # Summary
    total_checks = len(result["checks"])
    passed = sum(1 for c in result["checks"] if c.get("ok", False))
    failed = total_checks - passed
    
    result["summary"] = {
        "total_checks": total_checks,
        "passed": passed,
        "failed": failed,
        "warnings_count": len(result["warnings"])
    }
    
    return result


# ============================================================================
# JS VERIFICATION DETECTION
# ============================================================================

def detect_js_verification(html: str) -> Dict:
    """Detect if HTML is a JS verification page."""
    result = {"is_challenge": False, "reason": ""}
    
    if not html:
        return result
    
    html_lower = html.lower()
    
    indicators = [
        "cloudflare",
        "challenge",
        "verification",
        "captcha",
        "javascript required",
        "enable javascript",
        "please wait",
        "checking your browser",
        "ddos protection",
        "ray id",
        "cf-",
        "security check",
        "browser check"
    ]
    
    for indicator in indicators:
        if indicator in html_lower:
            result["is_challenge"] = True
            result["reason"] = f"Contains '{indicator}'"
            break
    
    if "window._cf_chl" in html_lower or "cf_chl" in html_lower:
        result["is_challenge"] = True
        result["reason"] = "Cloudflare challenge detected"
    
    return result

