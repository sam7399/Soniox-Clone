"""Database bootstrap, session factory and restart recovery."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from app.config import app_data_dir, get_config_manager
from app.db.models import Base, JobStatus, ProcessingJob

log = logging.getLogger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def _db_path() -> Path:
    cfg = get_config_manager().config
    if cfg.db_path:
        p = Path(cfg.db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return app_data_dir() / "globalvoice.db"


def init_db(db_url: str | None = None) -> Engine:
    """Create engine, tables, and run recovery. Idempotent."""
    global _engine, _session_factory
    if _engine is not None:
        return _engine
    url = db_url or f"sqlite:///{_db_path()}"
    _engine = create_engine(url, future=True,
                            connect_args={"check_same_thread": False}
                            if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _set_pragmas(dbapi_conn, _):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
    Base.metadata.create_all(_engine)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False,
                                    future=True)
    _recover_interrupted_jobs()
    return _engine


def reset_db_for_tests(db_url: str) -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
    init_db(db_url)


@contextmanager
def db_session() -> Iterator[OrmSession]:
    if _session_factory is None:
        init_db()
    assert _session_factory is not None
    s = _session_factory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def _recover_interrupted_jobs() -> None:
    """Jobs left RUNNING by a crash are requeued with saved progress."""
    with db_session() as s:
        stale = s.scalars(select(ProcessingJob).where(
            ProcessingJob.status == JobStatus.RUNNING)).all()
        for job in stale:
            job.status = JobStatus.PENDING
            job.stage = job.stage or "recovered"
            log.warning("Recovered interrupted job #%s (%s)", job.id, job.kind)
