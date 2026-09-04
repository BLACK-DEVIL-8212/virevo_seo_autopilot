"""SQLAlchemy models for the AI SEO Autopilot.

Comprehensive database schema for SEO optimization platform including:
- Website management with architecture detection
- Crawling and page analysis
- SEO issue tracking
- Keyword intelligence
- Optimization planning and execution
- Deployment and backup management
- Performance monitoring
- Audit logging
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Float, ForeignKey, JSON,
    Index, UniqueConstraint, CheckConstraint
)
from sqlalchemy.orm import relationship, validates
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


# ============================================================================
# UTILITY MIXINS
# ============================================================================

class TimestampMixin:
    """Mixin for created_at and updated_at timestamps."""
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SoftDeleteMixin:
    """Mixin for soft delete functionality."""
    deleted_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False)


# ============================================================================
# WEBSITE MODEL
# ============================================================================

class Website(Base, TimestampMixin):
    """Main website entity representing a client website."""
    __tablename__ = "websites"
    
    # Core fields
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    root_url = Column(String(500), nullable=False, index=True)
    connection_type = Column(String(50), default="public_url")  # public_url, ftp, sftp, ssh
    website_root_path = Column(String(500), default="")
    
    # Technology and architecture
    technology = Column(String(100), default="unknown")
    architecture_type = Column(String(100), default="static_html")  # static_html, react_spa, vue_spa, angular_spa, javascript_spa, ssr, hybrid
    rendering_mode = Column(String(50), default="raw")  # raw, rendered, hybrid
    deployment_strategy = Column(String(50), default="direct_html")  # direct_html, source_code_build, firebase_deploy, git_deploy, recommendation_only
    build_system = Column(String(100), default="")  # webpack, vite, parcel, rollup, gulp, unknown
    hosting_provider = Column(String(100), default="")  # firebase, netlify, vercel, aws, gcp, azure, unknown
    detected_spa_framework = Column(String(100), default="")
    detected_framework_evidence = Column(JSON, default=dict)
    last_architecture_check = Column(DateTime, nullable=True)
    
    # Business and SEO
    business_description = Column(Text, default="")
    seo_health_score = Column(Float, default=0.0)
    last_analyzed = Column(DateTime, nullable=True)
    
    # Source control
    source_available = Column(Boolean, default=False)
    repository_connected = Column(Boolean, default=False)
    repository_url = Column(String(500), default="")
    repository_branch = Column(String(100), default="main")
    
    # Relationships
    connections = relationship("Connection", back_populates="website", cascade="all, delete-orphan")
    pages = relationship("Page", back_populates="website", cascade="all, delete-orphan")
    crawls = relationship("Crawl", back_populates="website", cascade="all, delete-orphan")
    issues = relationship("SEOIssue", back_populates="website", cascade="all, delete-orphan")
    plans = relationship("OptimizationPlan", back_populates="website", cascade="all, delete-orphan")
    changes = relationship("SEOChange", back_populates="website", cascade="all, delete-orphan")
    backups = relationship("Backup", back_populates="website", cascade="all, delete-orphan")
    deployments = relationship("Deployment", back_populates="website", cascade="all, delete-orphan")
    snapshots = relationship("PerformanceSnapshot", back_populates="website", cascade="all, delete-orphan")
    optimizations = relationship("SEOOptimization", back_populates="website", cascade="all, delete-orphan")
    keywords = relationship("Keyword", back_populates="website", cascade="all, delete-orphan")
    jobs = relationship("BackgroundJob", back_populates="website")
    events = relationship("ProcessEvent", back_populates="website")
    
    def __repr__(self) -> str:
        return f"<Website(id={self.id}, name='{self.name}', root_url='{self.root_url}')>"
    
    @validates('root_url')
    def validate_root_url(self, key: str, value: str) -> str:
        """Validate root URL format."""
        if not value.startswith(('http://', 'https://')):
            raise ValueError("Root URL must start with http:// or https://")
        return value.rstrip('/')
    
    def is_spa(self) -> bool:
        """Check if website is a Single Page Application."""
        return self.architecture_type in (
            'react_spa', 'vue_spa', 'angular_spa', 'javascript_spa'
        )
    
    def can_auto_deploy(self) -> bool:
        """Check if website supports auto-deployment."""
        return self.deployment_strategy in ('direct_html', 'source_code_build')
    
    def get_connection(self) -> Optional[Connection]:
        """Get the primary connection for this website."""
        return self.connections[0] if self.connections else None


# ============================================================================
# CONNECTION MODEL
# ============================================================================

class Connection(Base, TimestampMixin):
    """Connection credentials for FTP/SFTP/SSH access."""
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
    last_status = Column(String(50), default="unknown")  # unknown, success, failed
    last_message = Column(Text, default="")
    
    # Relationships
    website = relationship("Website", back_populates="connections")
    
    def __repr__(self) -> str:
        return f"<Connection(id={self.id}, host='{self.host}', username='{self.username}')>"
    
    @property
    def is_configured(self) -> bool:
        """Check if connection is properly configured."""
        return bool(self.host and self.username)


# ============================================================================
# CRAWL MODEL
# ============================================================================

class Crawl(Base, TimestampMixin):
    """Crawl session record."""
    __tablename__ = "crawls"
    
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(50), default="running")  # running, completed, failed, paused, stopped
    pages_crawled = Column(Integer, default=0)
    max_pages = Column(Integer, default=50)
    max_depth = Column(Integer, default=3)
    source = Column(String(50), default="raw")  # raw, rendered, hybrid
    error_message = Column(Text, default="")
    
    # Relationships
    website = relationship("Website", back_populates="crawls")
    pages = relationship("Page", back_populates="crawl", cascade="all, delete-orphan")
    optimization = relationship("SEOOptimization", back_populates="crawl", uselist=False)
    
    def __repr__(self) -> str:
        return f"<Crawl(id={self.id}, website_id={self.website_id}, status='{self.status}')>"
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate crawl duration in seconds."""
        if self.finished_at and self.started_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
    
    def is_complete(self) -> bool:
        """Check if crawl is complete."""
        return self.status in ('completed', 'failed')


