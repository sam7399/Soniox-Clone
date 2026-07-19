"""OpenAI text-to-speech adapter."""
from __future__ import annotations

from pathlib import Path

from app.config import get_config_manager
from app.providers.base import TTSProvider, TTSVoice
from app.providers.http_util import get_api_key, get_binary

_VOICES = ["alloy", "ash", "coral", "echo", "fable", "onyx", "nova",
           "sage", "shimmer"]


class OpenAITTS(TTSProvider):
    key = "openai_tts"
    display_name = "OpenAI TTS (cloud)"
    is_local = False

    def list_voices(self) -> list[TTSVoice]:
        return [TTSVoice(v, v.title(), "multilingual") for v in _VOICES]

    def synthesize(self, text: str, voice_id: str, out_path: Path,
                   speed: float = 1.0, fmt: str = "wav") -> Path:
        pcfg = get_config_manager().get_provider(self.key)
        base = pcfg.base_url or "https://api.openai.com/v1"
        model = pcfg.model or "gpt-4o-mini-tts"
        fmt = "wav" if fmt not in ("mp3", "wav", "opus", "flac") else fmt
        audio = get_binary(
            f"{base}/audio/speech",
            headers={"Authorization": f"Bearer {get_api_key(self.key)}",
                     "Content-Type": "application/json"},
            json_body={"model": model, "voice": voice_id or "alloy",
                       "input": text[:4000], "speed": speed,
                       "response_format": fmt},
            timeout_s=pcfg.timeout_s)
        out_path = out_path.with_suffix(f".{fmt}")
        out_path.write_bytes(audio)
        return out_path
