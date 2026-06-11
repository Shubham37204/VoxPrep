# sessions.py 
# BUG FIX #9: POST /sessions/{id}/heartbeat — updates last_seen_at
# BUG FIX #2: GET  /sessions/{id}/state — backend resume, no frontend storage needed

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError                       # FIX: top-level import
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.nodes.coach import CoachNode
from app.agents.nodes.evaluator import EvaluatorNode
from app.agents.nodes.interviewer import InterviewerNode
from app.api.deps import get_db
from app.core.enums import SessionStatus
from app.core.exceptions import InvalidStateTransitionError, SessionNotFoundError
from app.models.question import Question
from app.models.answer import Answer
from app.models.session_event import SessionEvent
from app.repositories.answer_repository import AnswerRepository
from app.repositories.feedback_repository import FeedbackRepository
from app.repositories.session_repository import SessionRepository
from app.schemas.answer import TranscribeResponse
from app.schemas.feedback import FeedbackResponse, SessionCommunicationSummary
from app.schemas.score import NextQuestionResponse, ScoreResponse
from app.schemas.session import SessionCreateRequest, SessionResponse
from app.services.session_service import SessionOrchestrationService

router = APIRouter(prefix="/sessions", tags=["sessions"])

_evaluator = EvaluatorNode()
_interviewer = InterviewerNode()
_coach = CoachNode()
_stt_service = None
PLACEHOLDER_USER_ID = "00000000-0000-0000-0000-000000000001"


def _get_stt():
    global _stt_service
    if _stt_service is None:
        from app.services.stt_service import STTService
        _stt_service = STTService()
    return _stt_service


# ── Session lifecycle ─────────────────────────────────────────────

