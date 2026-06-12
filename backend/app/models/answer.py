import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, DateTime, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (
        UniqueConstraint("question_id", name="uq_answers_question_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    question_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("questions.id"), nullable=False, index=True
    )

    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Answer id={self.id[:8]} question={self.question_id[:8]}>"
