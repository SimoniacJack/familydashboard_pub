"""Database connection + session setup (SQLAlchemy 2.0, Postgres)."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Connection string comes from env so it swaps cleanly between local Postgres
# and RDS/containerised Postgres later. Falls back to a local dev default.
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://familydash:familydash@localhost:5432/familydashboard",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_session():
    """Create a new session. Caller is responsible for closing it.
    Prefer the `session_scope` context manager for request handlers."""
    return SessionLocal()


from contextlib import contextmanager


@contextmanager
def session_scope():
    """Transactional scope — commits on success, rolls back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
