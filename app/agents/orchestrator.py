"""Orchestrator - coordinates all SEO agents on a website."""
from __future__ import annotations
import json
from datetime import datetime
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from ..config import Config
from ..database.database import SessionLocal, new_session, retry_on_lock, log_audit, filter_model_fields
from ..database.models import (
    Website, Crawl, Page, SEOIssue, Keyword,
    OptimizationPlan, Connection, AuditLog,
)
from ..website.crawler import WebsiteCrawler
from ..website.website_analyzer import analyze_html, calculate_seo_score
from ..website.technology_detector import detect_from_html, detect_from_files
from ..website.url_mapper import best_mapping
from ..seo.audit import run_full_audit
from ..seo.sitemap import discover_sitemaps, fetch_sitemap, parse_sitemap, generate_sitemap, validate_sitemap
from ..seo.robots import fetch_robots, parse_robots, analyze_robots
from ..providers import (
    get_keyword_provider, get_trend_provider,
    extract_seed_terms,
)
from ..ai import get_provider
from ..keywords.engine import KeywordIntelligenceEngine
from ..agents.optimizer import run_seo_optimization
from ..agents.planner_agent import plan_for_page, aggregate_plan
from ..agents.risk import classify_risk, can_auto_implement, deployment_method
from ..deployment import deploy_change
from ..events import get_event_manager
from ..utils import is_js_verification_page, fetch_real_html


def _log(actor: str, action: str, target: str = "", details: dict = None, phase: str = ""):
    if details is None:
        details = {}
    if phase:
        details = {**details, "phase": phase}
    log_audit(actor, action, target=target, details=details)


