# session_repository.py — DB reads and writes for sessions and session_events
# Now writes session_events on every status transition (bug fix #10).
# Adds update_last_seen() for heartbeat support (bug fix #9).

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ALLOWED_TRANSITIONS, SessionStatus, SessionEventType
from app.core.exceptions import InvalidStateTransitionError, SessionNotFoundError
from app.models.session import Session
from app.models.session_event import SessionEvent


# Map status transitions → event types for automatic event logging
_TRANSITION_EVENTS: dict[SessionStatus, SessionEventType] = {
    SessionStatus.ACTIVE:    SessionEventType.SESSION_STARTED,
    SessionStatus.PAUSED:    SessionEventType.SESSION_PAUSED,
    SessionStatus.RETRYING:  SessionEventType.SESSION_RETRYING,
    SessionStatus.COMPLETED: SessionEventType.SESSION_COMPLETED,
    SessionStatus.FAILED:    SessionEventType.SESSION_FAILED,
}


class SessionRepository:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, user_id: str, role: str, difficulty: str) -> Session:
        """Create session and log SESSION_CREATED event."""
        session = Session(
            id=str(uuid.uuid4()),
            user_id=user_id,
            role=role,
            difficulty=difficulty,
            status=SessionStatus.CREATED.value,
        )
        self._db.add(session)
        await self._db.flush()   # Get session.id without committing yet

        # Log creation event — every session lifecycle step is auditable
        await self._log_event(
            session_id=session.id,
            event_type=SessionEventType.SESSION_CREATED,
            payload={"role": role, "difficulty": difficulty},
        )
        await self._db.commit()
        await self._db.refresh(session)
        return session

    async def get_by_id(self, session_id: str) -> Session:
        """Fetch session by PK. Raises SessionNotFoundError if missing."""
        result = await self._db.execute(
            select(Session).where(Session.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise SessionNotFoundError(f"Session {session_id} not found")
        return session

    async def transition_status(
        self,
        session_id: str,
        new_status: SessionStatus,
        payload: dict | None = None,
    ) -> Session:
        """
        Validate and apply a status transition.
        Writes a session_event row for every transition — automatic audit trail.
        Raises InvalidStateTransitionError if transition is not in ALLOWED_TRANSITIONS.
        """
        session = await self.get_by_id(session_id)
        current = SessionStatus(session.status)

        if new_status not in ALLOWED_TRANSITIONS[current]:
            raise InvalidStateTransitionError(
                f"Cannot transition session from {current.value} to {new_status.value}"
            )

        session.status = new_status.value

        now = datetime.now(timezone.utc)
        if new_status == SessionStatus.ACTIVE and session.started_at is None:
            session.started_at = now
            session.last_seen_at = now   # Initialize last_seen on first activation
        elif new_status in (SessionStatus.COMPLETED, SessionStatus.FAILED):
            session.ended_at = now

        # Log every transition — this is how you debug "interview froze at Q3"
        event_type = _TRANSITION_EVENTS.get(new_status, SessionEventType.SESSION_STARTED)
        await self._log_event(
            session_id=session_id,
            event_type=event_type,
            payload=payload,
        )

        await self._db.commit()
        await self._db.refresh(session)
        return session

    async def update_last_seen(self, session_id: str) -> None:
        """
        Update last_seen_at to now — called by POST /sessions/{id}/heartbeat.
        Background job compares last_seen_at against SESSION_TIMEOUT to detect
        abandoned sessions (browser crash, network drop).
        """
        session = await self.get_by_id(session_id)
        session.last_seen_at = datetime.now(timezone.utc)
        await self._db.commit()

    async def log_question_event(self, session_id: str, question_id: str, sequence: int) -> None:
        """Log QUESTION_ASKED event — called by SessionOrchestrationService."""
        await self._log_event(
            session_id=session_id,
            event_type=SessionEventType.QUESTION_ASKED,
            payload={"question_id": question_id, "sequence": sequence},
        )
        await self._db.commit()

    async def log_answer_event(self, session_id: str, answer_id: str, question_id: str) -> None:
        """Log ANSWER_RECEIVED event — called by SessionOrchestrationService."""
        await self._log_event(
            session_id=session_id,
            event_type=SessionEventType.ANSWER_RECEIVED,
            payload={"answer_id": answer_id, "question_id": question_id},
        )
        await self._db.commit()

    async def log_score_event(self, session_id: str, answer_id: str, overall_score: int) -> None:
        """Log SCORE_GENERATED event."""
        await self._log_event(
            session_id=session_id,
            event_type=SessionEventType.SCORE_GENERATED,
            payload={"answer_id": answer_id, "overall_score": overall_score},
        )
        await self._db.commit()

    async def _log_event(
        self,
        session_id: str,
        event_type: SessionEventType,
        payload: dict | None = None,
    ) -> None:
        """
        Insert a session_event row. Uses flush() not commit() — caller decides commit boundary.
        This makes it composable with other operations in the same transaction.
        """
        event = SessionEvent(
            id=str(uuid.uuid4()),
            session_id=session_id,
            event_type=event_type.value,
            payload=payload,
        )
        self._db.add(event)
        # Note: NO commit here — caller commits. Allows batching with other ops.