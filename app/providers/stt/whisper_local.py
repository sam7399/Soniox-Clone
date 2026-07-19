"""Local offline transcription using faster-whisper (CTranslate2).

Models are downloaded on first use into the app data folder and reused.
Runs on CPU by default; uses CUDA automatically when available.
Per-segment language detection makes mixed-language audio (e.g. Hinglish)
come out labelled segment by segment.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.config import app_data_dir, get_config_manager
from app.providers.base import (ProgressFn, ProviderError, STTProvider,
                                STTResult, STTSegment, Word)

log = logging.getLogger(__name__)

MODEL_SIZES = ["tiny", "base", "small", "medium", "large-v3"]
MODEL_DISK_MB = {"tiny": 75, "base": 145, "small": 484,
                 "medium": 1530, "large-v3": 3100}


class WhisperLocalSTT(STTProvider):
    key = "whisper_local"
    display_name = "Local Whisper (offline)"
    is_local = True
    supports_diarization = False
    supports_streaming = False

    def __init__(self) -> None:
        self._model = None
        self._model_name = ""

    # ----------------------------------------------------------------
    def check_available(self) -> tuple[bool, str]:
        try:
            import faster_whisper  # noqa: F401
            return True, "ready (model downloads on first use)"
        except ImportError:
            return False, ("faster-whisper is not installed. Reinstall the "
                           "application or run: pip install faster-whisper")

    def _device(self) -> tuple[str, str]:
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                return "cuda", "float16"
        except Exception:
            pass
        return "cpu", "int8"

    def _load(self, model_name: str):
        if self._model is not None and self._model_name == model_name:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise ProviderError(
                "faster-whisper missing",
                "The offline transcription engine is not installed. "
                "Reinstall the application, or switch to a cloud provider "
                "in Settings.") from e
        device, compute = self._device()
        models_dir = app_data_dir() / "models"
        models_dir.mkdir(exist_ok=True)
        log.info("Loading whisper model %s on %s/%s", model_name, device,
                 compute)
        self._model = WhisperModel(model_name, device=device,
                                   compute_type=compute,
                                   download_root=str(models_dir))
        self._model_name = model_name
        return self._model

    # ----------------------------------------------------------------
    def transcribe_file(self, audio_path: Path, language: str = "auto",
                        diarize: bool = False,
                        progress: ProgressFn | None = None) -> STTResult:
        cfg = get_config_manager().config
        model_name = cfg.stt_model or "small"
        if progress:
            progress(1, f"Loading local model ({model_name})")
        model = self._load(model_name)

        lang = None if language in ("", "auto") else language
        if progress:
            progress(5, "Transcribing")
        try:
            segments_iter, info = model.transcribe(
                str(audio_path), language=lang, word_timestamps=True,
                vad_filter=cfg.vad_enabled)
        except Exception as e:
            raise ProviderError(
                f"Local transcription failed: {e}",
                "The offline engine could not process this audio. The file "
                "may be corrupted or unsupported.") from e

        total = getattr(info, "duration", 0.0) or 0.0
        segments: list[STTSegment] = []
        langs: list[str] = []
        detected = getattr(info, "language", "") or (lang or "")
        for seg in segments_iter:
            words = [Word(w.word.strip(), w.start, w.end,
                          getattr(w, "probability", 1.0) or 1.0)
                     for w in (seg.words or [])]
            conf = (sum(w.confidence for w in words) / len(words)
                    if words else 1.0)
            segments.append(STTSegment(
                start_s=seg.start, end_s=seg.end, text=seg.text.strip(),
                language=detected, confidence=conf, words=words))
            if detected and detected not in langs:
                langs.append(detected)
            if progress and total:
                progress(min(5 + 90 * seg.end / total, 95), "Transcribing")
        if progress:
            progress(100, "Done")
        return STTResult(segments=segments, languages=langs,
                         duration_s=total, provider=self.key,
                         model=model_name)

    # -- model manager helpers ---------------------------------------
    @staticmethod
    def installed_models() -> list[str]:
        models_dir = app_data_dir() / "models"
        if not models_dir.exists():
            return []
        found = []
        for size in MODEL_SIZES:
            for p in models_dir.glob(f"*{size}*"):
                if p.is_dir():
                    found.append(size)
                    break
        return found
