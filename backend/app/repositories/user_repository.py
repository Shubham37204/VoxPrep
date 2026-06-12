from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_id(self, user_id: str) -> User | None:
        result = await self._db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self._db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def exists(self, email: str) -> bool:
        return await self.get_by_email(email) is not None

    async def create(self, email: str, name: str, hashed_password: str) -> User:
        """
        Insert new user row.
        Caller must hash password before passing — never store plaintext.
        """
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            name=name,
            hashed_password=hashed_password,
        )
        self._db.add(user)
        await self._db.commit()
        await self._db.refresh(user)
        return user
    