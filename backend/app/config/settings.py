from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    SECRET_KEY: str

    # SQLAlchemy format: postgresql+asyncpg://user:pass@host/db
    DATABASE_URL: str
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    QDRANT_URL: str

    GROQ_API_KEY: str
    GROQ_LLM_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_WHISPER_MODEL: str = "whisper-large-v3-turbo"

    ELEVENLABS_API_KEY: str
    ELEVENLABS_VOICE_ID: str = "21m00Tcm4TlvDq8ikWAM"

    LIVEKIT_URL: str = "ws://localhost:7880"
    LIVEKIT_API_KEY: str = "devkey"
    LIVEKIT_API_SECRET: str = "secret"

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    OTEL_ENDPOINT: str = "http://localhost:4317"
    LOG_LEVEL: str = "INFO"

    @field_validator("APP_ENV")
    @classmethod
    def validate_env(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"APP_ENV must be one of {allowed}")
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def PG_DSN(self) -> str:
        """
        psycopg3-compatible connection string for AsyncPostgresSaver.

        SQLAlchemy uses dialect prefixes (postgresql+asyncpg://) that psycopg3
        doesn't understand — it expects a plain postgresql:// DSN.

        This property strips any SQLAlchemy dialect suffix so both drivers
        can share a single DATABASE_URL env var without duplication.
        """
        url = self.DATABASE_URL
        # Handle both postgresql+asyncpg:// and postgresql+psycopg://
        if "+asyncpg" in url:
            return url.replace("postgresql+asyncpg://", "postgresql://")
        if "+psycopg" in url:
            return url.replace("postgresql+psycopg://", "postgresql://")
        # Already plain postgresql:// — passthrough
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()