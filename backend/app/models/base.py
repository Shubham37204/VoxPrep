from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    """
    Shared declarative base for all SQLAlchemy models.
    All models inherit from this — Alembic autogenerate reads Base.metadata.
    """
    pass

