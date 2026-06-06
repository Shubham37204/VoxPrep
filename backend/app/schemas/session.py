# schemas/session.py — Pydantic request and response shapes for session endpoints
# These are NOT the ORM models — they define what goes in and out of the API.
# Separation prevents accidentally exposing internal DB fields (hashed_password, etc.)

from datetime import datetime
from pydantic import BaseModel
from app.core.enums import SessionDifficulty, InterviewRole, SessionStatus


class SessionCreateRequest(BaseModel):
    # What the client sends when creating a new session
    role: InterviewRole
    difficulty: SessionDifficulty


class SessionResponse(BaseModel):
    # What the API returns — never expose user_id or internal fields
    id: str
    role: str
    difficulty: str
    status: str
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None

    model_config = {"from_attributes": True}   # Allows building from SQLAlchemy ORM objects


class SessionStatusUpdateRequest(BaseModel):
    # Explicit status update endpoint — used for pause/resume/complete
    new_status: SessionStatus
