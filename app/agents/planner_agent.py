"""Planners convert SEO issues into structured actions."""
from __future__ import annotations
import json
import uuid
from typing import List, Dict
from collections import Counter

from ..ai import get_provider
from .risk import classify_risk, deployment_method


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


def _heuristic_actions(page, issues) -> List[Dict]:
    actions: List[Dict] = []
    topic = page.get("topic") or "this page"
    cur_title = page.get("title", "")
    cur_desc = page.get("meta_description", "")
    keywords = page.get("keywords", [])
    kw_str = ", ".join(keywords[:3]) if keywords else ""

    if not cur_desc:
        proposed = (f"Discover {topic}. {kw_str.title()} — original, helpful, "
                    f"and tailored to your needs.").strip()
        if len(proposed) > 160:
            proposed = proposed[:157].rstrip() + "…"
        actions.append({
            "type": "meta_description",
            "current": "",
            "value": proposed,
            "reason": "A meta description improves CTR and snippet quality.",
            "confidence": 0.9, "risk": "low",
            "implementation_method": "html_meta_update",
        })
    if not cur_title:
        proposed_title = topic[:60].title()
        actions.append({
            "type": "title",
            "current": "",
            "value": proposed_title,
            "reason": "Every page needs a unique title.",
            "confidence": 0.95, "risk": "low",
            "implementation_method": "html_title_update",
        })
    if not page.get("canonical"):
        actions.append({
            "type": "canonical",
            "current": "",
            "value": page.get("url", ""),
            "reason": "Self-referencing canonical avoids duplicate content signals.",
            "confidence": 0.85, "risk": "low",
            "implementation_method": "html_meta_update",
        })
    if not page.get("open_graph"):
        actions.append({
            "type": "open_graph",
            "current": "",
            "value": {
                "og:title": cur_title or topic[:60],
                "og:description": cur_desc[:200] if cur_desc else f"Learn about {topic}.",
                "og:type": "website",
                "og:url": page.get("url", ""),
            },
            "reason": "Open Graph tags improve social sharing previews.",
            "confidence": 0.8, "risk": "low",
            "implementation_method": "html_meta_update",
        })
    if not page.get("structured_data"):
        actions.append({
            "type": "structured_data",
            "current": "",
            "value": {
                "@context": "https://schema.org",
                "@type": "WebPage",
                "name": cur_title or topic,
                "description": cur_desc or f"Information about {topic}.",
                "url": page.get("url", ""),
            },
            "reason": "Structured data enables rich search results.",
            "confidence": 0.8, "risk": "medium",
            "implementation_method": "html_structured_data_update",
        })
    return actions


def plan_for_page(page: Dict, issues: List[Dict], ai_provider=None) -> Dict:
    """Produce a structured optimization plan for a single page."""
    provider = ai_provider or get_provider()
    topic = page.get("topic") or page.get("title") or page.get("url", "Page")
    issues_summary = [
        f"- {i['issue_type']} ({i['severity']}): {i.get('title','')}" for i in issues
    ]

    keywords = page.get("keywords", [])
    keyword_strategy = page.get("keyword_strategy", {})
    content_gaps = page.get("content_gaps", [])

    keyword_strategy_text = ""
    if keyword_strategy:
        primary = keyword_strategy.get("primary_keyword", "")
        secondary = keyword_strategy.get("secondary_keywords", [])
        long_tail = keyword_strategy.get("long_tail_opportunities", [])
        keyword_strategy_text = f"Primary: {primary}. Secondary: {', '.join(secondary[:3])}. Long-tail: {', '.join(long_tail[:2])}."

    content_gaps_text = ""
    if content_gaps:
        content_gaps_text = "; ".join([g.get("recommendation", "") for g in content_gaps[:2]])

    try:
        text = provider.analyze(
            PROMPT_PLAN.format(
                topic=topic,
                current_title=page.get("title", ""),
                current_description=page.get("meta_description", ""),
                keywords=", ".join(keywords[:8]),
                keyword_strategy=keyword_strategy_text or "No specific strategy defined.",
                content_gaps=content_gaps_text or "No content gaps identified.",
                issues="\n".join(issues_summary) or "No major issues detected",
            ),
            context={"topic": topic, "keywords": keywords, "strategy": keyword_strategy},
        )
        parsed = json.loads(text)
        actions = parsed.get("actions", [])
        if not actions:
            actions = _heuristic_actions(page, issues)
    except Exception:
        actions = _heuristic_actions(page, issues)

    # Ensure every action has a risk + method
    for a in actions:
        a.setdefault("risk", "low")
        a.setdefault("confidence", 0.7)
        a.setdefault("implementation_method", deployment_method({"issue_type": a.get("type", "")}))
        a.setdefault("reason", a.get("reason", "AI suggested improvement"))
        a.setdefault("current", a.get("current", ""))

    return {
        "plan_id": str(uuid.uuid4())[:12],
        "page_url": page.get("url", ""),
        "summary": f"Optimization plan for {topic}",
        "actions": actions,
        "risk_breakdown": dict(Counter(a["risk"] for a in actions)),
        "keyword_strategy": keyword_strategy,
        "content_gaps": content_gaps,
    }


def aggregate_plan(page_plans: List[Dict]) -> Dict:
    total_actions = sum(len(p.get("actions", [])) for p in page_plans)
    risk_counter = Counter()
    for p in page_plans:
        for a in p.get("actions", []):
            risk_counter[a.get("risk", "medium")] += 1
    return {
        "plan_id": str(uuid.uuid4())[:12],
        "page_count": len(page_plans),
        "total_actions": total_actions,
        "risk_breakdown": dict(risk_counter),
        "pages": page_plans,
    }
    