# ============================================================================
# PAGE MODEL
# ============================================================================

class Page(Base, TimestampMixin):
    """Individual page from a crawl."""
    __tablename__ = "pages"
    
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    crawl_id = Column(Integer, ForeignKey("crawls.id"), nullable=True)
    
    # URL and routing
    url = Column(String(1000), nullable=False, index=True)
    canonical_url = Column(String(1000), default="")
    route_url = Column(String(1000), default="")
    server_file = Column(String(1000), default="")
    file_mapping_confidence = Column(Float, default=0.0)
    source_file_path = Column(String(500), default="")
    source_language = Column(String(50), default="")  # jsx, tsx, js, vue, svelte
    
    # HTTP response
    status_code = Column(Integer, default=0)
    content_type = Column(String(255), default="")
    
    # SEO metadata
    title = Column(Text, default="")
    meta_description = Column(Text, default="")
    h1 = Column(Text, default="")
    headings_json = Column(JSON, default=dict)
    word_count = Column(Integer, default=0)
    main_content = Column(Text, default="")
    
    # Media and links
    images_json = Column(JSON, default=dict)
    links_json = Column(JSON, default=dict)
    
    # Social and structured data
    og_json = Column(JSON, default=dict)
    twitter_json = Column(JSON, default=dict)
    structured_data_json = Column(JSON, default=dict)
    
    # Technical SEO
    language = Column(String(20), default="")
    robots_meta = Column(String(255), default="")
    
    # Rendering
    rendered = Column(Boolean, default=False)
    raw_html_path = Column(String(500), default="")
    rendered_html_path = Column(String(500), default="")
    rendered_html = Column(Text, default="")
    
    # Rendered SEO metadata
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
    rendered_word_count = Column(Integer, default=0)
    
    # SPA detection
    is_spa_route = Column(Boolean, default=False)
    
    # Scoring
    seo_score = Column(Float, default=0.0)
    duplicate_of = Column(Integer, ForeignKey("pages.id"), nullable=True)
    analyzed_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    website = relationship("Website", back_populates="pages")
    crawl = relationship("Crawl", back_populates="pages")
    issues = relationship("SEOIssue", back_populates="page")
    keywords = relationship("Keyword", back_populates="page")
    optimizations = relationship("PageOptimization", back_populates="page")
    changes = relationship("SEOChange", back_populates="page")
    
    __table_args__ = (
        Index('idx_pages_website_url', 'website_id', 'url'),
        Index('idx_pages_seo_score', 'website_id', 'seo_score'),
        Index('idx_pages_crawl_status', 'crawl_id', 'status_code'),
    )
    
    def __repr__(self) -> str:
        return f"<Page(id={self.id}, url='{self.url[:50]}...', score={self.seo_score})>"
    
    @property
    def is_valid_html(self) -> bool:
        """Check if page is valid HTML."""
        return 200 <= self.status_code < 400 and self.content_type == 'text/html'
    
    def has_issue(self, issue_type: str) -> bool:
        """Check if page has a specific issue type."""
        return any(i.issue_type == issue_type for i in self.issues)


