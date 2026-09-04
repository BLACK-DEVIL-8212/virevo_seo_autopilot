"""Provider abstractions for keyword research, trends, search performance, analytics.

Concrete providers can be plugged in (e.g. SEMrush, Google Keyword Planner,
Google Search Console, etc.). The core application must work with a built-in
local provider so it never depends on paid APIs.
"""
from __future__ import annotations
import re
import json
import logging
from typing import List, Dict, Optional, Any, Union, Callable
from collections import Counter
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

# Setup logging
logger = logging.getLogger(__name__)


# ============================================================================
# BASE PROVIDER CLASSES
# ============================================================================

class KeywordProvider(ABC):
    """Abstract base class for keyword research providers."""
    
    name = "base"
    requires_auth = False
    
    @abstractmethod
    def research(self, seed_terms: List[str], language: str = "en",
                 geo: str = "") -> List[Dict]:
        """Research keywords based on seed terms.
        
        Args:
            seed_terms: List of seed keyword terms
            language: Language code (e.g., 'en', 'es')
            geo: Geographic location (e.g., 'us', 'uk')
            
        Returns:
            List of keyword dictionaries with fields:
                - keyword: str
                - intent: str (informational, commercial, transactional, local, navigational)
                - search_volume: int
                - difficulty: float (0-1)
                - is_long_tail: bool
                - provider: str
        """
        pass
    
    def get_name(self) -> str:
        """Get provider name."""
        return self.name
    
    def is_configured(self) -> bool:
        """Check if provider is configured."""
        return True


class TrendProvider(ABC):
    """Abstract base class for trend analysis providers."""
    
    name = "base"
    requires_auth = False
    
    @abstractmethod
    def trends(self, terms: List[str], geo: str = "", days: int = 30) -> List[Dict]:
        """Get trend data for terms.
        
        Args:
            terms: List of terms to analyze
            geo: Geographic location
            days: Number of days to look back
            
        Returns:
            List of trend dictionaries with fields:
                - term: str
                - trend_score: float (0-1)
                - is_trending: bool
                - direction: str (rising, stable, declining)
                - volume_change: float
                - provider: str
        """
        pass
    
    def get_name(self) -> str:
        """Get provider name."""
        return self.name
    
    def is_configured(self) -> bool:
        """Check if provider is configured."""
        return True


class SearchPerformanceProvider(ABC):
    """Abstract base class for search performance providers."""
    
    name = "base"
    requires_auth = False
    
    @abstractmethod
    def fetch(self, site_url: str, days: int = 28, start_date: Optional[datetime] = None,
              end_date: Optional[datetime] = None) -> List[Dict]:
        """Fetch search performance data.
        
        Args:
            site_url: Website URL
            days: Number of days to fetch
            start_date: Start date (optional)
            end_date: End date (optional)
            
        Returns:
            List of performance dictionaries with fields:
                - url: str
                - impressions: int
                - clicks: int
                - ctr: float
                - average_position: float
                - date: datetime
                - provider: str
        """
        pass
    
    def get_name(self) -> str:
        """Get provider name."""
        return self.name
    
    def is_configured(self) -> bool:
        """Check if provider is configured."""
        return True


class CompetitorProvider(ABC):
    """Abstract base class for competitor analysis providers."""
    
    name = "base"
    requires_auth = False
    
    @abstractmethod
    def search(self, query: str, geo: str = "", limit: int = 10) -> List[str]:
        """Search for competitors.
        
        Args:
            query: Search query
            geo: Geographic location
            limit: Maximum number of results
            
        Returns:
            List of competitor URLs
        """
        pass
    
    @abstractmethod
    def get_keywords(self, url: str) -> List[str]:
        """Get keywords for a competitor.
        
        Args:
            url: Competitor URL
            
        Returns:
            List of keywords
        """
        pass
    
    def get_name(self) -> str:
        """Get provider name."""
        return self.name
    
    def is_configured(self) -> bool:
        """Check if provider is configured."""
        return True


# ============================================================================
# LOCAL PROVIDER IMPLEMENTATIONS
# ============================================================================

