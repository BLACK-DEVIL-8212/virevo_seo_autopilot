"""Automatic SEO optimization engine.

Runs after a full analysis when the average SEO score is below target.
Iteratively optimizes the lowest-scoring pages, verifies score improvement,
and stops when the target is reached or no safe improvements remain.

Database sessions are opened only for brief reads/writes and are never
held open during HTTP requests, AI calls, or HTML modification.
"""
from __future__ import annotations
import os
import requests
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse

from ..config import Config
from ..database.database import SessionLocal, new_session, retry_on_lock, log_audit
from ..database.models import (
    Website, Page, SEOIssue, SEOChange, SEOOptimization, PageOptimization,
    ProviderConfiguration, OptimizationPlan, Crawl, Connection,
)
from ..website.website_analyzer import analyze_html, calculate_seo_score
from ..agents.planner_agent import plan_for_page
from ..agents.risk import can_auto_implement
from ..deployment import deploy_change, rollback_change
from ..deployment.deployer import _safe_remote_root, _resolve_remote_path
from ..modifiers import apply_changes
from ..events import get_event_manager
from ..providers import get_trend_provider
from ..utils import is_js_verification_page, fetch_real_html
from ..website.url_mapper import best_mapping


_NON_HTML_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif",
    ".pdf", ".zip", ".mp4", ".mp3", ".wav", ".css", ".js", ".mjs",
    ".map", ".woff", ".woff2", ".ttf", ".eot", ".json", ".xml",
    ".txt", ".rss", ".atom", ".webmanifest", ".manifest",
    ".cur", ".wasm", ".swf",
}

_NON_HTML_PATHS = {
    "/sitemap.xml", "/sitemap-index.xml", "/sitemap_index.xml",
    "/robots.txt", "/favicon.ico", "/site.webmanifest",
    "/manifest.json", "/service-worker.js",
}


def _is_valid_html_page(url: str, html: str, status_code: int) -> bool:
    """Return True only if the URL and response look like a real HTML page."""
    if status_code < 200 or status_code >= 400:
        return False
    if not html or not html.strip():
        return False
    path = urlparse(url).path.lower()
    if path in _NON_HTML_PATHS:
        return False
    if any(path.endswith(ext) for ext in _NON_HTML_EXTENSIONS):
        return False
    lowered = html.lstrip().lower()
    if lowered.startswith("<!doctype") or lowered.startswith("<html"):
        return True
    if "<html" in lowered[:400].lower():
        return True
    return False


def _resolve_spa_deployment_target(website_id: int, url: str, changes: List[Dict], conn_obj) -> Optional[Dict]:
    """Inspect FTP server and determine the best deployment target for SPA SEO changes.

    Returns a dict with:
        - strategy: str (spa_index_html, static_html, non_html_file, not_supported)
        - server_file: str (FTP path)
        - reason: str
        - ftp_files_inspected: list
    or None if deployment is not supported.
    """
    from urllib.parse import urlparse
    from ..connections.connection_manager import FTPConnection, SFTPConnection

    path = urlparse(url).path.lower()
    ftp_files_inspected = []

    # Strategy D: Non-HTML SEO files (robots.txt, sitemap.xml)
    if path in ("/robots.txt", "/sitemap.xml", "/sitemap-index.xml", "/sitemap_index.xml"):
        remote_root = _safe_remote_root(website_id, conn_obj) if 'website_id' in dir() else "/"
        # We need to get the website object to get the remote root
        sess = new_session()
        try:
            website = sess.get(Website, website_id)
            if website:
                conn = sess.query(Connection).filter_by(website_id=website_id).first()
                remote_root = _safe_remote_root(website, conn)
        except Exception:
            pass
        finally:
            sess.close()

        server_file = path.lstrip("/")
        ftp_files_inspected.append(server_file)
        return {
            "strategy": "non_html_file",
            "server_file": server_file,
            "reason": f"Deploy {path} directly through FTP",
            "ftp_files_inspected": ftp_files_inspected,
        }

    # For HTML pages, inspect FTP structure
    sess = new_session()
    try:
        website = sess.get(Website, website_id)
        if not website:
            return None
        conn = sess.query(Connection).filter_by(website_id=website_id).first()
        if not conn:
            return None

        remote_root = _safe_remote_root(website, conn)

        # Connect to FTP and inspect structure
        try:
            connect_result = conn_obj.connect()
            if not connect_result.ok:
                emit("spa_deployment_analysis",
                     f"SPA deployment analysis for {url}: FTP connection failed",
                     severity="warning", url=url,
                     metadata={"error": connect_result.message})
                return {
                    "strategy": "not_supported",
                    "server_file": "",
                    "reason": f"FTP connection failed: {connect_result.message}",
                    "ftp_files_inspected": [],
                }

            # List root directory
            root_files = []
            try:
                root_files = conn_obj.listdir(remote_root or "/")
                ftp_files_inspected.extend([f"{remote_root.rstrip('/')}/{f}" if remote_root and remote_root != '/' else f"/{f}" for f in root_files[:20]])
            except Exception:
                pass

            emit("spa_deployment_analysis",
                 f"SPA deployment analysis for {url}: FTP files inspected: {len(ftp_files_inspected)} files",
                 severity="info", url=url,
                 metadata={"ftp_files_inspected": ftp_files_inspected[:20]})

            # Check for index.html
            index_path = "index.html"
            if remote_root and remote_root != "/":
                index_path = f"{remote_root.rstrip('/')}/index.html"

            has_index_html = False
            try:
                index_content = conn_obj.download(index_path)
                has_index_html = index_content is not None and len(index_content) > 0
                if has_index_html:
                    ftp_files_inspected.append(index_path)
            except Exception:
                pass

            if has_index_html:
                emit("spa_deployment_analysis",
                     f"SPA deployment analysis for {url}: Found index.html, strategy=spa_index_html",
                     severity="info", url=url,
                     metadata={"strategy": "spa_index_html", "server_file": index_path})
                return {
                    "strategy": "spa_index_html",
                    "server_file": index_path,
                    "reason": "SPA with editable index.html found. Global SEO metadata can be deployed to index.html.",
                    "ftp_files_inspected": ftp_files_inspected,
                }

            # Check for route-specific HTML files
            url_path = urlparse(url).path
            if url_path and url_path != "/":
                route_file = url_path.lstrip("/")
                if not route_file.endswith(".html"):
                    route_file = f"{route_file}.html"
                if remote_root and remote_root != "/":
                    route_file = f"{remote_root.rstrip('/')}/{route_file}"

                try:
                    route_content = conn_obj.download(route_file)
                    if route_content is not None and len(route_content) > 0:
                        ftp_files_inspected.append(route_file)
                        emit("spa_deployment_analysis",
                             f"SPA deployment analysis for {url}: Found route HTML, strategy=static_html",
                             severity="info", url=url,
                             metadata={"strategy": "static_html", "server_file": route_file})
                        return {
                            "strategy": "static_html",
                            "server_file": route_file,
                            "reason": f"Route-specific HTML file found: {route_file}",
                            "ftp_files_inspected": ftp_files_inspected,
                        }
                except Exception:
                    pass

            # Check for JavaScript config files that might contain SEO metadata
            js_configs = []
            for f in root_files:
                if f.endswith(".js") and any(kw in f.lower() for kw in ["config", "app", "main", "index"]):
                    js_configs.append(f)
                    ftp_files_inspected.append(f"{remote_root.rstrip('/')}/{f}" if remote_root and remote_root != '/' else f"/{f}")

            reason = ""
            if js_configs:
                reason = f"SPA with only JavaScript bundles found. No editable HTML source. Files: {', '.join(js_configs[:5])}"
            else:
                reason = "No deployable HTML or config files found on FTP server."

            emit("spa_deployment_analysis",
                 f"SPA deployment analysis for {url}: Not supported. {reason}",
                 severity="warning", url=url,
                 metadata={"strategy": "not_supported", "reason": reason, "ftp_files_inspected": ftp_files_inspected})

            return {
                "strategy": "not_supported",
                "server_file": "",
                "reason": reason,
                "ftp_files_inspected": ftp_files_inspected,
            }

        except Exception as e:
            emit("spa_deployment_analysis",
                 f"SPA deployment analysis for {url}: FTP inspection failed: {e}",
                 severity="warning", url=url,
                 metadata={"error": str(e)})
            return {
                "strategy": "not_supported",
                "server_file": "",
                "reason": f"FTP inspection failed: {e}",
                "ftp_files_inspected": ftp_files_inspected,
            }
    except Exception:
        pass
    finally:
        try:
            sess.close()
        except Exception:
            pass

    return None


