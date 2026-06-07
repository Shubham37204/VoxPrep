# feedback_repository.py — DB reads and writes for communication feedback
# Kept separate from answer_repository — feedback has its own query patterns
# (session summaries, aggregate stats) that would clutter AnswerRepository.

import uuid
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import Feedback


class FeedbackRepository:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, answer_id: str, data: dict) -> Feedback:
        """
        Persist CoachNode output as a Feedback row.
        data must contain all required keys from CoachNode.analyze() output.
        """
        feedback = Feedback(
            id=str(uuid.uuid4()),
            answer_id=answer_id,
            filler_count=data["filler_count"],
            word_count=data["word_count"],
            clarity_score=data["clarity_score"],
            confidence_score=data["confidence_score"],
            pace_assessment=data["pace_assessment"],
            recommendations=data["recommendations"],
            overall_communication_score=data["overall_communication_score"],
        )
        self._db.add(feedback)
        await self._db.commit()
        await self._db.refresh(feedback)
        return feedback

    async def get_by_answer(self, answer_id: str) -> Feedback | None:
        """Fetch feedback for a specific answer."""
        result = await self._db.execute(
            select(Feedback).where(Feedback.answer_id == answer_id)
        )
        return result.scalar_one_or_none()

    async def get_session_communication_summary(self, answer_ids: list[str]) -> dict:
        """
        Aggregate communication metrics across all answers in a session.
        Called by report generation (Phase 6 Celery task) — not per-answer.

        Returns dict with avg scores, total fillers, dominant pace pattern.
        Computes from DB — avoids loading all Feedback objects into memory.
        """
        if not answer_ids:
            return {}

        result = await self._db.execute(
            select(
                func.avg(Feedback.clarity_score).label("avg_clarity"),
                func.avg(Feedback.confidence_score).label("avg_confidence"),
                func.avg(Feedback.overall_communication_score).label("avg_comm"),
                func.sum(Feedback.filler_count).label("total_fillers"),
                func.sum(Feedback.word_count).label("total_words"),
            ).where(Feedback.answer_id.in_(answer_ids))
        )
        row = result.one_or_none()
        if not row:
            return {}

        return {
            "avg_clarity_score": round(float(row.avg_clarity or 0), 1),
            "avg_confidence_score": round(float(row.avg_confidence or 0), 1),
            "avg_communication_score": round(float(row.avg_comm or 0), 1),
            "total_filler_count": int(row.total_fillers or 0),
            "total_word_count": int(row.total_words or 0),
            # Filler rate: what % of words were fillers — useful metric
            "filler_rate_percent": round(
                (int(row.total_fillers or 0) / max(int(row.total_words or 1), 1)) * 100, 1
            ),
        }