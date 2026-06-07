# sessions.py — API routes for session lifecycle, transcription, evaluation, and coaching
#
# Phase 4 additions:
#   POST /sessions/{id}/coach           → analyze communication quality
#   GET  /sessions/{id}/communication   → session-level communication summary

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.nodes.coach import CoachNode
from app.agents.nodes.evaluator import EvaluatorNode
from app.agents.nodes.interviewer import InterviewerNode
from app.api.deps import get_db
from app.core.enums import SessionStatus
from app.core.exceptions import InvalidStateTransitionError, SessionNotFoundError
from app.repositories.answer_repository import AnswerRepository
from app.repositories.feedback_repository import FeedbackRepository
from app.repositories.session_repository import SessionRepository
from app.schemas.answer import TranscribeResponse
from app.schemas.feedback import FeedbackResponse, SessionCommunicationSummary
from app.schemas.score import NextQuestionResponse, ScoreResponse
from app.schemas.session import SessionCreateRequest, SessionResponse

router = APIRouter(prefix="/sessions", tags=["sessions"])

# Singletons — one instance per process
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
    """Create a new interview session."""
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
    """Transition CREATED → ACTIVE."""
    try:
        return await SessionRepository(db).transition_status(session_id, SessionStatus.ACTIVE)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


# ── Audio + transcript ────────────────────────────────────────────

@router.post("/{session_id}/transcribe", response_model=TranscribeResponse)
async def transcribe_answer(
    session_id: str,
    question_id: str,
    audio: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Accept audio upload, transcribe with Groq Whisper, store as Answer row."""
    try:
        session = await SessionRepository(db).get_by_id(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status != SessionStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail=f"Session must be active, is {session.status}")

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


# ── Evaluator (technical scoring) ────────────────────────────────

@router.post("/{session_id}/evaluate", response_model=ScoreResponse)
async def evaluate_answer(
    session_id: str,
    answer_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Score answer technically via EvaluatorNode. Independent of /coach."""
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
            question=question.text,
            transcript=answer.transcript,
            role=session.role,
            difficulty=session.difficulty,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Evaluator error: {e}")

    return await answer_repo.create_score(answer_id=answer_id, scores=scores)


# ── Coach (communication analysis) ───────────────────────────────

@router.post("/{session_id}/coach", response_model=FeedbackResponse)
async def coach_answer(
    session_id: str,
    answer_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Analyze communication quality of an answer via CoachNode.
    Runs independently of /evaluate — call both after receiving a transcript.
    Client can fire both in parallel: Promise.all([evaluate(), coach()]).
    """
    answer_repo = AnswerRepository(db)
    answer = await answer_repo.get_answer_by_id(answer_id)
    if not answer:
        raise HTTPException(status_code=404, detail="Answer not found")

    # Verify answer belongs to this session (ownership check)
    question = await answer_repo.get_question_by_id(answer.question_id)
    if not question or question.session_id != session_id:
        raise HTTPException(status_code=403, detail="Answer does not belong to this session")

    try:
        coaching_data = await _coach.analyze(transcript=answer.transcript)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Coach error: {e}")

    return await FeedbackRepository(db).create(answer_id=answer_id, data=coaching_data)


@router.get("/{session_id}/communication", response_model=SessionCommunicationSummary)
async def get_communication_summary(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregate communication metrics across all answers in the session.
    Used by the session summary / report view — not real-time.
    """
    answer_repo = AnswerRepository(db)
    pairs = await answer_repo.get_answers_for_session(session_id)

    # Collect answer IDs that have transcripts
    answer_ids = [a.id for _, a in pairs if a is not None]
    if not answer_ids:
        raise HTTPException(status_code=404, detail="No answers found for this session")

    summary = await FeedbackRepository(db).get_session_communication_summary(answer_ids)
    if not summary:
        raise HTTPException(status_code=404, detail="No coaching feedback found yet")

    return summary


# ── Interviewer (next question) ───────────────────────────────────

@router.post("/{session_id}/next-question", response_model=NextQuestionResponse)
async def get_next_question(session_id: str, db: AsyncSession = Depends(get_db)):
    """Generate next interview question based on session history and last scores."""
    try:
        session = await SessionRepository(db).get_by_id(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status != SessionStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail="Session must be active")

    answer_repo = AnswerRepository(db)
    pairs = await answer_repo.get_answers_for_session(session_id)

    qa_history = []
    last_scores = None
    for q, a in pairs:
        pair: dict = {"sequence": q.sequence, "question_text": q.text,
                      "question_id": q.id, "transcript": None, "scores": None}
        if a:
            pair["transcript"] = a.transcript
            score = await answer_repo.get_score_by_answer(a.id)
            if score:
                pair["scores"] = {"overall_score": score.overall_score,
                                  "follow_up_needed": score.follow_up_needed}
                last_scores = pair["scores"]
        qa_history.append(pair)

    next_sequence = len(pairs) + 1

    try:
        result = await _interviewer.generate_question(
            role=session.role, difficulty=session.difficulty,
            sequence=next_sequence, qa_history=qa_history, last_scores=last_scores,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Interviewer error: {e}")

    question = await answer_repo.create_question(
        session_id=session_id, text=result["question"], sequence=next_sequence,
    )
    return NextQuestionResponse(
        question_id=question.id, question_text=question.text,
        sequence=question.sequence, topic=result.get("topic"),
    )
