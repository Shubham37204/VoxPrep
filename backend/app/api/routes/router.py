# router.py — Mounts all v1 sub-routers onto the /api/v1 prefix
# Add new feature routers here as phases progress.

from fastapi import APIRouter

from app.api.routes import sessions

router = APIRouter(prefix="/api/routes")

# Phase 1 / 2 routes
router.include_router(sessions.router)

# Future phases — uncomment as implemented:
# from app.api.v1 import auth, users, livekit
# router.include_router(auth.router)
# router.include_router(users.router)
# router.include_router(livekit.router)
