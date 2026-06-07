# interviewer.py — InterviewerNode: generates the next interview question
#
# INPUT:  role, difficulty, qa_history, last_scores, sequence number
# OUTPUT: dict with question text, topic, reasoning
#
# Key routing logic (pre-LangGraph):
#   overall_score < 6 → probe same topic (follow-up)
#   overall_score >= 6 → move to new topic
#   sequence == 1 → no history, pick opening question
#
# temperature=0.7 — questions should vary across sessions, not be identical every time

import json

from groq import AsyncGroq

from app.config.settings import get_settings

settings = get_settings()

_SYSTEM_PROMPT_TEMPLATE = """You are an expert technical interviewer for a {role} position at {difficulty} difficulty.
Your job is to generate the next interview question.
Return ONLY a valid JSON object. No text outside the JSON.

Rules:
- If the last answer scored below 6 overall OR follow_up_needed is true: probe the same topic deeper
- If scored 6 or above: move to a new, related technical topic
- For first question: pick a foundational topic appropriate for {role} at {difficulty} level
- Vary question types: conceptual, scenario-based, system design, debugging, trade-offs
- Never repeat a question already asked in the history
- Questions must be clear, specific, and answerable verbally in 2-3 minutes

Return format:
{{
  "question": "the full question text — phrased naturally as a spoken interviewer would ask",
  "topic": "brief label for the technical area (e.g. 'database indexing', 'REST API design')",
  "reasoning": "one sentence: why you chose this question given the context"
}}"""


class InterviewerNode:
    """
    Generates contextual interview questions based on session history and last score.
    Used as a LangGraph node in Phase 5 — works independently in Phase 3.
    """

    def __init__(self) -> None:
        self._client = AsyncGroq(api_key=settings.GROQ_API_KEY)

    async def generate_question(
        self,
        role: str,
        difficulty: str,
        sequence: int,
        qa_history: list[dict],
        last_scores: dict | None = None,
    ) -> dict:
        """
        Generate the next interview question.

        Args:
            role:        Job role — e.g. "backend".
            difficulty:  Session difficulty — e.g. "medium".
            sequence:    Which question number this is (1-indexed).
            qa_history:  List of QAPair dicts from InterviewState.
            last_scores: EvaluatorNode output from the last answer, or None if first question.

        Returns:
            dict with keys: question, topic, reasoning.

        Raises:
            ValueError: If LLM returns malformed JSON or missing 'question' field.
        """
        # Build conversation history context for the LLM
        history_lines = []
        for qa in qa_history:
            history_lines.append(f"Q{qa['sequence']}: {qa['question_text']}")
            if qa.get("transcript"):
                history_lines.append(f"A{qa['sequence']}: {qa['transcript']}")
                if qa.get("scores"):
                    history_lines.append(f"Score: {qa['scores'].get('overall_score', '?')}/10")
            history_lines.append("")

        history_text = "\n".join(history_lines).strip() or "(no previous questions)"

        score_context = ""
        if last_scores:
            overall = last_scores.get("overall_score", "?")
            follow_up = last_scores.get("follow_up_needed", False)
            score_context = (
                f"\nLast answer score: {overall}/10"
                + (" — follow-up needed on same topic" if follow_up else " — move to new topic")
            )

        user_prompt = (
            f"Role: {role} | Difficulty: {difficulty} | Generating question #{sequence}"
            f"{score_context}\n\n"
            f"Conversation history:\n{history_text}\n\n"
            f"Generate question #{sequence}."
        )

        response = await self._client.chat.completions.create(
            model=settings.GROQ_LLM_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT_TEMPLATE.format(role=role, difficulty=difficulty)},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,    # Higher than evaluator — questions should vary
            max_tokens=300,
        )

        raw = response.choices[0].message.content

        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"InterviewerNode: invalid JSON from LLM: {raw!r}") from exc

        if "question" not in result:
            raise ValueError(f"InterviewerNode: 'question' field missing. Got: {result}")

        result.setdefault("topic", "general")
        result.setdefault("reasoning", "")

        return result
    