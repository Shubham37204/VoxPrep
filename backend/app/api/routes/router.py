# router.py — Mounts all sub-routers onto the /api/routes prefix
from fastapi import APIRouter
from app.api.routes import sessions

router = APIRouter(prefix="/api/routes")
router.include_router(sessions.router)