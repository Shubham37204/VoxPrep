import json
import re

from groq import AsyncGroq

from app.config.settings import get_settings

settings = get_settings()

_FILLER_PATTERNS: list[re.Pattern] = [
    re.compile(r'\bum+\b', re.IGNORECASE),          # um, umm, ummm
    re.compile(r'\buh+\b', re.IGNORECASE),           # uh, uhh
    re.compile(r'\byou know\b', re.IGNORECASE),      # you know
    re.compile(r'\bbasically\b', re.IGNORECASE),     # basically
    re.compile(r'\bright\?\b', re.IGNORECASE),       # right? (as a filler question)
    re.compile(r'\bkind of\b', re.IGNORECASE),       # kind of (hedging)
    re.compile(r'\bsort of\b', re.IGNORECASE),       # sort of (hedging)
]

_SYSTEM_PROMPT = """You are a communication coach evaluating how a job interview answer was delivered.
Assess communication quality ONLY — ignore technical accuracy completely.
Return ONLY valid JSON. No text outside the JSON.

Dimensions:
- clarity_score (1-10): How well-organized and easy to follow was the answer?
- confidence_score (1-10): How assertive and direct was the delivery? Penalize heavy hedging ("I think maybe", "I'm not sure but").
- pace_assessment: One of exactly these strings: "too_slow" | "appropriate" | "too_fast_or_rambling"
- recommendations: Array of 2-4 short, specific, actionable coaching tips. Reference actual patterns in the answer.
- overall_communication_score (1-10): Holistic communication quality.

Example output:
{
  "clarity_score": 6,
  "confidence_score": 5,
  "pace_assessment": "appropriate",
  "recommendations": [
    "Lead with the answer, then explain — you buried your main point.",
    "Replace hedging phrases like 'I think maybe' with direct statements.",
    "Use concrete numbers or examples to anchor abstract concepts."
  ],
  "overall_communication_score": 6
}"""


class CoachNode:
    """
    Analyzes communication quality of a spoken interview answer.
    Runs parallel to EvaluatorNode — does not block question generation.
    """

    def __init__(self) -> None:
        self._client = AsyncGroq(api_key=settings.GROQ_API_KEY)

    def _analyze_fillers(self, transcript: str) -> tuple[int, list[str]]:
        """
        Count filler word occurrences using regex (no API cost).
        Returns (total_count, list_of_found_fillers).
        """
        found: list[str] = []
        for pattern in _FILLER_PATTERNS:
            matches = pattern.findall(transcript)
            found.extend(matches)
        return len(found), found

    async def _llm_assess(self, transcript: str, filler_count: int, word_count: int) -> dict:
        """
        LLM assessment of clarity, confidence, pace, and recommendations.
        Passes filler count as context so LLM can reference it in recommendations.
        """
        user_prompt = (
            f"Candidate's answer ({word_count} words, {filler_count} filler word(s) detected):\n\n"
            f"{transcript}\n\n"
            "Assess the communication quality of this answer."
        )

        response = await self._client.chat.completions.create(
            model=settings.GROQ_LLM_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,    
            max_tokens=400,
        )

        raw = response.choices[0].message.content

        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"CoachNode: invalid JSON from LLM: {raw!r}") from exc

        required = {"clarity_score", "confidence_score", "pace_assessment", "recommendations", "overall_communication_score"}
        missing = required - set(result.keys())
        if missing:
            raise ValueError(f"CoachNode: missing fields in LLM response: {missing}")

        valid_pace = {"too_slow", "appropriate", "too_fast_or_rambling"}
        if result["pace_assessment"] not in valid_pace:
            result["pace_assessment"] = "appropriate"   

        for field in ("clarity_score", "confidence_score", "overall_communication_score"):
            result[field] = max(1, min(10, int(result[field])))

        if not isinstance(result["recommendations"], list):
            result["recommendations"] = [str(result["recommendations"])]

        return result

    async def analyze(self, transcript: str) -> dict:
        """
        Full communication analysis: filler detection + LLM assessment.

        Args:
            transcript: Raw STT output from the candidate's answer.

        Returns:
            dict with: filler_count, word_count, clarity_score, confidence_score,
                       pace_assessment, recommendations, overall_communication_score.

        Raises:
            ValueError: If LLM returns malformed or incomplete JSON.
        """
        if not transcript.strip():
            return {
                "filler_count": 0,
                "word_count": 0,
                "clarity_score": 1,
                "confidence_score": 1,
                "pace_assessment": "too_slow",
                "recommendations": ["The candidate did not provide an answer."],
                "overall_communication_score": 1,
            }

        word_count = len(transcript.split())
        filler_count, _found = self._analyze_fillers(transcript)

        llm_result = await self._llm_assess(transcript, filler_count, word_count)

        return {
            "filler_count": filler_count,
            "word_count": word_count,
            **llm_result,
        }
    