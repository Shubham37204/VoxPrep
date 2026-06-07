# state.py — LangGraph agent state definition
# InterviewState is the single shared object passed between all nodes in the graph.
# Every node reads from state and returns a partial update — LangGraph merges them.
# TypedDict enforces structure — no arbitrary keys silently added.

from typing import TypedDict


class QAPair(TypedDict):
    """One question-answer pair from the session history."""
    question_id: str
    question_text: str
    sequence: int
    answer_id: str | None        # None if question was asked but not yet answered
    transcript: str | None       # Raw STT output
    scores: dict | None          # EvaluatorNode output — None until evaluated


class InterviewState(TypedDict):
    """
    Full state of one interview session passed through the LangGraph pipeline.

    Flow:
        InterviewerNode sets next_question
        → user speaks → STT produces transcript
        → EvaluatorNode (main path) and CoachNode (parallel path) process transcript
        → EvaluatorNode updates last_scores, qa_history
        → InterviewerNode generates next question based on scores
        → repeat until is_complete = True
    """
    session_id: str
    user_id: str
    role: str              # e.g. "backend"
    difficulty: str        # e.g. "medium"

    # Full conversation history — grows each round
    qa_history: list[QAPair]

    # Set by InterviewerNode — cleared after question is stored in DB
    next_question: str | None

    # Set by EvaluatorNode — read by InterviewerNode to decide follow-up vs new topic
    last_scores: dict | None

    # Current question number (1-indexed)
    current_sequence: int

    # Set to True when session reaches its question limit or COMPLETED status
    is_complete: bool
    