# ============================================================================
# SEO ISSUE MODEL
# ============================================================================

class SEOIssue(Base, TimestampMixin):
    """SEO issue detected on a page."""
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
    
    # Relationships
    website = relationship("Website", back_populates="issues")
    page = relationship("Page", back_populates="issues")
    
    __table_args__ = (
        Index('idx_seo_issues_website', 'website_id'),
        Index('idx_seo_issues_page', 'page_id'),
        Index('idx_seo_issues_severity', 'severity'),
        Index('idx_seo_issues_resolved', 'resolved'),
    )
    
    def __repr__(self) -> str:
        return f"<SEOIssue(id={self.id}, type='{self.issue_type}', severity='{self.severity}')>"
    
    @property
    def is_critical(self) -> bool:
        """Check if issue is critical severity."""
        return self.severity == 'critical'
    
    def can_auto_fix(self) -> bool:
        """Check if issue can be auto-fixed."""
        return self.risk in ('low', 'medium') and self.confidence > 0.7


# ============================================================================
# KEYWORD MODEL
# ============================================================================

class Keyword(Base, TimestampMixin):
    """Keyword intelligence data."""
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
    
    # Relationships
    website = relationship("Website", back_populates="keywords")
    page = relationship("Page", back_populates="keywords")
    
    __table_args__ = (
        Index('idx_keywords_website', 'website_id'),
        Index('idx_keywords_page', 'page_id'),
        Index('idx_keywords_keyword', 'keyword'),
        UniqueConstraint('website_id', 'keyword', name='uq_keyword_website'),
    )
    
    def __repr__(self) -> str:
        return f"<Keyword(id={self.id}, keyword='{self.keyword}', volume={self.search_volume})>"
    
    @property
    def is_high_opportunity(self) -> bool:
        """Check if keyword is high opportunity."""
        return self.opportunity_score > 0.7 and self.difficulty < 0.5


# ============================================================================
# OPTIMIZATION PLAN MODEL
# ============================================================================

class OptimizationPlan(Base, TimestampMixin):
    """Optimization plan for a website."""
    __tablename__ = "optimization_plans"
    
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    
    title = Column(String(500), default="")
    summary = Column(Text, default="")
    actions_json = Column(JSON, default=list)
    risk_breakdown = Column(JSON, default=dict)
    status = Column(String(50), default="draft")  # draft, approved, deploying, completed
    
    # Relationships
    website = relationship("Website", back_populates="plans")
    
    def __repr__(self) -> str:
        return f"<OptimizationPlan(id={self.id}, title='{self.title[:50]}', status='{self.status}')>"
    
    @property
    def total_actions(self) -> int:
        """Get total number of actions in plan."""
        return len(self.actions_json)
    
    def get_actions_by_risk(self, risk_level: str) -> List[Dict]:
        """Get actions filtered by risk level."""
        return [a for a in self.actions_json if a.get('risk') == risk_level]


# ============================================================================
# SEO CHANGE MODEL
# ============================================================================

class SEOChange(Base, TimestampMixin):
    """Record of an SEO change/deployment."""
    __tablename__ = "seo_changes"
    
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=True)
    
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
    deployed_at = Column(DateTime, nullable=True)
    
    # Relationships
    website = relationship("Website", back_populates="changes")
    page = relationship("Page", back_populates="changes")
    backup = relationship("Backup", foreign_keys=[backup_id])
    deployment = relationship("Deployment", foreign_keys=[deployment_id])
    
    __table_args__ = (
        Index('idx_seo_changes_website', 'website_id'),
        Index('idx_seo_changes_status', 'status'),
        Index('idx_seo_changes_change_id', 'change_id'),
    )
    
    def __repr__(self) -> str:
        return f"<SEOChange(id={self.id}, change_id='{self.change_id}', status='{self.status}')>"
    
    @property
    def is_deployed(self) -> bool:
        """Check if change is deployed."""
        return self.status == 'deployed'
    
    def can_rollback(self) -> bool:
        """Check if change can be rolled back."""
        return self.is_deployed and self.backup_id is not None


