# session_repository.py — All database reads and writes for sessions
#
# Repository pattern: route handlers never write raw SQL or call session.add() directly.
# They call repository methods. This keeps DB logic in one place and makes testing easier.

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ALLOWED_TRANSITIONS, SessionStatus
from app.core.exceptions import InvalidStateTransitionError, SessionNotFoundError
from app.models.session import Session


class SessionRepository:

    def __init__(self, db: AsyncSession) -> None:
        # Accepts an injected session — never creates its own (that's the engine's job)
        self._db = db

    async def create(
        self,
        user_id: str,
        role: str,
        difficulty: str,
    ) -> Session:
        """Insert a new session row with CREATED status."""
        session = Session(
            id=str(uuid.uuid4()),
            user_id=user_id,
            role=role,
            difficulty=difficulty,
            status=SessionStatus.CREATED.value,
        )
        self._db.add(session)
        await self._db.commit()
        await self._db.refresh(session)   # Refresh to load server-side defaults (created_at)
        return session

    async def get_by_id(self, session_id: str) -> Session:
        """Fetch a session by primary key. Raises SessionNotFoundError if missing."""
        result = await self._db.execute(
            select(Session).where(Session.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise SessionNotFoundError(f"Session {session_id} not found")
        return session

    async def transition_status(self, session_id: str, new_status: SessionStatus) -> Session:
        """
        Update session status — validates against ALLOWED_TRANSITIONS before writing.
        Raises InvalidStateTransitionError if the transition is not permitted.
        """
        session = await self.get_by_id(session_id)
        current = SessionStatus(session.status)

        if new_status not in ALLOWED_TRANSITIONS[current]:
            raise InvalidStateTransitionError(
                f"Cannot transition session from {current.value} to {new_status.value}"
            )

        session.status = new_status.value

        # Track timing — started_at and ended_at are used for session duration metrics
        if new_status == SessionStatus.ACTIVE and session.started_at is None:
            session.started_at = datetime.now(timezone.utc)
        elif new_status in (SessionStatus.COMPLETED, SessionStatus.FAILED):
            session.ended_at = datetime.now(timezone.utc)

        await self._db.commit()
        await self._db.refresh(session)
        return session
