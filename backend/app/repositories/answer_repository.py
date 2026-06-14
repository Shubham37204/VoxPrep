import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.answer import Answer
from app.models.question import Question
from app.models.score import Score


class AnswerRepository:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_question(
        self,
        session_id: str,
        text: str,
        sequence: int,
        commit: bool = True,
    ) -> Question:
        """Insert a new question row for a session."""
        question = Question(
            id=str(uuid.uuid4()),
            session_id=session_id,
            text=text,
            sequence=sequence,
        )
        self._db.add(question)
        await self._db.flush()
        if commit:
            await self._db.commit()
            await self._db.refresh(question)
        return question

    async def get_question_by_id(self, question_id: str) -> Question | None:
        """Fetch a question by primary key."""
        result = await self._db.execute(
            select(Question).where(Question.id == question_id)
        )
        return result.scalar_one_or_none()

    async def create_answer(
        self,
        question_id: str,
        transcript: str,
        latency_ms: int | None = None,
        commit: bool = True,
    ) -> Answer:
        """Insert a transcript as an answer to a question."""
        answer = Answer(
            id=str(uuid.uuid4()),
            question_id=question_id,
            transcript=transcript,
            latency_ms=latency_ms,
        )
        self._db.add(answer)
        await self._db.flush()
        if commit:
            await self._db.commit()
            await self._db.refresh(answer)
        return answer

    async def get_answer_by_id(self, answer_id: str) -> Answer | None:
        """Fetch an answer by primary key."""
        result = await self._db.execute(
            select(Answer).where(Answer.id == answer_id)
        )
        return result.scalar_one_or_none()

    async def create_score(
        self,
        answer_id: str,
        scores: dict,
        commit: bool = True,
    ) -> Score:
        """
        Persist EvaluatorNode output as a Score row.
        scores dict must contain: technical_score, structure_score, relevance_score,
        overall_score, reasoning. follow_up_needed is optional (defaults False).
        """
        score = Score(
            id=str(uuid.uuid4()),
            answer_id=answer_id,
            technical_score=scores["technical_score"],
            structure_score=scores["structure_score"],
            relevance_score=scores["relevance_score"],
            overall_score=scores["overall_score"],
            reasoning=scores.get("reasoning", ""),
            follow_up_needed=scores.get("follow_up_needed", False),
        )
        self._db.add(score)
        await self._db.flush()
        if commit:
            await self._db.commit()
            await self._db.refresh(score)
        return score

    async def get_score_by_answer(self, answer_id: str) -> Score | None:
        """Fetch the score for a given answer."""
        result = await self._db.execute(
            select(Score).where(Score.answer_id == answer_id)
        )
        return result.scalar_one_or_none()

    async def get_answers_for_session(self, session_id: str) -> list[tuple[Question, Answer | None]]:
        """
        Fetch all questions for a session with their answers.
        Returns ordered by sequence. Answer may be None if not yet received.
        Uses 2 queries (not N+1).
        """
        result = await self._db.execute(
            select(Question)
            .where(Question.session_id == session_id)
            .order_by(Question.sequence)
        )
        questions = result.scalars().all()

        if not questions:
            return []

        question_ids = [q.id for q in questions]
        answer_result = await self._db.execute(
            select(Answer).where(Answer.question_id.in_(question_ids))
        )
        answer_map: dict[str, Answer] = {a.question_id: a for a in answer_result.scalars().all()}

        return [(q, answer_map.get(q.id)) for q in questions]

    async def delete_answer(self, answer_id: str) -> None:
        """
        Delete an answer row — used by compensating transaction in SessionOrchestrationService.
        Called when graph fails after Phase 1 commit, to avoid orphaned answers.
        No commit=False variant needed — compensating tx always commits immediately.
        """
        from sqlalchemy import delete as sa_delete
        await self._db.execute(
            sa_delete(Answer).where(Answer.id == answer_id)
        )
        await self._db.commit()