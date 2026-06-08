# state.py — LangGraph agent state definition
# InterviewState is the single object passed through all graph nodes.
# Each node returns a partial dict — LangGraph merges it into the current state.
# TypedDict enforces structure at type-check time; extra keys are ignored at runtime.

from typing import TypedDict


class QAPair(TypedDict):
    """One question-answer pair — grows as the session progresses."""
    question_id: str          # DB-assigned after persist (empty string before persist)
    question_text: str
    sequence: int
    answer_id: str | None     # None until user answers
    transcript: str | None    # Raw STT output
    scores: dict | None       # EvaluatorNode output — None until evaluated


class InterviewState(TypedDict):
    """
    Full shared state of one interview session.
    Persisted between graph invocations via LangGraph checkpointer.

    Lifecycle:
      begin()  → graph generates Q1 → state has next_question, qa_history=[Q1]
      respond() → graph processes answer → state has last_scores, last_coach_result, next Q
      repeat until is_complete = True
    """
    session_id: str
    user_id: str
    role: str
    difficulty: str

    # Full conversation history — one QAPair per question asked
    qa_history: list[QAPair]

    # Set by generate_question_node — read by service layer to persist + return to client
    next_question: str | None

    # Set by process_answer_node — read by interviewer for routing decision
    last_scores: dict | None

    # Set by process_answer_node — stored to DB by service layer, not used for routing
    last_coach_result: dict | None

    # Question number for the NEXT question to be generated
    current_sequence: int

    # True when current_sequence > MAX_QUESTIONS — triggers END routing
    is_complete: bool