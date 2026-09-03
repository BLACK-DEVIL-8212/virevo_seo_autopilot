"""Risk classification for SEO changes."""
from __future__ import annotations
from typing import Dict

RISK_LEVELS = ["low", "medium", "high", "critical"]

# Issue types that are considered safe (low risk) to auto-implement
LOW_RISK_TYPES = {
    "missing_meta_description",
    "meta_description_too_short",
    "meta_description_too_long",
    "title_too_short",
    "title_too_long",
    "missing_alt_text",
    "missing_og_tags",
    "missing_canonical",
    "missing_structured_data",
}

MEDIUM_RISK_TYPES = {
    "missing_h1",
    "multiple_h1",
    "heading_skip_h2",
    "heading_skip_h3",
    "heading_skip_h4",
    "heading_skip_h5",
    "heading_skip_h6",
    "missing_h2_sections",
    "no_internal_links",
    "noindex_page",
}

HIGH_RISK_TYPES = {
    "thin_content",
    "low_content_depth",
    "missing_title",
}


def classify_risk(issue: Dict) -> str:
    issue_type = issue.get("issue_type", "")
    if issue_type in HIGH_RISK_TYPES:
        return "high"
    if issue_type in MEDIUM_RISK_TYPES:
        return "medium"
    if issue_type in LOW_RISK_TYPES:
        return "low"
    if issue.get("severity") == "critical":
        return "high"
    if issue.get("severity") == "high":
        return "medium"
    return "medium"


def can_auto_implement(issue: Dict, mode: str, risk: str) -> bool:
    if mode == "analysis_only":
        return False
    if mode == "safe_autopilot":
        return risk == "low"
    if mode == "full_autonomous":
        return risk in ("low", "medium")
    return False


def deployment_method(issue: Dict) -> str:
    """Map issue type to implementation method."""
    mapping = {
        "missing_title": "html_title_update",
        "title_too_short": "html_title_update",
        "title_too_long": "html_title_update",
        "missing_meta_description": "html_meta_update",
        "meta_description_too_short": "html_meta_update",
        "meta_description_too_long": "html_meta_update",
        "missing_h1": "html_heading_update",
        "multiple_h1": "html_heading_update",
        "missing_h2_sections": "html_heading_update",
        "heading_skip_h2": "html_heading_update",
        "heading_skip_h3": "html_heading_update",
        "missing_alt_text": "html_alt_update",
        "missing_og_tags": "html_meta_update",
        "missing_canonical": "html_meta_update",
        "missing_structured_data": "html_structured_data_update",
        "no_internal_links": "html_link_update",
        "thin_content": "content_rewrite",
        "low_content_depth": "content_rewrite",
    }
    return mapping.get(issue.get("issue_type", ""), "html_meta_update")