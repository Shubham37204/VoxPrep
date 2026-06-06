# session_event.py — Phase 1 model (event log)
# Stores every significant event in a session for audit + debugging
# Not wired up yet — filled in alongside session_service

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import String, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class SessionEvent(Base):
    __tablename__ = "session_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Indexed — all event lookups are by session_id (e.g. "show me all events for session X")
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=False, index=True
    )

    # Event type from SessionEventType enum — stored as string for readability in raw SQL
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Flexible JSON payload — each event type has a different shape
    # Example: {"question_id": "abc", "sequence": 3} for QUESTION_ASKED
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
