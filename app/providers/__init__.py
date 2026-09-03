"""Provider abstractions for keyword research, trends, search performance, analytics.

Concrete providers can be plugged in (e.g. SEMrush, Google Keyword Planner,
Google Search Console, etc.). The core application must work with a built-in
local provider so it never depends on paid APIs.
"""
from __future__ import annotations
import re
from typing import List, Dict, Optional
from collections import Counter
from abc import ABC, abstractmethod


class KeywordProvider(ABC):
    name = "base"

    @abstractmethod
    def research(self, seed_terms: List[str], language: str = "en",
                 geo: str = "") -> List[Dict]:
        ...


class TrendProvider(ABC):
    name = "base"

    @abstractmethod
    def trends(self, terms: List[str], geo: str = "") -> List[Dict]:
        ...


class SearchPerformanceProvider(ABC):
    name = "base"

    @abstractmethod
    def fetch(self, site_url: str, days: int = 28) -> List[Dict]:
        ...


class CompetitorProvider(ABC):
    name = "base"

    @abstractmethod
    def search(self, query: str, geo: str = "", limit: int = 10) -> List[str]:
        ...


class LocalKeywordProvider(KeywordProvider):
    """Generates heuristic keyword ideas from seed terms.

    Uses common modifiers (best, how to, near me, etc.) to produce realistic
    keyword candidates when no paid provider is configured.
    """
    name = "local"

    MODIFIERS_PREFIX = [
        "best", "top", "affordable", "professional", "how to", "what is",
        "why", "vs", "near me", "online",
    ]
    MODIFIERS_SUFFIX = [
        "services", "company", "agency", "solutions", "near me", "cost",
        "price", "pricing", "reviews", "examples", "guide", "tips",
    ]
    INTENT_PREFIX = {
        "best": "commercial", "top": "commercial", "affordable": "commercial",
        "professional": "commercial", "vs": "commercial",
        "how to": "informational", "what is": "informational",
        "why": "informational",
        "near me": "local", "online": "transactional",
    }
    INTENT_SUFFIX = {
        "services": "commercial", "company": "commercial", "agency": "commercial",
        "solutions": "commercial", "near me": "local", "cost": "commercial",
        "price": "commercial", "pricing": "commercial",
        "reviews": "commercial", "examples": "informational", "guide": "informational",
        "tips": "informational",
    }

    def research(self, seed_terms: List[str], language: str = "en",
                 geo: str = "") -> List[Dict]:
        results: List[Dict] = []
        seen = set()
        for seed in seed_terms:
            seed = seed.strip().lower()
            if not seed:
                continue
            for pre in self.MODIFIERS_PREFIX:
                kw = f"{pre} {seed}"
                if kw not in seen:
                    seen.add(kw)
                    results.append({
                        "keyword": kw,
                        "intent": self.INTENT_PREFIX.get(pre, "informational"),
                        "search_volume": 0,
                        "is_long_tail": len(kw.split()) > 3,
                        "difficulty": 0.3,
                        "provider": self.name,
                    })
            for suf in self.MODIFIERS_SUFFIX:
                kw = f"{seed} {suf}"
                if kw not in seen:
                    seen.add(kw)
                    results.append({
                        "keyword": kw,
                        "intent": self.INTENT_SUFFIX.get(suf, "commercial"),
                        "search_volume": 0,
                        "is_long_tail": len(kw.split()) > 3,
                        "difficulty": 0.4,
                        "provider": self.name,
                    })
            # also the seed itself
            if seed not in seen:
                seen.add(seed)
                results.append({
                    "keyword": seed,
                    "intent": "informational",
                    "search_volume": 0,
                    "is_long_tail": len(seed.split()) > 3,
                    "difficulty": 0.5,
                    "provider": self.name,
                })
        return results


class LocalTrendProvider(TrendProvider):
    name = "local"

    def trends(self, terms: List[str], geo: str = "") -> List[Dict]:
        # Without real data we provide a placeholder trend score based on
        # the length and uniqueness of the term, so the UI still shows data.
        out = []
        for t in terms:
            words = len(t.split())
            out.append({
                "term": t,
                "trend_score": min(1.0, 0.2 + (words * 0.1)),
                "is_trending": words <= 3,
                "provider": self.name,
            })
        return out


class LocalSearchPerformanceProvider(SearchPerformanceProvider):
    name = "local"

    def fetch(self, site_url: str, days: int = 28) -> List[Dict]:
        # Returns empty list; real integration would query Search Console.
        return []


class LocalCompetitorProvider(CompetitorProvider):
    name = "local"

    def search(self, query: str, geo: str = "", limit: int = 10) -> List[str]:
        # No live search engine in local mode.
        return []


def get_keyword_provider(name: Optional[str] = None) -> KeywordProvider:
    return LocalKeywordProvider()


def get_trend_provider(name: Optional[str] = None) -> TrendProvider:
    return LocalTrendProvider()


def get_search_performance_provider(name: Optional[str] = None) -> SearchPerformanceProvider:
    return LocalSearchPerformanceProvider()


def get_competitor_provider(name: Optional[str] = None) -> CompetitorProvider:
    return LocalCompetitorProvider()


def extract_seed_terms(text: str, max_terms: int = 20) -> List[str]:
    """Extract likely seed terms from page text."""
    text = (text or "").lower()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    words = [w for w in text.split() if len(w) > 3]
    counter = Counter(words)
    return [w for w, _ in counter.most_common(max_terms)]