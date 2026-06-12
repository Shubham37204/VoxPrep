from datetime import datetime
from pydantic import BaseModel


class FeedbackResponse(BaseModel):
    id: str
    answer_id: str
    filler_count: int
    word_count: int
    clarity_score: int
    confidence_score: int
    pace_assessment: str
    recommendations: list[str]
    overall_communication_score: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionCommunicationSummary(BaseModel):
    avg_clarity_score: float
    avg_confidence_score: float
    avg_communication_score: float
    total_filler_count: int
    total_word_count: int
    filler_rate_percent: float