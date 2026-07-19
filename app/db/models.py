"""SQLAlchemy models for GlobalVoice AI (v1 core schema)."""
from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (JSON, Boolean, DateTime, Enum, Float, ForeignKey,
                        Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    modified_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow)


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SessionStatus(str, enum.Enum):
    NEW = "new"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    sessions: Mapped[list[Session]] = relationship(back_populates="project")


class Session(TimestampMixin, Base):
    """One transcription session (live recording or an imported file)."""
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(20), default="file")  # file|live
    source_path: Mapped[str] = mapped_column(Text, default="")
    audio_path: Mapped[str] = mapped_column(Text, default="")   # normalized wav
    file_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    language: Mapped[str] = mapped_column(String(120), default="")  # csv of detected
    provider: Mapped[str] = mapped_column(String(60), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus), default=SessionStatus.NEW, index=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    project: Mapped[Project | None] = relationship(back_populates="sessions")
    segments: Mapped[list[TranscriptSegment]] = relationship(
        back_populates="session", cascade="all, delete-orphan",
        order_by="TranscriptSegment.start_s")
    speakers: Mapped[list[Speaker]] = relationship(
        back_populates="session", cascade="all, delete-orphan")
    translations: Mapped[list[Translation]] = relationship(
        back_populates="session", cascade="all, delete-orphan")
    summaries: Mapped[list[Summary]] = relationship(
        back_populates="session", cascade="all, delete-orphan")
    jobs: Mapped[list[ProcessingJob]] = relationship(back_populates="session")


class Speaker(TimestampMixin, Base):
    __tablename__ = "speakers"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id"), index=True)
    label: Mapped[str] = mapped_column(String(60))        # "Speaker 1"
    display_name: Mapped[str] = mapped_column(String(120), default="")
    color: Mapped[str] = mapped_column(String(9), default="")
    session: Mapped[Session] = relationship(back_populates="speakers")
    __table_args__ = (UniqueConstraint("session_id", "label"),)


class TranscriptSegment(TimestampMixin, Base):
    __tablename__ = "transcript_segments"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id"), index=True)
    idx: Mapped[int] = mapped_column(Integer, default=0)
    start_s: Mapped[float] = mapped_column(Float, default=0.0)
    end_s: Mapped[float] = mapped_column(Float, default=0.0)
    speaker_id: Mapped[int | None] = mapped_column(
        ForeignKey("speakers.id"), nullable=True)
    language: Mapped[str] = mapped_column(String(16), default="")
    text: Mapped[str] = mapped_column(Text, default="")          # edited text
    original_text: Mapped[str] = mapped_column(Text, default="") # AI output, immutable
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    words_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_bookmarked: Mapped[bool] = mapped_column(Boolean, default=False)
    comment: Mapped[str] = mapped_column(Text, default="")

    session: Mapped[Session] = relationship(back_populates="segments")
    speaker: Mapped[Speaker | None] = relationship()


class Translation(TimestampMixin, Base):
    __tablename__ = "translations"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id"), index=True)
    target_language: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(60), default="")
    segments_json: Mapped[list] = mapped_column(JSON, default=list)
    # [{"idx":0,"start_s":..,"end_s":..,"speaker":"..","text":".."}]
    session: Mapped[Session] = relationship(back_populates="translations")
    __table_args__ = (UniqueConstraint("session_id", "target_language"),)


class Summary(TimestampMixin, Base):
    __tablename__ = "summaries"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="meeting")
    provider: Mapped[str] = mapped_column(String(60), default="")
    content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # {"executive_summary": "...", "action_items":[...], ...}
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=True)
    session: Mapped[Session] = relationship(back_populates="summaries")


class VocabularyTerm(TimestampMixin, Base):
    __tablename__ = "vocabulary"
    id: Mapped[int] = mapped_column(primary_key=True)
    term: Mapped[str] = mapped_column(String(200), index=True)
    category: Mapped[str] = mapped_column(String(80), default="general")
    replaces: Mapped[str] = mapped_column(Text, default="")  # csv of wrong spellings
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    do_not_translate: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("term", "category"),)


class ProcessingJob(TimestampMixin, Base):
    """Persistent job record. Enables restart recovery: any job left in
    RUNNING state at startup is reset to PENDING with its saved progress."""
    __tablename__ = "processing_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(40))  # transcribe|translate|summarize|tts|export
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), default=JobStatus.PENDING, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)   # 0..100
    stage: Mapped[str] = mapped_column(String(60), default="")
    params_json: Mapped[dict] = mapped_column(JSON, default=dict)
    state_json: Mapped[dict] = mapped_column(JSON, default=dict)  # resumable state
    error: Mapped[str] = mapped_column(Text, default="")
    error_ref: Mapped[str] = mapped_column(String(12), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    session: Mapped[Session | None] = relationship(back_populates="jobs")


class CostRecord(TimestampMixin, Base):
    __tablename__ = "cost_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(60), index=True)
    operation: Mapped[str] = mapped_column(String(40))
    units: Mapped[float] = mapped_column(Float, default=0.0)   # minutes or tokens
    unit_type: Mapped[str] = mapped_column(String(20), default="minutes")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user: Mapped[str] = mapped_column(String(120), default="local")
    action: Mapped[str] = mapped_column(String(80), index=True)
    module: Mapped[str] = mapped_column(String(60), default="")
    record: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(String(20), default="ok")
    error_ref: Mapped[str] = mapped_column(String(12), default="")


class TTSGeneration(TimestampMixin, Base):
    __tablename__ = "tts_generations"
    id: Mapped[int] = mapped_column(primary_key=True)
    text_preview: Mapped[str] = mapped_column(String(300))
    provider: Mapped[str] = mapped_column(String(60))
    voice: Mapped[str] = mapped_column(String(80), default="")
    language: Mapped[str] = mapped_column(String(16), default="")
    output_path: Mapped[str] = mapped_column(Text)
