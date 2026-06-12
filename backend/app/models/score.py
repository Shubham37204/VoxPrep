import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    answer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("answers.id"), nullable=False, index=True, unique=True
    )

    technical_score: Mapped[int] = mapped_column(Integer, nullable=False)  
    structure_score: Mapped[int] = mapped_column(Integer, nullable=False)   
    relevance_score: Mapped[int] = mapped_column(Integer, nullable=False)   

    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)

    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")

    follow_up_needed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Score answer={self.answer_id[:8]} overall={self.overall_score}/10>"
    