def _has_real_trend_provider(website_id: int) -> bool:
    """Return True only if a non-local trend provider is enabled."""
    sess = new_session()
    try:
        configs = sess.query(ProviderConfiguration).filter_by(
            provider_type="trend", enabled=True
        ).all()
        for cfg in configs:
            name = (cfg.provider_name or "").lower()
            if name not in ("local", "", "base"):
                return True
        return False
    finally:
        sess.close()


def _get_keyword_strategy(website_id: int, page_url: str) -> Dict:
    """Retrieve the latest keyword strategy for a page from the optimization plan."""
    sess = new_session()
    try:
        plan = sess.query(OptimizationPlan).filter_by(website_id=website_id)\
            .order_by(OptimizationPlan.created_at.desc()).first()
        if not plan or not plan.actions_json:
            return {}
        pages = plan.actions_json.get("pages", [])
        for p in pages:
            if p.get("page_url") == page_url:
                return p.get("keyword_strategy", {})
        return {}
    finally:
        sess.close()


def _fetch_page_html(url: str) -> Optional[tuple]:
    """Fetch current HTML for a page. Returns (html, status_code, content_type) or None."""
    result = fetch_real_html(url)
    if result.get("ok"):
        return result["html"], result["status_code"], "text/html"
    if result.get("challenge"):
        import logging
        logging.getLogger(__name__).warning(
            "Blocked by JS verification: %s indicators=%s sample=%s",
            url, result.get("challenge", {}).get("indicators", []), result.get("html", "")[:200],
        )
    return None


