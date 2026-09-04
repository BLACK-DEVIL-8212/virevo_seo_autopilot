"""Keyword Intelligence Engine - proactive keyword discovery, intent analysis, trend detection, content gap analysis."""
from __future__ import annotations
import re
import json
import logging
from typing import List, Dict, Optional, Set, Tuple
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse

# Setup logging
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Configuration for keyword intelligence."""
    MAX_KEYWORDS_PER_ANALYSIS = 100
    MIN_KEYWORD_RELEVANCE = 0.3
    TREND_LOOKBACK_DAYS = 30
    KEYWORD_PROVIDER = "local"
    TREND_PROVIDER = "local"
    SEARCH_PERFORMANCE_PROVIDER = "local"
    COMPETITOR_PROVIDER = "local"


# ============================================================================
# EVENT MANAGER
# ============================================================================

class EventManager:
    """Event manager for emitting events."""
    
    def __init__(self):
        self._handlers = {}
    
    def emit(self, job_id: str = "", event_type: str = "", message: str = "",
             agent_name: str = "", severity: str = "info", website_id: int = None,
             metadata: Dict = None):
        """Emit an event."""
        event = {
            "event_type": event_type,
            "message": message,
            "agent_name": agent_name or "Keyword Intelligence Agent",
            "severity": severity,
            "website_id": website_id,
            "metadata": metadata or {},
            "timestamp": datetime.utcnow().isoformat()
        }
        logger.info(f"{severity.upper()}: {message}")
        if metadata:
            logger.debug(f"  Metadata: {metadata}")


_event_manager = None

def get_event_manager() -> EventManager:
    global _event_manager
    if _event_manager is None:
        _event_manager = EventManager()
    return _event_manager


# ============================================================================
# PROVIDER IMPLEMENTATIONS
# ============================================================================

class KeywordProvider:
    """Keyword research provider."""
    
    def research(self, seed_terms: List[str]) -> List[Dict]:
        """Research keywords based on seed terms."""
        results = []
        
        # Common keyword patterns
        patterns = [
            ("tips", 100),
            ("guide", 150),
            ("best", 200),
            ("how to", 180),
            ("vs", 90),
            ("review", 120),
            ("ultimate", 80),
            ("complete", 110),
            ("expert", 95),
            ("master", 75),
            ("strategies", 130),
            ("techniques", 115),
            ("tools", 105),
            ("resources", 90),
            ("checklist", 70),
        ]
        
        for seed in seed_terms[:10]:
            # Base keyword
            results.append({
                "keyword": seed,
                "search_volume": 100,
                "difficulty": 0.5,
                "intent": "informational",
                "provider": "local"
            })
            
            # Variations
            for pattern, volume_multiplier in patterns[:5]:
                keyword = f"{pattern} for {seed}"
                results.append({
                    "keyword": keyword,
                    "search_volume": int(50 + volume_multiplier * 0.5),
                    "difficulty": round(0.3 + (hash(keyword) % 50) / 100, 2),
                    "intent": "informational" if pattern in ["tips", "guide", "how to"] else "commercial",
                    "provider": "local"
                })
        
        return results


class TrendProvider:
    """Trend analysis provider."""
    
    def trends(self, keywords: List[str]) -> List[Dict]:
        """Get trend data for keywords."""
        results = []
        
        for keyword in keywords:
            # Simulate trend data
            trend_score = 0.3 + (hash(keyword) % 70) / 100
            is_trending = trend_score > 0.7
            
            results.append({
                "keyword": keyword,
                "trend_score": round(trend_score, 2),
                "is_trending": is_trending,
                "direction": "rising" if is_trending else "stable" if trend_score > 0.4 else "declining",
                "volume_change": round((hash(keyword) % 40) - 20, 1),
                "provider": "local"
            })
        
        return results


class SearchPerformanceProvider:
    """Search performance provider."""
    
    def get_metrics(self, url: str, start_date: datetime = None, end_date: datetime = None) -> Dict:
        """Get search performance metrics."""
        return {
            "impressions": 100 + (hash(url) % 500),
            "clicks": 10 + (hash(url) % 100),
            "ctr": round(0.05 + (hash(url) % 30) / 100, 3),
            "average_position": round(5 + (hash(url) % 20), 1),
            "provider": "local"
        }


class CompetitorProvider:
    """Competitor analysis provider."""
    
    def get_competitors(self, url: str) -> List[str]:
        """Get competitor URLs."""
        domain = urlparse(url).netloc
        return [
            f"https://www.{domain}2.com",
            f"https://www.{domain}.co",
            f"https://www.{domain}pro.com"
        ]
    
    def get_keywords(self, url: str) -> List[str]:
        """Get competitor keywords."""
        domain = urlparse(url).netloc.split('.')[0]
        return [
            f"{domain} seo",
            f"{domain} guide",
            f"best {domain}",
            f"{domain} tips"
        ]


# ============================================================================
# PROVIDER FACTORY FUNCTIONS
# ============================================================================

def get_keyword_provider() -> KeywordProvider:
    """Get keyword provider instance."""
    return KeywordProvider()


def get_trend_provider() -> TrendProvider:
    """Get trend provider instance."""
    return TrendProvider()


def get_search_performance_provider() -> SearchPerformanceProvider:
    """Get search performance provider instance."""
    return SearchPerformanceProvider()


def get_competitor_provider() -> CompetitorProvider:
    """Get competitor provider instance."""
    return CompetitorProvider()


def extract_seed_terms(text: str, max_terms: int = 10) -> List[str]:
    """Extract seed terms from text."""
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
        "first", "last", "good", "great", "best", "better", "many", "much",
        "some", "any", "all", "each", "every", "both", "few", "more", "most",
        "other", "some", "such", "no", "nor", "not", "only", "own", "same",
        "so", "than", "too", "very", "can", "will", "just", "don", "should",
        "now", "also", "etc", "via", "get", "use", "using", "need", "want"
    }
    
    # Count word frequency
    word_freq = Counter(words)
    
    # Filter stop words and short words
    filtered = {w: c for w, c in word_freq.items() 
                if w not in stop_words and len(w) > 3 and c > 1}
    
    # Sort by frequency and return top terms
    sorted_terms = sorted(filtered.items(), key=lambda x: -x[1])
    return [term for term, _ in sorted_terms[:max_terms]]


# ============================================================================
# KEYWORD INTELLIGENCE ENGINE
# ============================================================================

class KeywordIntelligenceEngine:
    """Central engine for keyword research, analysis, and mapping."""

    def __init__(self, website_id: int, website_url: str, business_description: str = "", job_id: str = ""):
        self.website_id = website_id
        self.website_url = website_url
        self.business_description = business_description
        self.job_id = job_id
        self.event_manager = get_event_manager()
        self.keyword_provider = get_keyword_provider()
        self.trend_provider = get_trend_provider()
        self.search_perf_provider = get_search_performance_provider()
        self.competitor_provider = get_competitor_provider()

    def _emit(self, event_type: str, message: str = "", severity: str = "info", metadata: dict = None):
        """Emit an event."""
        self.event_manager.emit(
            job_id=self.job_id,
            event_type=event_type,
            message=message,
            agent_name="Keyword Intelligence Agent",
            severity=severity,
            website_id=self.website_id,
            metadata=metadata or {},
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
            "first", "last", "good", "great", "best", "better", "many", "much",
            "some", "any", "all", "each", "every", "both", "few", "more", "most",
            "other", "some", "such", "no", "nor", "not", "only", "own", "same",
            "so", "than", "too", "very", "can", "will", "just", "don", "should",
            "now", "also", "etc", "via", "get", "use", "using", "need", "want"
        }

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
            # Fallback seed terms
            seed_terms = ["seo", "website", "business", "optimization", "growth"]

        # Get keyword ideas from provider
        kw_ideas = self.keyword_provider.research(seed_terms)

        # Enhance with AI analysis if available
        enhanced_keywords = []
        for kw in kw_ideas[:max_keywords * 2]:
            enhanced = self._enhance_keyword(kw, topic_analysis)
            enhanced_keywords.append(enhanced)

        # Remove duplicates and low-relevance keywords
        seen = set()
        unique_keywords = []
        for kw in enhanced_keywords:
            kw_lower = kw["keyword"].lower()
            if kw_lower not in seen and kw.get("relevance", 0) >= Config.MIN_KEYWORD_RELEVANCE:
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

        # Check secondary terms
        secondary_terms = [t.lower() for t in topic_analysis.get("secondary_terms", [])]
        for term in secondary_terms:
            if term in kw_lower:
                relevance += 0.1

        relevance = min(1.0, relevance + 0.3)  # Base relevance
        keyword["relevance"] = round(relevance, 2)

        # Calculate opportunity score
        opportunity = self._calculate_opportunity(keyword, relevance)
        keyword["opportunity_score"] = round(opportunity, 2)

        # Add trend info
        trend_info = self._analyze_trend(keyword.get("keyword", ""))
        keyword["trend_score"] = trend_info.get("trend_score", 0.0)
        keyword["is_trending"] = trend_info.get("is_trending", False)
        keyword["trend_direction"] = trend_info.get("direction", "stable")

        # Add search volume if not present
        if "search_volume" not in keyword:
            keyword["search_volume"] = 50 + (hash(kw_lower) % 200)

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
        except Exception as e:
            logger.warning(f"Trend analysis failed for '{keyword}': {e}")

        # Fallback: simple heuristic based on keyword length and content
        words = len(keyword.split())
        trend_score = min(1.0, 0.2 + (words * 0.05) + (hash(keyword) % 30) / 100)
        
        return {
            "trend_score": round(trend_score, 2),
            "is_trending": trend_score > 0.7,
            "direction": "rising" if trend_score > 0.7 else "stable" if trend_score > 0.4 else "declining",
            "provider": "local",
        }

    def analyze_search_intent(self, keyword: str) -> Dict:
        """Analyze search intent for a keyword."""
        kw_lower = keyword.lower()

        intent_signals = {
            "transactional": ["buy", "price", "cost", "purchase", "order", "book", "subscribe", "demo", "free trial", "pricing", "near me", "shop", "store", "discount", "coupon", "deal", "offer", "sale", "quote", "estimate", "bill", "payment", "checkout"],
            "commercial": ["best", "top", "review", "vs", "comparison", "alternative", "solution", "service", "company", "agency", "pro", "expert", "professional", "quality", "rating", "test", "opinion", "recommendation", "list"],
            "informational": ["how to", "what is", "why", "guide", "tips", "learn", "tutorial", "explained", "definition", "meaning", "example", "benefits", "importance", "basics", "steps", "process", "difference", "types", "features", "advantages"],
            "local": ["near me", "local", "in", "city", "area", "nearby", "region", "state", "country", "zip code", "postcode", "store", "location", "map", "directions", "open now", "hours"],
            "navigational": ["login", "sign in", "dashboard", "account", "app", "portal", "home", "about", "contact", "support", "help", "faq", "terms", "privacy"],
        }

        scores = {}
        for intent, signals in intent_signals.items():
            score = sum(1 for signal in signals if signal in kw_lower)
            scores[intent] = score

        if not scores or max(scores.values()) == 0:
            # Default to informational if no signals found
            return {"intent": "informational", "confidence": 0.4}

        best_intent = max(scores, key=scores.get)
        confidence = min(1.0, 0.4 + (scores[best_intent] * 0.15))

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
        page_content = {}
        for page in pages_data:
            url = page.get("url", "")
            topic = page.get("title", "") or page.get("topic", "")
            content = page.get("main_content", "")
            if topic:
                page_topics[url] = topic.lower()
                page_content[url] = content.lower()

        # Check each keyword against existing content
        for kw in keywords:
            kw_lower = kw.get("keyword", "").lower()
            kw_parts = kw_lower.split()
            covered = False
            covering_page = None
            match_score = 0.0

            for url, topic in page_topics.items():
                # Check title and headings
                if kw_lower in topic:
                    covered = True
                    covering_page = url
                    match_score = 0.8
                    break
                # Check content
                content = page_content.get(url, "")
                if kw_lower in content:
                    covered = True
                    covering_page = url
                    match_score = 0.6
                    break
                # Check partial matches
                if any(part in topic or part in content for part in kw_parts if len(part) > 3):
                    covered = True
                    covering_page = url
                    match_score = 0.3
                    break

            # If not covered and has good opportunity score, create gap
            if not covered and kw.get("opportunity_score", 0) > 0.5:
                gap = {
                    "keyword": kw.get("keyword", ""),
                    "intent": kw.get("intent", "informational"),
                    "opportunity_score": kw.get("opportunity_score", 0),
                    "relevance": kw.get("relevance", 0),
                    "trend_direction": kw.get("trend_direction", "stable"),
                    "search_volume": kw.get("search_volume", 0),
                    "covering_page": covering_page,
                    "match_score": match_score,
                    "recommendation": self._get_gap_recommendation(kw),
                    "priority": "high" if kw.get("opportunity_score", 0) > 0.8 else "medium" if kw.get("opportunity_score", 0) > 0.6 else "low",
                }
                gaps.append(gap)

        # Sort by opportunity score
        gaps.sort(key=lambda x: -x.get("opportunity_score", 0))

        self._emit("content_gap_analysis_complete", f"Found {len(gaps)} content gaps",
                   metadata={"gaps_count": len(gaps), "high_priority": sum(1 for g in gaps if g["priority"] == "high")})

        return gaps

    def _get_gap_recommendation(self, keyword: Dict) -> str:
        """Get recommendation for a content gap."""
        intent = keyword.get("intent", "informational")
        kw = keyword.get("keyword", "")
        volume = keyword.get("search_volume", 0)

        if intent == "informational":
            return f"Create a new page or section targeting '{kw}' with comprehensive informational content. Search volume: {volume}."
        elif intent == "commercial":
            return f"Add a dedicated page or enhance existing content for '{kw}' with commercial focus and comparison."
        elif intent == "transactional":
            return f"Create a landing page or add conversion-focused content for '{kw}' with clear call-to-action."
        elif intent == "local":
            return f"Add location-specific content or pages for '{kw}' targeting local audience."
        else:
            return f"Consider adding content targeting '{kw}' to improve coverage and address search intent."

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

                # Title match (highest weight)
                if kw_lower in page_title:
                    score += 0.5
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
                        "current_coverage": "high" if score > 0.4 else "medium" if score > 0.2 else "low",
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
                "avg_opportunity_score": round(sum(k.get("opportunity_score", 0) for k in page_keywords) / max(1, len(page_keywords)), 2),
            })

        # Sort mappings by opportunity potential
        mappings.sort(key=lambda x: -x.get("avg_opportunity_score", 0))

        self._emit("keyword_mapping_complete", f"Mapped keywords to {len(mappings)} pages",
                   metadata={"pages_mapped": len(mappings), "total_mappings": sum(len(m.get("keywords", [])) for m in mappings)})

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
                    "opportunity_score": kw.get("opportunity_score", 0),
                })

        cannibalization = []
        for kw_text, pages in keyword_pages.items():
            if len(pages) > 1:
                # Sort by match score
                pages.sort(key=lambda x: -x.get("match_score", 0))
                cannibalization.append({
                    "keyword": kw_text,
                    "pages": pages,
                    "recommendation": f"Keyword '{kw_text}' appears on {len(pages)} pages. Consider consolidating or differentiating content.",
                    "severity": "high" if len(pages) > 2 else "medium",
                    "best_page": pages[0].get("page") if pages else None,
                })

        # Sort by severity
        cannibalization.sort(key=lambda x: 0 if x["severity"] == "high" else 1)

        self._emit("cannibalization_check_complete", f"Found {len(cannibalization)} cannibalization issues",
                   metadata={"cannibalization_count": len(cannibalization), "high_severity": sum(1 for c in cannibalization if c["severity"] == "high")})

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
            secondary = [k["keyword"] for k in existing_kws[:5] if k["keyword"] != primary and k.get("opportunity_score", 0) > 0.4]
            long_tail = [k["keyword"] for k in existing_kws if k.get("opportunity_score", 0) > 0.7][:3]

            # Check for content gaps on this page
            page_gaps = [g for g in content_gaps if g.get("covering_page") == page_url]

            strategy = {
                "page_url": page_url,
                "page_title": mapping.get("page_title", ""),
                "primary_keyword": primary,
                "secondary_keywords": secondary[:5],
                "long_tail_opportunities": long_tail,
                "content_gaps": page_gaps[:3],
                "cannibalization_risk": mapping.get("cannibalization_risk", False),
                "recommendations": self._generate_page_recommendations(mapping, page_gaps),
                "priority": "high" if mapping.get("total_opportunities", 0) > 5 or mapping.get("avg_opportunity_score", 0) > 0.6 else "medium",
                "total_opportunities": mapping.get("total_opportunities", 0),
            }
            strategies.append(strategy)

        # Add new page opportunities from content gaps
        gap_pages = [g for g in content_gaps if not g.get("covering_page") and g.get("opportunity_score", 0) > 0.6]
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
                "total_opportunities": 1,
            })

        # Sort strategies by priority
        strategies.sort(key=lambda x: 0 if x["priority"] == "high" else 1)

        self._emit("strategy_generation_complete", f"Generated {len(strategies)} page strategies",
                   metadata={"strategies_count": len(strategies), "new_pages": sum(1 for s in strategies if s.get("is_new_page"))})

        return strategies

    def _generate_page_recommendations(self, mapping: Dict, gaps: List[Dict]) -> List[str]:
        """Generate specific recommendations for a page."""
        recs = []
        primary = mapping.get("primary_keyword")
        
        if not primary:
            recs.append("No primary keyword identified. Consider optimizing page title and content for target keywords.")
        else:
            recs.append(f"Optimize page around primary keyword: '{primary}'")

        if mapping.get("cannibalization_risk"):
            recs.append("Keyword cannibalization risk detected. Consider consolidating or differentiating content across pages.")

        if mapping.get("total_opportunities", 0) > 5:
            recs.append(f"Page has {mapping.get('total_opportunities')} keyword opportunities. Prioritize high-opportunity keywords.")

        for gap in gaps[:2]:
            recs.append(gap.get("recommendation", "Add relevant content to address search intent."))

        # Add general recommendations
        if mapping.get("avg_opportunity_score", 0) > 0.6:
            recs.append("Page has good keyword opportunity score. Consider optimizing title and meta description.")

        return recs[:5]

    def get_competitor_keywords(self, url: str) -> List[str]:
        """Get keywords from competitors."""
        try:
            competitors = self.competitor_provider.get_competitors(url)
            all_keywords = []
            for comp in competitors[:3]:
                comp_keywords = self.competitor_provider.get_keywords(comp)
                all_keywords.extend(comp_keywords)
            return list(set(all_keywords))
        except Exception as e:
            logger.warning(f"Competitor analysis failed: {e}")
            return []

    def run_full_analysis(self, pages_data: List[Dict]) -> Dict:
        """Run complete keyword intelligence analysis."""
        self._emit("keyword_analysis_start", "Starting full keyword intelligence analysis")

        # 1. Analyze website topic
        topic = self.analyze_website_topic(pages_data)

        # 2. Discover keywords
        keywords = self.discover_keywords(topic, max_keywords=Config.MAX_KEYWORDS_PER_ANALYSIS)

        # 3. Analyze search intent for each keyword
        for kw in keywords:
            intent_info = self.analyze_search_intent(kw.get("keyword", ""))
            kw["intent"] = intent_info.get("intent", kw.get("intent", "informational"))
            kw["intent_confidence"] = intent_info.get("confidence", 0.5)

        # 4. Get competitor keywords
        competitor_kws = self.get_competitor_keywords(self.website_url)
        for comp_kw in competitor_kws[:10]:
            # Add competitor keywords if not already present
            if not any(k.get("keyword", "").lower() == comp_kw.lower() for k in keywords):
                keywords.append({
                    "keyword": comp_kw,
                    "search_volume": 50 + (hash(comp_kw) % 150),
                    "difficulty": round(0.4 + (hash(comp_kw) % 40) / 100, 2),
                    "intent": "informational",
                    "relevance": 0.5,
                    "opportunity_score": 0.5,
                    "is_trending": False,
                    "trend_direction": "stable",
                    "provider": "competitor",
                })

        # 5. Map keywords to pages
        mappings = self.map_keywords_to_pages(pages_data, keywords)

        # 6. Detect content gaps
        gaps = self.detect_content_gaps(pages_data, keywords)

        # 7. Detect cannibalization
        cannibalization = self.detect_cannibalization(mappings)

        # 8. Generate strategy
        strategies = self.generate_keyword_strategy(mappings, gaps, cannibalization)

        # 9. Calculate summary statistics
        total_keywords = len(keywords)
        high_opportunity = sum(1 for k in keywords if k.get("opportunity_score", 0) > 0.7)
        trending_keywords = sum(1 for k in keywords if k.get("is_trending", False))
        
        result = {
            "topic_analysis": topic,
            "keywords": keywords,
            "page_mappings": mappings,
            "content_gaps": gaps,
            "cannibalization": cannibalization,
            "strategies": strategies,
            "summary": {
                "total_keywords": total_keywords,
                "high_opportunity": high_opportunity,
                "trending_keywords": trending_keywords,
                "content_gaps_found": len(gaps),
                "cannibalization_issues": len(cannibalization),
                "pages_with_strategy": len([s for s in strategies if not s.get("is_new_page")]),
                "new_page_opportunities": len([s for s in strategies if s.get("is_new_page")]),
                "avg_keyword_relevance": round(sum(k.get("relevance", 0) for k in keywords) / max(1, len(keywords)), 2),
                "total_keyword_volume": sum(k.get("search_volume", 0) for k in keywords),
            },
            "generated_at": datetime.utcnow().isoformat(),
        }

        self._emit("keyword_analysis_complete", "Keyword intelligence analysis complete",
                   metadata=result["summary"])

        return result
