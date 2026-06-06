# engine.py — Async SQLAlchemy engine and session factory
# One engine per process — shared across all requests via connection pool.
# DO NOT create a new engine per request — that defeats connection pooling entirely.

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import get_settings

settings = get_settings()

# Global async engine — pooled connections to PostgreSQL via asyncpg
engine = create_async_engine(
    str(settings.DATABASE_URL),
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    # Log SQL only in development — never in production (leaks schema + query data)
    echo=settings.APP_ENV == "development",
    # pool_pre_ping=True sends a lightweight SELECT 1 before each checkout
    # to discard stale connections after DB restarts
    pool_pre_ping=True,
)

# Session factory — call this to obtain a new AsyncSession per request
AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    # expire_on_commit=False: keep ORM objects usable after commit
    # Without this, accessing obj.id after commit triggers a lazy load — broken in async
    expire_on_commit=False,
)
