# main.py — FastAPI application factory
# Lifespan: creates/disposes DB engine around server lifetime.
# Router: mounts all v1 API routes under /api/v1.

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import router as api_v1_router
from app.config.settings import get_settings
from app.db.engine import engine
from app.models import Base

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────
    # Create all tables if they don't exist — for development convenience
    # In production, use Alembic migrations instead (never create_all in prod)
    if settings.APP_ENV == "development":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    yield

    # ── Shutdown ──────────────────────────────────────────────────
    # Dispose engine — closes all pooled connections cleanly
    await engine.dispose()


app = FastAPI(
    title="VoxPrep API",
    version="0.2.0",
    description="AI Voice Interview Coach — Backend API",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
)

# Mount all versioned API routes
app.include_router(api_v1_router)


@app.get("/health", tags=["ops"])
async def health_check():
    # Liveness probe — used by Docker HEALTHCHECK and load balancer health checks
    return {"status": "ok", "env": settings.APP_ENV, "version": app.version}
