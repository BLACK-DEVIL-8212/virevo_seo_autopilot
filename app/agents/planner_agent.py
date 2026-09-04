"""Planners convert SEO issues into structured actions."""
from __future__ import annotations
import json
import re
import uuid
from typing import List, Dict, Any, Optional
from collections import Counter

# ============================================================================
# AI PROVIDER
# ============================================================================

class AIProvider:
    """AI provider for generating SEO recommendations."""
    
    def __init__(self, provider_type: str = "openai", api_key: str = None):
        self.provider_type = provider_type
        self.api_key = api_key
    
    def analyze(self, prompt: str, context: Dict = None) -> str:
        """Analyze and generate recommendations."""
        # Simple fallback implementation
        return self._generate_fallback_plan(prompt, context or {})
    
    def _generate_fallback_plan(self, prompt: str, context: Dict) -> str:
        """Generate a fallback plan when AI is not available."""
        topic = context.get("topic", "this page")
        keywords = context.get("keywords", [])
        
        actions = []
        
        # Title recommendation
        if "title" in prompt.lower() and "current title" in prompt.lower():
            if keywords:
                title = f"{keywords[0].title()} - Expert Guide"
            else:
                title = f"Complete Guide to {topic}"
            if len(title) > 65:
                title = title[:62] + "..."
            actions.append({
                "type": "title",
                "current": "",
                "value": title,
                "reason": "Optimized title with primary keyword and clear value proposition",
                "confidence": 0.9,
                "risk": "low",
                "implementation_method": "html_title_update"
            })
        
        # Meta description recommendation
        if "description" in prompt.lower() or "meta_description" in prompt.lower():
            if keywords:
                desc = f"Discover expert insights on {keywords[0]}. "
                desc += f"Learn about {', '.join(keywords[1:3]) if len(keywords) > 1 else topic}. "
                desc += "Get actionable tips and best practices."
            else:
                desc = f"Learn everything about {topic}. "
                desc += "Comprehensive guide with expert insights, tips, and best practices."
            if len(desc) > 160:
                desc = desc[:157] + "..."
            actions.append({
                "type": "meta_description",
                "current": "",
                "value": desc,
                "reason": "Optimized meta description improves CTR and search visibility",
                "confidence": 0.85,
                "risk": "low",
                "implementation_method": "html_meta_update"
            })
        
        # H1 recommendation
        actions.append({
            "type": "h1",
            "current": "",
            "value": f"Master {topic}",
            "reason": "Clear H1 heading with primary topic",
            "confidence": 0.8,
            "risk": "low",
            "implementation_method": "html_meta_update"
        })
        
        # Canonical URL
        actions.append({
            "type": "canonical",
            "current": "",
            "value": context.get("url", ""),
            "reason": "Self-referencing canonical URL prevents duplicate content issues",
            "confidence": 0.9,
            "risk": "low",
            "implementation_method": "html_meta_update"
        })
        
        # Open Graph tags
        actions.append({
            "type": "open_graph",
            "current": "",
            "value": {
                "og:title": context.get("title", topic),
                "og:description": context.get("meta_description", f"Learn about {topic}"),
                "og:type": "website",
                "og:url": context.get("url", "")
            },
            "reason": "Open Graph tags improve social sharing and engagement",
            "confidence": 0.8,
            "risk": "low",
            "implementation_method": "html_meta_update"
        })
        
        # Structured data
        actions.append({
            "type": "structured_data",
            "current": "",
            "value": {
                "@context": "https://schema.org",
                "@type": "WebPage",
                "name": context.get("title", topic),
                "description": context.get("meta_description", f"Information about {topic}"),
                "url": context.get("url", ""),
                "inLanguage": "en-US"
            },
            "reason": "Structured data enables rich search results and improves visibility",
            "confidence": 0.85,
            "risk": "medium",
            "implementation_method": "html_structured_data_update"
        })
        
        return json.dumps({"actions": actions, "summary": f"Optimization plan for {topic}"})


def get_provider(provider_type: str = "openai", api_key: str = None) -> AIProvider:
    """Get AI provider instance."""
    return AIProvider(provider_type, api_key)


# ============================================================================
# RISK ASSESSMENT
# ============================================================================

