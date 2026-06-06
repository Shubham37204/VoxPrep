# enums.py — All application-wide enums and state machine definitions
# Centralizing enums prevents magic strings scattered across models, services, and APIs.
# Import from here — never hardcode string literals like "active" in other files.

from enum import Enum


class SessionStatus(str, Enum):
    # str mixin allows direct DB storage and JSON serialization without extra conversion
    CREATED = "created"        # Session initialized, user has not spoken yet
    ACTIVE = "active"          # Interview is live — questions being asked
    PAUSED = "paused"          # User paused mid-session
    COMPLETED = "completed"    # All questions answered, session ended normally
    FAILED = "failed"          # Terminated due to error (timeout, STT failure, etc.)


# Allowed state transitions — SessionService MUST validate against this before any status update.
# A transition not in this map is a bug, not a user error — raise an exception, not a 400.
ALLOWED_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.CREATED:   {SessionStatus.ACTIVE, SessionStatus.FAILED},
    SessionStatus.ACTIVE:    {SessionStatus.PAUSED, SessionStatus.COMPLETED, SessionStatus.FAILED},
    SessionStatus.PAUSED:    {SessionStatus.ACTIVE, SessionStatus.FAILED},
    SessionStatus.COMPLETED: set(),   # Terminal — no further transitions permitted
    SessionStatus.FAILED:    set(),   # Terminal — no further transitions permitted
}


class SessionDifficulty(str, Enum):
    EASY = "easy"         # Conceptual questions, no follow-ups
    MEDIUM = "medium"     # Mixed — concepts + light implementation
    HARD = "hard"         # System design, deep dives, edge case probing


class InterviewRole(str, Enum):
    FRONTEND = "frontend"
    BACKEND = "backend"
    FULLSTACK = "fullstack"
    DATA_ENGINEER = "data_engineer"
    ML_ENGINEER = "ml_engineer"
    DEVOPS = "devops"
    SYSTEM_DESIGN = "system_design"


class SessionEventType(str, Enum):
    # Event types stored in session_events table — used for debugging and audit trail
    SESSION_CREATED = "session_created"
    SESSION_STARTED = "session_started"
    SESSION_PAUSED = "session_paused"
    SESSION_RESUMED = "session_resumed"
    SESSION_COMPLETED = "session_completed"
    SESSION_FAILED = "session_failed"
    QUESTION_ASKED = "question_asked"
    ANSWER_RECEIVED = "answer_received"
    SCORE_GENERATED = "score_generated"
    COACH_INTERVENTION = "coach_intervention"   # Coach detected issue (filler words, silence, etc.)
