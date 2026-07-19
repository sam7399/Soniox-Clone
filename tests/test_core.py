"""Core logic tests: DB, vocab correction, costs, credentials,
exporters, job recovery."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ------------------------------------------------------------------ DB

def test_db_roundtrip(sample_session):
    from app.db.database import db_session
    from app.db.models import Session
    with db_session() as s:
        sess = s.get(Session, sample_session)
        assert sess is not None
        assert len(sess.segments) == 3
        assert sess.segments[0].text.startswith("Hello")
        assert sess.speakers[0].display_name == "Asha"


def test_job_recovery():
    from app.db import database
    from app.db.database import db_session
    from app.db.models import JobStatus, ProcessingJob
    with db_session() as s:
        s.add(ProcessingJob(kind="transcribe",
                            status=JobStatus.RUNNING, progress=42.0))
    database._recover_interrupted_jobs()
    with db_session() as s:
        job = s.get(ProcessingJob, 1)
        assert job.status == JobStatus.PENDING
        assert job.progress == 42.0     # progress survives restart


# ---------------------------------------------------------------- vocab

def test_vocab_correction():
    from app.core.vocab import apply_corrections
    from app.db.database import db_session
    from app.db.models import VocabularyTerm
    with db_session() as s:
        s.add(VocabularyTerm(term="Soniox", replaces="sonyox, sonix"))
        s.add(VocabularyTerm(term="GlobalVoice",
                             replaces="global voice"))
    out = apply_corrections("We tested sonyox and Sonix with "
                            "Global Voice today.")
    assert "Soniox and Soniox" in out
    assert "GlobalVoice today" in out


def test_vocab_case_sensitive():
    from app.core.vocab import apply_corrections
    from app.db.database import db_session
    from app.db.models import VocabularyTerm
    with db_session() as s:
        s.add(VocabularyTerm(term="pH", replaces="ph",
                             case_sensitive=True))
    assert apply_corrections("the ph level") == "the pH level"
    # capitalized "Ph" must NOT match when case-sensitive
    assert apply_corrections("Ph level") == "Ph level"


def test_vocab_csv_roundtrip(tmp_path):
    from app.core import vocab
    csv_in = tmp_path / "in.csv"
    csv_in.write_text("term,category,replaces,case_sensitive,"
                      "do_not_translate\n"
                      "Acme Corp,companies,acme corp,0,1\n",
                      encoding="utf-8")
    assert vocab.import_csv(str(csv_in)) == 1
    assert vocab.do_not_translate_terms() == ["Acme Corp"]
    csv_out = tmp_path / "out.csv"
    assert vocab.export_csv(str(csv_out)) == 1
    assert "Acme Corp" in csv_out.read_text(encoding="utf-8")


# ---------------------------------------------------------------- costs

def test_cost_estimate_and_budget():
    from app.core import costs
    assert costs.estimate_stt_cost("openai_stt", 600) == pytest.approx(
        0.06)
    assert costs.estimate_stt_cost("whisper_local", 600) == 0.0
    costs.record_cost("openai_stt", "transcribe", 10, "minutes", 5.0)
    state, spent = costs.budget_state(10.0, 40)
    assert state == "warn"
    assert spent == pytest.approx(5.0)
    state, _ = costs.budget_state(4.0, 80)
    assert state == "over"


# ---------------------------------------------------------- credentials

def test_credential_store_encrypted_file(tmp_path, monkeypatch):
    from app.security import credentials
    store = credentials.CredentialStore(data_dir=tmp_path)
    store._kr = None                      # force file fallback
    store.set_key("openai_stt", "sk-secret-123")
    assert store.get_key("openai_stt") == "sk-secret-123"
    # key must not be stored in plain text on disk
    blob = (tmp_path / "credentials.enc").read_bytes()
    assert b"sk-secret-123" not in blob
    store.delete_key("openai_stt")
    assert store.get_key("openai_stt") is None
    assert credentials.redact("sk-secret-123") == "sk-s…23"


# ------------------------------------------------------------ exporters

@pytest.mark.parametrize("fmt", ["txt", "srt", "vtt", "json", "md",
                                 "html", "docx", "xlsx", "pdf"])
def test_export_formats(sample_session, tmp_path, fmt):
    from app.core.exporters import ExportOptions, export_session
    out = export_session(sample_session, fmt, tmp_path / "out",
                         ExportOptions(watermark="CONFIDENTIAL"))
    assert out.exists() and out.stat().st_size > 0


def test_export_srt_content(sample_session, tmp_path):
    from app.core.exporters import ExportOptions, export_session
    out = export_session(sample_session, "srt", tmp_path / "t")
    text = out.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:05,000" in text
    assert "Asha: Hello everyone" in text
    assert "Aaj hum product launch" in text


def test_export_json_structure(sample_session, tmp_path):
    from app.core.exporters import ExportOptions, export_session
    out = export_session(sample_session, "json", tmp_path / "t")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["session"] == "Test Meeting"
    assert len(data["segments"]) == 3
    assert data["segments"][1]["language"] == "hi"


# ------------------------------------------------------- provider logic

def test_privacy_mode_blocks_cloud():
    from app.config import get_config_manager
    from app.providers import registry
    from app.providers.base import ProviderError
    registry.register_builtin_providers()
    get_config_manager().config.privacy_mode = True
    with pytest.raises(ProviderError):
        registry.get_stt("openai_stt")
    local = registry.get_stt("whisper_local")   # local is still allowed
    assert local.is_local


def test_fallback_chain():
    from app.config import get_config_manager
    from app.providers import registry
    registry.register_builtin_providers()
    cfg = get_config_manager().config
    cfg.stt_provider = "openai_stt"
    cfg.stt_fallback_provider = "whisper_local"
    chain = registry.get_stt_with_fallback()
    assert [p.key for p in chain] == ["openai_stt", "whisper_local"]


def test_stt_segment_partial_flag():
    from app.providers.base import STTSegment
    seg = STTSegment(0, 1, "hello")
    assert seg.is_final is True
    partial = STTSegment(0, 1, "hel", is_final=False)
    assert partial.is_final is False


def test_soniox_token_grouping():
    from app.providers.stt.soniox_stt import SonioxSTT
    tokens = [
        {"text": "Hello", "start_ms": 0, "end_ms": 400,
         "speaker": "1", "language": "en", "confidence": 0.98},
        {"text": " world", "start_ms": 400, "end_ms": 800,
         "speaker": "1", "language": "en", "confidence": 0.97},
        {"text": "नमस्ते", "start_ms": 1200, "end_ms": 1700,
         "speaker": "2", "language": "hi", "confidence": 0.95},
    ]
    segs = SonioxSTT._tokens_to_segments(tokens)
    assert len(segs) == 2
    assert segs[0].text == "Hello world"
    assert segs[0].speaker == "Speaker 1"
    assert segs[1].language == "hi"


# ----------------------------------------------------- pipeline w/ mock

def test_pipeline_merge_and_vocab(monkeypatch, tmp_path):
    """Full transcribe_session flow with mocked audio + STT layers."""
    from app.core import pipeline
    from app.db.database import db_session
    from app.db.models import Session, SessionStatus, VocabularyTerm
    from app.providers.base import STTProvider, STTResult, STTSegment

    with db_session() as s:
        sess = Session(name="mock", source_path=str(tmp_path / "a.mp3"),
                       duration_s=10.0)
        s.add(sess)
        s.flush()
        sid = sess.id
        s.add(VocabularyTerm(term="Deepgram", replaces="deep gram"))

    class FakeSTT(STTProvider):
        key = "fake"
        display_name = "Fake"
        is_local = True

        def transcribe_file(self, audio_path, language="auto",
                            diarize=False, progress=None):
            return STTResult(
                segments=[STTSegment(0, 4, "We compared deep gram "
                                     "results", "en", "Speaker 1", 0.9),
                          STTSegment(4, 8, "बहुत अच्छा था", "hi",
                                     "Speaker 2", 0.8)],
                languages=["en", "hi"], duration_s=8.0,
                provider="fake", model="fake-1")

    monkeypatch.setattr(pipeline.audio_mod, "to_wav_16k_mono",
                        lambda src, dst, **kw: dst)
    monkeypatch.setattr(pipeline.audio_mod, "has_speech_energy",
                        lambda wav: True)
    monkeypatch.setattr(pipeline.audio_mod, "split_chunks",
                        lambda wav, out_dir, chunk_s=300:
                        [(wav, 0.0)])
    monkeypatch.setattr(pipeline.registry, "get_stt_with_fallback",
                        lambda key=None: [FakeSTT()])

    pipeline.transcribe_session(sid)

    with db_session() as s:
        sess = s.get(Session, sid)
        assert sess.status == SessionStatus.READY
        assert sess.language == "en,hi"
        texts = [seg.text for seg in sess.segments]
        assert texts[0] == "We compared Deepgram results"  # vocab fixed
        assert sess.segments[0].original_text == texts[0]
        labels = sorted(sp.label for sp in sess.speakers)
        assert labels == ["Speaker 1", "Speaker 2"]


def test_duplicate_detection(monkeypatch, tmp_path):
    from app.core import pipeline
    src = tmp_path / "a.mp3"
    src.write_bytes(b"fake audio bytes")
    monkeypatch.setattr(pipeline.audio_mod, "probe",
                        lambda p: {"duration_s": 5.0, "has_audio": True,
                                   "codec": "mp3"})
    sid = pipeline.create_session_for_file(src)
    assert sid > 0
    with pytest.raises(pipeline.PipelineError) as ei:
        pipeline.create_session_for_file(src)
    assert "already imported" in ei.value.user_message