class LocalKeywordProvider(KeywordProvider):
    """Generates heuristic keyword ideas from seed terms.

    Uses common modifiers (best, how to, near me, etc.) to produce realistic
    keyword candidates when no paid provider is configured.
    """
    name = "local"
    
    MODIFIERS_PREFIX = [
        "best", "top", "affordable", "professional", "expert", "how to",
        "what is", "why", "vs", "near me", "online", "ultimate", "complete",
        "beginner", "advanced", "simple", "easy", "quick", "step by step"
    ]
    
    MODIFIERS_SUFFIX = [
        "services", "company", "agency", "solutions", "near me", "cost",
        "price", "pricing", "reviews", "examples", "guide", "tips",
        "strategies", "techniques", "tools", "resources", "checklist",
        "template", "best practices", "insights", "ideas", "hacks"
    ]
    
    INTENT_PREFIX = {
        "best": "commercial", "top": "commercial", "affordable": "commercial",
        "professional": "commercial", "expert": "commercial",
        "how to": "informational", "what is": "informational",
        "why": "informational", "guide": "informational",
        "beginner": "informational", "advanced": "informational",
        "simple": "informational", "easy": "informational", "quick": "informational",
        "near me": "local", "online": "transactional",
        "ultimate": "informational", "complete": "informational",
        "step by step": "informational"
    }
    
    INTENT_SUFFIX = {
        "services": "commercial", "company": "commercial", "agency": "commercial",
        "solutions": "commercial", "near me": "local", "cost": "commercial",
        "price": "commercial", "pricing": "commercial",
        "reviews": "commercial", "examples": "informational", "guide": "informational",
        "tips": "informational", "strategies": "informational",
        "techniques": "informational", "tools": "commercial",
        "resources": "informational", "checklist": "informational",
        "template": "informational", "insights": "informational"
    }

    def research(self, seed_terms: List[str], language: str = "en",
                 geo: str = "") -> List[Dict]:
        """Generate keyword ideas from seed terms."""
        results: List[Dict] = []
        seen = set()
        
        for seed in seed_terms:
            seed = seed.strip().lower()
            if not seed or len(seed) < 2:
                continue
            
            # Add seed itself
            if seed not in seen:
                seen.add(seed)
                results.append({
                    "keyword": seed,
                    "intent": "informational",
                    "search_volume": 50 + (hash(seed) % 150),
                    "is_long_tail": len(seed.split()) > 3,
                    "difficulty": round(0.3 + (hash(seed) % 40) / 100, 2),
                    "provider": self.name,
                })
            
            # Prefix modifiers
            for pre in self.MODIFIERS_PREFIX[:10]:
                kw = f"{pre} {seed}"
                if kw not in seen:
                    seen.add(kw)
                    is_long_tail = len(kw.split()) > 3
                    volume = 100 + (hash(kw) % 200)
                    difficulty = round(0.2 + (hash(kw) % 50) / 100, 2)
                    results.append({
                        "keyword": kw,
                        "intent": self.INTENT_PREFIX.get(pre, "informational"),
                        "search_volume": volume,
                        "is_long_tail": is_long_tail,
                        "difficulty": difficulty,
                        "provider": self.name,
                    })
            
            # Suffix modifiers
            for suf in self.MODIFIERS_SUFFIX[:10]:
                kw = f"{seed} {suf}"
                if kw not in seen:
                    seen.add(kw)
                    is_long_tail = len(kw.split()) > 3
                    volume = 80 + (hash(kw) % 180)
                    difficulty = round(0.3 + (hash(kw) % 45) / 100, 2)
                    results.append({
                        "keyword": kw,
                        "intent": self.INTENT_SUFFIX.get(suf, "commercial"),
                        "search_volume": volume,
                        "is_long_tail": is_long_tail,
                        "difficulty": difficulty,
                        "provider": self.name,
                    })
        
        # Sort by search volume (descending)
        results.sort(key=lambda x: -x.get("search_volume", 0))
        
        return results


class LocalTrendProvider(TrendProvider):
    """Local trend provider with heuristic-based trend detection."""
    name = "local"
    
    def trends(self, terms: List[str], geo: str = "", days: int = 30) -> List[Dict]:
        """Generate trend data for terms."""
        out = []
        
        for term in terms:
            if not term:
                continue
            
            # Calculate heuristic trend score
            words = len(term.split())
            term_lower = term.lower()
            
            # Check for trending indicators
            trending_indicators = ["best", "top", "new", "2024", "2025", "trending", "popular", "ultimate", "complete"]
            trend_score = 0.2
            
            # Length-based score
            if words <= 3:
                trend_score += 0.3
            elif words <= 5:
                trend_score += 0.2
            else:
                trend_score += 0.1
            
            # Indicator-based score
            for indicator in trending_indicators:
                if indicator in term_lower:
                    trend_score += 0.15
                    break
            
            # Hash-based variation for diversity
            trend_score += (hash(term) % 20) / 100
            
            # Cap at 1.0
            trend_score = min(1.0, trend_score)
            
            is_trending = trend_score > 0.6
            
            # Determine direction
            if is_trending:
                direction = "rising"
            elif trend_score > 0.4:
                direction = "stable"
            else:
                direction = "declining"
            
            out.append({
                "term": term,
                "trend_score": round(trend_score, 2),
                "is_trending": is_trending,
                "direction": direction,
                "volume_change": round((hash(term) % 40) - 20, 1),
                "provider": self.name,
            })
        
        return out


