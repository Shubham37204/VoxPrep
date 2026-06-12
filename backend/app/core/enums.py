from enum import Enum


class SessionStatus(str, Enum):
    CREATED = "created"       # Initialized, not yet started
    ACTIVE = "active"         # Interview in progress
    PAUSED = "paused"         # Temporarily paused by user
    RETRYING = "retrying"     # Transient failure — retrying LLM/STT, not yet dead
    COMPLETED = "completed"   # Finished normally — terminal
    FAILED = "failed"         # Unrecoverable failure — terminal

ALLOWED_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.CREATED:   {SessionStatus.ACTIVE, SessionStatus.FAILED},
    SessionStatus.ACTIVE:    {SessionStatus.PAUSED, SessionStatus.RETRYING,
                              SessionStatus.COMPLETED, SessionStatus.FAILED},
    SessionStatus.PAUSED:    {SessionStatus.ACTIVE, SessionStatus.FAILED},
    SessionStatus.RETRYING:  {SessionStatus.ACTIVE, SessionStatus.FAILED},
    SessionStatus.COMPLETED: set(), 
    SessionStatus.FAILED:    set(),  
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
    SESSION_RETRYING = "session_retrying"     
    SESSION_COMPLETED = "session_completed"
    SESSION_FAILED = "session_failed"
    QUESTION_ASKED = "question_asked"
    ANSWER_RECEIVED = "answer_received"
    SCORE_GENERATED = "score_generated"
    COACH_INTERVENTION = "coach_intervention"
    RETRY_SUCCEEDED = "retry_succeeded"        
    RETRY_EXHAUSTED = "retry_exhausted"        