def run_full_analysis(website_id: int, on_progress=None, **kwargs) -> Dict:
    """End-to-end analysis: crawl, parse, audit, keyword research, plan.

    Database sessions are opened only for the brief moments needed to read
    or write records.  No SQLAlchemy session is held open during HTTP
    crawling, AI analysis, or other long-running work — this prevents
    ``sqlite3.OperationalError: database is locked`` when background job
    progress updates and event-storage threads try to write concurrently.
    """
    event_manager = get_event_manager()
    job_id = kwargs.get("job_id")

    def emit(event_type, message, severity="info", url="", metadata=None, agent_name=""):
        if job_id:
            event_manager.emit(
                job_id=job_id, event_type=event_type, message=message,
                severity=severity, url=url, metadata=metadata or {},
                website_id=website_id, agent_name=agent_name,
            )

    def _update_progress(progress: int, message: str = ""):
        """Update background job progress.

        Uses an independent session (via ``_record_progress``) so it never
        collides with the orchestrator's short-lived phase sessions.
        The ``retry_on_lock`` inside ``_record_progress`` handles brief
        SQLite write contention.
        """
        if job_id:
            from ..tasks.jobs import _record_progress
            _record_progress(job_id, progress, message)

    # ── Phase 0: Read website, extract plain data ──────────────────────
    sess = SessionLocal()
    try:
        website: Website = sess.get(Website, website_id)
        if not website:
            raise ValueError("Website not found")
        root_url = website.root_url
        website_name = website.name
        website_tech = website_technology = (website.technology or "")
        website_business = website.business_description or ""
        website_root_path = website.website_root_path or ""
    finally:
        sess.close()
        SessionLocal.remove()

    emit("analysis_started", f"Starting full analysis of {root_url}",
         metadata={"website": website_name})

    if on_progress:
        on_progress(5, f"Starting crawl of {root_url}")

    # ── Phase 1: Create crawl record, then crawl (HTTP — no session held) ──
    crawl_id: int
    sess = SessionLocal()
    try:
        crawl = Crawl(website_id=website_id, status="running",
                      max_pages=kwargs.get("max_pages") or Config.CRAWL_MAX_PAGES,
                      max_depth=kwargs.get("max_depth") or Config.CRAWL_MAX_DEPTH)
        sess.add(crawl)
        sess.commit()
        sess.refresh(crawl)
        crawl_id = crawl.id
    finally:
        sess.close()
        SessionLocal.remove()

    crawler = WebsiteCrawler(root_url,
                             max_pages=kwargs.get("max_pages"),
                             max_depth=kwargs.get("max_depth"))
    crawler.job_id = job_id

    results = crawler.crawl(
        on_progress=lambda p, m="", u="": (
            on_progress(p, m, u) if on_progress else None
        ),
        job_id=job_id,
    )

    # Use the authoritative crawl result from the crawler — this is the
    # single source of truth that both the Live Activity UI and the
    # Background Job result_json must agree on (Task 3).
    crawl_result = crawler.get_crawl_result()
    pages_crawled = crawl_result["pages_crawled"]
    pages_failed = crawl_result["pages_failed"]
    pages_discovered = crawl_result["pages_discovered"]
    pages_queued = crawl_result["pages_queued"]
    pages_skipped = crawl_result["pages_skipped"]
    pages_blocked = crawl_result["pages_blocked"]
    crawl_errors = crawl_result["errors"]
    fetch_errors = crawl_result["fetch_errors"]
    blocked_count = pages_blocked

    # ── Determine crawl status (Task 4) ──
    # Rules:
    #   pages_crawled == 0 and pages_failed > 0  → "failed", valid=False
    #   pages_crawled > 0 and pages_failed > 0   → "completed_with_failures", valid=True
    #   pages_crawled > 0 and pages_failed == 0  → "completed", valid=True
    if pages_crawled == 0 and pages_failed > 0:
        crawl_status = "failed"
        crawl_error = (
            f"All {pages_failed} page(s) failed to fetch. "
            f"Errors: {fetch_errors}"
            if fetch_errors else f"All {pages_failed} page(s) failed."
        )
        valid = False
    elif pages_failed > 0:
        crawl_status = "completed_with_failures"
        crawl_error = f"{pages_failed} page(s) failed to fetch"
        valid = True
    elif pages_crawled > 0:
        crawl_status = "completed"
        crawl_error = ""
        valid = True
    else:
        crawl_status = "failed"
        crawl_error = "No pages crawled and no failures recorded"
        valid = False

    # Emit the authoritative crawl result so get_job_stats can sync
    emit("crawl_result",
         f"Crawl result: {pages_crawled} crawled, {pages_failed} failed",
         severity="info" if pages_failed == 0 else "error",
         metadata=crawl_result)

    _update_progress(45, f"Crawl complete: {pages_crawled} pages crawled, {pages_failed} failed")
    _log("orchestrator", "crawl_completed", root_url,
         {"website_id": website_id, "pages_crawled": pages_crawled,
          "pages_failed": pages_failed, "pages_discovered": pages_discovered,
          "crawl_status": crawl_status, "errors": crawl_errors}, phase="crawl")

    # Persist crawl record with authoritative counters
    sess = new_session()
    try:
        crawl = sess.query(Crawl).filter_by(id=crawl_id).first()
        if crawl:
            crawl.status = crawl_status
            crawl.error_message = crawl_error or ""
            crawl.pages_crawled = pages_crawled
            crawl.source = crawl_result.get("source", "raw")
            crawl.finished_at = datetime.utcnow()
        sess.commit()
    except Exception:
        sess.rollback()
    finally:
        sess.close()
        SessionLocal.remove()

    # Update website architecture
    arch = getattr(crawler, 'architecture', {}) or {}
    sess = new_session()
    try:
        website = sess.get(Website, website_id)
        if website and arch:
            website.architecture_type = arch.get("architecture_type", website.architecture_type)
            website.rendering_mode = arch.get("rendering_mode", website.rendering_mode)
            website.deployment_strategy = arch.get("deployment_strategy", website.deployment_strategy)
            website.hosting_provider = arch.get("hosting_provider", website.hosting_provider)
            website.detected_spa_framework = arch.get("detected_spa_framework", website.detected_spa_framework)
            website.detected_framework_evidence = arch.get("evidence", [])
            website.build_system = arch.get("build_system", website.build_system)
            website.last_architecture_check = datetime.utcnow()
            sess.add(website)
        sess.commit()
    except Exception:
        sess.rollback()
    finally:
        sess.close()
        SessionLocal.remove()

    # If the crawl fully failed, skip analysis/optimization and return early
    if crawl_status == "failed":
        emit("analysis_failed",
             f"Crawl failed: {crawl_error}. Cannot analyze or optimize.",
             severity="error")
        _log("orchestrator", "full_analysis", root_url,
             {"website_id": website_id, "pages_crawled": pages_crawled,
              "pages_failed": pages_failed, "errors": crawl_errors,
              "crawl_status": crawl_status}, phase="failed")
        return {
            "ok": False,
            "valid": False,
            "pages_crawled": pages_crawled,
            "pages_failed": pages_failed,
            "pages_discovered": pages_discovered,
            "pages_queued": pages_queued,
            "pages_skipped": pages_skipped,
            "pages_blocked": blocked_count,
            "issues_found": 0,
            "technology": website_tech,
            "sitemap_urls": [],
            "robots": {},
            "keyword_count": 0,
            "plan_id": 0,
            # Do NOT save 0.0 as a real SEO score when no pages were
            # successfully analyzed (Task 5).  Use null instead.
            "seo_health_score": None,
            "crawl_status": crawl_status,
            "block_reason": crawl_error,
        }

    # ── Phase 2: Analyze pages in-memory (no DB session) ──────────────
    issues_by_page: Dict[int, List[Dict]] = {}
    all_keywords: List[Dict] = []
    tech_detected: List[str] = []
    total_issues = 0
    page_records: List[dict] = []  # plain dicts for batch insertion

    emit("analysis_phase", "Analyzing pages and detecting SEO issues",
         agent_name="SEO Audit Agent")

    for i, r in enumerate(results):
        html = r.get("html", "")
        status = r.get("status_code", 0)
        url = r.get("url", "")

        if r.get("rendered") and r.get("rendered_html"):
            html = r["rendered_html"]

        emit("page_analysis_started", f"Analyzing {url}",
             agent_name="SEO Audit Agent", url=url)

        analyzed = analyze_html(html, base_url=url)
        score = calculate_seo_score(analyzed)
        tech = detect_from_html(html)
        tech_detected.extend(tech.get("detected", []))

        mapping = best_mapping(url, website_root_path)

        page_dict = {
            "website_id": website_id,
            "crawl_id": crawl_id,
            "url": url,
            "canonical_url": analyzed.get("canonical", ""),
            "server_file": (mapping.get("best") or {}).get("file", ""),
            "file_mapping_confidence": (mapping.get("best") or {}).get("confidence", 0.0),
            "status_code": status,
            "content_type": "text/html",
            "title": analyzed.get("title", ""),
            "meta_description": analyzed.get("meta_description", ""),
            "h1": (analyzed.get("headings", {}).get("h1") or [""])[0],
            "headings_json": analyzed.get("headings", {}),
            "word_count": analyzed.get("word_count", 0),
            "main_content": analyzed.get("main_content", ""),
            "images_json": analyzed.get("images", {}),
            "links_json": analyzed.get("links", {}),
            "og_json": analyzed.get("open_graph", {}),
            "twitter_json": analyzed.get("twitter", {}),
            "structured_data_json": analyzed.get("structured_data", []),
            "language": analyzed.get("language", ""),
            "robots_meta": analyzed.get("robots_meta", ""),
            "rendered": bool(r.get("rendered")),
            "seo_score": score,
            "analyzed_at": datetime.utcnow(),
            "route_url": url,
            "rendered_html": r.get("rendered_html", "") or "",
            "rendered_word_count": analyzed.get("word_count", 0) if r.get("rendered") else 0,
            "rendered_title": analyzed.get("title", "") if r.get("rendered") else "",
            "rendered_meta_description": analyzed.get("meta_description", "") if r.get("rendered") else "",
            "rendered_h1": (analyzed.get("headings", {}).get("h1") or [""])[0] if r.get("rendered") else "",
            "rendered_headings_json": analyzed.get("headings", {}) if r.get("rendered") else {},
            "rendered_main_content": analyzed.get("main_content", "") if r.get("rendered") else "",
            "rendered_images_json": analyzed.get("images", {}) if r.get("rendered") else {},
            "rendered_links_json": analyzed.get("links", {}) if r.get("rendered") else {},
            "rendered_og_json": analyzed.get("open_graph", {}) if r.get("rendered") else {},
            "rendered_twitter_json": analyzed.get("twitter", {}) if r.get("rendered") else {},
            "rendered_structured_data_json": analyzed.get("structured_data", []) if r.get("rendered") else [],
            "rendered_canonical_url": analyzed.get("canonical", "") if r.get("rendered") else "",
            "rendered_language": analyzed.get("language", "") if r.get("rendered") else "",
            "rendered_robots_meta": analyzed.get("robots_meta", "") if r.get("rendered") else "",
            "is_spa_route": bool(r.get("is_spa")),
            "source_file_path": r.get("source_file_path", ""),
            "source_language": r.get("source_language", ""),
        }
        page_records.append(page_dict)

        audit_issues = run_full_audit(analyzed, status_code=status)
        issues_by_page[url] = audit_issues

        page_issue_count = 0
        for iss in audit_issues:
            page_issue_count += 1
            total_issues += 1
            emit("seo_issue_found",
                 f"{iss['title']} ({iss['severity']})",
                 agent_name="SEO Audit Agent",
                 severity="error" if iss["severity"] in ("critical", "high") else "warning",
                 url=url,
                 metadata={"issue_type": iss["issue_type"],
                           "severity": iss["severity"],
                           "title": iss["title"]})

        emit("page_analysis_completed",
             f"Found {page_issue_count} issues on {url}",
             agent_name="SEO Audit Agent",
             url=url,
             metadata={"issues_found": page_issue_count, "seo_score": score})

        # seed terms (collected in-memory, saved later)
        seeds = extract_seed_terms(analyzed.get("main_content", ""))
        for s in seeds[:10]:
            all_keywords.append({"term": s, "page_url": url})

        if on_progress:
            on_progress(45 + int(20 * (i + 1) / max(1, len(results))),
                        f"Analyzed {i + 1}/{len(results)} pages")

    # ── Phase 2b: Persist pages + issues (short transaction) ──────────
    issue_dicts: List[dict] = []
    for page_dict in page_records:
        issue_list = issues_by_page.get(page_dict["url"], [])
        for iss in issue_list:
            issue_dicts.append({
                "website_id": website_id,
                "page_id": None,  # filled after page insert
                "url": page_dict["url"],
                "issue_type": iss["issue_type"],
                "severity": iss["severity"],
                "title": iss["title"],
                "description": iss.get("description", ""),
                "current_value": str(iss.get("current_value", ""))[:1000],
                "proposed_value": str(iss.get("proposed_value", ""))[:1000],
                "implementation_method": iss.get("implementation_method", ""),
                "risk": iss.get("risk", classify_risk(iss)),
                "confidence": iss.get("confidence", 0.7),
            })

    sess = SessionLocal()
    try:
        valid_page_fields = filter_model_fields(Page, page_records[0]) if page_records else {}
        sess.add_all([Page(**filter_model_fields(Page, pd)) for pd in page_records])
        sess.flush()
        # Map URL → page_id for issues and keyword lookup
        url_to_page_id = {p.url: p.id for p in sess.query(Page).filter_by(
            website_id=website_id, crawl_id=crawl_id).all()}

        for issue_dict in issue_dicts:
            issue_dict["page_id"] = url_to_page_id.get(issue_dict["url"])
        sess.add_all([SEOIssue(**i) for i in issue_dicts])
        sess.commit()
    finally:
        sess.close()
        SessionLocal.remove()

    emit("pages_saved_completed",
         f"Saved {len(page_records)} pages and {len(issue_dicts)} issues to database",
         agent_name="Database",
         metadata={"pages_saved": len(page_records), "total_issues": total_issues})

    _log("orchestrator", "seo_audit_completed", root_url,
         {"website_id": website_id, "total_issues": total_issues, "pages_analyzed": len(results)}, phase="seo_audit")

    # ── Phase 3: Detect technology and update website record (short tx) ──
    primary_tech = tech_detected[0] if tech_detected else "unknown"
    if website_tech in ("unknown", "", None):
        website_tech = primary_tech
        sess = SessionLocal()
        try:
            sess.query(Website).filter_by(id=website_id).update(
                {"technology": primary_tech}, synchronize_session=False
            )
            sess.commit()
        finally:
            sess.close()
            SessionLocal.remove()

    # ── Phase 4: Sitemap + robots (HTTP — no session held) ────────────
    emit("analysis_phase", "Discovering sitemap and robots.txt",
         agent_name="Website Discovery Agent")
    if on_progress:
        on_progress(70, "Discovering sitemap and robots.txt")
    sitemaps = discover_sitemaps(root_url)
    sitemap_urls: List[str] = []
    for s_url in sitemaps:
        xml = fetch_sitemap(s_url)
        valid = validate_sitemap(xml or "")
        parsed = parse_sitemap(xml or "")
        sitemap_urls.extend([u["loc"] for u in parsed if u.get("type") == "url"])

    robots_text = fetch_robots(root_url)
    robots_info = analyze_robots(robots_text)

    # ── Phase 5: Keyword intelligence research (AI — no session held) ──
    emit("analysis_phase", "Running keyword intelligence analysis",
         agent_name="Keyword Intelligence Agent")
    if on_progress:
        on_progress(75, "Running keyword intelligence analysis")

    pages_data = []
    for r in results:
        analysis_html = r.get("rendered_html", r.get("html", "")) if r.get("rendered") else r.get("html", "")
        analyzed = analyze_html(analysis_html, base_url=r.get("url", ""))
        pages_data.append({
            "url": r.get("url", ""),
            "title": analyzed.get("title", ""),
            "meta_description": analyzed.get("meta_description", ""),
            "main_content": analyzed.get("main_content", ""),
            "headings": analyzed.get("headings", {}),
            "word_count": analyzed.get("word_count", 0),
        })

    kw_engine = KeywordIntelligenceEngine(
        website_id=website_id,
        website_url=root_url,
        business_description=website_business,
    )
    kw_result = kw_engine.run_full_analysis(pages_data)

    keyword_summary = kw_result.get("summary", {})
    all_keywords_data = kw_result.get("keywords", [])
    page_mappings = kw_result.get("page_mappings", [])
    content_gaps = kw_result.get("content_gaps", [])
    cannibalization = kw_result.get("cannibalization", [])
    strategies = kw_result.get("strategies", [])

    # Build page_url → page_id map (short read session)
    keyword_dicts: List[dict] = []
    if all_keywords_data:
        sess = SessionLocal()
        try:
            page_url_ids = {p.url: p.id for p in sess.query(Page).filter_by(
                website_id=website_id, crawl_id=crawl_id).all()}
        finally:
            sess.close()
            SessionLocal.remove()

        for kw in all_keywords_data:
            page_id = None
            for mapping in page_mappings:
                if kw.get("keyword", "").lower() in [k.get("keyword", "").lower() for k in mapping.get("keywords", [])]:
                    page_id = page_url_ids.get(mapping.get("page_url"))
                    break
            keyword_dicts.append({
                "website_id": website_id,
                "page_id": page_id,
                "keyword": kw.get("keyword", ""),
                "cluster": kw.get("intent", ""),
                "intent": kw.get("intent", ""),
                "search_volume": kw.get("search_volume", 0),
                "difficulty": kw.get("difficulty", 0.0),
                "relevance": kw.get("relevance", 0.0),
                "opportunity_score": kw.get("opportunity_score", 0.0),
                "is_long_tail": kw.get("is_long_tail", False),
                "is_trending": kw.get("is_trending", False),
                "provider": kw.get("provider", "local"),
            })

        # Persist keywords (short write transaction)
        sess = SessionLocal()
        try:
            sess.add_all([Keyword(**kd) for kd in keyword_dicts])
            sess.commit()
        finally:
            sess.close()
            SessionLocal.remove()

    emit("keyword_research_completed",
         f"Found {len(all_keywords_data)} keywords, {len(content_gaps)} content gaps",
         agent_name="Keyword Intelligence Agent",
         metadata=keyword_summary)

    _log("orchestrator", "keyword_research_completed", root_url,
         {"website_id": website_id, "keyword_count": len(all_keywords_data),
          "content_gaps": len(content_gaps), "cannibalization": len(cannibalization)}, phase="keyword_research")

    emit("seo_analysis_completed",
         f"SEO analysis complete. {total_issues} issues found across {len(results)} pages.",
         agent_name="SEO Audit Agent",
         metadata={"total_issues": total_issues, "pages_analyzed": len(results)})

    # ── Phase 6: Build optimization plan (AI — session held only for page read) ──
    emit("analysis_phase", "Building AI optimization plan",
         agent_name="Optimization Planner")
    if on_progress:
        on_progress(85, "Building AI optimization plan")
    ai_provider = get_provider()

    strategy_map = {s.get("page_url"): s for s in strategies if s.get("page_url")}

    # Read pages into plain data (short read transaction) ──────────────────
    sess = SessionLocal()
    try:
        pages_for_planning = sess.query(Page).filter_by(
            website_id=website_id, crawl_id=crawl_id
        ).all()
        page_data_list = [{
            "id": p.id,
            "url": p.url,
            "title": p.title,
            "h1": p.h1,
            "meta_description": p.meta_description,
            "canonical_url": p.canonical_url,
            "og_json": p.og_json,
            "structured_data_json": p.structured_data_json,
        } for p in pages_for_planning]
    finally:
        sess.close()
        SessionLocal.remove()

    # Map URL → id for planning phase
    page_url_to_id = {pd["url"]: pd["id"] for pd in page_data_list}

    # AI planning — no DB session held ────────────────────────────────────
    page_plans = []
    for pd in page_data_list:
        issues = issues_by_page.get(pd["url"], [])
        strategy = strategy_map.get(pd["url"], {})
        page_keywords = strategy.get("primary_keyword") or ""
        secondary = strategy.get("secondary_keywords", [])
        if secondary and not page_keywords:
            page_keywords = secondary[0]
        all_page_kws = [page_keywords] + secondary if page_keywords else secondary

        plan = plan_for_page(
            {
                "url": pd["url"],
                "topic": (pd["title"] or pd["h1"] or pd["url"]),
                "title": pd["title"],
                "meta_description": pd["meta_description"],
                "canonical": pd["canonical_url"],
                "open_graph": pd["og_json"],
                "structured_data": pd["structured_data_json"],
                "keywords": all_page_kws,
                "keyword_strategy": strategy,
                "content_gaps": strategy.get("content_gaps", []),
            },
            issues, ai_provider=ai_provider,
        )
        page_plans.append(plan)
    agg = aggregate_plan(page_plans)

    agg["keyword_intelligence"] = {
        "summary": keyword_summary,
        "strategies_count": len(strategies),
        "content_gaps_count": len(content_gaps),
        "cannibalization_count": len(cannibalization),
        "high_opportunity_keywords": keyword_summary.get("high_opportunity", 0),
    }

    # ── Phase 7: Persist plan + finalize crawl (short write transaction) ──
    plan_id: int
    seo_health_score: Optional[float]
    sess = SessionLocal()
    try:
        plan_row = OptimizationPlan(
            website_id=website_id,
            title=f"Optimization plan for {website_name}",
            summary=f"Keyword intelligence: {keyword_summary.get('total_keywords', 0)} keywords, {len(content_gaps)} content gaps, {len(cannibalization)} cannibalization issues",
            actions_json=agg,
            risk_breakdown=agg.get("risk_breakdown", {}),
            status="draft",
        )
        sess.add(plan_row)
        sess.flush()
        plan_id = plan_row.id

        # SEO health score (average page score) — exclude invalid/zero scores.
        # When no pages were successfully crawled, do NOT overwrite the
        # website's previous valid score with 0.0 (Task 5).
        avg_scores = sess.query(Page.seo_score).filter(
            Page.website_id == website_id,
            Page.crawl_id == crawl_id,
            Page.seo_score > 0,
        ).all()
        if avg_scores and pages_crawled > 0:
            score_val = round(sum(p[0] for p in avg_scores) / max(1, len(avg_scores)), 1)
        elif pages_crawled > 0:
            score_val = 0.0
        else:
            score_val = None  # Do not overwrite previous score

        website_update: Dict = {"last_analyzed": datetime.utcnow()}
        if score_val is not None:
            website_update["seo_health_score"] = score_val
        sess.query(Website).filter_by(id=website_id).update(
            website_update,
            synchronize_session=False,
        )
        sess.query(Crawl).filter_by(id=crawl_id).update(
            {"finished_at": datetime.utcnow(),
             "status": crawl_status,
             "pages_crawled": pages_crawled,
             "error_message": crawl_error or ""},
            synchronize_session=False,
        )
        sess.commit()
        seo_health_score = score_val
    finally:
        sess.close()
        SessionLocal.remove()

    emit("score_calculation_completed",
         f"SEO health score: {seo_health_score}",
         agent_name="SEO Audit Agent",
         metadata={"seo_health_score": seo_health_score, "pages_scored": len(page_data_list)})

    emit("analysis_completed",
         f"Analysis complete. {pages_crawled} pages crawled, {total_issues} issues found.",
         severity="success",
         metadata={"pages_crawled": pages_crawled,
                   "pages_failed": pages_failed,
                   "issues_found": total_issues,
                   "seo_health_score": seo_health_score})

    _log("orchestrator", "plan_created", root_url,
         {"website_id": website_id, "total_actions": agg.get("total_actions", 0)}, phase="planning")

    # ── Phase 8: Auto-deploy (if enabled; each deploy_change opens its own session) ──
    mode = Config.SEO_AUTOMATION_MODE
    if mode != "analysis_only":
        try:
            for page_plan in page_plans:
                page_url = page_plan.get("page_url", "")
                server_file = page_plan.get("_server_file")
                if not server_file:
                    mapping = best_mapping(page_url, website_root_path or "")
                    if mapping and mapping.get("best"):
                        server_file = mapping["best"]["file"]
                    else:
                        server_file = next((pd.get("url") for pd in page_data_list
                                           if pd["url"] == page_url), page_url)

                for action in page_plan.get("actions", []):
                    risk = action.get("risk", "medium")
                    if not can_auto_implement({}, mode, risk):
                        continue

                    try:
                        fetch_result = fetch_real_html(page_url)
                        if not fetch_result.get("ok"):
                            _log("orchestrator", "page_fetch_failed", page_url,
                                 {"website_id": website_id, "error": fetch_result.get("error"),
                                  "challenge": fetch_result.get("challenge")},
                                 phase="deployment")
                            continue
                        current_html = fetch_result["html"]
                    except Exception:
                        continue

                    change_payload = [{
                        "type": action.get("type", "meta_description"),
                        "value": action.get("value", ""),
                        "match": "",
                        "reason": action.get("reason", ""),
                        "risk": risk,
                        "confidence": action.get("confidence", 0.7),
                        "implementation_method": action.get(
                            "implementation_method", "html_meta_update"
                        ),
                    }]

                    try:
                        result = deploy_change(
                            website_id,
                            server_file,
                            current_html.encode("utf-8"),
                            change_payload,
                            page_url=page_url,
                        )
                        emit(
                            "seo_change_deployed",
                            f"Auto-deployed {action.get('type')} on {page_url}",
                            agent_name="Auto Deploy",
                            url=page_url,
                            metadata={"result": result, "action_type": action.get("type")},
                        )
                    except Exception as e:
                        emit(
                            "seo_change_failed",
                            f"Auto-deploy failed for {action.get('type')} on {page_url}: {e}",
                            agent_name="Auto Deploy",
                            severity="error",
                            url=page_url,
                        )
        except Exception as e:
            emit(
                "auto_implement_failed",
                f"Auto-implement encountered an error: {e}",
                severity="warning",
            )

    if on_progress:
        on_progress(100, "Done")

    # ── Phase 9: Auto-optimization (if average score below target) ─────
    mode = Config.SEO_AUTOMATION_MODE
    if crawl_status in ("completed", "completed_with_failures") and mode != "analysis_only" and seo_health_score is not None and seo_health_score < 90:
        try:
            from ..tasks import enqueue as _enqueue
            opt_job_id = _enqueue(
                "seo_optimization", website_id,
                run_seo_optimization,
                website_id=website_id,
                crawl_id=crawl_id,
                target_score=95.0,
                max_iterations=3,
            )
            emit("optimization_queued",
                 f"SEO optimization queued (avg score {seo_health_score} < 90).",
                 agent_name="Optimization Engine",
                 metadata={"avg_score": seo_health_score, "target_score": 95.0,
                           "optimization_job_id": opt_job_id})
        except Exception as e:
            emit("optimization_queue_failed",
                 f"Failed to queue optimization: {e}",
                 severity="warning", agent_name="Optimization Engine")

    # ── Phase 10: Final audit + return ─────────────────────────────────
    final_phase = crawl_status if crawl_status != "completed" else "completed"
    _log("orchestrator", "full_analysis", root_url,
         {"pages": pages_crawled, "pages_failed": pages_failed,
          "issues": total_issues, "crawl_status": crawl_status,
          "pages_blocked": blocked_count}, phase=final_phase)

    return {
        "ok": crawl_status in ("completed", "completed_with_failures"),
        "valid": crawl_status in ("completed", "completed_with_failures"),
        "pages_crawled": pages_crawled,
        "pages_failed": pages_failed,
        "pages_discovered": pages_discovered,
        "pages_queued": pages_queued,
        "pages_skipped": pages_skipped,
        "pages_blocked": blocked_count,
        "issues_found": total_issues,
        "technology": primary_tech,
        "sitemap_urls": sitemap_urls,
        "robots": robots_info,
        "keyword_count": len(all_keywords_data),
        "plan_id": plan_id,
        "seo_health_score": seo_health_score,
        "crawl_status": crawl_status,
        "analysis_status": crawl_status,
        "block_reason": crawl_error if crawl_status in ("failed", "blocked") else "",
    }
