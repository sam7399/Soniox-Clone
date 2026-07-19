"""End-to-end processing pipeline for one session.

validate -> hash/duplicate check -> convert -> (silence check) ->
chunk -> transcribe (with provider fallback) -> merge -> vocabulary
correction -> persist -> cost record.

The pipeline records progress in the ProcessingJob row so that an
interrupted job can be retried after restart without redoing completed
chunks (chunk results are cached in state_json).
"""
from __future__ import annotations

import logging
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import select

from app.config import app_data_dir, get_config_manager
from app.core import audio as audio_mod
from app.core import costs, vocab
from app.core.audio import AudioError
from app.db.database import db_session
from app.db.models import (ProcessingJob, Session, SessionStatus, Speaker,
                           TranscriptSegment)
from app.providers import registry
from app.providers.base import ProgressFn, ProviderError, STTResult, STTSegment

log = logging.getLogger(__name__)


def new_error_ref() -> str:
    return uuid.uuid4().hex[:8].upper()


class PipelineError(Exception):
    def __init__(self, message: str, user_message: str, ref: str) -> None:
        super().__init__(message)
        self.user_message = user_message
        self.error_ref = ref


def create_session_for_file(path: Path, project_id: int | None = None,
                            name: str | None = None) -> int:
    """Validate a source file, detect duplicates, create Session row.
    Returns session id. Raises PipelineError for unusable files."""
    ref = new_error_ref()
    if path.suffix.lower() not in audio_mod.SUPPORTED_EXTS:
        raise PipelineError(f"unsupported ext {path.suffix}",
                            f"'{path.suffix}' files are not supported. "
                            "Supported: audio (mp3, wav, m4a, flac, ogg...) "
                            "and video (mp4, mov, mkv, avi, webm...).", ref)
    try:
        info = audio_mod.probe(path)
    except AudioError as e:
        raise PipelineError(str(e), e.user_message, ref) from e
    if not info["has_audio"]:
        raise PipelineError("no audio stream",
                            "This file contains no audio track.", ref)
    fhash = audio_mod.file_hash(path)
    with db_session() as s:
        dup = s.scalars(select(Session).where(
            Session.file_hash == fhash,
            Session.is_deleted.is_(False))).first()
        if dup is not None:
            raise PipelineError(
                "duplicate file",
                f"This file was already imported as session "
                f"'{dup.name}'. Delete that session first if you want "
                "to process it again.", ref)
        sess = Session(name=name or path.stem, project_id=project_id,
                       source_type="file", source_path=str(path),
                       file_hash=fhash, duration_s=info["duration_s"],
                       status=SessionStatus.NEW)
        s.add(sess)
        s.flush()
        return sess.id


def transcribe_session(session_id: int, job_id: int | None = None,
                       progress: ProgressFn | None = None,
                       provider_key: str | None = None,
                       diarize: bool | None = None) -> None:
    """Run the full STT pipeline for a session. Blocking; call from a
    worker thread."""
    cfg = get_config_manager().config
    diarize = cfg.diarization if diarize is None else diarize
    ref = new_error_ref()

    with db_session() as s:
        sess = s.get(Session, session_id)
        if sess is None:
            raise PipelineError("session missing", "Session not found.", ref)
        sess.status = SessionStatus.PROCESSING
        src = Path(sess.source_path)

    def report(pct: float, stage: str) -> None:
        if progress:
            progress(pct, stage)
        if job_id is not None:
            with db_session() as s:
                job = s.get(ProcessingJob, job_id)
                if job is not None:
                    job.progress = pct
                    job.stage = stage

    tmp_root = Path(tempfile.mkdtemp(prefix="gva_",
                                     dir=str(_work_dir())))
    try:
        # 1. Convert to 16k mono wav
        report(2, "Preparing audio")
        wav = audio_mod.to_wav_16k_mono(
            src, tmp_root / "audio.wav",
            noise_reduction=cfg.noise_reduction)

        # 2. Silence check
        if not audio_mod.has_speech_energy(wav):
            raise PipelineError(
                "no speech energy",
                "No speech was detected in this recording. Check that "
                "the correct microphone was used and the audio is not "
                "silent.", ref)

        # 3. Chunk
        report(6, "Splitting audio")
        chunks = audio_mod.split_chunks(wav, tmp_root / "chunks",
                                        chunk_s=cfg.chunk_seconds)

        # 4. Transcribe with fallback chain, resuming completed chunks
        done_chunks: dict[str, dict] = {}
        if job_id is not None:
            with db_session() as s:
                job = s.get(ProcessingJob, job_id)
                if job is not None:
                    done_chunks = dict(job.state_json or {})

        providers = registry.get_stt_with_fallback(provider_key)
        merged: list[STTSegment] = []
        languages: list[str] = []
        used_provider = used_model = ""
        n = len(chunks)
        for i, (chunk_path, offset) in enumerate(chunks):
            key = f"chunk_{i}"
            if key in done_chunks:
                result = _result_from_state(done_chunks[key])
            else:
                result = _transcribe_with_chain(
                    providers, chunk_path, cfg.stt_language, diarize,
                    lambda p, st, i=i, n=n: report(
                        8 + (i + p / 100) * 80 / n,
                        f"Transcribing part {i + 1}/{n}"))
                done_chunks[key] = _result_to_state(result)
                if job_id is not None:
                    with db_session() as s:
                        job = s.get(ProcessingJob, job_id)
                        if job is not None:
                            job.state_json = dict(done_chunks)
            used_provider = result.provider or used_provider
            used_model = result.model or used_model
            for seg in result.segments:
                seg.start_s += offset
                seg.end_s += offset
                merged.append(seg)
            for lang in result.languages:
                if lang and lang not in languages:
                    languages.append(lang)

        merged.sort(key=lambda x: x.start_s)
        merged = _drop_overlap_dups(merged)

        # 5. Vocabulary correction
        report(90, "Applying custom vocabulary")
        terms = vocab.load_terms()
        for seg in merged:
            corrected = vocab.apply_corrections(seg.text, terms)
            seg.text = corrected

        # 6. Persist
        report(94, "Saving transcript")
        _save_segments(session_id, merged, languages,
                       used_provider, used_model)

        # 7. Cost
        with db_session() as s:
            sess = s.get(Session, session_id)
            dur = sess.duration_s if sess else 0.0
        cost = costs.estimate_stt_cost(used_provider, dur)
        costs.record_cost(used_provider, "transcribe", dur / 60.0,
                          "minutes", cost, session_id)
        with db_session() as s:
            sess = s.get(Session, session_id)
            if sess is not None:
                sess.cost_usd += cost
                sess.status = SessionStatus.READY
        report(100, "Completed")
    except (PipelineError, ProviderError, AudioError):
        with db_session() as s:
            sess = s.get(Session, session_id)
            if sess is not None:
                sess.status = SessionStatus.FAILED
        raise
    finally:
        _cleanup_tmp(tmp_root)


