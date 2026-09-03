"""Keyword Intelligence Engine - proactive keyword discovery, intent analysis, trend detection, content gap analysis."""
from __future__ import annotations
import re
import json
import logging
from typing import List, Dict, Optional, Set, Tuple
from collections import Counter
from datetime import datetime

from ..config import Config
from ..events import get_event_manager
from ..providers import (
    get_keyword_provider, get_trend_provider,
    get_search_performance_provider, get_competitor_provider,
    extract_seed_terms,
)

logger = logging.getLogger(__name__)


class KeywordIntelligenceEngine:
    """Central engine for keyword research, analysis, and mapping."""

    def __init__(self, website_id: int, website_url: str, business_description: str = ""):
        self.website_id = website_id
        self.website_url = website_url
        self.business_description = business_description
        self.event_manager = get_event_manager()
        self.keyword_provider = get_keyword_provider()
        self.trend_provider = get_trend_provider()
        self.search_perf_provider = get_search_performance_provider()
        self.competitor_provider = get_competitor_provider()

    def _emit(self, event_type: str, message: str = "", severity: str = "info", metadata: dict = None):
        self.event_manager.emit(
            job_id="", event_type=event_type, message=message,
            agent_name="Keyword Intelligence Agent", severity=severity,
            website_id=self.website_id, metadata=metadata or {},
        )

    def analyze_website_topic(self, pages_data: List[Dict]) -> Dict:
        """Analyze website pages to determine primary topic and business niche."""
        self._emit("keyword_topic_analysis_start", "Analyzing website topics and business niche")

        all_text = []
        titles = []
        descriptions = []
        headings = []

        for page in pages_data:
            titles.append(page.get("title", ""))
            descriptions.append(page.get("meta_description", ""))
            headings.extend(page.get("headings", {}).get("h1", []))
            headings.extend(page.get("headings", {}).get("h2", []))
            all_text.append(page.get("main_content", ""))

        combined = " ".join(all_text)
        combined_lower = combined.lower()

        # Extract high-frequency meaningful terms
        words = re.findall(r"[a-z]{3,}", combined_lower)
        word_freq = Counter(words)

        # Remove common stop words
        stop_words = {"the", "and", "for", "with", "this", "that", "from", "have", "been", "were", "was", "are", "not", "but", "they", "their", "what", "when", "where", "which", "while", "about", "your", "more", "other", "some", "into", "than", "them", "then", "these", "through", "over", "such", "after", "also", "just", "most", "very", "every", "should", "could", "would", "there", "here", "where", "being", "because", "between", "both", "during", "before", "after", "under", "again", "further", "once", "without", "within", "along", "across", "behind", "beyond", "toward", "towards", "upon", "whether", "either", "neither", "though", "although", "even", "only", "many", "much", "well", "back", "still", "way", "take", "come", "make", "like", "long", "look", "right", "used", "know", "get", "got", "let", "say", "said", "see", "two", "one", "new", "first", "last", "good", "great", "best", "better", "many", "much", "some", "any", "all", "each", "every", "both", "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very", "can", "will", "just", "don", "should", "now"}

        filtered = {w: c for w, c in word_freq.items() if w not in stop_words and c > 1}
        top_terms = [w for w, _ in sorted(filtered.items(), key=lambda x: -x[1])[:30]]

        # Extract business indicators
        business_indicators = []
        business_patterns = [
            r"(?:we|our|us)\s+(?:provide|offer|specialize|deliver)\s+([^.]+)",
            r"(?:software|service|solutions|platform|product|app|tool|system)",
            r"(?:for|to)\s+(?:business|company|enterprise|organization|retail|shop|restaurant|store)",
        ]
        for pattern in business_patterns:
            matches = re.findall(pattern, combined_lower)
            business_indicators.extend(matches)

        topic = {
            "primary_terms": top_terms[:10],
            "secondary_terms": top_terms[10:20],
            "business_indicators": business_indicators[:10],
            "page_titles": [t for t in titles if t][:10],
            "avg_title_length": sum(len(t) for t in titles if t) / max(1, len([t for t in titles if t])),
            "has_meta_descriptions": sum(1 for d in descriptions if d),
            "total_pages": len(pages_data),
        }

        self._emit("keyword_topic_analysis_complete", f"Identified {len(top_terms)} topic terms",
                   metadata={"primary_terms": top_terms[:5], "total_pages": len(pages_data)})

        return topic

    def discover_keywords(self, topic_analysis: Dict, max_keywords: int = 50) -> List[Dict]:
        """Discover relevant keywords based on website topic analysis."""
        self._emit("keyword_discovery_start", "Discovering relevant keywords")

        seed_terms = topic_analysis.get("primary_terms", [])[:15]
        if not seed_terms:
            seed_terms = ["seo", "website", "business"]

        # Get keyword ideas from provider
        kw_ideas = self.keyword_provider.research(seed_terms)

        # Enhance with AI analysis if available
        enhanced_keywords = []
        for kw in kw_ideas[:max_keywords]:
            enhanced = self._enhance_keyword(kw, topic_analysis)
            enhanced_keywords.append(enhanced)

        # Remove duplicates and low-relevance keywords
        seen = set()
        unique_keywords = []
        for kw in enhanced_keywords:
            kw_lower = kw["keyword"].lower()
            if kw_lower not in seen:
                seen.add(kw_lower)
                unique_keywords.append(kw)

        self._emit("keyword_discovery_complete", f"Discovered {len(unique_keywords)} unique keywords",
                   metadata={"count": len(unique_keywords), "sample": [k["keyword"] for k in unique_keywords[:5]]})

        return unique_keywords[:max_keywords]

    def _enhance_keyword(self, keyword: Dict, topic_analysis: Dict) -> Dict:
        """Enhance keyword with relevance scoring and metadata."""
        kw_lower = keyword.get("keyword", "").lower()

        # Calculate relevance score based on topic overlap
        primary_terms = [t.lower() for t in topic_analysis.get("primary_terms", [])]
        relevance = 0.0
        for term in primary_terms:
            if term in kw_lower:
                relevance += 0.3
            elif kw_lower in term:
                relevance += 0.2

        relevance = min(1.0, relevance + 0.5)
        keyword["relevance"] = round(relevance, 2)

        # Calculate opportunity score
        opportunity = self._calculate_opportunity(keyword, relevance)
        keyword["opportunity_score"] = round(opportunity, 2)

        # Add trend info
        trend_info = self._analyze_trend(keyword.get("keyword", ""))
        keyword["trend_score"] = trend_info.get("trend_score", 0.0)
        keyword["is_trending"] = trend_info.get("is_trending", False)
        keyword["trend_direction"] = trend_info.get("direction", "stable")

        return keyword

    def _calculate_opportunity(self, keyword: Dict, relevance: float) -> float:
        """Calculate opportunity score for a keyword."""
        difficulty = keyword.get("difficulty", 0.5)
        intent = keyword.get("intent", "informational")

        # Higher score for: high relevance, lower difficulty, commercial/transactional intent
        intent_bonus = {
            "commercial": 0.2,
            "transactional": 0.25,
            "informational": 0.1,
            "local": 0.15,
            "navigational": 0.05,
        }.get(intent, 0.0)

        difficulty_penalty = difficulty * 0.3
        score = (relevance * 0.5) + intent_bonus + (1.0 - difficulty_penalty)
        return min(1.0, max(0.0, score))

    def _analyze_trend(self, keyword: str) -> Dict:
        """Analyze trend status for a keyword."""
        try:
            trends = self.trend_provider.trends([keyword])
            if trends:
                return trends[0]
        except Exception:
            pass

        # Fallback: simple heuristic
        words = len(keyword.split())
        return {
            "trend_score": min(1.0, 0.2 + (words * 0.1)),
            "is_trending": words <= 3,
            "direction": "stable",
            "provider": "local",
        }

    def analyze_search_intent(self, keyword: str) -> Dict:
        """Analyze search intent for a keyword."""
        kw_lower = keyword.lower()

        intent_signals = {
            "transactional": ["buy", "price", "cost", "purchase", "order", "book", "subscribe", "demo", "free trial", "pricing", "near me"],
            "commercial": ["best", "top", "review", "vs", "comparison", "alternative", "solution", "service", "company", "agency"],
            "informational": ["how to", "what is", "why", "guide", "tips", "learn", "tutorial", "explained", "definition"],
            "local": ["near me", "local", "in", "city", "area", "nearby"],
            "navigational": ["login", "sign in", "dashboard", "account", "app"],
        }

        scores = {}
        for intent, signals in intent_signals.items():
            score = sum(1 for signal in signals if signal in kw_lower)
            scores[intent] = score

        if not scores or max(scores.values()) == 0:
            return {"intent": "informational", "confidence": 0.5}

        best_intent = max(scores, key=scores.get)
        confidence = min(1.0, 0.5 + (scores[best_intent] * 0.2))

        return {
            "intent": best_intent,
            "confidence": round(confidence, 2),
            "signals_found": [s for s in intent_signals[best_intent] if s in kw_lower],
        }

    def detect_content_gaps(self, pages_data: List[Dict], keywords: List[Dict]) -> List[Dict]:
        """Detect content gaps between keyword opportunities and existing content."""
        self._emit("content_gap_analysis_start", "Analyzing content gaps")

        gaps = []

        # Group pages by topic
        page_topics = {}
        for page in pages_data:
            url = page.get("url", "")
            topic = page.get("title", "") or page.get("topic", "")
            if topic:
                page_topics[url] = topic.lower()

        # Check each keyword against existing content
        for kw in keywords:
            kw_lower = kw.get("keyword", "").lower()
            covered = False
            covering_page = None

            for url, topic in page_topics.items():
                if kw_lower in topic or any(part in topic for part in kw_lower.split()):
                    covered = True
                    covering_page = url
                    break

            if not covered and kw.get("opportunity_score", 0) > 0.6:
                gap = {
                    "keyword": kw.get("keyword", ""),
                    "intent": kw.get("intent", "informational"),
                    "opportunity_score": kw.get("opportunity_score", 0),
                    "relevance": kw.get("relevance", 0),
                    "trend_direction": kw.get("trend_direction", "stable"),
                    "covering_page": covering_page,
                    "recommendation": self._get_gap_recommendation(kw),
                    "priority": "high" if kw.get("opportunity_score", 0) > 0.8 else "medium",
                }
                gaps.append(gap)

        self._emit("content_gap_analysis_complete", f"Found {len(gaps)} content gaps",
                   metadata={"gaps_count": len(gaps), "high_priority": sum(1 for g in gaps if g["priority"] == "high")})

        return gaps

    def _get_gap_recommendation(self, keyword: Dict) -> str:
        """Get recommendation for a content gap."""
        intent = keyword.get("intent", "informational")
        kw = keyword.get("keyword", "")

        if intent == "informational":
            return f"Create a new page or section targeting '{kw}' with comprehensive informational content."
        elif intent == "commercial":
            return f"Add a dedicated page or enhance existing content for '{kw}' with commercial focus."
        elif intent == "transactional":
            return f"Create a landing page or add conversion-focused content for '{kw}'."
        elif intent == "local":
            return f"Add location-specific content or pages for '{kw}'."
        else:
            return f"Consider adding content targeting '{kw}' to improve coverage."

    def map_keywords_to_pages(self, pages_data: List[Dict], keywords: List[Dict]) -> List[Dict]:
        """Map keywords to appropriate pages based on content relevance."""
        self._emit("keyword_mapping_start", "Mapping keywords to pages")

        mappings = []

        for page in pages_data:
            page_url = page.get("url", "")
            page_title = page.get("title", "").lower()
            page_content = page.get("main_content", "").lower()
            page_headings = " ".join(page.get("headings", {}).get("h1", []) + page.get("headings", {}).get("h2", [])).lower()

            page_keywords = []

            for kw in keywords:
                kw_lower = kw.get("keyword", "").lower()
                score = 0.0

                # Title match
                if kw_lower in page_title:
                    score += 0.4
                # Heading match
                elif kw_lower in page_headings:
                    score += 0.3
                # Content match
                elif kw_lower in page_content:
                    score += 0.2
                # Partial match
                else:
                    parts = kw_lower.split()
                    if any(part in page_title or part in page_content for part in parts if len(part) > 4):
                        score += 0.1

                if score > 0.1:
                    page_keywords.append({
                        "keyword": kw.get("keyword", ""),
                        "relevance": kw.get("relevance", 0),
                        "opportunity_score": kw.get("opportunity_score", 0),
                        "match_score": round(score, 2),
                        "intent": kw.get("intent", "informational"),
                        "is_trending": kw.get("is_trending", False),
                        "current_coverage": "high" if score > 0.3 else "medium" if score > 0.15 else "low",
                    })

            # Sort by opportunity score
            page_keywords.sort(key=lambda x: -x.get("opportunity_score", 0))

            # Detect keyword cannibalization
            primary_keywords = [k for k in page_keywords if k.get("match_score", 0) > 0.3]

            mappings.append({
                "page_url": page_url,
                "page_title": page.get("title", ""),
                "keywords": page_keywords[:10],
                "primary_keyword": primary_keywords[0]["keyword"] if primary_keywords else None,
                "cannibalization_risk": len(primary_keywords) > 3,
                "total_opportunities": len(page_keywords),
            })

        self._emit("keyword_mapping_complete", f"Mapped keywords to {len(mappings)} pages",
                   metadata={"pages_mapped": len(mappings)})

        return mappings

    def detect_cannibalization(self, mappings: List[Dict]) -> List[Dict]:
        """Detect keyword cannibalization across pages."""
        self._emit("cannibalization_check_start", "Checking for keyword cannibalization")

        keyword_pages = {}
        for mapping in mappings:
            for kw in mapping.get("keywords", []):
                kw_text = kw.get("keyword", "").lower()
                if kw_text not in keyword_pages:
                    keyword_pages[kw_text] = []
                keyword_pages[kw_text].append({
                    "page": mapping.get("page_url", ""),
                    "title": mapping.get("page_title", ""),
                    "match_score": kw.get("match_score", 0),
                })

        cannibalization = []
        for kw_text, pages in keyword_pages.items():
            if len(pages) > 1:
                cannibalization.append({
                    "keyword": kw_text,
                    "pages": pages,
                    "recommendation": f"Keyword '{kw_text}' appears on {len(pages)} pages. Consider consolidating or differentiating content.",
                    "severity": "high" if len(pages) > 2 else "medium",
                })

        self._emit("cannibalization_check_complete", f"Found {len(cannibalization)} cannibalization issues",
                   metadata={"cannibalization_count": len(cannibalization)})

        return cannibalization

    def generate_keyword_strategy(self, page_mappings: List[Dict], content_gaps: List[Dict], cannibalization: List[Dict]) -> List[Dict]:
        """Generate comprehensive keyword strategy for all pages."""
        self._emit("strategy_generation_start", "Generating keyword strategy")

        strategies = []

        # Process existing pages
        for mapping in page_mappings:
            page_url = mapping.get("page_url", "")
            existing_kws = mapping.get("keywords", [])

            # Determine primary and secondary keywords
            primary = mapping.get("primary_keyword")
            secondary = [k["keyword"] for k in existing_kws[:5] if k["keyword"] != primary]
            long_tail = [k["keyword"] for k in existing_kws if k.get("opportunity_score", 0) > 0.7][:3]

            # Check for content gaps on this page
            page_gaps = [g for g in content_gaps if g.get("covering_page") == page_url or not g.get("covering_page")]

            strategy = {
                "page_url": page_url,
                "page_title": mapping.get("page_title", ""),
                "primary_keyword": primary,
                "secondary_keywords": secondary,
                "long_tail_opportunities": long_tail,
                "content_gaps": page_gaps[:3],
                "cannibalization_risk": mapping.get("cannibalization_risk", False),
                "recommendations": self._generate_page_recommendations(mapping, page_gaps),
                "priority": "high" if mapping.get("total_opportunities", 0) > 5 else "medium",
            }
            strategies.append(strategy)

        # Add new page opportunities from content gaps
        gap_pages = [g for g in content_gaps if not g.get("covering_page")]
        for gap in gap_pages[:10]:
            strategies.append({
                "page_url": None,
                "page_title": f"New page opportunity: {gap.get('keyword', '')}",
                "primary_keyword": gap.get("keyword", ""),
                "secondary_keywords": [],
                "long_tail_opportunities": [],
                "content_gaps": [gap],
                "cannibalization_risk": False,
                "recommendations": [gap.get("recommendation", "")],
                "priority": gap.get("priority", "medium"),
                "is_new_page": True,
            })

        self._emit("strategy_generation_complete", f"Generated {len(strategies)} page strategies",
                   metadata={"strategies_count": len(strategies), "new_pages": sum(1 for s in strategies if s.get("is_new_page"))})

        return strategies

    def _generate_page_recommendations(self, mapping: Dict, gaps: List[Dict]) -> List[str]:
        """Generate specific recommendations for a page."""
        recs = []
        primary = mapping.get("primary_keyword")
        if not primary:
            recs.append("No primary keyword identified. Consider optimizing page title and content for target keywords.")

        if mapping.get("cannibalization_risk"):
            recs.append("Keyword cannibalization risk detected. Consider consolidating or differentiating content.")

        for gap in gaps[:2]:
            recs.append(gap.get("recommendation", "Add relevant content to address search intent."))

        return recs[:5]

    def run_full_analysis(self, pages_data: List[Dict]) -> Dict:
        """Run complete keyword intelligence analysis."""
        self._emit("keyword_analysis_start", "Starting full keyword intelligence analysis")

        # 1. Analyze website topic
        topic = self.analyze_website_topic(pages_data)

        # 2. Discover keywords
        keywords = self.discover_keywords(topic)

        # 3. Analyze search intent for each keyword
        for kw in keywords:
            intent_info = self.analyze_search_intent(kw.get("keyword", ""))
            kw["intent"] = intent_info.get("intent", kw.get("intent", "informational"))
            kw["intent_confidence"] = intent_info.get("confidence", 0.5)

        # 4. Map keywords to pages
        mappings = self.map_keywords_to_pages(pages_data, keywords)

        # 5. Detect content gaps
        gaps = self.detect_content_gaps(pages_data, keywords)

        # 6. Detect cannibalization
        cannibalization = self.detect_cannibalization(mappings)

        # 7. Generate strategy
        strategies = self.generate_keyword_strategy(mappings, gaps, cannibalization)

        result = {
            "topic_analysis": topic,
            "keywords": keywords,
            "page_mappings": mappings,
            "content_gaps": gaps,
            "cannibalization": cannibalization,
            "strategies": strategies,
            "summary": {
                "total_keywords": len(keywords),
                "high_opportunity": sum(1 for k in keywords if k.get("opportunity_score", 0) > 0.7),
                "trending_keywords": sum(1 for k in keywords if k.get("is_trending", False)),
                "content_gaps_found": len(gaps),
                "cannibalization_issues": len(cannibalization),
                "pages_with_strategy": len(strategies),
            },
        }

        self._emit("keyword_analysis_complete", "Keyword intelligence analysis complete",
                   metadata=result["summary"])

        return result