def _update_page_analysis(page_id: int, analyzed: Dict, new_score: float, crawl_id: int) -> None:
    """Update a Page record with fresh analysis results.
    
    Only overwrites fields when the new analysis is valid. Preserves previous
    valid values when the new analysis is incomplete or failed.
    """
    sess = new_session()
    try:
        page = sess.get(Page, page_id)
        if not page:
            return
        
        # Determine if the new analysis is valid and complete
        new_word_count = analyzed.get("word_count")
        new_main_content = (analyzed.get("main_content", "") or "").strip()
        is_valid_analysis = (
            new_score is not None 
            and new_score > 0
            and (new_word_count or 0) > 0
            and len(new_main_content) > 0
        )
        
        if not is_valid_analysis:
            # Analysis appears incomplete or failed - preserve all previous values
            return
        
        page.title = analyzed.get("title", "") or page.title
        page.meta_description = analyzed.get("meta_description", "") or page.meta_description
        page.h1 = (analyzed.get("headings", {}).get("h1") or [""])[0] or page.h1
        page.headings_json = analyzed.get("headings", {})
        page.word_count = new_word_count
        page.main_content = new_main_content[:5000]
        page.images_json = analyzed.get("images", {})
        page.links_json = analyzed.get("links", {})
        page.og_json = analyzed.get("open_graph", {})
        page.twitter_json = analyzed.get("twitter", {})
        page.structured_data_json = analyzed.get("structured_data", [])
        page.canonical_url = analyzed.get("canonical", "") or page.canonical_url
        page.robots_meta = analyzed.get("robots_meta", "") or page.robots_meta
        page.language = analyzed.get("language", "") or page.language
        page.seo_score = new_score
        page.analyzed_at = datetime.utcnow()
        sess.add(page)
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def _snapshot_page(page: Page) -> Dict:
    """Capture a complete snapshot of a page's current analysis state."""
    return {
        "page_id": page.id,
        "seo_score": page.seo_score,
        "word_count": page.word_count,
        "title": page.title,
        "meta_description": page.meta_description,
        "canonical_url": page.canonical_url,
        "h1": page.h1,
        "headings_json": page.headings_json,
        "main_content": page.main_content,
        "images_json": page.images_json,
        "links_json": page.links_json,
        "og_json": page.og_json,
        "twitter_json": page.twitter_json,
        "structured_data_json": page.structured_data_json,
        "robots_meta": page.robots_meta,
        "language": page.language,
        "analyzed_at": page.analyzed_at.isoformat() if page.analyzed_at else None,
    }


def _restore_page_snapshot(page_id: int, snapshot: Dict, crawl_id: int) -> None:
    """Restore a page's analysis state from a saved snapshot."""
    sess = new_session()
    try:
        page = sess.get(Page, page_id)
        if not page:
            return
        for key, value in snapshot.items():
            if key == "page_id":
                continue
            if hasattr(page, key):
                setattr(page, key, value)
        sess.add(page)
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def _compute_valid_pages_average(website_id: int, crawl_id: int) -> tuple:
    """Compute average score across valid HTML pages only.
    
    Returns (average, valid_count, total_count).
    """
    sess = new_session()
    try:
        all_pages = sess.query(Page).filter_by(
            website_id=website_id, crawl_id=crawl_id
        ).all()
    finally:
        sess.close()

    valid_scores = []
    for p in all_pages:
        if p.seo_score is None or p.seo_score <= 0:
            continue
        path = (p.server_file or p.url or "").lower()
        if any(path.endswith(ext) for ext in _NON_HTML_EXTENSIONS):
            continue
        if path in _NON_HTML_PATHS:
            continue
        if p.content_type and "html" not in (p.content_type or "").lower():
            continue
        valid_scores.append(p.seo_score)

    if not valid_scores:
        return 0.0, 0, len(all_pages)
    return round(sum(valid_scores) / len(valid_scores), 1), len(valid_scores), len(all_pages)


def _page_already_optimized(website_id: int, page_id: int, change_type: str, optimization_id: int) -> bool:
    """Check if this page/change_type combo was already attempted in this optimization run."""
    sess = new_session()
    try:
        existing = sess.query(PageOptimization).filter_by(
            optimization_id=optimization_id,
            page_id=page_id,
        ).filter(
            PageOptimization.changes_applied.contains([{"type": change_type}])
        ).first()
        return existing is not None
    finally:
        sess.close()


