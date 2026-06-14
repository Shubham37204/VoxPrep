from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.db.engine import AsyncSessionFactory
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.session_service import SessionOrchestrationService

settings = get_settings()
_bearer = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Decode JWT from Authorization: Bearer <token>.
    Raises 401 on missing, invalid, or expired token.
    Raises 401 if user_id from token no longer exists in DB.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        user_id: str = payload.get("sub")
        if not user_id:
            raise JWTError("missing sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = await UserRepository(db).get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_session_service(
    db: AsyncSession = Depends(get_db),
) -> SessionOrchestrationService:
    """
    Dependency that constructs SessionOrchestrationService with both:
      - db: the request-scoped AsyncSession (Phase 1 + compensating delete)
      - session_factory: AsyncSessionFactory (Phase 3 fresh session)

    Why inject session_factory here and not inside the service:
      - SessionOrchestrationService should not import from db.engine directly
      - Keeps service layer decoupled from infrastructure
      - Makes testing trivial — pass a mock factory in tests
    """
    return SessionOrchestrationService(
        db=db,
        session_factory=AsyncSessionFactory,
    )