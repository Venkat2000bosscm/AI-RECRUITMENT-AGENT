import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./recruitment.db")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY") or None
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    upload_dir: str = os.getenv("UPLOAD_DIR", "./uploads")
    seed_demo_data: bool = _env_bool("SEED_DEMO_DATA", True)
    cors_origins: list[str] = field(default_factory=lambda: os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","))
    strong_match_threshold: float = float(os.getenv("STRONG_MATCH_THRESHOLD", "0.75"))
    partial_match_threshold: float = float(os.getenv("PARTIAL_MATCH_THRESHOLD", "0.5"))
    min_confidence: float = float(os.getenv("MIN_CONFIDENCE", "0.65"))
    low_application_threshold: int = int(os.getenv("LOW_APPLICATION_THRESHOLD", "5"))
    smtp_host: str | None = os.getenv("SMTP_HOST") or None
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str | None = os.getenv("SMTP_USER") or None
    smtp_password: str | None = os.getenv("SMTP_PASSWORD") or None
    smtp_from: str = os.getenv("SMTP_FROM", "recruiting@example.com")


settings = Settings()