def _optimize_single_page(
    website_id: int,
    page: Page,
    issues: List[Dict],
    keyword_strategy: Dict,
    mode: str,
    job_id: str,
    optimization_run_id: str,
    optimization_id: int,
    real_trend_available: bool,
    website_root_path: str = "",
) -> Dict:
    """Optimize a single page and return results."""
    url = page.url
    server_file = page.server_file or url

    # Always resolve server_file via url_mapper for accurate FTP paths
    mapping = best_mapping(url, website_root_path or "")
    if mapping and mapping.get("best"):
        server_file = mapping["best"]["file"]
    elif not server_file or server_file.startswith("http") or server_file == url:
        server_file = urlparse(url).path.lstrip("/") or "index.html"

    emit = lambda event_type, message, severity="info", url="", metadata=None, agent_name="": (
        get_event_manager().emit(
            job_id=job_id, event_type=event_type, message=message,
            severity=severity, url=url, metadata=metadata or {},
            website_id=website_id, agent_name=agent_name or "Optimization Engine",
        ) if job_id else None
    )

    # 1. Fetch current HTML
    fetched = _fetch_page_html(url)
    if not fetched:
        emit("page_optimize_skipped", f"Could not fetch {url}", severity="warning", url=url,
             metadata={"reason": "fetch_failed"})
        return {
            "page_id": page.id, "page_url": url, "original_score": page.seo_score,
            "optimized_score": page.seo_score, "status": "skipped",
            "changes_applied": [], "change_reasons": [], "reason": "fetch_failed",
        }

    current_html, status_code, content_type = fetched

    # 1a. Validate it's actually HTML
    if not _is_valid_html_page(url, current_html, status_code):
        emit("page_optimize_skipped", f"Skipped non-HTML resource: {url}", severity="warning", url=url,
             metadata={"reason": "non_html", "content_type": content_type})
        return {
            "page_id": page.id, "page_url": url, "original_score": page.seo_score,
            "optimized_score": page.seo_score, "status": "skipped",
            "changes_applied": [], "change_reasons": [], "reason": "non_html",
        }

    # 2. Analyze current state
    analyzed = analyze_html(current_html, base_url=url)
    original_score = calculate_seo_score(analyzed)

    # 2a. Validate analysis is meaningful before proceeding
    prev_score = page.seo_score or 0
    prev_word_count = page.word_count or 0
    new_word_count = analyzed.get("word_count", 0)
    new_main_content = (analyzed.get("main_content", "") or "").strip()
    
    analysis_is_valid = (
        original_score is not None
        and original_score > 0
        and new_word_count > 0
        and len(new_main_content) > 0
    )
    
    if not analysis_is_valid and prev_score > 0:
        emit("page_optimize_skipped",
             f"Analysis returned invalid data (score={original_score}, words={new_word_count}) for {url}. Preserving previous score {prev_score}.",
             severity="warning", url=url,
             metadata={"reason": "invalid_analysis", "original_score": original_score,
                       "new_word_count": new_word_count, "prev_score": prev_score})
        return {
            "page_id": page.id, "page_url": url, "original_score": prev_score,
            "optimized_score": prev_score, "status": "skipped",
            "changes_applied": [], "change_reasons": [], "reason": "invalid_analysis",
        }

    # 2b. Save original snapshot before any changes
    original_snapshot = _snapshot_page(page)

    # 3. Generate optimization plan
    page_keywords = []
    primary = keyword_strategy.get("primary_keyword", "")
    secondary = keyword_strategy.get("secondary_keywords", [])
    if primary:
        page_keywords.append(primary)
    page_keywords.extend(secondary[:3])

    plan = plan_for_page(
        {
            "url": url,
            "topic": page.title or page.h1 or url,
            "title": page.title,
            "meta_description": page.meta_description,
            "canonical": page.canonical_url,
            "open_graph": page.og_json,
            "structured_data": page.structured_data_json,
            "keywords": page_keywords,
            "keyword_strategy": keyword_strategy,
            "content_gaps": keyword_strategy.get("content_gaps", []),
        },
        issues,
    )

    # 4. Filter actions by risk/mode and deduplicate
    safe_actions = []
    seen_change_types = set()
    for action in plan.get("actions", []):
        risk = action.get("risk", "medium")
        if not can_auto_implement({"risk": risk}, mode, risk):
            continue
        change_type = action.get("type", "meta_description")
        if change_type in seen_change_types:
            continue
        if _page_already_optimized(website_id, page.id, change_type, optimization_id):
            continue
        seen_change_types.add(change_type)
        safe_actions.append(action)

    if not safe_actions:
        emit("page_optimize_skipped", f"No safe actions for {url}", severity="info", url=url,
             metadata={"reason": "no_safe_actions"})
        return {
            "page_id": page.id, "page_url": url, "original_score": original_score,
            "optimized_score": original_score, "status": "skipped",
            "changes_applied": [], "change_reasons": [], "reason": "no_safe_actions",
        }

    # 5. Apply changes locally
    changes_payload = []
    change_reasons = []
    for a in safe_actions:
        changes_payload.append({
            "type": a.get("type", "meta_description"),
            "value": a.get("value", ""),
            "match": "",
            "reason": a.get("reason", ""),
            "risk": a.get("risk", "low"),
            "confidence": a.get("confidence", 0.7),
            "implementation_method": a.get("implementation_method", "html_meta_update"),
            "optimization_run_id": optimization_run_id,
        })
        change_reasons.append(a.get("reason", ""))

    new_html, applied_log = apply_changes(current_html, changes_payload)

    # 6. Re-analyze modified HTML locally
    modified_analyzed = analyze_html(new_html, base_url=url)
    proposed_score = calculate_seo_score(modified_analyzed)

    # 7. Only proceed if local score improved
    if proposed_score < original_score:
        emit("page_optimize_skipped",
             f"Proposed change would drop score {original_score} -> {proposed_score} for {url}",
             severity="warning", url=url,
             metadata={"original_score": original_score, "proposed_score": proposed_score})
        return {
            "page_id": page.id, "page_url": url, "original_score": original_score,
            "optimized_score": original_score, "status": "skipped",
            "changes_applied": [], "change_reasons": [], "reason": "score_regression",
            "proposed_score": proposed_score,
        }

    # 7a. Check deployment strategy
    website_sess = new_session()
    try:
        website_obj = website_sess.get(Website, website_id)
        if website_obj:
            if website_obj.deployment_strategy == "recommendation_only":
                emit("page_optimize_skipped",
                     f"Skipping deployment for {url}: deployment strategy is recommendation_only",
                     severity="warning", url=url,
                     metadata={"reason": "recommendation_only", "strategy": website_obj.deployment_strategy})
                return {
                    "page_id": page.id, "page_url": url, "original_score": original_score,
                    "optimized_score": original_score, "status": "skipped",
                    "changes_applied": [], "change_reasons": [], "reason": "recommendation_only",
                    "deploy_result": {"deployment_strategy": website_obj.deployment_strategy},
                }
            if website_obj.connection_type in ("ftp", "sftp") and website_obj.architecture_type not in ("static_html", None, ""):
                # Do NOT automatically skip SPA deployment.
                # Inspect FTP server to determine actual deployable target.
                from ..connections.connection_manager import (
                    build_connection_from_ids, FTPConnection, SFTPConnection
                )
                conn = sess.query(Connection).filter_by(website_id=website_id).first()
                if conn:
                    conn_obj = build_connection_from_ids(
                        website_id=website_id,
                        root_url=website_obj.root_url,
                        connection_type=website_obj.connection_type,
                        website_root_path=website_obj.website_root_path,
                        connection_host=conn.host,
                        connection_port=conn.port or 21,
                        connection_username=conn.username,
                        connection_password=conn.password_encrypted or "",
                        connection_private_key=conn.private_key_encrypted or "",
                    )
                    target = _resolve_spa_deployment_target(website_id, url, changes_payload, conn_obj)
                    if target and target.get("strategy") in ("spa_index_html", "static_html", "non_html_file"):
                        server_file = target["server_file"]
                        emit("deployment_strategy_resolved",
                             f"SPA deployment strategy: {target['strategy']} for {url}",
                             severity="info", url=url,
                             metadata={"strategy": target["strategy"],
                                       "server_file": server_file,
                                       "reason": target.get("reason", ""),
                                       "ftp_files": target.get("ftp_files_inspected", [])})
                        # Continue to deployment with resolved server_file
                    else:
                        reason = target.get("reason", "No deployable target found") if target else "Could not inspect FTP server"
                        emit("page_optimize_skipped",
                             f"Skipping deployment for {url}: {reason}",
                             severity="warning", url=url,
                             metadata={"reason": "deployment_not_supported",
                                       "architecture": website_obj.architecture_type,
                                       "details": reason,
                                       "ftp_files_inspected": target.get("ftp_files_inspected", []) if target else []})
                        log_audit("system", "page_optimize_skipped", "", {
                            "website_id": website_id,
                            "page_id": page.id,
                            "page_url": url,
                            "reason": "deployment_not_supported",
                            "architecture": website_obj.architecture_type,
                            "details": reason,
                        })
                        return {
                            "page_id": page.id, "page_url": url, "original_score": original_score,
                            "optimized_score": original_score, "status": "skipped",
                            "changes_applied": [], "change_reasons": [], "reason": "deployment_not_supported",
                            "deploy_result": {"architecture": website_obj.architecture_type,
                                              "deployment_strategy": website_obj.deployment_strategy,
                                              "details": reason},
                        }
                else:
                    emit("page_optimize_skipped",
                         f"Skipping deployment for {url}: no FTP connection configured.",
                         severity="warning", url=url,
                         metadata={"reason": "no_ftp_connection"})
                    return {
                        "page_id": page.id, "page_url": url, "original_score": original_score,
                        "optimized_score": original_score, "status": "skipped",
                        "changes_applied": [], "change_reasons": [], "reason": "no_ftp_connection",
                        "deploy_result": {"architecture": website_obj.architecture_type,
                                          "deployment_strategy": website_obj.deployment_strategy},
                    }
    finally:
        website_sess.close()

    # 8. Deploy the change (deployer handles preflight, upload, and verification)
    try:
        emit("deploy_started", f"Deploying {len(changes_payload)} change(s) for {url}",
             url=url, metadata={"server_file": server_file, "changes": len(changes_payload)})
        result = deploy_change(
            website_id,
            server_file,
            current_html.encode("utf-8"),
            changes_payload,
            page_url=url,
        )
        if not result.get("ok"):
            error_type = result.get("error_type", "unknown")
            error_msg = result.get("message", "Deploy failed")
            emit("page_optimize_failed",
                 f"Deploy failed for {url}: {error_type} - {error_msg}",
                 severity="error", url=url,
                 metadata={"error_type": error_type, "error_detail": result.get("error_detail", {})})
            log_audit("system", "page_optimize_failed", result.get("change_id", ""), {
                "website_id": website_id,
                "page_id": page.id,
                "page_url": url,
                "error_type": error_type,
                "error_msg": error_msg,
                "original_score": original_score,
            })
            return {
                "page_id": page.id, "page_url": url, "original_score": original_score,
                "optimized_score": original_score, "status": "failed",
                "changes_applied": [], "change_reasons": [], "reason": f"deploy_{error_type}",
                "deploy_result": result,
            }

        emit("deploy_completed", f"Deployment succeeded for {url}",
             url=url, metadata={"change_id": result.get("change_id"), "status": result.get("status")})

        # 9. Re-fetch the deployed page and re-analyze (verification step)
        verified_html = _fetch_page_html(url)
        verified_score = original_score
        meta_verified = True
        meta_error = None
        if verified_html:
            verified_analyzed = analyze_html(verified_html[0], base_url=url)
            verified_score = calculate_seo_score(verified_analyzed)
            
            # Verify meta description was actually deployed for meta_description changes
            if any(c.get("type") == "meta_description" for c in changes_payload):
                from bs4 import BeautifulSoup
                try:
                    deployed_soup = BeautifulSoup(verified_html[0], "html.parser")
                    expected_desc = next((c.get("value") for c in changes_payload if c.get("type") == "meta_description"), "")
                    if expected_desc:
                        actual_desc = ""
                        for meta in deployed_soup.find_all("meta"):
                            if meta.get("name", "").lower() == "description":
                                actual_desc = meta.get("content", "")
                                break
                        if actual_desc != expected_desc:
                            meta_verified = False
                            meta_error = f"Expected meta description '{expected_desc[:50]}...' but found '{actual_desc[:50]}...'"
                except Exception as e:
                    meta_verified = False
                    meta_error = f"Meta description verification failed: {e}"

        # 10. Only keep if verified score > original score
        if verified_score <= original_score or not meta_verified:
            # Rollback: restore original content
            reason = "verified_score_not_improved" if verified_score <= original_score else "meta_verification_failed"
            try:
                rollback_result = rollback_change(result.get("seo_change_id"))
                emit("page_optimize_rolled_back",
                     f"Rolled back {url}: {reason}",
                     severity="warning", url=url,
                     metadata={"original_score": original_score,
                               "verified_score": verified_score,
                               "meta_verified": meta_verified,
                               "meta_error": meta_error,
                               "rollback": rollback_result})
                log_audit("system", "page_optimize_rolled_back", result.get("change_id", ""), {
                    "website_id": website_id,
                    "page_id": page.id,
                    "page_url": url,
                    "reason": reason,
                    "original_score": original_score,
                    "verified_score": verified_score,
                    "meta_verified": meta_verified,
                    "meta_error": meta_error,
                    "rollback": rollback_result,
                })
            except Exception as rb_exc:
                emit("page_optimize_rollback_failed",
                     f"Rollback failed for {url}: {rb_exc}",
                     severity="error", url=url)

            # Restore original page analysis from snapshot
            _restore_page_snapshot(page.id, original_snapshot, page.crawl_id)

            return {
                "page_id": page.id, "page_url": url,
                "original_score": prev_score, "optimized_score": prev_score,
                "status": "rolled_back",
                "changes_applied": [], "change_reasons": [], "reason": reason,
                "proposed_score": proposed_score, "verified_score": verified_score,
                "meta_verified": meta_verified, "meta_error": meta_error,
            }

        # 11. Success: update page with verified analysis
        if verified_html:
            _update_page_analysis(page.id, verified_analyzed, verified_score, page.crawl_id)
        else:
            _update_page_analysis(page.id, modified_analyzed, proposed_score, page.crawl_id)

        emit("page_optimize_improved",
             f"SEO score improved from {original_score} to {verified_score} for {url}",
             severity="success", url=url,
             metadata={
                 "original_score": original_score,
                 "proposed_score": proposed_score,
                 "verified_score": verified_score,
                 "changes_count": len(changes_payload),
             })
        log_audit("system", "page_optimize_improved", result.get("change_id", ""), {
            "website_id": website_id,
            "page_id": page.id,
            "page_url": url,
            "original_score": original_score,
            "proposed_score": proposed_score,
            "verified_score": verified_score,
            "changes_count": len(changes_payload),
        })

        return {
            "page_id": page.id, "page_url": url,
            "original_score": original_score, "optimized_score": verified_score,
            "status": "improved",
            "changes_applied": changes_payload,
            "change_reasons": change_reasons,
            "reason": "score_improved",
            "proposed_score": proposed_score,
            "verified_score": verified_score,
        }

    except Exception as e:
        emit("page_optimize_failed",
             f"Exception optimizing {url}: {e}",
             severity="error", url=url)
        log_audit("system", "page_optimize_exception", "", {
            "website_id": website_id,
            "page_id": page.id,
            "page_url": url,
            "error": str(e),
        })
        # Restore original snapshot on unexpected exception
        try:
            _restore_page_snapshot(page.id, original_snapshot, page.crawl_id)
        except Exception:
            pass
        return {
            "page_id": page.id, "page_url": url, "original_score": prev_score,
            "optimized_score": prev_score, "status": "failed",
            "changes_applied": [], "change_reasons": [], "reason": str(e),
        }


