from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class QuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    text: str
    sequence: int
