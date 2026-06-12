import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


    answer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("answers.id"), nullable=False, index=True, unique=True
    )
    filler_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)     

    clarity_score: Mapped[int] = mapped_column(Integer, nullable=False)            
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False)        
    pace_assessment: Mapped[str] = mapped_column(String(30), nullable=False)      

    recommendations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    overall_communication_score: Mapped[int] = mapped_column(Integer, nullable=False) 

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Feedback answer={self.answer_id[:8]} comm={self.overall_communication_score}/10 fillers={self.filler_count}>"
    