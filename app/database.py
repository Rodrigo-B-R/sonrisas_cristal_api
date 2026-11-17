"""SQLAlchemy engine, session and base class."""

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

# pool_pre_ping drops dead connections (for example after the database restarts)
_pool_options = {} if _is_sqlite else {"pool_size": 5, "max_overflow": 5, "pool_pre_ping": True}
engine = create_engine(settings.database_url, **_pool_options)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """One session per request. Anything not committed is rolled back when it closes."""
    with SessionLocal() as db:
        yield db


def set_audit_user(db: Session, user_id: int) -> None:
    """Tell the database triggers who is making the change.

    Call it before writing to registro_entradas or asistencia, and commit
    in the same transaction (the setting only lives until the transaction ends).
    """
    if db.get_bind().dialect.name != "postgresql":
        return
    db.execute(text("SELECT set_config('app.id_usuario', :user_id, true)"), {"user_id": str(user_id)})