# ============================================================================
# BACKUP MODEL
# ============================================================================

class Backup(Base, TimestampMixin):
    """Backup of original content before changes."""
    __tablename__ = "backups"
    
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    
    change_id = Column(String(50), nullable=False)
    server_file = Column(String(1000), nullable=False)
    local_path = Column(String(1000), nullable=False)
    sha256_before = Column(String(128), default="")
    content_size = Column(Integer, default=0)
    
    # Relationships
    website = relationship("Website", back_populates="backups")
    
    def __repr__(self) -> str:
        return f"<Backup(id={self.id}, file='{self.server_file}', size={self.content_size})>"


# ============================================================================
# DEPLOYMENT MODEL
# ============================================================================

class Deployment(Base, TimestampMixin):
    """Deployment record."""
    __tablename__ = "deployments"
    
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    
    change_id = Column(String(50), default="")
    server_file = Column(String(1000), default="")
    status = Column(String(50), default="pending")  # pending, deploying, deployed, failed, rolled_back
    message = Column(Text, default="")
    verification_json = Column(JSON, default=dict)
    
    # Relationships
    website = relationship("Website", back_populates="deployments")
    
    def __repr__(self) -> str:
        return f"<Deployment(id={self.id}, change_id='{self.change_id}', status='{self.status}')>"
    
    @property
    def is_successful(self) -> bool:
        """Check if deployment was successful."""
        return self.status == 'deployed'


# ============================================================================
# PERFORMANCE SNAPSHOT MODEL
# ============================================================================

class PerformanceSnapshot(Base, TimestampMixin):
    """Performance snapshot from search console/analytics."""
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
    
    # Relationships
    website = relationship("Website", back_populates="snapshots")
    
    __table_args__ = (
        Index('idx_performance_website', 'website_id'),
        Index('idx_performance_snapshot_date', 'snapshot_date'),
        Index('idx_performance_page_url', 'page_url'),
    )


# ============================================================================
# SEO OPTIMIZATION MODEL
# ============================================================================

class SEOOptimization(Base, TimestampMixin):
    """Tracks an SEO auto-optimization run for a website."""
    __tablename__ = "seo_optimizations"
    
    id = Column(Integer, primary_key=True)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=False)
    crawl_id = Column(Integer, ForeignKey("crawls.id"), nullable=True)
    
    status = Column(String(50), default="running")  # running, completed, partial, failed, rolled_back
    score_before = Column(Float, default=0.0)
    score_after = Column(Float, default=0.0)
    target_score = Column(Float, default=95.0)
    pages_optimized = Column(Integer, default=0)
    pages_remaining = Column(Integer, default=0)
    max_iterations = Column(Integer, default=3)
    iteration = Column(Integer, default=0)
    changes_applied = Column(Integer, default=0)
    finished_at = Column(DateTime, nullable=True)
    
    # Relationships
    website = relationship("Website", back_populates="optimizations")
    crawl = relationship("Crawl", back_populates="optimization")
    page_optimizations = relationship("PageOptimization", back_populates="optimization", cascade="all, delete-orphan")
    
    def __repr__(self) -> str:
        return f"<SEOOptimization(id={self.id}, status='{self.status}', score={self.score_after})>"
    
    @property
    def improvement(self) -> float:
        """Calculate improvement in SEO score."""
        return self.score_after - self.score_before
    
    @property
    def is_complete(self) -> bool:
        """Check if optimization is complete."""
        return self.status in ('completed', 'failed', 'rolled_back')


# ============================================================================
# PAGE OPTIMIZATION MODEL
# ============================================================================

class PageOptimization(Base, TimestampMixin):
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
    
    # Relationships
    optimization = relationship("SEOOptimization", back_populates="page_optimizations")
    page = relationship("Page", back_populates="optimizations")
    
    def __repr__(self) -> str:
        return f"<PageOptimization(id={self.id}, page_url='{self.page_url[:50]}', status='{self.status}')>"
    
    @property
    def improvement(self) -> float:
        """Calculate improvement for this page."""
        return self.optimized_score - self.original_score


