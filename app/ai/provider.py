"""AI Provider abstraction.

Allows swapping between mock, OpenAI, Anthropic, or local LLMs.
"""
from __future__ import annotations
import logging
import os
import json
import time
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class AIProvider(ABC):
    name: str = "base"

    @abstractmethod
    def analyze(self, prompt: str, context: Optional[Dict] = None) -> str:
        ...

    def plan(self, prompt: str, context: Optional[Dict] = None) -> Dict:
        text = self.analyze(prompt, context)
        try:
            return json.loads(text)
        except Exception:
            return {"raw": text}

    def generate(self, prompt: str, context: Optional[Dict] = None) -> str:
        return self.analyze(prompt, context)

    def classify(self, prompt: str, context: Optional[Dict] = None) -> str:
        return self.analyze(prompt, context)

    def summarize(self, prompt: str, context: Optional[Dict] = None) -> str:
        return self.analyze(prompt, context)


class MockProvider(AIProvider):
    name = "mock"

    def analyze(self, prompt: str, context: Optional[Dict] = None) -> str:
        # Deterministic mock that produces sensible JSON when asked for plans
        ctx = context or {}
        page_topic = ctx.get("topic", "this page")
        keywords = ctx.get("keywords", [])
        kw_str = ", ".join(keywords[:5]) if keywords else ""
        if "proposed_value" in str(ctx) or "plan" in prompt.lower():
            plan = {
                "summary": f"Recommended SEO improvements for {page_topic}.",
                "actions": [
                    {
                        "type": "meta_description",
                        "current": ctx.get("current_description", ""),
                        "value": ctx.get("proposed_description",
                                         f"Discover {page_topic}. {kw_str.title()} - trusted, original, helpful.".strip()),
                        "reason": "Adds a relevant, compelling meta description.",
                        "confidence": 0.9,
                        "risk": "low",
                        "implementation_method": "html_meta_update",
                    },
                ],
            }
            return json.dumps(plan)
        return f"[MOCK AI] Processed prompt of {len(prompt)} chars."


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(self, api_key: str = "", model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model

    def _call(self, prompt: str, max_tokens: int = 800) -> str:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)
            r = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens, temperature=0.4,
            )
            return r.choices[0].message.content or ""
        except Exception as e:
            raise RuntimeError(f"OpenAI call failed: {e}")

    def analyze(self, prompt: str, context: Optional[Dict] = None) -> str:
        return self._call(prompt)


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, api_key: str = "", model: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model

    def _call(self, prompt: str, max_tokens: int = 800) -> str:
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            r = client.messages.create(
                model=self.model, max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return r.content[0].text or ""
        except Exception as e:
            raise RuntimeError(f"Anthropic call failed: {e}")

    def analyze(self, prompt: str, context: Optional[Dict] = None) -> str:
        return self._call(prompt)


class HuggingFaceProvider(AIProvider):
    name = "huggingface"

    def __init__(self, api_key: str = "", model: str = ""):
        self.api_key = api_key or os.environ.get("HUGGINGFACE_API_KEY", "")
        self.model = model or os.environ.get("AI_MODEL", "user052/EDIATH-Q4_K_M")
        self._manager = None

    def _get_manager(self):
        if self._manager is None:
            from ..ai.model_manager import get_model_manager
            self._manager = get_model_manager()
        return self._manager

    def _call(self, prompt: str, max_tokens: int = 800) -> str:
        manager = self._get_manager()
        result = manager.submit_task(prompt, max_tokens=max_tokens)
        if not result.get("ok") and result.get("status") != "completed":
            raise RuntimeError(f"AI model not ready: {result.get('message', 'Unknown error')}")

        from ..events import get_event_manager
        event_manager = get_event_manager()
        event_manager.emit(
            job_id="", event_type="ai_request_start",
            message=f"AI request started: {prompt[:80]}...",
            agent_name="AI Provider",
            severity="info",
            metadata={"model": self.model, "provider": "huggingface"},
        )

        try:
            text = result.get("result", "")
            event_manager.emit(
                job_id="", event_type="ai_request_complete",
                message=f"AI response received ({len(text)} chars)",
                agent_name="AI Provider",
                severity="success",
                metadata={"model": self.model, "response_length": len(text)},
            )
            return text
        except Exception as e:
            event_manager.emit(
                job_id="", event_type="ai_request_failed",
                message=f"AI request failed: {e}",
                agent_name="AI Provider",
                severity="error",
                metadata={"model": self.model, "error": str(e)},
            )
            raise RuntimeError(f"AI generation failed: {e}")

    def analyze(self, prompt: str, context: Optional[Dict] = None) -> str:
        return self._call(prompt)


def get_provider(name: str = "", api_key: str = "", model: str = "") -> AIProvider:
    name = (name or os.environ.get("AI_PROVIDER", "mock")).lower()
    if name == "openai":
        return OpenAIProvider(api_key=api_key, model=model or "gpt-4o-mini")
    if name == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model)
    if name == "huggingface":
        return HuggingFaceProvider(api_key=api_key, model=model)
    return MockProvider()