class LocalSearchPerformanceProvider(SearchPerformanceProvider):
    """Local search performance provider with mock data."""
    name = "local"
    
    def fetch(self, site_url: str, days: int = 28, start_date: Optional[datetime] = None,
              end_date: Optional[datetime] = None) -> List[Dict]:
        """Generate mock search performance data."""
        results = []
        
        if not site_url:
            return results
        
        # Generate mock data for the last 'days' days
        end = end_date or datetime.utcnow()
        start = start_date or (end - timedelta(days=days))
        
        current = start
        while current <= end:
            # Generate mock metrics with some variation
            base_impressions = 50 + (hash(f"{site_url}_{current}") % 200)
            base_clicks = 5 + (hash(f"{site_url}_{current}_clicks") % 50)
            
            results.append({
                "url": site_url,
                "date": current,
                "impressions": base_impressions,
                "clicks": base_clicks,
                "ctr": round(base_clicks / max(1, base_impressions), 3),
                "average_position": round(5 + (hash(f"{site_url}_{current}_pos") % 15), 1),
                "provider": self.name,
            })
            current += timedelta(days=1)
        
        return results


class LocalCompetitorProvider(CompetitorProvider):
    """Local competitor provider with basic functionality."""
    name = "local"
    
    def search(self, query: str, geo: str = "", limit: int = 10) -> List[str]:
        """Search for competitors."""
        if not query:
            return []
        
        # Generate mock competitor URLs based on query
        results = []
        query_clean = query.replace(" ", "")
        
        for i in range(min(limit, 8)):
            results.append(f"https://www.{query_clean}{i+1}.com")
            results.append(f"https://www.{query_clean}pro{i+1}.com")
            results.append(f"https://www.{query_clean}co{i+1}.com")
        
        return list(set(results))[:limit]
    
    def get_keywords(self, url: str) -> List[str]:
        """Get keywords for a competitor."""
        if not url:
            return []
        
        # Generate mock keywords based on URL
        domain = url.split("//")[-1].split("/")[0].split(".")[0]
        
        keywords = [
            domain,
            f"{domain} seo",
            f"{domain} marketing",
            f"best {domain}",
            f"{domain} tips",
            f"{domain} guide",
            f"{domain} strategies",
            f"{domain} services",
            f"{domain} near me",
            f"affordable {domain}",
        ]
        
        return keywords


# ============================================================================
# PROVIDER FACTORY
# ============================================================================

class ProviderFactory:
    """Factory for creating provider instances."""
    
    _providers = {
        "keyword": {
            "local": LocalKeywordProvider,
        },
        "trend": {
            "local": LocalTrendProvider,
        },
        "search_performance": {
            "local": LocalSearchPerformanceProvider,
        },
        "competitor": {
            "local": LocalCompetitorProvider,
        },
    }
    
    @classmethod
    def register_provider(cls, provider_type: str, name: str, provider_class):
        """Register a new provider."""
        if provider_type not in cls._providers:
            cls._providers[provider_type] = {}
        cls._providers[provider_type][name] = provider_class
    
    @classmethod
    def create_provider(cls, provider_type: str, name: str = "local", **kwargs):
        """Create a provider instance."""
        providers = cls._providers.get(provider_type, {})
        provider_class = providers.get(name)
        
        if not provider_class:
            logger.warning(f"Provider {name} not found for type {provider_type}, using local")
            provider_class = providers.get("local")
        
        if provider_class:
            return provider_class(**kwargs)
        
        raise ValueError(f"No provider found for type {provider_type} and name {name}")
    
    @classmethod
    def get_available_providers(cls, provider_type: str) -> List[str]:
        """Get list of available provider names for a type."""
        return list(cls._providers.get(provider_type, {}).keys())


# ============================================================================
# PROVIDER MANAGER
# ============================================================================

