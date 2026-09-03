"""Flask application factory and routes.

All HTML is rendered server-side via Jinja2 — no JS framework required.
A minimal vanilla-JS snippet (only for small UX enhancements) is generated
inline by Python, never written by hand.
"""
from __future__ import annotations
import os
import json
import queue
import threading
from pathlib import Path
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    jsonify, abort, Response, stream_with_context,
)

from .config import Config
from .database.database import init_db, get_session, close_session, log_audit
from .database.models import (
    Website, Connection, Page, SEOIssue, Keyword, OptimizationPlan,
    SEOChange, Backup, Deployment, PerformanceSnapshot, BackgroundJob,
    AuditLog, ProviderConfiguration, Crawl, ProcessEvent,
    SEOOptimization, PageOptimization,
)
from .security.encryption import encrypt, decrypt, mask
from .agents.orchestrator import run_full_analysis
from .agents.planner_agent import plan_for_page
from .agents.risk import classify_risk, can_auto_implement, deployment_method
from .agents.optimizer import run_seo_optimization
from .connections.connection_manager import (
    build_connection_from_website, build_connection_from_ids, FTPConnection, SFTPConnection,
    SSHConnection, PublicUrlAccess,
)
from .deployment import deploy_change, rollback_change
from .tasks import enqueue, get_job, list_jobs, control_job
from .seo.sitemap import discover_sitemaps, fetch_sitemap, parse_sitemap, generate_sitemap, validate_sitemap
from .seo.robots import fetch_robots, parse_robots, analyze_robots
from .events import get_event_manager


ACTIVE_JOB_STATUSES = ("running", "queued", "paused")


def create_app() -> Flask:
    app = Flask(__name__, template_folder="frontend/templates",
                static_folder="frontend/static")
    app.config.from_object(Config)
    app.config["SECRET_KEY"] = Config.SECRET_KEY
    app.jinja_env.add_extension("jinja2.ext.do")

    init_db()

    app.teardown_appcontext(close_session)

    register_routes(app)
    register_filters(app)

    if app.config.get("DEBUG") or os.environ.get("APP_DEBUG", "1") == "1":
        routes = []
        for rule in app.url_map.iter_rules():
            if rule.endpoint != "static":
                routes.append(f"  {','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'})):<10} {rule.rule}")
        print("\n[route-registry] Registered routes:")
        for r in sorted(routes):
            print(r)
        print(f"[route-registry] Total: {len(routes)} routes\n")

    def _ai_startup_check():
        manager = None
        try:
            import logging
            logger = logging.getLogger(__name__)
            from app.ai.model_manager import get_model_manager
            manager = get_model_manager()
            manager._emit("ai_system_check_start", "AI system check started")
            manager.start_background_initialization()
        except Exception as e:
            import traceback
            logger.error("AI startup check failed: %s", traceback.format_exc_exc())
            if manager:
                manager._emit("ai_system_failed", f"AI startup check failed: {e}", severity="error")

    threading.Thread(target=_ai_startup_check, daemon=True).start()

    return app


def register_filters(app):
    @app.template_filter("dt")
    def _dt(value):
        if not value:
            return ""
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                return value
        return value.strftime("%Y-%m-%d %H:%M")

    @app.template_filter("pct")
    def _pct(value):
        try:
            return f"{float(value):.1f}"
        except Exception:
            return "0.0"

    @app.template_filter("truncate_words")
    def _tw(value, n=20):
        if not value:
            return ""
        words = value.split()
        return " ".join(words[:n]) + ("…" if len(words) > n else "")

    @app.template_filter("risk_badge")
    def _rb(value):
        v = (value or "").lower()
        return {
            "low": "badge-low",
            "medium": "badge-medium",
            "high": "badge-high",
            "critical": "badge-critical",
        }.get(v, "badge-medium")

    @app.template_filter("severity_badge")
    def _sb(value):
        return _rb(value)