@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(payload: SessionCreateRequest, db: AsyncSession = Depends(get_db)):
    return await SessionRepository(db).create(
        user_id=PLACEHOLDER_USER_ID,
        role=payload.role.value,
        difficulty=payload.difficulty.value,
    )


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await SessionRepository(db).get_by_id(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")


@router.post("/{session_id}/start", response_model=SessionResponse)
async def start_session(session_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await SessionRepository(db).transition_status(session_id, SessionStatus.ACTIVE)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


# ── Bug fix #9: Heartbeat ─────────────────────────────────────────

@router.post("/{session_id}/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
async def heartbeat(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    Update last_seen_at to now.
    Frontend calls this every 30s during an active interview.
    Background job (Phase 8 Celery) marks sessions FAILED if
    last_seen_at is older than SESSION_TIMEOUT (e.g. 5 minutes).
    """
    try:
        await SessionRepository(db).update_last_seen(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")


# ── Bug fix #2: Backend resume endpoint ───────────────────────────

class SessionStateResponse(BaseModel):
    session_id: str
    status: str
    role: str
    difficulty: str
    current_question_id: str | None
    current_question_text: str | None
    current_sequence: int | None
    questions_answered: int
    is_complete: bool
    recent_events: list[dict]


@router.get("/{session_id}/state", response_model=SessionStateResponse)
async def get_session_state(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    Return current interview state from the backend.
    Bug fix #2: frontend doesn't need to store question_id locally.
    On page refresh / device switch / browser crash:
      GET /sessions/{id}/state → resume from here.
    """
    try:
        session = await SessionRepository(db).get_by_id(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")

    answer_repo = AnswerRepository(db)
    pairs = await answer_repo.get_answers_for_session(session_id)

    # Find the last question that has NO answer — that's the current question
    current_q = None
    for q, a in pairs:
        if a is None:
            current_q = q
            break

    questions_answered = sum(1 for _, a in pairs if a is not None)

    # Last 5 session events for client-side debugging / resume context
    events_result = await db.execute(
        select(SessionEvent)
        .where(SessionEvent.session_id == session_id)
        .order_by(SessionEvent.created_at.desc())
        .limit(5)
    )
    recent_events = [
        {"event_type": e.event_type, "payload": e.payload, "created_at": str(e.created_at)}
        for e in events_result.scalars().all()
    ]

    return SessionStateResponse(
        session_id=session_id,
        status=session.status,
        role=session.role,
        difficulty=session.difficulty,
        current_question_id=current_q.id if current_q else None,
        current_question_text=current_q.text if current_q else None,
        current_sequence=current_q.sequence if current_q else None,
        questions_answered=questions_answered,
        is_complete=session.status == SessionStatus.COMPLETED.value,
        recent_events=recent_events,
    )


# ── Phase 5: LangGraph endpoints ─────────────────────────────────

class BeginResponse(BaseModel):
    question_id: str
    question_text: str
    sequence: int


class RespondRequest(BaseModel):
    question_id: str
    transcript: str
    latency_ms: int | None = None


class RespondResponse(BaseModel):
    session_complete: bool
    question_id: str | None = None
    question_text: str | None = None
    sequence: int | None = None
    scores: dict | None = None


@router.post("/{session_id}/begin", response_model=BeginResponse)
async def begin_interview(session_id: str, db: AsyncSession = Depends(get_db)):
    try:
        session = await SessionRepository(db).get_by_id(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != SessionStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail=f"Session must be active, is {session.status}")
    try:
        return await SessionOrchestrationService(db).begin(session_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Graph error: {e}")


@router.post("/{session_id}/respond", response_model=RespondResponse)
async def respond_to_question(
    session_id: str, payload: RespondRequest, db: AsyncSession = Depends(get_db)
):
    """
    Submit answer. Duplicate submissions return 409 (UniqueConstraint on question_id).
    On transient failure: service retries up to 2x before propagating error.
    On failure after retries: session is marked FAILED.
    """
    try:
        session = await SessionRepository(db).get_by_id(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != SessionStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail=f"Session must be active, is {session.status}")
    try:
        return await SessionOrchestrationService(db).respond(
            session_id=session_id,
            question_id=payload.question_id,
            transcript=payload.transcript,
            latency_ms=payload.latency_ms,
        )
    except IntegrityError:                                      # FIX: top-level import, correct exception type
        raise HTTPException(status_code=409, detail="Answer already submitted for this question")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error: {e}")


# ── Phase 2-4 direct endpoints ────────────────────────────────────

@router.post("/{session_id}/transcribe", response_model=TranscribeResponse)
async def transcribe_answer(
    session_id: str, question_id: str, audio: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        session = await SessionRepository(db).get_by_id(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != SessionStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail="Session must be active")
    audio_bytes = await audio.read(25 * 1024 * 1024)
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Audio file is empty")
    try:
        transcript, latency_ms = await _get_stt().transcribe(audio_bytes, audio.filename or "audio.webm")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"STT error: {e}")
    answer = await AnswerRepository(db).create_answer(
        question_id=question_id, transcript=transcript, latency_ms=latency_ms
    )
    return TranscribeResponse(transcript=transcript, latency_ms=latency_ms, answer_id=answer.id)


@router.post("/{session_id}/evaluate", response_model=ScoreResponse)
async def evaluate_answer(session_id: str, answer_id: str, db: AsyncSession = Depends(get_db)):
    answer_repo = AnswerRepository(db)
    answer = await answer_repo.get_answer_by_id(answer_id)
    if not answer:
        raise HTTPException(status_code=404, detail="Answer not found")
    question = await answer_repo.get_question_by_id(answer.question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    try:
        session = await SessionRepository(db).get_by_id(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        scores = await _evaluator.evaluate(
            question=question.text, transcript=answer.transcript,
            role=session.role, difficulty=session.difficulty,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Evaluator error: {e}")
    return await answer_repo.create_score(answer_id=answer_id, scores=scores)


@router.post("/{session_id}/coach", response_model=FeedbackResponse)
async def coach_answer(session_id: str, answer_id: str, db: AsyncSession = Depends(get_db)):
    answer_repo = AnswerRepository(db)
    answer = await answer_repo.get_answer_by_id(answer_id)
    if not answer:
        raise HTTPException(status_code=404, detail="Answer not found")
    question = await answer_repo.get_question_by_id(answer.question_id)
    if not question or question.session_id != session_id:
        raise HTTPException(status_code=403, detail="Answer does not belong to this session")
    try:
        coaching_data = await _coach.analyze(transcript=answer.transcript)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Coach error: {e}")
    return await FeedbackRepository(db).create(answer_id=answer_id, data=coaching_data)


@router.get("/{session_id}/communication", response_model=SessionCommunicationSummary)
async def get_communication_summary(session_id: str, db: AsyncSession = Depends(get_db)):
    answer_repo = AnswerRepository(db)
    pairs = await answer_repo.get_answers_for_session(session_id)
    answer_ids = [a.id for _, a in pairs if a is not None]
    if not answer_ids:
        raise HTTPException(status_code=404, detail="No answers found")
    summary = await FeedbackRepository(db).get_session_communication_summary(answer_ids)
    if not summary:
        raise HTTPException(status_code=404, detail="No coaching feedback found")
    return summary

