# schemas/answer.py — Pydantic shapes for question and answer endpoints

from datetime import datetime
from pydantic import BaseModel


class QuestionResponse(BaseModel):
    id: str
    session_id: str
    text: str
    sequence: int
    asked_at: datetime

    model_config = {"from_attributes": True}


class AnswerResponse(BaseModel):
    id: str
    question_id: str
    transcript: str
    latency_ms: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TranscribeResponse(BaseModel):
    # Returned after submitting audio to the /transcribe endpoint
    transcript: str
    latency_ms: int
    answer_id: str          # FK stored in DB — client can use this to poll scores later