def classify_risk(issue: Dict) -> str:
    """Classify risk level of an SEO issue."""
    severity = issue.get("severity", "medium")
    issue_type = issue.get("issue_type", "")
    
    # High risk issues
    if any(term in issue_type.lower() for term in ["canonical", "redirect", "noindex", "duplicate"]):
        return "high"
    if severity == "critical":
        return "high"
    
    # Medium risk issues
    if any(term in issue_type.lower() for term in ["title", "description", "h1", "heading"]):
        return "medium"
    if severity == "high":
        return "medium"
    
    # Low risk issues
    return "low"


def deployment_method(issue: Dict) -> str:
    """Determine deployment method for an issue."""
    issue_type = issue.get("issue_type", "")
    
    method_map = {
        "title": "html_title_update",
        "meta_description": "html_meta_update",
        "h1": "html_meta_update",
        "heading": "html_meta_update",
        "canonical": "html_meta_update",
        "structured_data": "html_structured_data_update",
        "open_graph": "html_meta_update",
        "robots": "html_meta_update",
        "sitemap": "sitemap_update",
    }
    
    for key, method in method_map.items():
        if key in issue_type.lower():
            return method
    
    return "html_meta_update"


# ============================================================================
# PROMPT TEMPLATE
# ============================================================================

PROMPT_PLAN = """You are an AI SEO optimization agent. Given the page analysis and keyword strategy,
produce a JSON plan with a "summary" and an "actions" list. Each action must
have: type, current, value, reason, confidence (0-1), risk (low|medium|high),
implementation_method.

Constraints:
- Do not invent business facts (no fake phone numbers, addresses).
- Suggest only changes that can be made safely.
- Keep titles under 65 chars and meta descriptions 120-160 chars.
- Use the provided keywords naturally. Do not stuff keywords.
- Focus on topical relevance and search intent.

PAGE TOPIC: {topic}
CURRENT TITLE: {current_title}
CURRENT DESCRIPTION: {current_description}
KEYWORDS: {keywords}
KEYWORD STRATEGY: {keyword_strategy}
CONTENT GAPS: {content_gaps}
ISSUES: {issues}
"""


# ============================================================================
# HEURISTIC ACTIONS
# ============================================================================

