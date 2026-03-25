from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def _default_db_url() -> str:
    db_path = os.getenv("DB_PATH", "./itgc_sox_agent.db")
    return f"sqlite:///{db_path}"


class Base(DeclarativeBase):
    pass


engine = create_engine(
    _default_db_url(),
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    from backend.storage import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_alerts_risk_note()


def _migrate_alerts_risk_note() -> None:
    """Add risk_note column to alerts table if it doesn't exist (SQLite migration)."""
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(alerts)")).fetchall()]
        if "risk_note" not in cols:
            conn.execute(text("ALTER TABLE alerts ADD COLUMN risk_note TEXT"))
            conn.commit()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

