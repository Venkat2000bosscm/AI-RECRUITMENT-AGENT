import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./recruitment.db")
    demo_mode: bool = _env_bool("DEMO_MODE", True)
    auto_create_schema: bool = _env_bool("AUTO_CREATE_SCHEMA", True)
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
    score_weights: dict[str, float] = field(
        default_factory=lambda: {
            "required_skills": _env_float("SCORE_WEIGHT_REQUIRED_SKILLS", 0.5),
            "preferred_skills": _env_float("SCORE_WEIGHT_PREFERRED_SKILLS", 0.15),
            "experience": _env_float("SCORE_WEIGHT_EXPERIENCE", 0.2),
            "similarity": _env_float("SCORE_WEIGHT_TEXT_RELEVANCE", 0.15),
        }
    )
    smtp_host: str | None = os.getenv("SMTP_HOST") or None
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str | None = os.getenv("SMTP_USER") or None
    smtp_password: str | None = os.getenv("SMTP_PASSWORD") or None
    smtp_from: str = os.getenv("SMTP_FROM", "recruiting@example.com")

    def __post_init__(self) -> None:
        if not self.demo_mode and self.seed_demo_data:
            raise ValueError("SEED_DEMO_DATA must be false when DEMO_MODE is false")
        if not self.demo_mode and self.auto_create_schema:
            raise ValueError("AUTO_CREATE_SCHEMA must be false when DEMO_MODE is false; run Alembic migrations explicitly")
        if not 0 <= self.strong_match_threshold <= 1:
            raise ValueError("STRONG_MATCH_THRESHOLD must be between 0 and 1")
        if not 0 <= self.partial_match_threshold <= self.strong_match_threshold:
            raise ValueError("PARTIAL_MATCH_THRESHOLD must be between 0 and STRONG_MATCH_THRESHOLD")
        if not 0 <= self.min_confidence <= 1:
            raise ValueError("MIN_CONFIDENCE must be between 0 and 1")
        if sum(self.score_weights.values()) <= 0:
            raise ValueError("At least one candidate scoring weight must be greater than zero")


settings = Settings()