def _heuristic_actions(page: Dict, issues: List[Dict]) -> List[Dict]:
    """Generate heuristic-based actions when AI is unavailable."""
    actions: List[Dict] = []
    topic = page.get("topic") or page.get("title") or "this page"
    cur_title = page.get("title", "")
    cur_desc = page.get("meta_description", "")
    keywords = page.get("keywords", [])
    kw_str = ", ".join(keywords[:3]) if keywords else ""
    url = page.get("url", "")
    
    # Meta description
    if not cur_desc or len(cur_desc) < 50:
        proposed = f"Discover {topic}. "
        if kw_str:
            proposed += f"{kw_str.title()} — expert insights, tips, and best practices. "
        else:
            proposed += f"Expert insights, tips, and best practices for {topic}. "
        proposed = proposed.strip()
        if len(proposed) > 160:
            proposed = proposed[:157].rstrip() + "..."
        actions.append({
            "type": "meta_description",
            "current": cur_desc or "",
            "value": proposed,
            "reason": "Meta description improves CTR and search snippet quality",
            "confidence": 0.9,
            "risk": "low",
            "implementation_method": "html_meta_update",
        })
    
    # Title
    if not cur_title or len(cur_title) < 20:
        proposed_title = topic[:60].title()
        if keywords:
            proposed_title = f"{keywords[0].title()} - {proposed_title[:50]}"
        if len(proposed_title) > 65:
            proposed_title = proposed_title[:62] + "..."
        actions.append({
            "type": "title",
            "current": cur_title or "",
            "value": proposed_title,
            "reason": "Every page needs a unique, keyword-rich title",
            "confidence": 0.95,
            "risk": "low",
            "implementation_method": "html_title_update",
        })
    
    # H1 heading
    if not page.get("h1"):
        proposed_h1 = topic[:60].title()
        if keywords:
            proposed_h1 = keywords[0].title()
        actions.append({
            "type": "h1",
            "current": "",
            "value": proposed_h1,
            "reason": "H1 heading provides clear page structure and SEO value",
            "confidence": 0.85,
            "risk": "low",
            "implementation_method": "html_meta_update",
        })
    
    # Canonical URL
    if not page.get("canonical"):
        actions.append({
            "type": "canonical",
            "current": "",
            "value": url,
            "reason": "Self-referencing canonical avoids duplicate content signals",
            "confidence": 0.85,
            "risk": "low",
            "implementation_method": "html_meta_update",
        })
    
    # Open Graph
    og = page.get("open_graph", {})
    if not og or not og.get("og:title"):
        og_title = cur_title or topic[:60]
        og_desc = cur_desc[:200] if cur_desc else f"Learn about {topic}."
        actions.append({
            "type": "open_graph",
            "current": "",
            "value": {
                "og:title": og_title,
                "og:description": og_desc,
                "og:type": "website",
                "og:url": url,
            },
            "reason": "Open Graph tags improve social sharing previews",
            "confidence": 0.8,
            "risk": "low",
            "implementation_method": "html_meta_update",
        })
    
    # Structured data
    structured_data = page.get("structured_data", [])
    if not structured_data:
        sd_value = {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": cur_title or topic,
            "description": cur_desc or f"Information about {topic}.",
            "url": url,
            "inLanguage": "en-US"
        }
        # Add breadcrumb if applicable
        if page.get("breadcrumbs"):
            sd_value["breadcrumb"] = {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": i + 1,
                        "name": item,
                        "item": item_url
                    }
                    for i, (item, item_url) in enumerate(page.get("breadcrumbs", []))
                ]
            }
        actions.append({
            "type": "structured_data",
            "current": "",
            "value": sd_value,
            "reason": "Structured data enables rich search results",
            "confidence": 0.8,
            "risk": "medium",
            "implementation_method": "html_structured_data_update",
        })
    
    # Twitter Cards
    twitter = page.get("twitter", {})
    if not twitter or not twitter.get("twitter:title"):
        actions.append({
            "type": "twitter",
            "current": "",
            "value": {
                "twitter:card": "summary_large_image",
                "twitter:title": cur_title or topic[:60],
                "twitter:description": cur_desc[:200] if cur_desc else f"Learn about {topic}.",
            },
            "reason": "Twitter Cards improve social sharing on Twitter/X",
            "confidence": 0.8,
            "risk": "low",
            "implementation_method": "html_meta_update",
        })
    
    # Robots meta if missing
    if not page.get("robots_meta"):
        actions.append({
            "type": "robots",
            "current": "",
            "value": "index, follow",
            "reason": "Robots meta tag ensures proper search engine crawling",
            "confidence": 0.9,
            "risk": "medium",
            "implementation_method": "html_meta_update",
        })
    
    return actions


def _validate_action(action: Dict) -> Dict:
    """Validate and fix action fields."""
    # Ensure required fields
    action.setdefault("type", "unknown")
    action.setdefault("current", "")
    action.setdefault("value", "")
    action.setdefault("reason", "Improvement recommended")
    action.setdefault("confidence", 0.7)
    action.setdefault("risk", "low")
    action.setdefault("implementation_method", "html_meta_update")
    
    # Validate title length
    if action["type"] == "title":
        value = action.get("value", "")
        if len(value) > 65:
            action["value"] = value[:62] + "..."
    
    # Validate meta description length
    if action["type"] == "meta_description":
        value = action.get("value", "")
        if len(value) > 160:
            action["value"] = value[:157] + "..."
        elif len(value) < 50 and value:
            action["value"] = value + " Learn more now."
    
    # Fix risk values
    if action.get("risk") not in ["low", "medium", "high"]:
        action["risk"] = "low"
    
    # Fix confidence values
    confidence = action.get("confidence", 0.7)
    if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
        action["confidence"] = 0.7
    else:
        action["confidence"] = min(1.0, max(0.0, confidence))
    
    return action


# ============================================================================
# MAIN PLANNER FUNCTIONS
# ============================================================================

