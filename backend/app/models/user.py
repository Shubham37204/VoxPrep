# user.py — SQLAlchemy ORM model for the `users` table
# Uses SQLAlchemy 2.0 Mapped[] annotation style — explicit, type-safe, no magic columns.

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class User(Base):
    __tablename__ = "users"

    # UUID primary key — avoids sequential ID enumeration attacks
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Indexed — every auth lookup queries by email
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    # Store only bcrypt hash — plaintext password never touches the DB
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # server_default lets the DB set the value — avoids clock skew between app servers
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email}>"
