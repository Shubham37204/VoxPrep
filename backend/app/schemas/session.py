from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import SessionDifficulty, InterviewRole


class SessionCreateRequest(BaseModel):
    role: InterviewRole
    difficulty: SessionDifficulty


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    role: str
    difficulty: str
    status: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    last_seen_at: datetime | None = None
    created_at: datetime | None = None

    