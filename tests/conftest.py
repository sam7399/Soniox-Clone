from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Isolated config + fresh in-memory DB per test."""
    import app.config as config_mod
    monkeypatch.setattr(config_mod, "_manager", None)
    monkeypatch.setattr(config_mod, "app_data_dir",
                        lambda: tmp_path)
    from app.db import database
    database.reset_db_for_tests("sqlite://")
    yield


@pytest.fixture
def sample_session():
    """Create a session with a few segments and speakers."""
    from app.db.database import db_session
    from app.db.models import (Session, SessionStatus, Speaker,
                               TranscriptSegment)
    with db_session() as s:
        sess = Session(name="Test Meeting", duration_s=125.0,
                       language="en,hi", provider="whisper_local",
                       status=SessionStatus.READY)
        s.add(sess)
        s.flush()
        sp = Speaker(session_id=sess.id, label="Speaker 1",
                     display_name="Asha")
        s.add(sp)
        s.flush()
        rows = [
            (0, 0.0, 5.0, "Hello everyone, welcome to the meeting.",
             "en", sp.id),
            (1, 5.0, 11.0, "Aaj hum product launch discuss karenge.",
             "hi", sp.id),
            (2, 11.0, 18.0, "The deadline is next Friday.", "en", None),
        ]
        for idx, st, en, text, lang, spk in rows:
            s.add(TranscriptSegment(
                session_id=sess.id, idx=idx, start_s=st, end_s=en,
                text=text, original_text=text, language=lang,
                speaker_id=spk, confidence=0.9))
        s.flush()
        return sess.id
