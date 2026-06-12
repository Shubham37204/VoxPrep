from __future__ import annotations

import json

from groq import AsyncGroq
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.models.answer import Answer
from app.models.feedback import Feedback
from app.models.question import Question
from app.models.score import Score
from app.observability.logging import get_logger
from app.repositories.answer_repository import AnswerRepository
from app.repositories.session_repository import SessionRepository

settings = get_settings()
logger = get_logger(__name__)

_REPORT_SYSTEM_PROMPT = """
You are an expert technical interview coach generating a post-interview performance report.
Given a candidate's Q&A history with scores and communication feedback, produce a structured
JSON report. Be specific, actionable, and honest — avoid generic praise.

Return ONLY valid JSON with this exact shape:
{
  "overall_score": <float 0-10>,
  "technical_summary": "<2-3 sentences on technical depth and accuracy>",
  "communication_summary": "<2-3 sentences on clarity, confidence, pace>",
  "strengths": ["<specific strength 1>", "<specific strength 2>"],
  "improvements": ["<specific area 1>", "<specific area 2>"],
  "recommended_topics": ["<topic to study>"],
  "hire_signal": "strong" | "mixed" | "weak"
}
""".strip()


class ReportService:
    """
    Generate a structured post-interview report after session completes.
    Aggregates DB data (scores + feedback) then calls LLM for narrative synthesis.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._client = AsyncGroq(api_key=settings.GROQ_API_KEY)

    async def generate(self, session_id: str) -> dict:
        """
        Build and return full session report.

        Steps:
          1. Load session + all Q/A/score/feedback rows
          2. Compute aggregate stats (avg scores, total fillers)
          3. Call LLM for narrative summary
          4. Return merged report dict

        Raises:
            ValueError: Session not found or no answers yet.
        """
        session = await SessionRepository(self._db).get_by_id(session_id)

        answer_repo = AnswerRepository(self._db)
        pairs = await answer_repo.get_answers_for_session(session_id)
        answered = [(q, a) for q, a in pairs if a is not None]

        if not answered:
            raise ValueError(f"No completed answers for session {session_id}")

        # Load scores and feedback for each answer
        qa_records = []
        total_technical = total_structure = total_relevance = total_overall = 0
        total_fillers = 0
        total_comm_score = 0
        count = len(answered)

        for q, a in answered:
            score_res = await self._db.execute(
                select(Score).where(Score.answer_id == a.id)
            )
            score = score_res.scalar_one_or_none()

            fb_res = await self._db.execute(
                select(Feedback).where(Feedback.answer_id == a.id)
            )
            feedback = fb_res.scalar_one_or_none()

            if score:
                total_technical += score.technical_score
                total_structure += score.structure_score
                total_relevance += score.relevance_score
                total_overall += score.overall_score

            if feedback:
                total_fillers += feedback.filler_count or 0
                total_comm_score += feedback.overall_communication_score or 0

            qa_records.append({
                "sequence": q.sequence,
                "question": q.text,
                "transcript": a.transcript,
                "technical_score": score.technical_score if score else None,
                "structure_score": score.structure_score if score else None,
                "overall_score": score.overall_score if score else None,
                "reasoning": score.reasoning if score else None,
                "filler_count": feedback.filler_count if feedback else None,
                "recommendations": feedback.recommendations if feedback else [],
                "pace": feedback.pace_assessment if feedback else None,
            })

        aggregate = {
            "avg_technical": round(total_technical / count, 1),
            "avg_structure": round(total_structure / count, 1),
            "avg_relevance": round(total_relevance / count, 1),
            "avg_overall": round(total_overall / count, 1),
            "avg_communication": round(total_comm_score / count, 1),
            "total_filler_words": total_fillers,
            "questions_answered": count,
        }

        # LLM narrative synthesis
        narrative = await self._synthesize_narrative(
            role=session.role,
            difficulty=session.difficulty,
            qa_records=qa_records,
            aggregate=aggregate,
        )

        return {
            "session_id": session_id,
            "role": session.role,
            "difficulty": session.difficulty,
            "aggregate": aggregate,
            **narrative,
        }

    async def _synthesize_narrative(
        self,
        role: str,
        difficulty: str,
        qa_records: list[dict],
        aggregate: dict,
    ) -> dict:
        """Call Groq LLM to generate structured narrative report."""
        user_prompt = (
            f"Role: {role} | Difficulty: {difficulty}\n"
            f"Aggregate: {json.dumps(aggregate)}\n"
            f"Q&A History:\n{json.dumps(qa_records, indent=2)}"
        )

        response = await self._client.chat.completions.create(
            model=settings.GROQ_LLM_MODEL,
            messages=[
                {"role": "system", "content": _REPORT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,     # Low temp — consistent structured output
            max_tokens=1024,
        )

        raw = response.choices[0].message.content.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "report_llm_json_parse_failed",
                session_id="unknown",
                raw_preview=raw[:200],
            )
            # Fallback — return aggregate only, skip narrative
            return {
                "overall_score": aggregate["avg_overall"],
                "technical_summary": "Report generation failed — raw scores available.",
                "communication_summary": None,
                "strengths": [],
                "improvements": [],
                "recommended_topics": [],
                "hire_signal": "mixed",
            }
        
        