# ============================================================================
# PROVIDER CONFIGURATION MODEL
# ============================================================================

class ProviderConfiguration(Base, TimestampMixin):
    """Configuration for external providers."""
    __tablename__ = "provider_configurations"
    
    id = Column(Integer, primary_key=True)
    provider_type = Column(String(100), nullable=False)  # keyword, trend, search_perf, analytics
    provider_name = Column(String(100), nullable=False)
    config_json = Column(JSON, default=dict)
    enabled = Column(Boolean, default=True)
    
    def __repr__(self) -> str:
        return f"<ProviderConfiguration(id={self.id}, type='{self.provider_type}', name='{self.provider_name}')>"


# ============================================================================
# AUDIT LOG MODEL
# ============================================================================

class AuditLog(Base, TimestampMixin):
    """Audit log for all system actions."""
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True)
    actor = Column(String(100), default="system")
    action = Column(String(200), nullable=False)
    target = Column(String(500), default="")
    details_json = Column(JSON, default=dict)
    
    __table_args__ = (
        Index('idx_audit_logs_actor', 'actor'),
        Index('idx_audit_logs_action', 'action'),
        Index('idx_audit_logs_created_at', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, actor='{self.actor}', action='{self.action}')>"


# ============================================================================
# BACKGROUND JOB MODEL
# ============================================================================

class BackgroundJob(Base, TimestampMixin):
    """Background job tracking."""
    __tablename__ = "background_jobs"
    
    id = Column(Integer, primary_key=True)
    job_id = Column(String(80), unique=True, nullable=False)
    job_type = Column(String(100), nullable=False)
    website_id = Column(Integer, ForeignKey("websites.id"), nullable=True)
    
    status = Column(String(50), default="queued")  # queued, running, completed, failed, paused, stopped
    progress = Column(Integer, default=0)
    message = Column(Text, default="")
    result_json = Column(JSON, default=dict)
    _control = Column(String(50), default="")  # pause, resume, stop signals
    
    # Relationships
    website = relationship("Website", back_populates="jobs")
    
    __table_args__ = (
        Index('idx_background_jobs_status', 'status'),
        Index('idx_background_jobs_website', 'website_id'),
        Index('idx_background_jobs_job_type', 'job_type'),
    )
    
    def __repr__(self) -> str:
        return f"<BackgroundJob(id={self.id}, job_id='{self.job_id}', status='{self.status}')>"
    
    @property
    def is_running(self) -> bool:
        """Check if job is running."""
        return self.status == 'running'
    
    @property
    def is_complete(self) -> bool:
        """Check if job is complete."""
        return self.status in ('completed', 'failed', 'stopped')


# ============================================================================
# PROCESS EVENT MODEL
# ============================================================================

class ProcessEvent(Base, TimestampMixin):
    """Real-time process events for UI updates."""
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
    
    # Relationships
    website = relationship("Website", back_populates="events")
    
    __table_args__ = (
        Index('idx_process_events_job', 'job_id'),
        Index('idx_process_events_created_at', 'created_at'),
        Index('idx_process_events_type', 'event_type'),
    )
    
    def __repr__(self) -> str:
        return f"<ProcessEvent(id={self.id}, job_id='{self.job_id}', event_type='{self.event_type}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            'id': self.id,
            'job_id': self.job_id,
            'website_id': self.website_id,
            'agent_name': self.agent_name,
            'event_type': self.event_type,
            'severity': self.severity,
            'message': self.message,
            'url': self.url,
            'metadata': self.metadata_json,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

def init_database(engine):
    """Initialize database with all tables."""
    Base.metadata.create_all(engine)


def get_model_list() -> List[str]:
    """Get list of all model names."""
    return [
        'Website', 'Connection', 'Crawl', 'Page', 'SEOIssue', 'Keyword',
        'OptimizationPlan', 'SEOChange', 'Backup', 'Deployment',
        'PerformanceSnapshot', 'SEOOptimization', 'PageOptimization',
        'ProviderConfiguration', 'AuditLog', 'BackgroundJob', 'ProcessEvent'
    ]
