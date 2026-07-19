"""Persistent background job queue.

Jobs live in the processing_jobs table; a single worker thread executes
them sequentially (audio work is CPU/IO heavy, serial is safer on
laptops). The queue survives restarts: database.init_db() re-queues jobs
that were RUNNING at crash time, and transcription resumes from the last
completed chunk via ProcessingJob.state_json.
"""
from __future__ import annotations

import logging
import threading
import traceback
from typing import Callable

from sqlalchemy import select

from app.core import pipeline
from app.core.pipeline import PipelineError, new_error_ref
from app.db.database import db_session
from app.db.models import AuditLog, JobStatus, ProcessingJob
from app.providers.base import ProviderError

log = logging.getLogger(__name__)

# Listeners: fn(job_id, status, progress, stage)
JobListener = Callable[[int, str, float, str], None]


class JobQueue:
    def __init__(self) -> None:
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._cancel_ids: set[int] = set()
        self._listeners: list[JobListener] = []
        self._thread: threading.Thread | None = None

    # -- lifecycle ----------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="gva-jobqueue")
        self._thread.start()

    def shutdown(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def add_listener(self, fn: JobListener) -> None:
        self._listeners.append(fn)

    def _emit(self, job_id: int, status: str, progress: float,
              stage: str) -> None:
        for fn in list(self._listeners):
            try:
                fn(job_id, status, progress, stage)
            except Exception:
                log.exception("job listener failed")

    # -- public API ---------------------------------------------------
    def enqueue_transcription(self, session_id: int,
                              provider_key: str | None = None,
                              diarize: bool | None = None) -> int:
        with db_session() as s:
            job = ProcessingJob(session_id=session_id, kind="transcribe",
                                params_json={"provider": provider_key,
                                             "diarize": diarize})
            s.add(job)
            s.flush()
            job_id = job.id
        self._wake.set()
        return job_id

    def cancel(self, job_id: int) -> None:
        self._cancel_ids.add(job_id)
        with db_session() as s:
            job = s.get(ProcessingJob, job_id)
            if job is not None and job.status == JobStatus.PENDING:
                job.status = JobStatus.CANCELLED
                self._emit(job_id, "cancelled", job.progress, "")

    def retry(self, job_id: int) -> None:
        with db_session() as s:
            job = s.get(ProcessingJob, job_id)
            if job is not None and job.status in (JobStatus.FAILED,
                                                  JobStatus.CANCELLED):
                job.status = JobStatus.PENDING
                job.error = ""
                job.error_ref = ""
        self._wake.set()

    def pending_count(self) -> int:
        with db_session() as s:
            return len(s.scalars(select(ProcessingJob).where(
                ProcessingJob.status.in_(
                    [JobStatus.PENDING, JobStatus.RUNNING]))).all())

    # -- worker -------------------------------------------------------
    def _next_job(self) -> int | None:
        with db_session() as s:
            job = s.scalars(select(ProcessingJob)
                            .where(ProcessingJob.status ==
                                   JobStatus.PENDING)
                            .order_by(ProcessingJob.id)).first()
            if job is None:
                return None
            job.status = JobStatus.RUNNING
            job.attempts += 1
            return job.id

    def _run(self) -> None:
        while not self._stop.is_set():
            job_id = self._next_job()
            if job_id is None:
                self._wake.wait(timeout=2.0)
                self._wake.clear()
                continue
            self._execute(job_id)

    def _execute(self, job_id: int) -> None:
        with db_session() as s:
            job = s.get(ProcessingJob, job_id)
            if job is None:
                return
            kind = job.kind
            session_id = job.session_id
            params = dict(job.params_json or {})
        self._emit(job_id, "running", 0.0, "Starting")

        def on_progress(pct: float, stage: str) -> None:
            if job_id in self._cancel_ids:
                raise _Cancelled()
            self._emit(job_id, "running", pct, stage)

        try:
            if kind == "transcribe" and session_id is not None:
                pipeline.transcribe_session(
                    session_id, job_id=job_id, progress=on_progress,
                    provider_key=params.get("provider"),
                    diarize=params.get("diarize"))
            else:
                raise PipelineError(f"unknown job kind {kind}",
                                    "Unknown job type.", new_error_ref())
            with db_session() as s:
                job = s.get(ProcessingJob, job_id)
                if job is not None:
                    job.status = JobStatus.COMPLETED
                    job.progress = 100.0
                    job.state_json = {}
            self._emit(job_id, "completed", 100.0, "Completed")
        except _Cancelled:
            with db_session() as s:
                job = s.get(ProcessingJob, job_id)
                if job is not None:
                    job.status = JobStatus.CANCELLED
            self._cancel_ids.discard(job_id)
            self._emit(job_id, "cancelled", 0.0, "Cancelled")
        except (PipelineError, ProviderError) as e:
            ref = getattr(e, "error_ref", "") or new_error_ref()
            user_msg = getattr(e, "user_message", str(e))
            self._fail(job_id, str(e), user_msg, ref)
        except Exception as e:  # unexpected: log full trace, show ref
            ref = new_error_ref()
            log.error("Job %s crashed [%s]\n%s", job_id, ref,
                      traceback.format_exc())
            self._fail(job_id, str(e),
                       f"An unexpected error occurred (ref {ref}). "
                       "See Help > Logs for details.", ref)

    def _fail(self, job_id: int, technical: str, user_msg: str,
              ref: str) -> None:
        log.error("Job %s failed [%s]: %s", job_id, ref, technical)
        with db_session() as s:
            job = s.get(ProcessingJob, job_id)
            if job is not None:
                job.status = JobStatus.FAILED
                job.error = user_msg
                job.error_ref = ref
            s.add(AuditLog(action="job_failed", module="jobs",
                           record=str(job_id), detail=technical[:2000],
                           result="error", error_ref=ref))
        self._emit(job_id, "failed", 0.0, user_msg)


class _Cancelled(Exception):
    pass


_queue: JobQueue | None = None


def get_queue() -> JobQueue:
    global _queue
    if _queue is None:
        _queue = JobQueue()
    return _queue
