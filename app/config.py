"""Configuration loaded from environment variables."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


class Config:
    SECRET_KEY = os.environ.get("APP_SECRET_KEY", "dev-secret-change-me")

    DATABASE_URL = os.environ.get(
        "DATABASE_URL", f"sqlite:///{(ROOT / 'ai_seo.db').as_posix()}"
    )

    CREDENTIAL_ENCRYPTION_KEY = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "")

    AI_PROVIDER = os.environ.get("AI_PROVIDER", "mock")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    HUGGINGFACE_API_KEY = os.environ.get("HUGGINGFACE_API_KEY", "")
    AI_MODEL = os.environ.get("AI_MODEL", "user052/EDIATH-Q4_K_M")

    CRAWL_MAX_PAGES = int(os.environ.get("CRAWL_MAX_PAGES", "50"))
    CRAWL_MAX_DEPTH = int(os.environ.get("CRAWL_MAX_DEPTH", "3"))
    CRAWL_DELAY_SECONDS = float(os.environ.get("CRAWL_DELAY_SECONDS", "0.5"))

    SEO_AUTOMATION_MODE = os.environ.get("SEO_AUTOMATION_MODE", "safe_autopilot")

    BACKUP_DIR = ROOT / "backups"
    BACKUP_DIR.mkdir(exist_ok=True)

    @classmethod
    def as_dict(cls):
        return {k: v for k, v in vars(cls).items() if not k.startswith("_") and k.isupper()}