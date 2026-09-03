"""Rendered page analysis.

Provides a lightweight rendered-page fetcher that doesn't depend on heavy
browser automation when not available. Falls back to raw HTML when no
renderer is installed.
"""
from __future__ import annotations
from typing import Optional, List, Dict


def has_playwright() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def has_requests() -> bool:
    try:
        import requests  # noqa: F401
        return True
    except Exception:
        return False


class PageRenderer:
    """Try Playwright if available, otherwise mark as raw."""

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.use_playwright = has_playwright()

    def render(self, url: str, wait_for_selector: str = "", wait_timeout: int = 5000,
               wait_until: str = "networkidle") -> dict:
        """Render a page with Playwright.

        Args:
            url: URL to render.
            wait_for_selector: CSS selector to wait for before capturing HTML.
            wait_timeout: Max wait time in ms for selector/network idle.
            wait_until: Playwright wait condition.
        """
        if not self.use_playwright:
            return {
                "ok": False,
                "rendered": False,
                "html": "",
                "reason": "Playwright not installed. Falling back to raw HTML.",
            }
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                ctx = browser.new_context(
                    user_agent="AI-SEO-Autopilot/1.0",
                    viewport={"width": 1280, "height": 800},
                )
                page = ctx.new_page()
                page.goto(url, timeout=self.timeout * 1000, wait_until="domcontentloaded")

                # Wait for specific selector if provided (useful for SPA root elements)
                if wait_for_selector:
                    try:
                        page.wait_for_selector(wait_for_selector, timeout=wait_timeout)
                    except Exception:
                        pass

                # Wait for network idle or fallback timeout
                try:
                    if wait_until == "networkidle":
                        page.wait_for_load_state("networkidle", timeout=wait_timeout)
                    else:
                        page.wait_for_timeout(wait_timeout)
                except Exception:
                    page.wait_for_timeout(2000)

                html = page.content()
                browser.close()
                return {"ok": True, "rendered": True, "html": html}
        except Exception as e:
            return {"ok": False, "rendered": False, "html": "", "reason": str(e)}

    def render_batch(self, urls: List[str], wait_for_selector: str = "",
                     wait_timeout: int = 3000) -> Dict[str, dict]:
        """Render multiple URLs reusing a single browser instance."""
        if not self.use_playwright or not urls:
            return {url: {"ok": False, "rendered": False, "html": "", "reason": "no playwright"} for url in urls}
        results = {}
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                ctx = browser.new_context(
                    user_agent="AI-SEO-Autopilot/1.0",
                    viewport={"width": 1280, "height": 800},
                )
                page = ctx.new_page()
                for url in urls:
                    try:
                        page.goto(url, timeout=self.timeout * 1000, wait_until="domcontentloaded")
                        if wait_for_selector:
                            try:
                                page.wait_for_selector(wait_for_selector, timeout=wait_timeout)
                            except Exception:
                                pass
                        try:
                            page.wait_for_load_state("networkidle", timeout=wait_timeout)
                        except Exception:
                            page.wait_for_timeout(wait_timeout)
                        html = page.content()
                        results[url] = {"ok": True, "rendered": True, "html": html}
                    except Exception as e:
                        results[url] = {"ok": False, "rendered": False, "html": "", "reason": str(e)}
                browser.close()
        except Exception as e:
            for url in urls:
                results.setdefault(url, {"ok": False, "rendered": False, "html": "", "reason": str(e)})
        return results