def plan_for_page(page: Dict, issues: List[Dict], ai_provider=None) -> Dict:
    """Produce a structured optimization plan for a single page."""
    provider = ai_provider or get_provider()
    topic = page.get("topic") or page.get("title") or page.get("url", "Page")
    
    # Format issues summary
    issues_summary = []
    for i in issues:
        issue_type = i.get("issue_type", "unknown")
        severity = i.get("severity", "medium")
        title = i.get("title", "")
        description = i.get("description", "")
        if title:
            issues_summary.append(f"- {issue_type} ({severity}): {title}")
        elif description:
            issues_summary.append(f"- {issue_type} ({severity}): {description[:100]}")
        else:
            issues_summary.append(f"- {issue_type} ({severity})")
    
    keywords = page.get("keywords", [])
    keyword_strategy = page.get("keyword_strategy", {})
    content_gaps = page.get("content_gaps", [])
    
    # Format keyword strategy
    keyword_strategy_text = ""
    if keyword_strategy:
        primary = keyword_strategy.get("primary_keyword", "")
        secondary = keyword_strategy.get("secondary_keywords", [])
        long_tail = keyword_strategy.get("long_tail_opportunities", [])
        keyword_strategy_text = f"Primary: {primary}. Secondary: {', '.join(secondary[:3])}. Long-tail: {', '.join(long_tail[:2])}."
    else:
        keyword_strategy_text = "No specific strategy defined."
    
    # Format content gaps
    content_gaps_text = ""
    if content_gaps:
        gap_texts = []
        for gap in content_gaps[:3]:
            if isinstance(gap, dict):
                gap_texts.append(gap.get("recommendation", gap.get("description", str(gap))))
            else:
                gap_texts.append(str(gap))
        content_gaps_text = "; ".join(gap_texts)
    else:
        content_gaps_text = "No content gaps identified."
    
    # Try AI provider
    actions = []
    try:
        if hasattr(provider, 'analyze'):
            response = provider.analyze(
                PROMPT_PLAN.format(
                    topic=topic,
                    current_title=page.get("title", ""),
                    current_description=page.get("meta_description", ""),
                    keywords=", ".join(keywords[:8]),
                    keyword_strategy=keyword_strategy_text,
                    content_gaps=content_gaps_text,
                    issues="\n".join(issues_summary) or "No major issues detected",
                ),
                context={"topic": topic, "keywords": keywords, "strategy": keyword_strategy, "url": page.get("url", "")},
            )
            
            # Parse response
            if isinstance(response, str):
                try:
                    parsed = json.loads(response)
                    actions = parsed.get("actions", [])
                except json.JSONDecodeError:
                    # Try to extract JSON from response
                    json_match = re.search(r'\{.*\}', response, re.DOTALL)
                    if json_match:
                        try:
                            parsed = json.loads(json_match.group())
                            actions = parsed.get("actions", [])
                        except json.JSONDecodeError:
                            actions = []
                    else:
                        actions = []
            elif isinstance(response, dict):
                actions = response.get("actions", [])
    except Exception as e:
        # Fallback to heuristic actions
        actions = _heuristic_actions(page, issues)
    
    # If no actions generated, use heuristic fallback
    if not actions:
        actions = _heuristic_actions(page, issues)
    
    # Validate and enhance actions
    validated_actions = []
    for action in actions:
        # Ensure action has required fields
        if not isinstance(action, dict):
            continue
        
        # Ensure type exists
        if "type" not in action:
            continue
        
        # Add risk if missing
        if "risk" not in action:
            issue_type = action.get("type", "")
            action["risk"] = classify_risk({"issue_type": issue_type})
        
        # Add implementation method if missing
        if "implementation_method" not in action:
            action["implementation_method"] = deployment_method({"issue_type": action.get("type", "")})
        
        # Ensure current value exists
        if "current" not in action:
            action["current"] = ""
        
        # Ensure confidence exists
        if "confidence" not in action:
            action["confidence"] = 0.8
        
        # Validate and fix
        validated_actions.append(_validate_action(action))
    
    # Remove duplicate action types
    seen_types = set()
    unique_actions = []
    for action in validated_actions:
        action_type = action.get("type")
        if action_type not in seen_types:
            seen_types.add(action_type)
            unique_actions.append(action)
    
    return {
        "plan_id": str(uuid.uuid4())[:12],
        "page_url": page.get("url", ""),
        "summary": f"Optimization plan for {topic}",
        "actions": unique_actions,
        "risk_breakdown": dict(Counter(a.get("risk", "low") for a in unique_actions)),
        "keyword_strategy": keyword_strategy,
        "content_gaps": content_gaps,
        "issues_addressed": len(issues),
    }


