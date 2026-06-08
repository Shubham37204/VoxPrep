# enums.py — All application-wide enums and state machine definitions

from enum import Enum


class SessionStatus(str, Enum):
    CREATED = "created"       # Initialized, not yet started
    ACTIVE = "active"         # Interview in progress
    PAUSED = "paused"         # Temporarily paused by user
    RETRYING = "retrying"     # Transient failure — retrying LLM/STT, not yet dead
    COMPLETED = "completed"   # Finished normally — terminal
    FAILED = "failed"         # Unrecoverable failure — terminal


# Retry is a recoverable intermediate state — transitions back to ACTIVE on success,
# to FAILED only after max retries exhausted.
ALLOWED_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.CREATED:   {SessionStatus.ACTIVE, SessionStatus.FAILED},
    SessionStatus.ACTIVE:    {SessionStatus.PAUSED, SessionStatus.RETRYING,
                              SessionStatus.COMPLETED, SessionStatus.FAILED},
    SessionStatus.PAUSED:    {SessionStatus.ACTIVE, SessionStatus.FAILED},
    # Retry succeeded or gave up
    SessionStatus.RETRYING:  {SessionStatus.ACTIVE, SessionStatus.FAILED},
    SessionStatus.COMPLETED: set(),   # Terminal
    SessionStatus.FAILED:    set(),   # Terminal
}


class SessionDifficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class InterviewRole(str, Enum):
    FRONTEND = "frontend"
    BACKEND = "backend"
    FULLSTACK = "fullstack"
    DATA_ENGINEER = "data_engineer"
    ML_ENGINEER = "ml_engineer"
    DEVOPS = "devops"
    SYSTEM_DESIGN = "system_design"


class SessionEventType(str, Enum):
    SESSION_CREATED = "session_created"
    SESSION_STARTED = "session_started"
    SESSION_PAUSED = "session_paused"
    SESSION_RESUMED = "session_resumed"
    SESSION_RETRYING = "session_retrying"       # Transient failure, retrying
    SESSION_COMPLETED = "session_completed"
    SESSION_FAILED = "session_failed"
    QUESTION_ASKED = "question_asked"
    ANSWER_RECEIVED = "answer_received"
    SCORE_GENERATED = "score_generated"
    COACH_INTERVENTION = "coach_intervention"
    RETRY_SUCCEEDED = "retry_succeeded"         # Retry resolved successfully
    RETRY_EXHAUSTED = "retry_exhausted"         # All retries used up
