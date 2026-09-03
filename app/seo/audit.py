"""SEO analysis modules - all return lists of issues."""
from __future__ import annotations
from typing import List, Dict, Any


SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _issue(issue_type: str, severity: str, title: str, description: str = "",
           current="", proposed="", method="", risk="medium", confidence=0.7) -> Dict:
    return {
        "issue_type": issue_type,
        "severity": severity,
        "title": title,
        "description": description,
        "current_value": current,
        "proposed_value": proposed,
        "implementation_method": method,
        "risk": risk,
        "confidence": confidence,
    }


def check_title(analyzed: Dict) -> List[Dict]:
    issues: List[Dict] = []
    title = analyzed.get("title", "") or ""
    if not title.strip():
        issues.append(_issue(
            "missing_title", "critical", "Missing title tag",
            "The page has no <title> tag. Search engines rely on it heavily.",
            current="", proposed="Add a descriptive, keyword-relevant title (40-60 chars).",
            method="html_title_update", risk="low", confidence=0.95,
        ))
    elif len(title) < 20:
        issues.append(_issue(
            "title_too_short", "medium", "Title is too short",
            f"Title is {len(title)} chars; aim for 30-65.",
            current=title, proposed="Expand the title with relevant keywords.",
            method="html_title_update", risk="low", confidence=0.85,
        ))
    elif len(title) > 70:
        issues.append(_issue(
            "title_too_long", "low", "Title exceeds 65 chars",
            f"Title is {len(title)} chars; search engines may truncate it.",
            current=title, proposed="Shorten the title to under 65 chars.",
            method="html_title_update", risk="low", confidence=0.7,
        ))
    return issues


def check_meta_description(analyzed: Dict) -> List[Dict]:
    issues: List[Dict] = []
    desc = analyzed.get("meta_description", "") or ""
    if not desc.strip():
        issues.append(_issue(
            "missing_meta_description", "high", "Missing meta description",
            "Search engines may auto-generate snippet; add a hand-crafted one.",
            current="", proposed="Add a compelling 120-160 char meta description.",
            method="html_meta_update", risk="low", confidence=0.95,
        ))
    elif len(desc) < 70:
        issues.append(_issue(
            "meta_description_too_short", "low", "Meta description too short",
            "Use 120-160 chars for better CTR.",
            current=desc, proposed="Expand the meta description.",
            method="html_meta_update", risk="low", confidence=0.8,
        ))
    elif len(desc) > 170:
        issues.append(_issue(
            "meta_description_too_long", "low", "Meta description too long",
            "Search engines may truncate it.",
            current=desc, proposed="Shorten the meta description.",
            method="html_meta_update", risk="low", confidence=0.7,
        ))
    return issues


def check_headings(analyzed: Dict) -> List[Dict]:
    issues: List[Dict] = []
    headings = analyzed.get("headings", {}) or {}
    h1s = headings.get("h1", [])
    if not h1s:
        issues.append(_issue(
            "missing_h1", "high", "Missing H1 heading",
            "Every page should have exactly one H1.",
            current="", proposed="Add a clear H1 reflecting the page topic.",
            method="html_heading_update", risk="medium", confidence=0.9,
        ))
    elif len(h1s) > 1:
        issues.append(_issue(
            "multiple_h1", "medium", f"Multiple H1 tags ({len(h1s)})",
            "Use only one H1 per page.",
            current=" | ".join(h1s),
            proposed="Consolidate to a single H1.",
            method="html_heading_update", risk="medium", confidence=0.85,
        ))

    h2s = headings.get("h2", [])
    if not h2s and len(analyzed.get("main_content", "")) > 600:
        issues.append(_issue(
            "missing_h2_sections", "medium", "Long content without H2 sections",
            "Break content into sections with H2 headings.",
            current="", proposed="Add H2 subheadings to structure the content.",
            method="html_heading_update", risk="medium", confidence=0.7,
        ))

    # Heading hierarchy check
    for level in range(2, 7):
        if headings.get(f"h{level}") and not any(headings.get(f"h{i}") for i in range(1, level)):
            issues.append(_issue(
                f"heading_skip_h{level}", "low", f"H{level} appears without preceding H{level-1}",
                f"Heading hierarchy should be sequential.",
                current="", proposed=f"Add an H{level-1} above or convert H{level} to H{level-1}.",
                method="html_heading_update", risk="medium", confidence=0.6,
            ))
            break
    return issues


