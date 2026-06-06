# answer.py — SQLAlchemy model for the `answers` table
# One answer = one user response to one question.
# transcript is the raw STT output from Groq Whisper.
# latency_ms tracks time from audio-end to transcript-ready — key UX metric.

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # FK to questions — not sessions — because scores and feedback are per-answer, not per-session
    question_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("questions.id"), nullable=False, index=True
    )

    # Raw transcript from Whisper — exactly as returned, no cleaning applied yet
    transcript: Mapped[str] = mapped_column(Text, nullable=False)

    # Time from audio submission to transcript response — NULL if not yet measured
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Answer id={self.id[:8]} len={len(self.transcript)}>"