def register_routes(app: Flask):
    @app.route("/")
    def dashboard():
        sess = get_session()
        try:
            websites = sess.query(Website).order_by(Website.created_at.desc()).all()
            total_pages = sess.query(Page).count()
            total_issues = sess.query(SEOIssue).filter_by(resolved=False).count()
            critical = sess.query(SEOIssue).filter_by(severity="critical", resolved=False).count()
            recent_changes = sess.query(SEOChange).order_by(SEOChange.created_at.desc()).limit(10).all()
            jobs = sess.query(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(8).all()
            avg_score = 0.0
            if websites:
                scores = [w.seo_health_score or 0 for w in websites]
                avg_score = round(sum(scores) / len(scores), 1) if scores else 0

            latest_opts = {}
            for w in websites:
                opt = sess.query(SEOOptimization).filter_by(website_id=w.id)\
                    .order_by(SEOOptimization.created_at.desc()).first()
                latest_opts[w.id] = opt

            stats = {
                "websites": len(websites),
                "pages": total_pages,
                "issues": total_issues,
                "critical": critical,
                "avg_score": avg_score,
                "deployed_changes": sess.query(SEOChange).filter_by(status="deployed").count(),
                "pending": sess.query(SEOChange).filter(SEOChange.status.in_(["proposed", "approved"])).count(),
            }
            return render_template("dashboard.html", stats=stats, websites=websites,
                                   recent_changes=recent_changes, jobs=jobs, latest_opts=latest_opts)
        finally:
            pass

    @app.route("/connect", methods=["GET", "POST"])
    def connect_website():
        if request.method == "POST":
            sess = get_session()
            name = request.form.get("name", "").strip() or "Untitled Site"
            root_url = request.form.get("root_url", "").strip()
            ctype = request.form.get("connection_type", "public_url")
            host = request.form.get("host", "").strip()
            port = request.form.get("port") or None
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            private_key = request.form.get("private_key", "")
            web_root = request.form.get("web_root", "").strip() or ""

            if not root_url:
                flash("Root URL is required", "error")
                return redirect(url_for("connect_website"))

            website = Website(
                name=name, root_url=root_url, connection_type=ctype,
                website_root_path=web_root, technology="unknown",
            )
            sess.add(website)
            sess.flush()

            if ctype in ("ftp", "sftp", "ssh"):
                conn = Connection(
                    website_id=website.id,
                    host=host, port=int(port) if port else None,
                    username=username,
                    password_encrypted=encrypt(password) if password else "",
                    private_key_encrypted=encrypt(private_key) if private_key else "",
                )
                sess.add(conn)
            sess.commit()
            log_audit("user", "website_created", name,
                      {"website_id": website.id, "root_url": root_url,
                       "connection_type": ctype})
            flash(f"Website '{name}' added.", "success")
            return redirect(url_for("website_detail", website_id=website.id))
        return render_template("connect.html")

    @app.route("/website/<int:website_id>")
    def website_detail(website_id):
        sess = get_session()
        website = sess.get(Website, website_id) or abort(404)

        latest_crawl = sess.query(Crawl).filter_by(website_id=website_id)\
            .order_by(Crawl.started_at.desc()).first()
        crawl_id = latest_crawl.id if latest_crawl else None

        pages = sess.query(Page).filter_by(website_id=website_id, crawl_id=crawl_id)\
            .order_by(Page.seo_score.asc()).limit(500).all()

        page_ids = [p.id for p in pages]
        issues = sess.query(SEOIssue).filter(
            SEOIssue.website_id == website_id,
            SEOIssue.resolved == False,
            SEOIssue.page_id.in_(page_ids) if page_ids else False,
        ).limit(100).all() if page_ids else []

        plans = sess.query(OptimizationPlan).filter_by(website_id=website_id)\
            .order_by(OptimizationPlan.created_at.desc()).all()
        changes = sess.query(SEOChange).filter_by(website_id=website_id)\
            .order_by(SEOChange.created_at.desc()).limit(20).all()
        jobs = [j for j in list_jobs(website_id=website_id) if j["website_id"] == website_id]
        return render_template("website_detail.html", website=website, pages=pages,
                               issues=issues, plans=plans, changes=changes, jobs=jobs)

    @app.route("/website/<int:website_id>/test-connection", methods=["POST"])
    def test_connection(website_id):
        sess = get_session()
        website = sess.get(Website, website_id) or abort(404)
        conn = sess.query(Connection).filter_by(website_id=website_id).first()
        conn_obj = build_connection_from_ids(
            website_id=website_id,
            root_url=website.root_url,
            connection_type=website.connection_type,
            website_root_path=website.website_root_path,
            connection_host=conn.host if conn else "",
            connection_port=conn.port if conn else 21,
            connection_username=conn.username if conn else "",
            connection_password=conn.password_encrypted if conn else "",
            connection_private_key=conn.private_key_encrypted if conn else "",
        )
        try:
            if isinstance(conn_obj, PublicUrlAccess):
                r = conn_obj.head(website.root_url)
                ok = r.get("status_code", 0) < 400
                msg = f"HTTP {r.get('status_code')} reachable" if ok else f"Error: {r.get('error', 'unreachable')}"
                capability = "analysis_only"
            elif isinstance(conn_obj, (FTPConnection, SFTPConnection)):
                res = conn_obj.connect()
                ok = res.ok
                msg = res.message
                capability = res.access_capability
            elif isinstance(conn_obj, SSHConnection):
                res = conn_obj.connect()
                ok = res.ok
                msg = res.message
                capability = res.access_capability
            else:
                ok, msg, capability = False, "Unknown connection type", "analysis_only"
        finally:
            try:
                conn_obj.close()
            except Exception:
                pass

        if conn:
            conn.last_status = "ok" if ok else "failed"
            conn.last_message = msg
            conn.last_tested = datetime.utcnow()
            sess.commit()
        return jsonify({"ok": ok, "message": msg, "capability": capability})

    @app.route("/website/<int:website_id>/crawl", methods=["POST"])
    def start_crawl(website_id):
        sess = get_session()
        if sess.get(Website, website_id) is None:
            abort(404)

        def task(**kwargs):
            return run_full_analysis(website_id, **kwargs)

        job_id = enqueue("full_analysis", website_id, task,
                         max_pages=Config.CRAWL_MAX_PAGES,
                         max_depth=Config.CRAWL_MAX_DEPTH)
        flash(f"Analysis queued as {job_id}", "info")
        return redirect(url_for("website_detail", website_id=website_id))

    @app.route("/website/<int:website_id>/optimize", methods=["POST"])
    def start_optimization(website_id):
        sess = get_session()
        website = sess.get(Website, website_id) or abort(404)

        latest_crawl = sess.query(Crawl).filter_by(website_id=website_id)\
            .order_by(Crawl.started_at.desc()).first()
        if not latest_crawl:
            flash("Run an analysis first before optimizing.", "error")
            return redirect(url_for("website_detail", website_id=website_id))

        target_score = float(request.form.get("target_score", 95.0))
        max_iterations = int(request.form.get("max_iterations", 3))

        def task(**kwargs):
            return run_seo_optimization(
                website_id=website_id,
                crawl_id=latest_crawl.id,
                target_score=target_score,
                max_iterations=max_iterations,
                **kwargs,
            )

        job_id = enqueue("seo_optimization", website_id, task)
        flash(f"SEO optimization queued as {job_id}", "info")
        return redirect(url_for("website_detail", website_id=website_id))

    @app.route("/website/<int:website_id>/optimization")
    def website_optimization(website_id):
        sess = get_session()
        website = sess.get(Website, website_id) or abort(404)

        optimizations = sess.query(SEOOptimization).filter_by(website_id=website_id)\
            .order_by(SEOOptimization.created_at.desc()).limit(10).all()

        page_opts = []
        if optimizations:
            latest_opt = optimizations[0]
            page_opts = sess.query(PageOptimization).filter_by(
                optimization_id=latest_opt.id
            ).order_by(PageOptimization.original_score.asc()).limit(50).all()

        return render_template("optimization.html", website=website,
                               optimizations=optimizations, page_opts=page_opts)

    @app.route("/api/website/<int:website_id>/optimization")
    def api_website_optimization(website_id):
        sess = get_session()
        website = sess.get(Website, website_id) or abort(404)

        latest_opt = sess.query(SEOOptimization).filter_by(website_id=website_id)\
            .order_by(SEOOptimization.created_at.desc()).first()

        if not latest_opt:
            return jsonify({
                "has_optimization": False,
                "avg_score": website.seo_health_score or 0,
                "target_score": 95.0,
                "status": "none",
            })

        page_opts = sess.query(PageOptimization).filter_by(
            optimization_id=latest_opt.id
        ).all()

        return jsonify({
            "has_optimization": True,
            "optimization_id": latest_opt.id,
            "status": latest_opt.status,
            "score_before": latest_opt.score_before,
            "score_after": latest_opt.score_after,
            "target_score": latest_opt.target_score,
            "pages_optimized": latest_opt.pages_optimized,
            "pages_remaining": latest_opt.pages_remaining,
            "changes_applied": latest_opt.changes_applied,
            "iteration": latest_opt.iteration,
            "max_iterations": latest_opt.max_iterations,
            "created_at": latest_opt.created_at.isoformat() if latest_opt.created_at else None,
            "finished_at": latest_opt.finished_at.isoformat() if latest_opt.finished_at else None,
            "pages": [
                {
                    "page_url": po.page_url,
                    "original_score": po.original_score,
                    "optimized_score": po.optimized_score,
                    "status": po.status,
                    "changes_count": len(po.changes_applied or []),
                }
                for po in page_opts
            ],
        })

    @app.route("/jobs/<job_id>")
    def job_status(job_id):
        job = get_job(job_id)
        if not job:
            abort(404)
        return render_template("job.html", job=job)

    @app.route("/api/jobs/<job_id>")
    def api_job_status(job_id):
        job = get_job(job_id)
        if not job:
            return jsonify({"error": "not found"}), 404
        return jsonify({
            "job_id": job["job_id"],
            "status": job["status"],
            "progress": job["progress"],
            "message": job["message"],
            "result": job["result_json"],
        })

    @app.route("/website/<int:website_id>/issues")
    def website_issues(website_id):
        sess = get_session()
        website = sess.get(Website, website_id) or abort(404)
        sev = request.args.get("severity")
        q = sess.query(SEOIssue).filter_by(website_id=website_id, resolved=False)
        if sev:
            q = q.filter_by(severity=sev)
        issues = q.order_by(SEOIssue.severity.desc()).all()
        return render_template("issues.html", website=website, issues=issues, current_sev=sev)

    @app.route("/website/<int:website_id>/keywords")
    def website_keywords(website_id):
        sess = get_session()
        website = sess.get(Website, website_id) or abort(404)

        keywords = sess.query(Keyword).filter_by(website_id=website_id).limit(500).all()

        latest_crawl = sess.query(Crawl).filter_by(website_id=website_id)\
            .order_by(Crawl.started_at.desc()).first()
        crawl_id = latest_crawl.id if latest_crawl else None

        pages = sess.query(Page).filter_by(website_id=website_id, crawl_id=crawl_id).all() if crawl_id else []

        plans = sess.query(OptimizationPlan).filter_by(website_id=website_id)\
            .order_by(OptimizationPlan.created_at.desc()).all()

        latest_plan = plans[0] if plans else None
        keyword_intelligence = {}
        if latest_plan and latest_plan.actions_json:
            keyword_intelligence = latest_plan.actions_json.get("keyword_intelligence", {})

        return render_template("keywords.html", website=website, keywords=keywords,
                               pages=pages, plans=plans, latest_plan=latest_plan,
                               keyword_intelligence=keyword_intelligence)

    @app.route("/api/website/<int:website_id>/keyword-intelligence")
    def api_keyword_intelligence(website_id):
        from app.keywords.engine import KeywordIntelligenceEngine
        sess = get_session()
        website = sess.get(Website, website_id) or abort(404)

        latest_crawl = sess.query(Crawl).filter_by(website_id=website_id)\
            .order_by(Crawl.started_at.desc()).first()
        if not latest_crawl:
            return jsonify({"error": "No crawl data found"}), 404

        pages = sess.query(Page).filter_by(website_id=website_id, crawl_id=latest_crawl.id).all()
        pages_data = []
        for p in pages:
            pages_data.append({
                "url": p.url,
                "title": p.title,
                "meta_description": p.meta_description,
                "main_content": p.main_content,
                "headings": p.headings_json or {},
                "word_count": p.word_count,
            })

        engine = KeywordIntelligenceEngine(
            website_id=website_id,
            website_url=website.root_url,
            business_description=website.business_description or "",
        )
        result = engine.run_full_analysis(pages_data)
        return jsonify(result)

    @app.route("/website/<int:website_id>/plan")
    def website_plan(website_id):
        sess = get_session()
        website = sess.get(Website, website_id) or abort(404)
        plans = sess.query(OptimizationPlan).filter_by(website_id=website_id)\
            .order_by(OptimizationPlan.created_at.desc()).all()
        return render_template("plan.html", website=website, plans=plans)

    @app.route("/website/<int:website_id>/changes")
    def website_changes(website_id):
        sess = get_session()
        website = sess.get(Website, website_id) or abort(404)
        changes = sess.query(SEOChange).filter_by(website_id=website_id)\
            .order_by(SEOChange.created_at.desc()).all()
        backups = sess.query(Backup).filter_by(website_id=website_id)\
            .order_by(Backup.created_at.desc()).limit(50).all()
        return render_template("changes.html", website=website, changes=changes, backups=backups)

    @app.route("/website/<int:website_id>/monitoring")
    def website_monitoring(website_id):
        sess = get_session()
        website = sess.get(Website, website_id) or abort(404)
        snapshots = sess.query(PerformanceSnapshot).filter_by(website_id=website_id)\
            .order_by(PerformanceSnapshot.snapshot_date.desc()).all()
        return render_template("monitoring.html", website=website, snapshots=snapshots)

    @app.route("/website/<int:website_id>/settings", methods=["GET", "POST"])
    def website_settings(website_id):
        sess = get_session()
        website = sess.get(Website, website_id) or abort(404)
        if request.method == "POST":
            website.name = request.form.get("name", website.name)
            website.website_root_path = request.form.get("web_root", website.website_root_path)
            website.business_description = request.form.get("business_description", "")
            sess.commit()
            log_audit("user", "website_settings_updated", website.name,
                      {"website_id": website_id, "name": website.name,
                       "root_path": website.website_root_path})
            flash("Settings saved", "success")
            return redirect(url_for("website_settings", website_id=website_id))
        return render_template("settings.html", website=website, mask=mask)

    @app.route("/change/<int:change_id>/rollback", methods=["POST"])
    def rollback(change_id):
        result = rollback_change(change_id)
        log_audit("user", "rollback", f"change-{change_id}",
                  {"change_id": change_id, "result": result})
        flash(result.get("message", "Done"), "success" if result.get("ok") else "error")
        sess = get_session()
        ch = sess.get(SEOChange, change_id)
        if ch:
            return redirect(url_for("website_changes", website_id=ch.website_id))
        return redirect(url_for("dashboard"))

    @app.route("/website/<int:website_id>/deploy-issue/<int:issue_id>", methods=["POST"])
    def deploy_issue(website_id, issue_id):
        """Public URL mode: deploy by re-fetching page and applying suggested fix."""
        sess = get_session()
        issue = sess.get(SEOIssue, issue_id) or abort(404)
        page = sess.get(Page, issue.page_id) if issue.page_id else None
        if not page:
            flash("No page mapped to issue", "error")
            return redirect(url_for("website_issues", website_id=website_id))
        try:
            r = requests.get(page.url, timeout=15,
                             headers={"User-Agent": "AI-SEO-Autopilot/1.0"})
            html = r.text
        except Exception as e:
            flash(f"Could not fetch page: {e}", "error")
            return redirect(url_for("website_issues", website_id=website_id))

        changes = [{
            "type": _map_issue_to_change_type(issue.issue_type),
            "value": issue.proposed_value or "",
            "match": "",
            "reason": issue.description,
            "risk": issue.risk or "low",
            "confidence": issue.confidence or 0.7,
            "implementation_method": issue.implementation_method or deployment_method({"issue_type": issue.issue_type}),
        }]
        result = deploy_change(website_id, page.server_file or page.url,
                               html.encode("utf-8"), changes, page_url=page.url)
        flash(result.get("message", "Done"), "success" if result.get("ok") else "error")
        issue.status = "deployed" if result.get("ok") else "failed"
        if result.get("ok"):
            issue.resolved = True
        sess.commit()
        return redirect(url_for("website_changes", website_id=website_id))

    @app.route("/api/sitemap-preview/<int:website_id>")
    def sitemap_preview(website_id):
        sess = get_session()
        website = sess.get(Website, website_id) or abort(404)
        sitemaps = discover_sitemaps(website.root_url)
        data = []
        for s in sitemaps:
            xml = fetch_sitemap(s)
            data.append({
                "url": s,
                "valid": validate_sitemap(xml or ""),
                "urls": [u["loc"] for u in parse_sitemap(xml or [])][:200],
            })
        # Also generate one from our crawled pages
        urls = [p.url for p in sess.query(Page).filter_by(website_id=website_id).all()]
        generated = generate_sitemap(urls)
        return jsonify({"existing": data, "generated": generated, "url_count": len(urls)})

    @app.route("/api/robots-preview/<int:website_id>")
    def robots_preview(website_id):
        sess = get_session()
        website = sess.get(Website, website_id) or abort(404)
        text = fetch_robots(website.root_url)
        return jsonify({"raw": text, "analysis": analyze_robots(text)})

    @app.route("/website/<int:website_id>/delete", methods=["POST"])
    def delete_website(website_id):
        sess = get_session()
        website = sess.get(Website, website_id) or abort(404)

        active_statuses = ACTIVE_JOB_STATUSES
        active_jobs = [
            j for j in list_jobs(website_id=website_id)
            if j["website_id"] == website_id and j["status"] in active_statuses
        ]

        stop_and_remove = False
        if request.is_json:
            data = request.get_json(silent=True) or {}
            stop_and_remove = bool(data.get("stop_jobs"))
        else:
            stop_and_remove = bool(request.form.get("stop_jobs"))

        if active_jobs and not stop_and_remove:
            if request.is_json:
                return jsonify({
                    "ok": False,
                    "error": "active_jobs",
                    "message": "This website has active SEO jobs. Stop them before removing.",
                    "jobs": [
                        {
                            "job_id": j["job_id"],
                            "job_type": j["job_type"],
                            "status": j["status"],
                            "progress": j["progress"],
                            "message": j["message"],
                        }
                        for j in active_jobs
                    ],
                }), 409
            flash("This website has active SEO jobs. Stop them before removing.", "error")
            return redirect(url_for("website_detail", website_id=website_id))

        if active_jobs and stop_and_remove:
            for j in active_jobs:
                try:
                    control_job(j["job_id"], "stop")
                except Exception:
                    pass

            import time
            deadline = time.time() + 5
            while time.time() < deadline:
                sess.expire_all()
                remaining = [
                    j for j in list_jobs(website_id=website_id)
                    if j["website_id"] == website_id and j["status"] in active_statuses
                ]
                if not remaining:
                    break
                time.sleep(0.5)

            sess.expire_all()
            still_active = [
                j for j in list_jobs(website_id=website_id)
                if j["website_id"] == website_id and j["status"] in active_statuses
            ]
            if still_active:
                if request.is_json:
                    return jsonify({
                        "ok": False,
                        "error": "jobs_not_stopped",
                        "message": "Could not stop all active jobs. Please try again.",
                        "jobs": [
                            {
                                "job_id": j["job_id"],
                                "job_type": j["job_type"],
                                "status": j["status"],
                            }
                            for j in still_active
                        ],
                    }), 409
                flash("Could not stop all active jobs. Please try again.", "error")
                return redirect(url_for("website_detail", website_id=website_id))

        website_name = website.name
        website_url = website.root_url

        from app.database.database import new_session

        job_sess = new_session()
        try:
            job_sess.query(ProcessEvent)\
                .filter_by(website_id=website_id)\
                .delete(synchronize_session=False)
            job_sess.query(Keyword)\
                .filter_by(website_id=website_id)\
                .delete(synchronize_session=False)
            job_sess.query(BackgroundJob)\
                .filter_by(website_id=website_id)\
                .delete(synchronize_session=False)
            job_sess.commit()
        except Exception:
            job_sess.rollback()
            raise
        finally:
            job_sess.close()

        sess.delete(website)
        sess.commit()
        log_audit("user", "WEBSITE_REMOVED", website_name,
                  {"website_url": website_url, "website_id": website_id,
                   "local_data_removed": True, "hosting_files_touched": False,
                   "ftp_server_modified": False,
                   "active_jobs_stopped": bool(active_jobs and stop_and_remove),
                   "deletion_scope": "local_application_only",
                   "message": "Website removed from AI SEO Autopilot"})

        if request.is_json:
            return jsonify({
                "ok": True,
                "message": "Website removed successfully",
                "website_id": website_id,
            })

        flash("Website removed from AI SEO Autopilot. No hosting files were deleted.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/audit-log")
    def audit_log():
        sess = get_session()
        logs = sess.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(200).all()
        return render_template("audit.html", logs=logs)

    @app.route("/live-activity")
    def live_activity():
        """Live AI Activity Monitor page."""
        job_id = request.args.get("job_id")
        website_id = request.args.get("website_id", type=int)
        event_manager = get_event_manager()

        jobs = list_jobs(website_id=website_id, limit=20)
        selected_job = None
        events = []
        stats = {}

        if job_id:
            selected_job = get_job(job_id)
            if selected_job:
                events = event_manager.get_events(job_id, limit=500)
                stats = event_manager.get_job_stats(job_id)

        return render_template("live_activity.html", jobs=jobs, selected_job=selected_job,
                               events=events, stats=stats, job_id=job_id)

    @app.route("/api/events/stream/<job_id>")
    def stream_events(job_id):
        """Server-Sent Events endpoint for real-time updates."""
        event_manager = get_event_manager()
        q = queue.Queue(maxsize=100)
        event_manager.subscribe(job_id, q)

        def generate():
            try:
                existing = event_manager.get_events(job_id, limit=100)
                for event in existing:
                    yield f"data: {json.dumps(event)}\n\n"

                while True:
                    try:
                        event = q.get(timeout=30)
                        yield f"data: {json.dumps(event)}\n\n"
                    except queue.Empty:
                        yield f"data: {json.dumps({'event_type': 'keepalive'})}\n\n"
            finally:
                event_manager.unsubscribe(job_id, q)

        return Response(stream_with_context(generate()), mimetype="text/event-stream",
                       headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.route("/api/events/stats/<job_id>")
    def event_stats(job_id):
        """Get aggregated stats for a job."""
        event_manager = get_event_manager()
        return jsonify(event_manager.get_job_stats(job_id))

    @app.route("/api/jobs/<job_id>/control", methods=["POST"])
    def control_job_route(job_id):
        """Control a running job (pause/resume/stop)."""
        data = request.get_json() or {}
        signal = data.get("signal")
        if signal not in ("pause", "resume", "stop"):
            return jsonify({"error": "Invalid signal"}), 400
        control_job(job_id, signal)
        return jsonify({"ok": True, "signal": signal})

    @app.route("/api/jobs/active")
    def active_jobs():
        """Get all active jobs."""
        sess = get_session()
        jobs = sess.query(BackgroundJob).filter(
            BackgroundJob.status.in_(["running", "queued", "paused"])
        ).order_by(BackgroundJob.created_at.desc()).all()
        return jsonify([{
            "job_id": j.job_id,
            "job_type": j.job_type,
            "status": j.status,
            "progress": j.progress,
            "message": j.message,
            "website_id": j.website_id,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        } for j in jobs])

    @app.route("/api/website/<int:website_id>/active-jobs")
    def api_website_active_jobs(website_id):
        sess = get_session()
        website = sess.get(Website, website_id)
        if not website:
            return jsonify({"success": False, "error": "Website not found"}), 404
        active_statuses = ACTIVE_JOB_STATUSES
        jobs = [
            j for j in list_jobs(website_id=website_id)
            if j["website_id"] == website_id and j["status"] in active_statuses
        ]
        return jsonify({
            "success": True,
            "website_id": website_id,
            "website_name": website.name,
            "has_active_jobs": bool(jobs),
            "active_job_count": len(jobs),
            "active_jobs": [
                {
                    "job_id": j["job_id"],
                    "type": j["job_type"],
                    "job_type": j["job_type"],
                    "status": j["status"],
                    "progress": j["progress"],
                    "message": j["message"],
                    "started_at": j["created_at"],
                }
                for j in jobs
            ],
            "jobs": [
                {
                    "job_id": j["job_id"],
                    "job_type": j["job_type"],
                    "status": j["status"],
                    "progress": j["progress"],
                    "message": j["message"],
                    "created_at": j["created_at"],
                }
                for j in jobs
            ],
        })

    @app.route("/api/ai/status")
    def api_ai_status():
        try:
            from app.ai.model_manager import get_model_manager
            manager = get_model_manager()
            return jsonify(manager.get_status())
        except Exception as e:
            return jsonify({"error": str(e), "ai_status": "error"}), 500

    @app.route("/api/ai/test", methods=["POST"])
    def api_ai_test():
        try:
            from app.ai.model_manager import get_model_manager
            manager = get_model_manager()
            result = manager.ensure_ready()
            return jsonify(result)
        except Exception as e:
            import traceback
            return jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()[-500:]}), 500

    @app.route("/api/ai/repair", methods=["POST"])
    def api_ai_repair():
        try:
            from app.ai.model_manager import get_model_manager
            manager = get_model_manager()
            result = manager.repair()
            return jsonify(result)
        except Exception as e:
            import traceback
            return jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()[-500:]}), 500


def _map_issue_to_change_type(issue_type: str) -> str:
    return {
        "missing_title": "title",
        "title_too_short": "title",
        "title_too_long": "title",
        "missing_meta_description": "meta_description",
        "meta_description_too_short": "meta_description",
        "meta_description_too_long": "meta_description",
        "missing_h1": "structured_data",  # safely handled as noop if value empty
        "missing_alt_text": "image_alt",
        "missing_canonical": "canonical",
        "missing_og_tags": "open_graph",
        "missing_structured_data": "structured_data",
    }.get(issue_type, "meta_description")
    