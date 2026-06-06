# __init__.py — Exports DeclarativeBase shared by all models
# Every model imports Base from here so they all share the same metadata object.
# metadata is what Alembic and create_all() use to discover tables.

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
