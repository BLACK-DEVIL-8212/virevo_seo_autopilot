"""SQLAlchemy models for the AI SEO Autopilot."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Float, ForeignKey, JSON,
)
from sqlalchemy.orm import relationship
from .database import Base


class Website(Base):
    __tablename__ = "websites"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    root_url = Column(String(500), nullable=False, index=True)
    connection_type = Column(String(50), default="public_url")  # public_url, ftp, sftp, ssh
    website_root_path = Column(String(500), default="")
    technology = Column(String(100), default="unknown")
    business_description = Column(Text, default="")
    seo_health_score = Column(Float, default=0.0)
    last_analyzed = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    connections = relationship("Connection", back_populates="website", cascade="all, delete-orphan")
    pages = relationship("Page", back_populates="website", cascade="all, delete-orphan")
    crawls = relationship("Crawl", back_populates="website", cascade="all, delete-orphan")
    issues = relationship("SEOIssue", back_populates="website", cascade="all, delete-orphan")
    plans = relationship("OptimizationPlan", back_populates="website", cascade="all, delete-orphan")
    changes = relationship("SEOChange", back_populates="website", cascade="all, delete-orphan")
    backups = relationship("Backup", back_populates="website", cascade="all, delete-orphan")
    deployments = relationship("Deployment", back_populates="website", cascade="all, delete-orphan")
    snapshots = relationship("PerformanceSnapshot", back_populates="website", cascade="all, delete-orphan")

    architecture_type = Column(String(100), default="static_html")  # static_html, react_spa, vue_spa, angular_spa, javascript_spa, ssr, hybrid
    rendering_mode = Column(String(50), default="raw")  # raw, rendered, hybrid
    deployment_strategy = Column(String(50), default="direct_html")  # direct_html, source_code_build, firebase_deploy, git_deploy, recommendation_only
    source_available = Column(Boolean, default=False)
    build_system = Column(String(100), default="")  # webpack, vite, parcel, rollup, gulp, unknown
    hosting_provider = Column(String(100), default="")  # firebase, netlify, vercel, aws, gcp, azure, unknown
    repository_connected = Column(Boolean, default=False)
    repository_url = Column(String(500), default="")
    repository_branch = Column(String(100), default="main")
    detected_spa_framework = Column(String(100), default="")
    detected_framework_evidence = Column(JSON, default=dict)
    last_architecture_check = Column(DateTime, nullable=True)


class Connection(Base):
    __tablename__ = "connections"
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    host = Column(String(255), default="")
    port = Column(Integer, nullable=True)
    username = Column(String(255), default="")
    password_encrypted = Column(Text, default="")
    private_key_encrypted = Column(Text, default="")
    extra_json = Column(JSON, default=dict)
    last_tested = Column(DateTime, nullable=True)
    last_status = Column(String(50), default="unknown")
    last_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    website = relationship("Website", back_populates="connections")


class Crawl(Base):
    __tablename__ = "crawls"
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(50), default="running")  # running, completed, failed
    pages_crawled = Column(Integer, default=0)
    max_pages = Column(Integer, default=50)
    max_depth = Column(Integer, default=3)
    source = Column(String(50), default="raw")  # raw or rendered
    error_message = Column(Text, default="")

    website = relationship("Website", back_populates="crawls")
    pages = relationship("Page", back_populates="crawl")


class Page(Base):
    __tablename__ = "pages"
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    crawl_id = Column(Integer, ForeignKey("crawls.id"), nullable=True)
    url = Column(String(1000), nullable=False, index=True)
    canonical_url = Column(String(1000), default="")
    server_file = Column(String(1000), default="")
    file_mapping_confidence = Column(Float, default=0.0)
    status_code = Column(Integer, default=0)
    content_type = Column(String(255), default="")
    title = Column(Text, default="")
    meta_description = Column(Text, default="")
    h1 = Column(Text, default="")
    headings_json = Column(JSON, default=dict)
    word_count = Column(Integer, default=0)
    main_content = Column(Text, default="")
    images_json = Column(JSON, default=dict)
    links_json = Column(JSON, default=dict)
    og_json = Column(JSON, default=dict)
    twitter_json = Column(JSON, default=dict)
    structured_data_json = Column(JSON, default=dict)
    language = Column(String(20), default="")
    robots_meta = Column(String(255), default="")
    rendered = Column(Boolean, default=False)
    raw_html_path = Column(String(500), default="")
    rendered_html_path = Column(String(500), default="")
    seo_score = Column(Float, default=0.0)
    duplicate_of = Column(Integer, ForeignKey("pages.id"), nullable=True)
    analyzed_at = Column(DateTime, default=datetime.utcnow)

    # SPA / rendered-page fields
    route_url = Column(String(1000), default="")
    rendered_html = Column(Text, default="")
    rendered_word_count = Column(Integer, default=0)
    rendered_title = Column(Text, default="")
    rendered_meta_description = Column(Text, default="")
    rendered_h1 = Column(Text, default="")
    rendered_headings_json = Column(JSON, default=dict)
    rendered_main_content = Column(Text, default="")
    rendered_images_json = Column(JSON, default=dict)
    rendered_links_json = Column(JSON, default=dict)
    rendered_og_json = Column(JSON, default=dict)
    rendered_twitter_json = Column(JSON, default=dict)
    rendered_structured_data_json = Column(JSON, default=dict)
    rendered_canonical_url = Column(String(1000), default="")
    rendered_language = Column(String(20), default="")
    rendered_robots_meta = Column(String(255), default="")
    is_spa_route = Column(Boolean, default=False)
    source_file_path = Column(String(500), default="")
    source_language = Column(String(50), default="")  # jsx, tsx, js, vue, svelte

    website = relationship("Website", back_populates="pages")
    crawl = relationship("Crawl", back_populates="pages")


class SEOIssue(Base):
    __tablename__ = "seo_issues"
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=True)
    url = Column(String(1000), default="")
    issue_type = Column(String(100), nullable=False)  # e.g. missing_meta_description
    severity = Column(String(20), default="medium")  # critical, high, medium, low
    title = Column(String(500), default="")
    description = Column(Text, default="")
    current_value = Column(Text, default="")
    proposed_value = Column(Text, default="")
    implementation_method = Column(String(100), default="")
    risk = Column(String(20), default="medium")
    confidence = Column(Float, default=0.5)
    status = Column(String(50), default="open")  # open, planned, deployed, dismissed
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    website = relationship("Website", back_populates="issues")


class Keyword(Base):
    __tablename__ = "keywords"
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=True)
    keyword = Column(String(500), nullable=False, index=True)
    cluster = Column(String(255), default="")
    intent = Column(String(50), default="informational")  # commercial, transactional, informational, navigational, local
    search_volume = Column(Integer, default=0)
    difficulty = Column(Float, default=0.0)
    relevance = Column(Float, default=0.0)
    opportunity_score = Column(Float, default=0.0)
    is_long_tail = Column(Boolean, default=False)
    is_trending = Column(Boolean, default=False)
    provider = Column(String(100), default="local")
    created_at = Column(DateTime, default=datetime.utcnow)


class OptimizationPlan(Base):
    __tablename__ = "optimization_plans"
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    title = Column(String(500), default="")
    summary = Column(Text, default="")
    actions_json = Column(JSON, default=list)
    risk_breakdown = Column(JSON, default=dict)
    status = Column(String(50), default="draft")  # draft, approved, deploying, completed
    created_at = Column(DateTime, default=datetime.utcnow)

    website = relationship("Website", back_populates="plans")


class SEOChange(Base):
    __tablename__ = "seo_changes"
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    change_id = Column(String(50), unique=True, nullable=False, index=True)
    page_url = Column(String(1000), default="")
    server_file = Column(String(1000), default="")
    change_type = Column(String(100), default="")
    before_value = Column(Text, default="")
    after_value = Column(Text, default="")
    reasoning = Column(Text, default="")
    confidence = Column(Float, default=0.0)
    risk = Column(String(20), default="medium")
    status = Column(String(50), default="proposed")  # proposed, approved, deployed, failed, rolled_back
    backup_id = Column(Integer, ForeignKey("backups.id"), nullable=True)
    deployment_id = Column(Integer, ForeignKey("deployments.id"), nullable=True)
    validation_result = Column(Text, default="")
    failure_details = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    deployed_at = Column(DateTime, nullable=True)

    website = relationship("Website", back_populates="changes")
    backup = relationship("Backup", foreign_keys=[backup_id])
    deployment = relationship("Deployment", foreign_keys=[deployment_id])


class Backup(Base):
    __tablename__ = "backups"
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    change_id = Column(String(50), nullable=False)
    server_file = Column(String(1000), nullable=False)
    local_path = Column(String(1000), nullable=False)
    sha256_before = Column(String(128), default="")
    content_size = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    website = relationship("Website", back_populates="backups")


class Deployment(Base):
    __tablename__ = "deployments"
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    change_id = Column(String(50), default="")
    server_file = Column(String(1000), default="")
    status = Column(String(50), default="pending")
    message = Column(Text, default="")
    verification_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    website = relationship("Website", back_populates="deployments")


class PerformanceSnapshot(Base):
    __tablename__ = "performance_snapshots"
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    page_url = Column(String(1000), default="")
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    ctr = Column(Float, default=0.0)
    average_position = Column(Float, default=0.0)
    indexed = Column(Boolean, default=True)
    crawl_errors = Column(Integer, default=0)
    snapshot_date = Column(DateTime, default=datetime.utcnow)
    provider = Column(String(100), default="local")

    website = relationship("Website", back_populates="snapshots")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    actor = Column(String(100), default="system")
    action = Column(String(200), nullable=False)
    target = Column(String(500), default="")
    details_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class SEOOptimization(Base):
    """Tracks an SEO auto-optimization run for a website."""
    __tablename__ = "seo_optimizations"
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    crawl_id = Column(Integer, ForeignKey("crawls.id"), nullable=True)
    status = Column(String(50), default="running")  # running, completed, partial, failed
    score_before = Column(Float, default=0.0)
    score_after = Column(Float, default=0.0)
    target_score = Column(Float, default=95.0)
    pages_optimized = Column(Integer, default=0)
    pages_remaining = Column(Integer, default=0)
    max_iterations = Column(Integer, default=3)
    iteration = Column(Integer, default=0)
    changes_applied = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

    website = relationship("Website")
    crawl = relationship("Crawl")


class PageOptimization(Base):
    """Tracks the optimization of a single page within an SEOOptimization run."""
    __tablename__ = "page_optimizations"
    id = Column(Integer, primary_key=True)
    optimization_id = Column(Integer, ForeignKey("seo_optimizations.id"), nullable=False)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=True)
    page_url = Column(String(1000), default="")
    original_score = Column(Float, default=0.0)
    optimized_score = Column(Float, default=0.0)
    status = Column(String(50), default="pending")  # pending, in_progress, improved, skipped, failed, rolled_back
    issues_detected = Column(JSON, default=list)
    changes_proposed = Column(JSON, default=list)
    changes_applied = Column(JSON, default=list)
    change_reasons = Column(JSON, default=list)
    expected_benefit = Column(JSON, default=dict)
    failure_details = Column(JSON, default=dict)
    deploy_result = Column(JSON, default=dict)
    optimization_timestamp = Column(DateTime, default=datetime.utcnow)


class ProviderConfiguration(Base):
    __tablename__ = "provider_configurations"
    id = Column(Integer, primary_key=True)
    provider_type = Column(String(100), nullable=False)  # keyword, trend, search_perf, analytics
    provider_name = Column(String(100), nullable=False)
    config_json = Column(JSON, default=dict)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    id = Column(Integer, primary_key=True)
    job_id = Column(String(80), unique=True, nullable=False)
    job_type = Column(String(100), nullable=False)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=True)
    status = Column(String(50), default="queued")  # queued, running, completed, failed, paused, stopped
    progress = Column(Integer, default=0)
    message = Column(Text, default="")
    result_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    _control = Column(String(50), default="")  # pause, resume, stop signals


class ProcessEvent(Base):
    __tablename__ = "process_events"
    id = Column(Integer, primary_key=True)
    job_id = Column(String(80), nullable=False, index=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=True)
    agent_name = Column(String(100), default="")
    event_type = Column(String(100), nullable=False)
    severity = Column(String(20), default="info")  # info, warning, error, success
    message = Column(Text, default="")
    url = Column(String(1000), default="")
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)