def run_seo_optimization(
    website_id: int,
    crawl_id: int,
    target_score: float = 95.0,
    max_iterations: int = 3,
    min_page_score: float = 0.0,
    on_progress=None,
    **kwargs,
) -> Dict:
    """Run automatic SEO optimization for a website.

    Iterates over lowest-scoring pages, applies safe optimizations,
    verifies score improvement, and stops when target is reached.
    """
    event_manager = get_event_manager()
    job_id = kwargs.get("job_id")
    mode = Config.SEO_AUTOMATION_MODE
    optimization_run_id = f"OPT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{website_id}"

    def emit(event_type, message, severity="info", url="", metadata=None, agent_name=""):
        if job_id:
            event_manager.emit(
                job_id=job_id, event_type=event_type, message=message,
                severity=severity, url=url, metadata=metadata or {},
                website_id=website_id, agent_name=agent_name or "Optimization Engine",
            )

    def _update_progress(progress: int, message: str = ""):
        if job_id:
            from ..tasks.jobs import _record_progress
            _record_progress(job_id, progress, message)

    # ── Read website and crawl metadata (short session) ─────────────────
    sess = SessionLocal()
    try:
        website: Website = sess.get(Website, website_id)
        if not website:
            raise ValueError("Website not found")
        crawl: Optional[Crawl] = sess.get(Crawl, crawl_id) if crawl_id else None
    finally:
        sess.close()
        SessionLocal.remove()

    root_url = website.root_url
    website_name = website.name
    website_root_path = website.website_root_path or ""

    # Compute initial valid average
    initial_avg, valid_count, total_count = _compute_valid_pages_average(website_id, crawl_id)
    current_avg = initial_avg

    emit("optimization_started",
         f"Average SEO score is {current_avg}. Starting optimization.",
         metadata={
             "target_score": target_score,
             "mode": mode,
             "valid_pages": valid_count,
             "total_pages": total_count,
         })
    log_audit("system", "optimization_started", optimization_run_id, {
        "website_id": website_id,
        "crawl_id": crawl_id,
        "initial_avg": current_avg,
        "target_score": target_score,
        "mode": mode,
        "valid_pages": valid_count,
        "total_pages": total_count,
    })

    # ── Load pages and issues (short sessions) ──────────────────────────
    sess = SessionLocal()
    try:
        pages = sess.query(Page).filter_by(website_id=website_id, crawl_id=crawl_id)\
            .order_by(Page.seo_score.asc()).all()
        page_ids = [p.id for p in pages]
        issues_q = sess.query(SEOIssue).filter(
            SEOIssue.website_id == website_id,
            SEOIssue.resolved == False,
            SEOIssue.page_id.in_(page_ids) if page_ids else False,
        )
        all_issues = issues_q.all()
    finally:
        sess.close()
        SessionLocal.remove()

    issues_by_page: Dict[int, List[Dict]] = {}
    for iss in all_issues:
        pid = iss.page_id or 0
        issues_by_page.setdefault(pid, []).append({
            "issue_type": iss.issue_type,
            "severity": iss.severity,
            "title": iss.title,
            "description": iss.description,
            "current_value": iss.current_value,
            "proposed_value": iss.proposed_value,
            "implementation_method": iss.implementation_method,
            "risk": iss.risk,
            "confidence": iss.confidence,
        })

    # ── Create optimization tracking record ─────────────────────────────
    opt_id: int
    sess = new_session()
    try:
        opt = SEOOptimization(
            website_id=website_id,
            crawl_id=crawl_id,
            status="running",
            score_before=current_avg,
            target_score=target_score,
            pages_optimized=0,
            pages_remaining=len([p for p in pages if p.seo_score < target_score]),
            max_iterations=max_iterations,
            iteration=0,
            changes_applied=0,
        )
        sess.add(opt)
        sess.commit()
        sess.refresh(opt)
        opt_id = opt.id
    finally:
        sess.close()

    real_trend_available = _has_real_trend_provider(website_id)

    # ── Optimization loop ───────────────────────────────────────────────
    total_changes_applied = 0
    pages_optimized_count = 0
    pages_failed_count = 0
    pages_rolled_back_count = 0
    stop_reason = "target_reached"
    circuit_breaker_triggered = False
    all_iter_results: List[Dict] = []

    for iteration in range(max_iterations):
        _update_progress(10 + int(80 * iteration / max(1, max_iterations)),
                         f"Iteration {iteration + 1}/{max_iterations}")
        emit("optimization_iteration_started",
             f"Starting optimization iteration {iteration + 1}",
             metadata={"iteration": iteration + 1, "max_iterations": max_iterations})

        # Refresh pages from DB to pick up updated scores from previous iterations
        sess = new_session()
        try:
            pages = sess.query(Page).filter_by(website_id=website_id, crawl_id=crawl_id)\
                .order_by(Page.seo_score.asc()).all()
        finally:
            sess.close()

        pages_optimized_this_iter = 0
        pages_failed_this_iter = 0
        pages_rolled_back_this_iter = 0
        iter_results: List[Dict] = []

        for page in pages:
            if page.seo_score is None or page.seo_score >= target_score:
                continue

            # Skip non-HTML pages
            path = (page.server_file or page.url or "").lower()
            if any(path.endswith(ext) for ext in _NON_HTML_EXTENSIONS):
                continue
            if path in _NON_HTML_PATHS:
                continue
            if page.content_type and "html" not in (page.content_type or "").lower():
                continue

            page_issues = issues_by_page.get(page.id, [])
            keyword_strategy = _get_keyword_strategy(website_id, page.url)

            # Research keywords if real provider is available
            if real_trend_available:
                trend_provider = get_trend_provider()
                try:
                    trends = trend_provider.trends([page.title or page.h1 or ""])
                    if trends:
                        emit("keyword_research", f"Found trend data for {page.url}",
                             url=page.url, metadata={"trends": trends[:3]})
                except Exception:
                    pass

            result = _optimize_single_page(
                website_id=website_id,
                page=page,
                issues=page_issues,
                keyword_strategy=keyword_strategy,
                mode=mode,
                job_id=job_id,
                optimization_run_id=optimization_run_id,
                optimization_id=opt_id,
                real_trend_available=real_trend_available,
                website_root_path=website_root_path,
            )

            iter_results.append(result)
            if result.get("status") == "improved":
                pages_optimized_this_iter += 1
                total_changes_applied += len(result.get("changes_applied", []))
            elif result.get("status") == "failed":
                pages_failed_this_iter += 1
                pages_failed_count += 1
            elif result.get("status") == "rolled_back":
                pages_rolled_back_this_iter += 1
                pages_rolled_back_count += 1

        # ── Recalculate average score (valid HTML pages only) ───────────
        new_avg, valid_count, total_count = _compute_valid_pages_average(website_id, crawl_id)

        pages_optimized_count += pages_optimized_this_iter

        # ── Circuit breaker: stop if average dropped significantly ──────
        if new_avg < current_avg:
            emit("circuit_breaker_triggered",
                 f"Average SEO score dropped from {current_avg} to {new_avg}. Stopping optimization.",
                 severity="error",
                 metadata={"previous_avg": current_avg, "new_avg": new_avg})
            log_audit("system", "circuit_breaker_triggered", optimization_run_id, {
                "website_id": website_id,
                "iteration": iteration + 1,
                "previous_avg": current_avg,
                "new_avg": new_avg,
                "stop_reason": "circuit_breaker",
            })
            stop_reason = "circuit_breaker"
            circuit_breaker_triggered = True

            # Try to rollback the last successful change if any
            last_deployed = None
            sess = new_session()
            try:
                last_deployed = sess.query(SEOChange).filter_by(website_id=website_id)\
                    .order_by(SEOChange.created_at.desc()).first()
            finally:
                sess.close()

            if last_deployed and last_deployed.backup_id:
                try:
                    rollback_change(last_deployed.id)
                    emit("circuit_breaker_rollback",
                         f"Rolled back last change due to score drop.",
                         severity="warning")
                    log_audit("system", "circuit_breaker_rollback", optimization_run_id, {
                        "website_id": website_id,
                        "seo_change_id": last_deployed.id,
                        "iteration": iteration + 1,
                    })
                except Exception:
                    pass
            break

        # ── Persist iteration results ──────────────────────────────────
        sess = new_session()
        try:
            opt = sess.get(SEOOptimization, opt_id)
            opt.iteration = iteration + 1
            opt.score_after = new_avg
            opt.pages_optimized = pages_optimized_count
            opt.pages_remaining = max(0, len([p for p in pages
                                              if p.seo_score is not None and p.seo_score < target_score]))
            opt.changes_applied = total_changes_applied
            sess.add(opt)

            for pr in iter_results:
                po = PageOptimization(
                    optimization_id=opt_id,
                    page_id=pr.get("page_id"),
                    page_url=pr.get("page_url", ""),
                    original_score=pr.get("original_score", 0.0),
                    optimized_score=pr.get("optimized_score", 0.0),
                    status=pr.get("status", "pending"),
                    issues_detected=[{"issue_type": i.get("issue_type"), "severity": i.get("severity")}
                                     for i in issues_by_page.get(pr.get("page_id") or 0, [])],
                    changes_proposed=pr.get("changes_applied", []),
                    changes_applied=pr.get("changes_applied", []),
                    change_reasons=pr.get("change_reasons", []),
                    expected_benefit={"score_delta": pr.get("optimized_score", 0) - pr.get("original_score", 0)},
                    failure_details=pr.get("deploy_result", {}).get("error_detail", {}) if pr.get("deploy_result") else {},
                    deploy_result=pr.get("deploy_result", {}),
                    optimization_timestamp=datetime.utcnow(),
                )
                sess.add(po)

            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

        current_avg = new_avg
        all_iter_results.extend(iter_results)

        emit("optimization_iteration_completed",
             f"Iteration {iteration + 1} complete. Average score: {new_avg}",
             metadata={"iteration": iteration + 1, "avg_score": new_avg})
        log_audit("system", "optimization_iteration_completed", optimization_run_id, {
            "website_id": website_id,
            "iteration": iteration + 1,
            "avg_score": new_avg,
            "pages_optimized_this_iter": pages_optimized_this_iter,
            "pages_failed_this_iter": pages_failed_this_iter,
            "pages_rolled_back_this_iter": pages_rolled_back_this_iter,
        })

        # ── Stop conditions ─────────────────────────────────────────────
        if new_avg >= target_score:
            stop_reason = "target_reached"
            break
        if pages_optimized_this_iter == 0 and not circuit_breaker_triggered:
            stop_reason = "no_improvements"
            break
        if iteration >= max_iterations - 1:
            stop_reason = "max_iterations_reached"
            break

    # ── Finalize ────────────────────────────────────────────────────────
    final_avg, _, _ = _compute_valid_pages_average(website_id, crawl_id)
    
    # Compute final status from actual all_iter_results to avoid counter bugs
    total_attempted = len(all_iter_results)
    total_improved = sum(1 for r in all_iter_results if r.get("status") == "improved")
    total_failed = sum(1 for r in all_iter_results if r.get("status") == "failed")
    total_rolled_back = sum(1 for r in all_iter_results if r.get("status") == "rolled_back")
    total_skipped = sum(1 for r in all_iter_results if r.get("status") == "skipped")
    
    if circuit_breaker_triggered:
        final_status = "rolled_back"
    elif total_attempted > 0 and total_improved == 0 and total_failed > 0:
        final_status = "failed"
    elif total_improved > 0 and (total_failed > 0 or total_rolled_back > 0):
        final_status = "completed_with_failures"
    elif total_improved > 0 and total_failed == 0 and total_rolled_back == 0:
        final_status = "completed"
    elif total_attempted > 0 and total_failed > 0:
        final_status = "failed"
    elif total_skipped > 0 and total_improved == 0 and total_failed == 0:
        final_status = "completed_no_changes_deployed"
    else:
        final_status = "completed"
    
    # Do NOT update website health score if nothing improved and score would drop
    if final_status in ("failed", "rolled_back") and final_avg < current_avg:
        final_avg = current_avg

    sess = new_session()
    try:
        opt = sess.get(SEOOptimization, opt_id)
        opt.status = final_status
        opt.finished_at = datetime.utcnow()
        opt.score_after = final_avg
        sess.add(opt)
        sess.commit()
    finally:
        sess.close()

    # Update website health score
    sess = new_session()
    try:
        sess.query(Website).filter_by(id=website_id).update(
            {"seo_health_score": final_avg, "last_analyzed": datetime.utcnow()},
            synchronize_session=False,
        )
        sess.commit()
    finally:
        sess.close()

    emit("optimization_completed",
         f"Website average SEO score: {current_avg} -> {final_avg}.",
         severity="success" if final_status == "completed" else "warning",
         metadata={
             "score_before": current_avg,
             "score_after": final_avg,
             "target_score": target_score,
             "pages_optimized": total_improved,
             "pages_failed": total_failed,
             "pages_rolled_back": total_rolled_back,
             "pages_skipped": total_skipped,
             "changes_applied": total_changes_applied,
             "changes_attempted": total_attempted,
             "changes_failed": total_failed,
             "changes_rolled_back": total_rolled_back,
             "stop_reason": stop_reason,
             "iterations": iteration + 1,
             "status": final_status,
         })
    log_audit("system", "optimization_completed", optimization_run_id, {
        "website_id": website_id,
        "crawl_id": crawl_id,
        "optimization_id": opt_id,
        "score_before": current_avg,
        "score_after": final_avg,
        "target_score": target_score,
        "pages_optimized": total_improved,
        "pages_failed": total_failed,
        "pages_rolled_back": total_rolled_back,
        "pages_skipped": total_skipped,
        "changes_applied": total_changes_applied,
        "changes_attempted": total_attempted,
        "changes_failed": total_failed,
        "changes_rolled_back": total_rolled_back,
        "stop_reason": stop_reason,
        "iterations": iteration + 1,
        "status": final_status,
    })

    if on_progress:
        on_progress(100, "Optimization complete")

    return {
        "ok": final_status in ("completed", "completed_with_failures"),
        "website_id": website_id,
        "crawl_id": crawl_id,
        "optimization_id": opt_id,
        "score_before": current_avg,
        "score_after": final_avg,
        "target_score": target_score,
        "pages_optimized": total_improved,
        "pages_failed": total_failed,
        "pages_rolled_back": total_rolled_back,
        "pages_skipped": total_skipped,
        "changes_attempted": total_attempted,
        "changes_applied": total_changes_applied,
        "changes_failed": total_failed,
        "changes_rolled_back": total_rolled_back,
        "stop_reason": stop_reason,
        "iterations": iteration + 1,
        "status": final_status,
    }