def aggregate_plan(page_plans: List[Dict]) -> Dict:
    """Aggregate multiple page plans into a single plan."""
    if not page_plans:
        return {
            "plan_id": str(uuid.uuid4())[:12],
            "page_count": 0,
            "total_actions": 0,
            "risk_breakdown": {},
            "pages": [],
            "summary": "No pages to optimize"
        }
    
    total_actions = sum(len(p.get("actions", [])) for p in page_plans)
    risk_counter = Counter()
    type_counter = Counter()
    
    for p in page_plans:
        for a in p.get("actions", []):
            risk_counter[a.get("risk", "medium")] += 1
            type_counter[a.get("type", "unknown")] += 1
    
    # Calculate priority pages
    priority_pages = sorted(
        page_plans,
        key=lambda p: len(p.get("actions", [])),
        reverse=True
    )[:10]
    
    return {
        "plan_id": str(uuid.uuid4())[:12],
        "page_count": len(page_plans),
        "total_actions": total_actions,
        "risk_breakdown": dict(risk_counter),
        "type_breakdown": dict(type_counter),
        "priority_pages": priority_pages,
        "pages": page_plans,
        "summary": f"Optimization plan for {len(page_plans)} pages with {total_actions} total actions",
    }


def generate_priority_plan(website_id: int, pages_data: List[Dict], issues: List[Dict]) -> Dict:
    """Generate a priority-based optimization plan for a website."""
    # Score pages by issue count and severity
    scored_pages = []
    for page in pages_data:
        page_url = page.get("url", "")
        page_issues = [i for i in issues if i.get("page_url") == page_url]
        
        # Calculate score based on issues
        score = 0
        for issue in page_issues:
            severity = issue.get("severity", "medium")
            if severity == "critical":
                score += 3
            elif severity == "high":
                score += 2
            elif severity == "medium":
                score += 1
        
        scored_pages.append({
            "page": page,
            "score": score,
            "issue_count": len(page_issues),
            "issues": page_issues
        })
    
    # Sort by score descending
    scored_pages.sort(key=lambda x: x["score"], reverse=True)
    
    # Generate plans for top pages
    plans = []
    for item in scored_pages[:20]:  # Limit to 20 pages
        if item["score"] > 0:
            plan = plan_for_page(item["page"], item["issues"])
            plans.append(plan)
    
    return aggregate_plan(plans)


def filter_actions_by_risk(plan: Dict, max_risk: str = "medium") -> Dict:
    """Filter actions by maximum risk level."""
    risk_levels = {"low": 0, "medium": 1, "high": 2}
    max_level = risk_levels.get(max_risk, 1)
    
    filtered_actions = []
    for action in plan.get("actions", []):
        action_risk = action.get("risk", "low")
        if risk_levels.get(action_risk, 0) <= max_level:
            filtered_actions.append(action)
    
    return {
        **plan,
        "actions": filtered_actions,
        "filtered_by": max_risk,
        "filtered_count": len(filtered_actions),
        "original_count": len(plan.get("actions", [])),
    }


def estimate_impact(plan: Dict) -> Dict:
    """Estimate the potential SEO impact of a plan."""
    actions = plan.get("actions", [])
    high_impact = 0
    medium_impact = 0
    low_impact = 0
    
    for action in actions:
        confidence = action.get("confidence", 0.7)
        risk = action.get("risk", "medium")
        
        if confidence >= 0.8 and risk == "low":
            high_impact += 1
        elif confidence >= 0.6:
            medium_impact += 1
        else:
            low_impact += 1
    
    total_score = 0
    for action in actions:
        confidence = action.get("confidence", 0.7)
        risk_penalty = {"low": 1.0, "medium": 0.8, "high": 0.6}
        total_score += confidence * risk_penalty.get(action.get("risk", "low"), 0.8)
    
    max_score = len(actions) * 1.0
    impact_percentage = (total_score / max_score * 100) if max_score > 0 else 0
    
    return {
        "high_impact_actions": high_impact,
        "medium_impact_actions": medium_impact,
        "low_impact_actions": low_impact,
        "total_actions": len(actions),
        "impact_percentage": round(impact_percentage, 1),
        "estimated_score_improvement": round(impact_percentage / 100 * 15, 1),  # Up to 15 points
    }
