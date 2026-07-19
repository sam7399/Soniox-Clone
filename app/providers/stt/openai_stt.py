"""OpenAI Whisper API adapter (audio/transcriptions, verbose_json)."""
from __future__ import annotations

from pathlib import Path

from app.config import get_config_manager
from app.providers.base import (ProgressFn, STTProvider, STTResult,
                                STTSegment)
from app.providers.http_util import get_api_key, request_json


class OpenAISTT(STTProvider):
    key = "openai_stt"
    display_name = "OpenAI Whisper (cloud)"
    is_local = False
    supports_diarization = False

    def check_available(self) -> tuple[bool, str]:
        try:
            get_api_key(self.key)
            return True, "API key configured"
        except Exception:
            return False, "No API key configured (Settings > Providers)"

    def transcribe_file(self, audio_path: Path, language: str = "auto",
                        diarize: bool = False,
                        progress: ProgressFn | None = None) -> STTResult:
        pcfg = get_config_manager().get_provider(self.key)
        base = pcfg.base_url or "https://api.openai.com/v1"
        model = pcfg.model or "whisper-1"
        api_key = get_api_key(self.key)
        if progress:
            progress(10, "Uploading to OpenAI")

        with open(audio_path, "rb") as f:
            data = request_json(
                "POST", f"{base}/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (audio_path.name, f),
                       "model": (None, model),
                       "response_format": (None, "verbose_json"),
                       **({"language": (None, language)}
                          if language not in ("", "auto") else {})},
                timeout_s=pcfg.timeout_s, retries=pcfg.retries)

        if progress:
            progress(90, "Parsing response")
        detected = data.get("language", "")
        segments = [STTSegment(
            start_s=s.get("start", 0.0), end_s=s.get("end", 0.0),
            text=(s.get("text") or "").strip(), language=detected,
            confidence=min(1.0, max(0.0, 1.0 + s.get("avg_logprob", 0.0))))
            for s in data.get("segments", [])]
        if not segments and data.get("text"):
            segments = [STTSegment(0.0, data.get("duration", 0.0),
                                   data["text"].strip(), detected)]
        if progress:
            progress(100, "Done")
        return STTResult(segments=segments,
                         languages=[detected] if detected else [],
                         duration_s=data.get("duration", 0.0),
                         provider=self.key, model=model)
