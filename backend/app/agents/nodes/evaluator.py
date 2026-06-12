import json

from groq import AsyncGroq

from app.config.settings import get_settings

settings = get_settings()

_SYSTEM_PROMPT = """You are an expert technical interviewer scoring a candidate's answer.
Return ONLY a valid JSON object. No explanation outside the JSON.

Scoring scale: 1 (very poor) to 10 (exceptional)

Dimensions:
- technical_score: accuracy and depth of technical knowledge shown
- structure_score: clarity, organization, use of concrete examples
- relevance_score: how directly the answer addresses what was asked
- overall_score: your holistic assessment (not a simple average)
- reasoning: 2-3 sentences explaining the scores honestly
- follow_up_needed: true if overall_score < 6 and the topic deserves a follow-up probe

Example output:
{
  "technical_score": 7,
  "structure_score": 5,
  "relevance_score": 8,
  "overall_score": 7,
  "reasoning": "Candidate showed solid understanding of indexing mechanics but skipped composite index trade-offs. Structure was loose — answer jumped between points without examples.",
  "follow_up_needed": false
}"""


class EvaluatorNode:
    """
    Scores one candidate answer and returns structured feedback.
    Used as a LangGraph node in Phase 5 — works independently in Phase 3.
    """

    def __init__(self) -> None:
        self._client = AsyncGroq(api_key=settings.GROQ_API_KEY)

    async def evaluate(
        self,
        question: str,
        transcript: str,
        role: str,
        difficulty: str,
    ) -> dict:
        """
        Score a candidate answer via Groq LLM.

        Args:
            question:   The question that was asked (for context).
            transcript: The candidate's spoken answer (raw STT output).
            role:       Job role — e.g. "backend", "ml_engineer".
            difficulty: Session difficulty — e.g. "medium".

        Returns:
            dict with keys: technical_score, structure_score, relevance_score,
                            overall_score, reasoning, follow_up_needed.

        Raises:
            ValueError: If LLM returns malformed JSON or missing required fields.
        """
        if not transcript.strip():
            return {
                "technical_score": 1,
                "structure_score": 1,
                "relevance_score": 1,
                "overall_score": 1,
                "reasoning": "No answer was provided by the candidate.",
                "follow_up_needed": True,
            }

        user_prompt = (
            f"Role: {role} | Difficulty: {difficulty}\n\n"
            f"Question asked:\n{question}\n\n"
            f"Candidate's answer:\n{transcript}\n\n"
            "Score this answer."
        )

        response = await self._client.chat.completions.create(
            model=settings.GROQ_LLM_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,   
            max_tokens=400,
        )

        raw = response.choices[0].message.content

        try:
            scores = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"EvaluatorNode: invalid JSON from LLM: {raw!r}") from exc

        required = {"technical_score", "structure_score", "relevance_score", "overall_score", "reasoning"}
        missing = required - set(scores.keys())
        if missing:
            raise ValueError(f"EvaluatorNode: LLM response missing fields: {missing}. Got: {scores}")

        for field in ("technical_score", "structure_score", "relevance_score", "overall_score"):
            scores[field] = max(1, min(10, int(scores[field])))

        scores.setdefault("follow_up_needed", scores["overall_score"] < 6)

        return scores
    