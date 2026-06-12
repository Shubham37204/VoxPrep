import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=False, index=True
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)

    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    asked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Question id={self.id[:8]} seq={self.sequence}>"
