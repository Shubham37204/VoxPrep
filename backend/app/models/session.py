# session.py — SQLAlchemy ORM model for the `sessions` table
# One session = one complete interview attempt by one user for one role.

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base
from app.core.enums import SessionStatus, SessionDifficulty, InterviewRole


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Indexed — most queries filter by user_id to fetch a user's session history
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )

    # Interview configuration — set at creation, immutable after
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)

    # Status managed exclusively by SessionService — never update directly
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SessionStatus.CREATED.value
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # started_at / ended_at are nullable — session may not have started or finished yet
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Session id={self.id} status={self.status} role={self.role}>"