class ProviderManager:
    """Manager for provider instances with caching."""
    
    _instance = None
    _providers = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Initialize the provider manager."""
        self._providers = {
            "keyword": {},
            "trend": {},
            "search_performance": {},
            "competitor": {},
        }
    
    def get_keyword_provider(self, name: str = "local") -> KeywordProvider:
        """Get keyword provider."""
        return self._get_provider("keyword", name)
    
    def get_trend_provider(self, name: str = "local") -> TrendProvider:
        """Get trend provider."""
        return self._get_provider("trend", name)
    
    def get_search_performance_provider(self, name: str = "local") -> SearchPerformanceProvider:
        """Get search performance provider."""
        return self._get_provider("search_performance", name)
    
    def get_competitor_provider(self, name: str = "local") -> CompetitorProvider:
        """Get competitor provider."""
        return self._get_provider("competitor", name)
    
    def _get_provider(self, provider_type: str, name: str):
        """Get a provider instance."""
        if name in self._providers.get(provider_type, {}):
            return self._providers[provider_type][name]
        
        provider = ProviderFactory.create_provider(provider_type, name)
        self._providers[provider_type][name] = provider
        return provider
    
    def set_provider(self, provider_type: str, name: str, provider):
        """Set a provider instance."""
        if provider_type not in self._providers:
            self._providers[provider_type] = {}
        self._providers[provider_type][name] = provider


# ============================================================================
# PROVIDER HELPER FUNCTIONS
# ============================================================================

def get_keyword_provider(name: Optional[str] = None) -> KeywordProvider:
    """Get keyword provider instance."""
    if name is None:
        return LocalKeywordProvider()
    
    try:
        return ProviderFactory.create_provider("keyword", name)
    except ValueError:
        logger.warning(f"Keyword provider '{name}' not found, using local")
        return LocalKeywordProvider()


def get_trend_provider(name: Optional[str] = None) -> TrendProvider:
    """Get trend provider instance."""
    if name is None:
        return LocalTrendProvider()
    
    try:
        return ProviderFactory.create_provider("trend", name)
    except ValueError:
        logger.warning(f"Trend provider '{name}' not found, using local")
        return LocalTrendProvider()


def get_search_performance_provider(name: Optional[str] = None) -> SearchPerformanceProvider:
    """Get search performance provider instance."""
    if name is None:
        return LocalSearchPerformanceProvider()
    
    try:
        return ProviderFactory.create_provider("search_performance", name)
    except ValueError:
        logger.warning(f"Search performance provider '{name}' not found, using local")
        return LocalSearchPerformanceProvider()


def get_competitor_provider(name: Optional[str] = None) -> CompetitorProvider:
    """Get competitor provider instance."""
    if name is None:
        return LocalCompetitorProvider()
    
    try:
        return ProviderFactory.create_provider("competitor", name)
    except ValueError:
        logger.warning(f"Competitor provider '{name}' not found, using local")
        return LocalCompetitorProvider()


def extract_seed_terms(text: str, max_terms: int = 20) -> List[str]:
    """Extract likely seed terms from page text."""
    if not text:
        return []
    
    # Clean text
    text = (text or "").lower()
    text = re.sub(r"<[^>]+>", " ", text)  # Remove HTML tags
    text = re.sub(r"[^a-z0-9\s]", " ", text)  # Remove special characters
    
    # Split into words
    words = [w for w in text.split() if len(w) > 3]
    
    # Count frequency
    counter = Counter(words)
    
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
        "first", "last", "good", "great", "best", "better"
    }
    
    # Filter stop words
    filtered = {w: c for w, c in counter.items() if w not in stop_words}
    
    # Sort by frequency
    sorted_terms = sorted(filtered.items(), key=lambda x: -x[1])
    
    # Return top terms
    return [term for term, _ in sorted_terms[:max_terms]]


def classify_search_intent(keyword: str) -> Dict[str, Any]:
    """Classify search intent for a keyword."""
    kw_lower = keyword.lower()
    
    intent_signals = {
        "transactional": ["buy", "price", "cost", "purchase", "order", "book", 
                         "subscribe", "demo", "free trial", "pricing", "near me",
                         "shop", "store", "discount", "coupon", "deal", "offer",
                         "sale", "quote", "estimate"],
        "commercial": ["best", "top", "review", "vs", "comparison", "alternative",
                      "solution", "service", "company", "agency", "pro", "expert",
                      "professional", "quality", "rating", "test", "opinion"],
        "informational": ["how to", "what is", "why", "guide", "tips", "learn",
                         "tutorial", "explained", "definition", "meaning",
                         "example", "benefits", "importance", "basics", "steps"],
        "local": ["near me", "local", "in", "city", "area", "nearby", "region",
                 "state", "country", "zip code", "postcode", "store", "location"],
        "navigational": ["login", "sign in", "dashboard", "account", "app",
                        "portal", "home", "about", "contact", "support"],
    }
    
    scores = {}
    for intent, signals in intent_signals.items():
        score = sum(1 for signal in signals if signal in kw_lower)
        scores[intent] = score
    
    if not scores or max(scores.values()) == 0:
        return {"intent": "informational", "confidence": 0.5}
    
    best_intent = max(scores, key=scores.get)
    confidence = min(1.0, 0.4 + (scores[best_intent] * 0.15))
    
    return {
        "intent": best_intent,
        "confidence": round(confidence, 2),
        "signals_found": [s for s in intent_signals[best_intent] if s in kw_lower],
    }
