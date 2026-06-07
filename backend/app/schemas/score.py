# schemas/score.py — Pydantic shapes for score and evaluation endpoints

from datetime import datetime
from pydantic import BaseModel


class ScoreResponse(BaseModel):
    id: str
    answer_id: str
    technical_score: int
    structure_score: int
    relevance_score: int
    overall_score: int
    reasoning: str
    follow_up_needed: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class NextQuestionResponse(BaseModel):
    question_id: str
    question_text: str
    sequence: int
    topic: str | None
    