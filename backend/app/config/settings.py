# settings.py — Single source of truth for all configuration
# pydantic-settings reads values from environment variables (or .env file).
# All services import settings via get_settings() — never read os.environ directly.

from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    # ── Application ───────────────────────────────────────────────
    APP_ENV: str = "development"       # Controls behavior like debug mode, log verbosity
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    SECRET_KEY: str                    # General-purpose signing key — must be secret in prod

    # ── Database ──────────────────────────────────────────────────
    DATABASE_URL: str                  # Full async DSN: postgresql+asyncpg://user:pass@host/db
    DATABASE_POOL_SIZE: int = 10       # Persistent connections per worker process
    DATABASE_MAX_OVERFLOW: int = 20    # Extra connections allowed when pool is full

    # ── Redis ─────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── Groq ──────────────────────────────────────────────────────
    GROQ_API_KEY: str
    GROQ_LLM_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_WHISPER_MODEL: str = "whisper-large-v3-turbo"

    # ── ElevenLabs ────────────────────────────────────────────────
    ELEVENLABS_API_KEY: str
    ELEVENLABS_VOICE_ID: str = "21m00Tcm4TlvDq8ikWAM"   # Rachel voice — default interviewer voice

    # ── LiveKit ───────────────────────────────────────────────────
    LIVEKIT_URL: str = "ws://localhost:7880"
    LIVEKIT_API_KEY: str = "devkey"
    LIVEKIT_API_SECRET: str = "secret"

    # ── JWT Auth ──────────────────────────────────────────────────
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # ── Observability ─────────────────────────────────────────────
    OTEL_ENDPOINT: str = "http://localhost:4317"
    LOG_LEVEL: str = "INFO"

    @field_validator("APP_ENV")
    @classmethod
    def validate_env(cls, v: str) -> str:
        # Reject invalid APP_ENV values early — prevents misconfigured deployments
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"APP_ENV must be one of {allowed}")
        return v

    model_config = SettingsConfigDict(
        env_file=".env",            # Load from .env file when running locally
        env_file_encoding="utf-8",
        case_sensitive=True,        # GROQ_API_KEY != groq_api_key
        extra="ignore",             # Silently ignore extra env vars (e.g. shell vars)
    )

    @property
    def is_production(self) -> bool:
        # Convenience check — used to gate features like detailed error responses
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    # lru_cache ensures .env is read once per process — not on every function call
    return Settings()
