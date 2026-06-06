# answer_repository.py — Database reads and writes for questions and answers
#
# Both Question and Answer are here because they are tightly coupled:
# an answer cannot exist without a question, and they're always queried together.

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.answer import Answer
from app.models.question import Question


class AnswerRepository:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_question(self, session_id: str, text: str, sequence: int) -> Question:
        """Insert a new question row for a session."""
        question = Question(
            id=str(uuid.uuid4()),
            session_id=session_id,
            text=text,
            sequence=sequence,
        )
        self._db.add(question)
        await self._db.commit()
        await self._db.refresh(question)
        return question

    async def create_answer(
        self,
        question_id: str,
        transcript: str,
        latency_ms: int | None = None,
    ) -> Answer:
        """Insert a transcript as an answer to a question."""
        answer = Answer(
            id=str(uuid.uuid4()),
            question_id=question_id,
            transcript=transcript,
            latency_ms=latency_ms,
        )
        self._db.add(answer)
        await self._db.commit()
        await self._db.refresh(answer)
        return answer

    async def get_answers_for_session(self, session_id: str) -> list[tuple[Question, Answer | None]]:
        """
        Fetch all questions for a session with their answers (if any).
        Returns pairs — a question may not have an answer yet (user hasn't spoken).
        """
        result = await self._db.execute(
            select(Question)
            .where(Question.session_id == session_id)
            .order_by(Question.sequence)
        )
        questions = result.scalars().all()

        # Fetch answers for all question IDs in one query — avoids N+1
        question_ids = [q.id for q in questions]
        if not question_ids:
            return []

        answer_result = await self._db.execute(
            select(Answer).where(Answer.question_id.in_(question_ids))
        )
        # Build lookup dict: question_id → Answer
        answer_map: dict[str, Answer] = {a.question_id: a for a in answer_result.scalars().all()}

        return [(q, answer_map.get(q.id)) for q in questions]
