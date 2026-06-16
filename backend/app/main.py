from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from app.agents.graph import init_interview_graph
from app.api.routes.router import router as api_router
from app.config.settings import get_settings
from app.db.engine import engine
from app.models import Base
from app.observability.logging import (
    configure_logging,
    get_logger,
)
from app.observability.tracing import (
    configure_tracing,
    shutdown_tracing,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────────
    configure_logging(log_level=settings.LOG_LEVEL)
    logger = get_logger(__name__)

    configure_tracing(
        service_name="voxprep",
        export_to_console=(settings.APP_ENV == "development"),
        endpoint=settings.OTEL_ENDPOINT if settings.is_production else None,
    )

    logger.info("voxprep_startup", env=settings.APP_ENV, version=app.version)

    if settings.APP_ENV == "development":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    # Init LangGraph with AsyncPostgresSaver.
    # Must run AFTER DB is ready — setup() creates checkpoint tables.
    # Uses a separate psycopg3 pool — independent of SQLAlchemy pool.
    await init_interview_graph(settings.PG_DSN)
    logger.info("interview_graph_initialized", checkpointer="AsyncPostgresSaver")

    yield

    # ── Shutdown ───────────────────────────────────────────────────
    shutdown_tracing()
    await engine.dispose()
    logger.info("voxprep_shutdown")


app = FastAPI(
    title="VoxPrep API",
    version="0.3.0",
    description="AI Voice Interview Coach — Backend API",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
)

app.include_router(api_router)


@app.get("/health", tags=["ops"])
async def health_check():
    """Liveness probe — Docker HEALTHCHECK and load balancer health checks."""
    return {"status": "ok", "env": settings.APP_ENV, "version": app.version}


@app.get("/metrics", tags=["ops"])
async def prometheus_metrics():
    """
    Prometheus scrape endpoint.
    Returns all registered metrics in text exposition format.
    Scraped by Prometheus server (default interval: 15s).
    Add to prometheus.yml:
      scrape_configs:
        - job_name: voxprep
          static_configs:
            - targets: ['host:8000']
    """
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
