"""Offline TTS via pyttsx3 (Windows SAPI5 voices).

Voice availability and languages depend on the voices installed in
Windows. Output is always WAV. Runs fully offline.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.providers.base import ProviderError, TTSProvider, TTSVoice

log = logging.getLogger(__name__)


class LocalTTS(TTSProvider):
    key = "local_tts"
    display_name = "Local voices (offline)"
    is_local = True

    def _engine(self):
        try:
            import pyttsx3
            return pyttsx3.init()
        except Exception as e:
            raise ProviderError(
                f"pyttsx3 init failed: {e}",
                "No offline voice engine is available on this computer. "
                "Install Windows voices (Settings > Time & Language > "
                "Speech) or use a cloud TTS provider.") from e

    def list_voices(self) -> list[TTSVoice]:
        try:
            eng = self._engine()
            voices = []
            for v in eng.getProperty("voices"):
                langs = getattr(v, "languages", []) or []
                lang = (langs[0].decode() if langs and
                        isinstance(langs[0], bytes) else
                        str(langs[0]) if langs else "")
                voices.append(TTSVoice(v.id, v.name, lang,
                                       getattr(v, "gender", "") or ""))
            eng.stop()
            return voices
        except ProviderError:
            return []

    def synthesize(self, text: str, voice_id: str, out_path: Path,
                   speed: float = 1.0, fmt: str = "wav") -> Path:
        eng = self._engine()
        if voice_id:
            eng.setProperty("voice", voice_id)
        base_rate = eng.getProperty("rate") or 200
        eng.setProperty("rate", int(base_rate * speed))
        out_path = out_path.with_suffix(".wav")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        eng.save_to_file(text, str(out_path))
        eng.runAndWait()
        eng.stop()
        if not out_path.exists():
            raise ProviderError("Local TTS produced no output",
                                "The offline voice engine failed to "
                                "generate audio. Try a different voice.")
        return out_path
