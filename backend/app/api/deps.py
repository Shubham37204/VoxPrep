# deps.py — FastAPI dependency injection functions
# Every route that needs a DB session declares: db: AsyncSession = Depends(get_db)
# The session is automatically closed (and rolled back on error) after the response.

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import AsyncSessionFactory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    # Yields one session per request — never share sessions across requests
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            # Rollback on any unhandled exception — leaves DB in clean state
            await session.rollback()
            raise
        # Session auto-closes when context manager exits (even on exception)