# ------------------------------------------------------------------ utils

def _work_dir() -> Path:
    d = app_data_dir() / "work"
    d.mkdir(exist_ok=True)
    return d


def _cleanup_tmp(root: Path) -> None:
    import shutil
    try:
        shutil.rmtree(root, ignore_errors=True)
    except OSError:
        pass


def _transcribe_with_chain(providers, path: Path, language: str,
                           diarize: bool, progress) -> STTResult:
    last: ProviderError | None = None
    for p in providers:
        try:
            return p.transcribe_file(path, language=language,
                                     diarize=diarize and
                                     p.supports_diarization,
                                     progress=progress)
        except ProviderError as e:
            log.warning("Provider %s failed: %s", p.key, e)
            last = e
    assert last is not None
    raise last


def _drop_overlap_dups(segs: list[STTSegment]) -> list[STTSegment]:
    """Remove near-identical segments produced by chunk overlap."""
    out: list[STTSegment] = []
    for seg in segs:
        if out and abs(seg.start_s - out[-1].start_s) < 0.6 \
                and seg.text.strip() == out[-1].text.strip():
            continue
        out.append(seg)
    return out


def _result_to_state(r: STTResult) -> dict:
    return {"provider": r.provider, "model": r.model,
            "languages": r.languages, "duration_s": r.duration_s,
            "segments": [asdict(s) for s in r.segments]}


def _result_from_state(d: dict) -> STTResult:
    from app.providers.base import Word
    segs = []
    for s in d.get("segments", []):
        words = [Word(**w) for w in s.get("words", [])]
        s2 = {k: v for k, v in s.items() if k != "words"}
        segs.append(STTSegment(**s2, words=words) if "words" not in s2
                    else STTSegment(**s2))
    return STTResult(segments=segs, languages=d.get("languages", []),
                     duration_s=d.get("duration_s", 0.0),
                     provider=d.get("provider", ""),
                     model=d.get("model", ""))


def _save_segments(session_id: int, segs: list[STTSegment],
                   languages: list[str], provider: str,
                   model: str) -> None:
    with db_session() as s:
        sess = s.get(Session, session_id)
        assert sess is not None
        # Replace any previous transcript (re-run case)
        for old in list(sess.segments):
            s.delete(old)
        for old_sp in list(sess.speakers):
            s.delete(old_sp)
        s.flush()

        speaker_map: dict[str, Speaker] = {}
        colors = ["#4F8EF7", "#F76F4F", "#4FCB8B", "#C77DFF", "#FFB84F",
                  "#5AD0D0"]
        for i, seg in enumerate(segs):
            sp = None
            if seg.speaker:
                sp = speaker_map.get(seg.speaker)
                if sp is None:
                    sp = Speaker(session_id=session_id, label=seg.speaker,
                                 color=colors[len(speaker_map)
                                              % len(colors)])
                    s.add(sp)
                    s.flush()
                    speaker_map[seg.speaker] = sp
            s.add(TranscriptSegment(
                session_id=session_id, idx=i, start_s=seg.start_s,
                end_s=seg.end_s, speaker_id=sp.id if sp else None,
                language=seg.language, text=seg.text,
                original_text=seg.text, confidence=seg.confidence,
                words_json=[asdict(w) for w in seg.words] or None))
        sess.language = ",".join(languages)
        sess.provider = provider
        sess.model = model
