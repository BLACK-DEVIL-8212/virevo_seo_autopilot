"""Configuration loaded from environment variables.

Provides a centralized configuration management system with:
- Environment variable loading with defaults
- Type conversion and validation
- Secure credential handling
- Directory management
- Configuration export for debugging
"""
import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

# Setup logging
logger = logging.getLogger(__name__)

# Determine root directory
ROOT = Path(__file__).resolve().parent.parent

# Load environment variables from .env file
load_dotenv(ROOT / ".env")


class Config:
    """Application configuration loaded from environment variables."""
    
    # =========================================================================
    # SECURITY
    # =========================================================================
    SECRET_KEY = os.environ.get("APP_SECRET_KEY", "dev-secret-change-me")
    
    # Encryption key for sensitive credentials (must be 32 bytes for Fernet)
    CREDENTIAL_ENCRYPTION_KEY = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "")
    
    # =========================================================================
    # DATABASE
    # =========================================================================
    DATABASE_URL = os.environ.get(
        "DATABASE_URL", 
        f"sqlite:///{(ROOT / 'ai_seo.db').as_posix()}"
    )
    
    # Database pool settings
    DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "5"))
    DB_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", "10"))
    DB_POOL_TIMEOUT = int(os.environ.get("DB_POOL_TIMEOUT", "30"))
    DB_POOL_RECYCLE = int(os.environ.get("DB_POOL_RECYCLE", "1800"))
    DB_ECHO = os.environ.get("DB_ECHO", "false").lower() in ("true", "1", "yes")
    
    # =========================================================================
    # AI PROVIDERS
    # =========================================================================
    AI_PROVIDER = os.environ.get("AI_PROVIDER", "mock")  # mock, openai, anthropic, huggingface, ollama
    
    # OpenAI
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    OPENAI_MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS", "2000"))
    OPENAI_TEMPERATURE = float(os.environ.get("OPENAI_TEMPERATURE", "0.7"))
    
    # Anthropic
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-3-sonnet-20240229")
    ANTHROPIC_MAX_TOKENS = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "2000"))
    
    # Hugging Face
    HUGGINGFACE_API_KEY = os.environ.get("HUGGINGFACE_API_KEY", "")
    HUGGINGFACE_MODEL = os.environ.get("HUGGINGFACE_MODEL", "user052/EDIATH-Q4_K_M")
    
    # Ollama (local)
    OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama2")
    
    # Fallback model
    AI_MODEL = os.environ.get("AI_MODEL", "user052/EDIATH-Q4_K_M")
    AI_TIMEOUT = int(os.environ.get("AI_TIMEOUT", "60"))
    AI_MAX_RETRIES = int(os.environ.get("AI_MAX_RETRIES", "3"))
    
    # =========================================================================
    # CRAWLING
    # =========================================================================
    CRAWL_MAX_PAGES = int(os.environ.get("CRAWL_MAX_PAGES", "50"))
    CRAWL_MAX_DEPTH = int(os.environ.get("CRAWL_MAX_DEPTH", "3"))
    CRAWL_DELAY_SECONDS = float(os.environ.get("CRAWL_DELAY_SECONDS", "0.5"))
    CRAWL_TIMEOUT = int(os.environ.get("CRAWL_TIMEOUT", "30"))
    CRAWL_USER_AGENT = os.environ.get(
        "CRAWL_USER_AGENT", 
        "AI-SEO-Autopilot/1.0 (+https://example.com/bot)"
    )
    CRAWL_RESPECT_ROBOTS = os.environ.get("CRAWL_RESPECT_ROBOTS", "true").lower() in ("true", "1", "yes")
    
    # =========================================================================
    # RENDERING (Playwright)
    # =========================================================================
    USE_PLAYWRIGHT = os.environ.get("USE_PLAYWRIGHT", "true").lower() in ("true", "1", "yes")
    PLAYWRIGHT_TIMEOUT = int(os.environ.get("PLAYWRIGHT_TIMEOUT", "30"))
    PLAYWRIGHT_HEADLESS = os.environ.get("PLAYWRIGHT_HEADLESS", "true").lower() in ("true", "1", "yes")
    PLAYWRIGHT_VIEWPORT_WIDTH = int(os.environ.get("PLAYWRIGHT_VIEWPORT_WIDTH", "1280"))
    PLAYWRIGHT_VIEWPORT_HEIGHT = int(os.environ.get("PLAYWRIGHT_VIEWPORT_HEIGHT", "800"))
    PLAYWRIGHT_WAIT_TIMEOUT = int(os.environ.get("PLAYWRIGHT_WAIT_TIMEOUT", "5000"))
    
    # =========================================================================
    # SEO OPTIMIZATION
    # =========================================================================
    SEO_AUTOMATION_MODE = os.environ.get("SEO_AUTOMATION_MODE", "safe_autopilot")
    # Valid modes: analysis_only, safe_autopilot, moderate, aggressive
    
    SEO_TARGET_SCORE = float(os.environ.get("SEO_TARGET_SCORE", "95.0"))
    SEO_MIN_SCORE_IMPROVEMENT = float(os.environ.get("SEO_MIN_SCORE_IMPROVEMENT", "0.5"))
    SEO_MAX_ITERATIONS = int(os.environ.get("SEO_MAX_ITERATIONS", "3"))
    SEO_MAX_PAGES_PER_ITERATION = int(os.environ.get("SEO_MAX_PAGES_PER_ITERATION", "10"))
    SEO_MIN_WORD_COUNT = int(os.environ.get("SEO_MIN_WORD_COUNT", "250"))
    SEO_DEFAULT_TITLE_LENGTH_MIN = int(os.environ.get("SEO_DEFAULT_TITLE_LENGTH_MIN", "30"))
    SEO_DEFAULT_TITLE_LENGTH_MAX = int(os.environ.get("SEO_DEFAULT_TITLE_LENGTH_MAX", "65"))
    SEO_DEFAULT_DESC_LENGTH_MIN = int(os.environ.get("SEO_DEFAULT_DESC_LENGTH_MIN", "70"))
    SEO_DEFAULT_DESC_LENGTH_MAX = int(os.environ.get("SEO_DEFAULT_DESC_LENGTH_MAX", "170"))
    
    # =========================================================================
    # PROVIDERS
    # =========================================================================
    KEYWORD_PROVIDER = os.environ.get("KEYWORD_PROVIDER", "local")  # local, semrush, google_planner, ahrefs
    TREND_PROVIDER = os.environ.get("TREND_PROVIDER", "local")  # local, google_trends, semrush
    SEARCH_PERFORMANCE_PROVIDER = os.environ.get("SEARCH_PERFORMANCE_PROVIDER", "local")  # local, google_search_console
    COMPETITOR_PROVIDER = os.environ.get("COMPETITOR_PROVIDER", "local")  # local, semrush, ahrefs
    
    # Provider API keys
    SEMRUSH_API_KEY = os.environ.get("SEMRUSH_API_KEY", "")
    GOOGLE_PLANNER_API_KEY = os.environ.get("GOOGLE_PLANNER_API_KEY", "")
    AHREFS_API_KEY = os.environ.get("AHREFS_API_KEY", "")
    GOOGLE_SEARCH_CONSOLE_CREDENTIALS = os.environ.get("GOOGLE_SEARCH_CONSOLE_CREDENTIALS", "")
    
    # =========================================================================
    # DEPLOYMENT
    # =========================================================================
    DEPLOYMENT_STRATEGY = os.environ.get("DEPLOYMENT_STRATEGY", "auto")  # auto, manual, recommendation_only
    DEPLOYMENT_BACKUP_ENABLED = os.environ.get("DEPLOYMENT_BACKUP_ENABLED", "true").lower() in ("true", "1", "yes")
    DEPLOYMENT_VERIFY_REMOTE = os.environ.get("DEPLOYMENT_VERIFY_REMOTE", "true").lower() in ("true", "1", "yes")
    DEPLOYMENT_MAX_RETRIES = int(os.environ.get("DEPLOYMENT_MAX_RETRIES", "3"))
    DEPLOYMENT_RETRY_DELAY = int(os.environ.get("DEPLOYMENT_RETRY_DELAY", "2"))
    
    # =========================================================================
    # PATHS
    # =========================================================================
    BACKUP_DIR = ROOT / "backups"
    BACKUP_DIR.mkdir(exist_ok=True)
    
    LOG_DIR = ROOT / "logs"
    LOG_DIR.mkdir(exist_ok=True)
    
    DATA_DIR = ROOT / "data"
    DATA_DIR.mkdir(exist_ok=True)
    
    TEMP_DIR = ROOT / "temp"
    TEMP_DIR.mkdir(exist_ok=True)
    
    # =========================================================================
    # LOGGING
    # =========================================================================
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
    LOG_FILE = os.environ.get("LOG_FILE", str(LOG_DIR / "app.log"))
    LOG_FORMAT = os.environ.get(
        "LOG_FORMAT", 
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    LOG_MAX_BYTES = int(os.environ.get("LOG_MAX_BYTES", "10485760"))  # 10MB
    LOG_BACKUP_COUNT = int(os.environ.get("LOG_BACKUP_COUNT", "5"))
    
    # =========================================================================
    # CACHE
    # =========================================================================
    CACHE_ENABLED = os.environ.get("CACHE_ENABLED", "true").lower() in ("true", "1", "yes")
    CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "3600"))
    CACHE_MAX_SIZE = int(os.environ.get("CACHE_MAX_SIZE", "1000"))
    
    # =========================================================================
    # RATE LIMITING
    # =========================================================================
    RATE_LIMIT_ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes")
    RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "100"))
    RATE_LIMIT_PERIOD = int(os.environ.get("RATE_LIMIT_PERIOD", "60"))  # seconds
    
    # =========================================================================
    # MONITORING
    # =========================================================================
    MONITORING_ENABLED = os.environ.get("MONITORING_ENABLED", "true").lower() in ("true", "1", "yes")
    MONITORING_INTERVAL = int(os.environ.get("MONITORING_INTERVAL", "300"))  # seconds
    
    # =========================================================================
    # CLASS METHODS
    # =========================================================================
    
    @classmethod
    def as_dict(cls) -> Dict[str, Any]:
        """Return all configuration as a dictionary (redacting sensitive values)."""
        sensitive_keys = {
            "SECRET_KEY", "CREDENTIAL_ENCRYPTION_KEY", "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY", "HUGGINGFACE_API_KEY", "SEMRUSH_API_KEY",
            "GOOGLE_PLANNER_API_KEY", "AHREFS_API_KEY", 
            "GOOGLE_SEARCH_CONSOLE_CREDENTIALS"
        }
        
        config_dict = {}
        for key, value in vars(cls).items():
            if not key.startswith("_") and key.isupper():
                if key in sensitive_keys and value:
                    config_dict[key] = "***REDACTED***"
                else:
                    config_dict[key] = value
        return config_dict
    
    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """Get a configuration value by key."""
        return getattr(cls, key, default)
    
    @classmethod
    def is_development(cls) -> bool:
        """Check if running in development mode."""
        return os.environ.get("ENV", "development").lower() == "development"
    
    @classmethod
    def is_production(cls) -> bool:
        """Check if running in production mode."""
        return os.environ.get("ENV", "development").lower() == "production"
    
    @classmethod
    def is_testing(cls) -> bool:
        """Check if running in testing mode."""
        return os.environ.get("ENV", "development").lower() == "testing"
    
    @classmethod
    def get_environment(cls) -> str:
        """Get the current environment name."""
        return os.environ.get("ENV", "development")
    
    @classmethod
    def get_ai_provider_config(cls) -> Dict[str, Any]:
        """Get AI provider configuration."""
        config = {
            "provider": cls.AI_PROVIDER,
            "timeout": cls.AI_TIMEOUT,
            "max_retries": cls.AI_MAX_RETRIES,
        }
        
        if cls.AI_PROVIDER == "openai":
            config.update({
                "api_key": cls.OPENAI_API_KEY,
                "model": cls.OPENAI_MODEL,
                "max_tokens": cls.OPENAI_MAX_TOKENS,
                "temperature": cls.OPENAI_TEMPERATURE,
            })
        elif cls.AI_PROVIDER == "anthropic":
            config.update({
                "api_key": cls.ANTHROPIC_API_KEY,
                "model": cls.ANTHROPIC_MODEL,
                "max_tokens": cls.ANTHROPIC_MAX_TOKENS,
            })
        elif cls.AI_PROVIDER == "huggingface":
            config.update({
                "api_key": cls.HUGGINGFACE_API_KEY,
                "model": cls.HUGGINGFACE_MODEL,
            })
        elif cls.AI_PROVIDER == "ollama":
            config.update({
                "host": cls.OLLAMA_HOST,
                "model": cls.OLLAMA_MODEL,
            })
        
        return config
    
    @classmethod
    def get_crawl_config(cls) -> Dict[str, Any]:
        """Get crawl configuration."""
        return {
            "max_pages": cls.CRAWL_MAX_PAGES,
            "max_depth": cls.CRAWL_MAX_DEPTH,
            "delay_seconds": cls.CRAWL_DELAY_SECONDS,
            "timeout": cls.CRAWL_TIMEOUT,
            "user_agent": cls.CRAWL_USER_AGENT,
            "respect_robots": cls.CRAWL_RESPECT_ROBOTS,
            "use_playwright": cls.USE_PLAYWRIGHT,
            "playwright_timeout": cls.PLAYWRIGHT_TIMEOUT,
            "playwright_headless": cls.PLAYWRIGHT_HEADLESS,
        }
    
    @classmethod
    def get_seo_config(cls) -> Dict[str, Any]:
        """Get SEO optimization configuration."""
        return {
            "automation_mode": cls.SEO_AUTOMATION_MODE,
            "target_score": cls.SEO_TARGET_SCORE,
            "min_score_improvement": cls.SEO_MIN_SCORE_IMPROVEMENT,
            "max_iterations": cls.SEO_MAX_ITERATIONS,
            "max_pages_per_iteration": cls.SEO_MAX_PAGES_PER_ITERATION,
            "min_word_count": cls.SEO_MIN_WORD_COUNT,
            "title_length_min": cls.SEO_DEFAULT_TITLE_LENGTH_MIN,
            "title_length_max": cls.SEO_DEFAULT_TITLE_LENGTH_MAX,
            "desc_length_min": cls.SEO_DEFAULT_DESC_LENGTH_MIN,
            "desc_length_max": cls.SEO_DEFAULT_DESC_LENGTH_MAX,
        }
    
    @classmethod
    def get_deployment_config(cls) -> Dict[str, Any]:
        """Get deployment configuration."""
        return {
            "strategy": cls.DEPLOYMENT_STRATEGY,
            "backup_enabled": cls.DEPLOYMENT_BACKUP_ENABLED,
            "verify_remote": cls.DEPLOYMENT_VERIFY_REMOTE,
            "max_retries": cls.DEPLOYMENT_MAX_RETRIES,
            "retry_delay": cls.DEPLOYMENT_RETRY_DELAY,
        }
    
    @classmethod
    def validate(cls) -> List[str]:
        """Validate configuration and return list of issues."""
        issues = []
        
        # Check for required keys in production
        if cls.is_production():
            if cls.SECRET_KEY == "dev-secret-change-me":
                issues.append("SECRET_KEY must be changed from default in production")
            
            if cls.AI_PROVIDER == "mock" and cls.AI_PROVIDER not in ["mock", "local"]:
                issues.append("AI_PROVIDER must be configured in production")
            
            if cls.AI_PROVIDER == "openai" and not cls.OPENAI_API_KEY:
                issues.append("OPENAI_API_KEY is required when using OpenAI")
            
            if cls.AI_PROVIDER == "anthropic" and not cls.ANTHROPIC_API_KEY:
                issues.append("ANTHROPIC_API_KEY is required when using Anthropic")
        
        # Validate encryption key
        if cls.CREDENTIAL_ENCRYPTION_KEY:
            if len(cls.CREDENTIAL_ENCRYPTION_KEY) != 44:
                issues.append("CREDENTIAL_ENCRYPTION_KEY must be 44 characters (base64-encoded 32 bytes)")
        
        # Validate numeric values
        if cls.CRAWL_MAX_PAGES <= 0:
            issues.append("CRAWL_MAX_PAGES must be greater than 0")
        
        if cls.CRAWL_MAX_DEPTH <= 0:
            issues.append("CRAWL_MAX_DEPTH must be greater than 0")
        
        if cls.CRAWL_DELAY_SECONDS < 0:
            issues.append("CRAWL_DELAY_SECONDS must be non-negative")
        
        if not 0 <= cls.SEO_TARGET_SCORE <= 100:
            issues.append("SEO_TARGET_SCORE must be between 0 and 100")
        
        # Validate directories
        if not cls.BACKUP_DIR.exists():
            issues.append(f"BACKUP_DIR does not exist: {cls.BACKUP_DIR}")
        
        if not cls.LOG_DIR.exists():
            issues.append(f"LOG_DIR does not exist: {cls.LOG_DIR}")
        
        # Validate automation mode
        valid_modes = {"analysis_only", "safe_autopilot", "moderate", "aggressive"}
        if cls.SEO_AUTOMATION_MODE not in valid_modes:
            issues.append(f"SEO_AUTOMATION_MODE must be one of: {valid_modes}")
        
        return issues
    
    @classmethod
    def print_config(cls, show_sensitive: bool = False) -> None:
        """Print configuration in a readable format."""
        print("=" * 60)
        print("AI SEO Autopilot Configuration")
        print("=" * 60)
        print(f"Environment: {cls.get_environment()}")
        print(f"Database: {cls.DATABASE_URL}")
        print(f"AI Provider: {cls.AI_PROVIDER}")
        print(f"Crawl Max Pages: {cls.CRAWL_MAX_PAGES}")
        print(f"Crawl Max Depth: {cls.CRAWL_MAX_DEPTH}")
        print(f"SEO Automation Mode: {cls.SEO_AUTOMATION_MODE}")
        print(f"SEO Target Score: {cls.SEO_TARGET_SCORE}")
        print(f"Use Playwright: {cls.USE_PLAYWRIGHT}")
        print(f"Backup Directory: {cls.BACKUP_DIR}")
        print(f"Log Directory: {cls.LOG_DIR}")
        
        if show_sensitive:
            print("\n--- Sensitive Configuration ---")
            print(f"Secret Key: {cls.SECRET_KEY[:8]}...")
            if cls.OPENAI_API_KEY:
                print(f"OpenAI API Key: {cls.OPENAI_API_KEY[:10]}...")
            if cls.ANTHROPIC_API_KEY:
                print(f"Anthropic API Key: {cls.ANTHROPIC_API_KEY[:10]}...")
        
        print("\n--- Validation ---")
        issues = cls.validate()
        if issues:
            print("⚠ Issues found:")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("✓ No issues found")
        
        print("=" * 60)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_config() -> Config:
    """Get the configuration class."""
    return Config


def get_database_url() -> str:
    """Get the database URL."""
    return Config.DATABASE_URL


def is_playwright_enabled() -> bool:
    """Check if Playwright is enabled."""
    return Config.USE_PLAYWRIGHT


def get_log_level() -> str:
    """Get the log level."""
    return Config.LOG_LEVEL


def setup_logging() -> None:
    """Set up logging based on configuration."""
    import logging.config
    
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": Config.LOG_FORMAT,
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": Config.LOG_LEVEL,
                "formatter": "default",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": Config.LOG_LEVEL,
                "formatter": "default",
                "filename": Config.LOG_FILE,
                "maxBytes": Config.LOG_MAX_BYTES,
                "backupCount": Config.LOG_BACKUP_COUNT,
            },
        },
        "root": {
            "level": Config.LOG_LEVEL,
            "handlers": ["console", "file"],
        },
    }
    
    logging.config.dictConfig(log_config)
