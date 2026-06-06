# sessions.py — API routes for session lifecycle and transcript ingestion
#
# Endpoints:
#   POST /sessions              → create new session
#   GET  /sessions/{id}         → get session details
#   POST /sessions/{id}/start   → transition CREATED → ACTIVE
#   POST /sessions/{id}/transcribe → accept audio, return transcript, store answer
#
# Route handlers are intentionally thin:
#   - Validate input (Pydantic does this automatically)
#   - Call repository or service
#   - Return response
# NO business logic here — that belongs in services or repositories.

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.enums import SessionStatus
from app.core.exceptions import InvalidStateTransitionError, SessionNotFoundError
from app.repositories.answer_repository import AnswerRepository
from app.repositories.session_repository import SessionRepository
from app.schemas.answer import TranscribeResponse
from app.schemas.session import SessionCreateRequest, SessionResponse, SessionStatusUpdateRequest
from app.services.stt_service import STTService

router = APIRouter(prefix="/sessions", tags=["sessions"])

# STT service is instantiated once per module load — not per request
# This reuses the Groq client connection rather than creating a new one each time
_stt_service = STTService()


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new interview session for the authenticated user."""
    # TODO Phase 1 auth: replace hardcoded user_id with current_user.id from JWT
    PLACEHOLDER_USER_ID = "00000000-0000-0000-0000-000000000001"

    repo = SessionRepository(db)
    session = await repo.create(
        user_id=PLACEHOLDER_USER_ID,
        role=payload.role.value,
        difficulty=payload.difficulty.value,
    )
    return session


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Fetch session details by ID."""
    repo = SessionRepository(db)
    try:
        return await repo.get_by_id(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")


@router.post("/{session_id}/start", response_model=SessionResponse)
async def start_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Transition session from CREATED → ACTIVE."""
    repo = SessionRepository(db)
    try:
        return await repo.transition_status(session_id, SessionStatus.ACTIVE)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{session_id}/transcribe", response_model=TranscribeResponse)
async def transcribe_answer(
    session_id: str,
    question_id: str,              # Which question is being answered
    audio: UploadFile = File(...),  # Browser sends WebM blob from MediaRecorder
    db: AsyncSession = Depends(get_db),
):
    """
    Accept audio upload, transcribe with Groq Whisper, store as an Answer row.

    Flow:
      1. Read audio bytes from upload
      2. Verify session is ACTIVE
      3. Call STTService.transcribe()
      4. Store transcript in answers table via AnswerRepository
      5. Return transcript + latency to client
    """
    # Verify session is ACTIVE before touching Groq API — avoid wasting quota
    session_repo = SessionRepository(db)
    try:
        session = await session_repo.get_by_id(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status != SessionStatus.ACTIVE.value:
        raise HTTPException(
            status_code=409,
            detail=f"Session is {session.status}, must be active to accept answers",
        )

    # Read audio bytes — limit to 25MB (Groq Whisper limit)
    audio_bytes = await audio.read(25 * 1024 * 1024)
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Audio file is empty")

    # Determine filename extension from upload — Groq uses this to decode the format
    filename = audio.filename or "audio.webm"

    # Transcribe — this is the external API call, can fail with groq.APIError
    try:
        transcript, latency_ms = await _stt_service.transcribe(audio_bytes, filename)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"STT service error: {str(e)}")

    # Persist transcript as an Answer row
    answer_repo = AnswerRepository(db)
    answer = await answer_repo.create_answer(
        question_id=question_id,
        transcript=transcript,
        latency_ms=latency_ms,
    )

    return TranscribeResponse(
        transcript=transcript,
        latency_ms=latency_ms,
        answer_id=answer.id,
    )