def check_content(analyzed: Dict) -> List[Dict]:
    issues: List[Dict] = []
    wc = analyzed.get("word_count", 0)
    main = analyzed.get("main_content", "")
    if wc < 150:
        issues.append(_issue(
            "thin_content", "high", f"Thin content ({wc} words)",
            "Aim for at least 300 words of useful, original content.",
            current=f"{wc} words", proposed="Expand with helpful, original information.",
            method="content_rewrite", risk="high", confidence=0.8,
        ))
    elif wc < 300:
        issues.append(_issue(
            "low_content_depth", "medium", f"Content is light ({wc} words)",
            "Consider deeper coverage of the topic.",
            current=f"{wc} words", proposed="Add useful subtopics and examples.",
            method="content_rewrite", risk="high", confidence=0.6,
        ))
    return issues


def check_images(analyzed: Dict) -> List[Dict]:
    issues: List[Dict] = []
    images = analyzed.get("images", {}).get("images", [])
    missing_alt = [i for i in images if not i.get("alt")]
    if missing_alt:
        sample = ", ".join([(i.get("src") or "")[:60] for i in missing_alt[:3]])
        issues.append(_issue(
            "missing_alt_text", "medium",
            f"{len(missing_alt)} of {len(images)} images missing ALT text",
            "ALT text helps SEO and accessibility.",
            current=sample, proposed="Add descriptive ALT text for each image.",
            method="html_alt_update", risk="low", confidence=0.9,
        ))
    return issues


def check_links(analyzed: Dict) -> List[Dict]:
    issues: List[Dict] = []
    links = analyzed.get("links", {})
    if links.get("internal_count", 0) == 0:
        issues.append(_issue(
            "no_internal_links", "medium", "No internal links found",
            "Add contextual internal links to related pages.",
            current="", proposed="Add 2-5 relevant internal links.",
            method="html_link_update", risk="medium", confidence=0.7,
        ))
    return issues


def check_technical(analyzed: Dict, status_code: int = 200) -> List[Dict]:
    issues: List[Dict] = []
    if status_code == 0:
        issues.append(_issue(
            "fetch_failed", "critical", "Could not fetch the page",
            "The crawler could not retrieve the page.",
            current=str(status_code), proposed="Check site availability.",
            method="none", risk="low", confidence=0.9,
        ))
    elif status_code >= 400:
        issues.append(_issue(
            "http_error", "critical", f"HTTP {status_code}",
            "Page returned an error status.",
            current=str(status_code), proposed="Fix the underlying server issue.",
            method="none", risk="low", confidence=0.95,
        ))

    canonical = analyzed.get("canonical", "")
    robots_meta = analyzed.get("robots_meta", "").lower()
    if "noindex" in robots_meta:
        issues.append(_issue(
            "noindex_page", "high", "Page is set to noindex",
            "Search engines will not index this page.",
            current=robots_meta, proposed="Remove noindex if page should rank.",
            method="html_meta_update", risk="medium", confidence=0.95,
        ))
    if not canonical:
        issues.append(_issue(
            "missing_canonical", "medium", "Missing canonical link",
            "Add a canonical URL to avoid duplicate content issues.",
            current="", proposed="Add a self-referencing canonical tag.",
            method="html_meta_update", risk="low", confidence=0.85,
        ))
    if not analyzed.get("open_graph"):
        issues.append(_issue(
            "missing_og_tags", "low", "Missing Open Graph tags",
            "OG tags improve social sharing previews.",
            current="", proposed="Add og:title, og:description, og:image.",
            method="html_meta_update", risk="low", confidence=0.8,
        ))
    if not analyzed.get("structured_data"):
        issues.append(_issue(
            "missing_structured_data", "medium", "Missing JSON-LD structured data",
            "Add structured data to enable rich results.",
            current="", proposed="Add appropriate JSON-LD (Organization, WebPage, etc.).",
            method="html_structured_data_update", risk="medium", confidence=0.85,
        ))
    return issues


def run_full_audit(analyzed: Dict, status_code: int = 200) -> List[Dict]:
    issues: List[Dict] = []
    issues.extend(check_title(analyzed))
    issues.extend(check_meta_description(analyzed))
    issues.extend(check_headings(analyzed))
    issues.extend(check_content(analyzed))
    issues.extend(check_images(analyzed))
    issues.extend(check_links(analyzed))
    issues.extend(check_technical(analyzed, status_code))
    issues.sort(key=lambda i: -SEVERITY_RANK.get(i["severity"], 0))
    return issues