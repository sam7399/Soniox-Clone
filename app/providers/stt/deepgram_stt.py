"""Deepgram pre-recorded transcription adapter (nova-2, diarization)."""
from __future__ import annotations

from pathlib import Path

from app.config import get_config_manager
from app.providers.base import (ProgressFn, ProviderError, STTProvider,
                                STTResult, STTSegment, Word)
from app.providers.http_util import get_api_key, request_json


class DeepgramSTT(STTProvider):
    key = "deepgram_stt"
    display_name = "Deepgram (cloud)"
    is_local = False
    supports_diarization = True

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
        base = pcfg.base_url or "https://api.deepgram.com/v1"
        model = pcfg.model or "nova-2"
        api_key = get_api_key(self.key)

        params = [f"model={model}", "smart_format=true", "punctuate=true",
                  "utterances=true"]
        if diarize:
            params.append("diarize=true")
        if language not in ("", "auto"):
            params.append(f"language={language}")
        else:
            params.append("detect_language=true")
        url = f"{base}/listen?{'&'.join(params)}"

        if progress:
            progress(10, "Uploading to Deepgram")
        data = request_json(
            "POST", url,
            headers={"Authorization": f"Token {api_key}",
                     "Content-Type": "audio/*"},
            data=audio_path.read_bytes(),
            timeout_s=pcfg.timeout_s, retries=pcfg.retries)

        if progress:
            progress(90, "Parsing response")
        try:
            results = data["results"]
            channel = results["channels"][0]
            alt = channel["alternatives"][0]
        except (KeyError, IndexError) as e:
            raise ProviderError("Unexpected Deepgram response shape") from e

        detected = channel.get("detected_language", "") or (
            language if language != "auto" else "")
        segments: list[STTSegment] = []
        utterances = results.get("utterances") or []
        if utterances:
            for u in utterances:
                spk = (f"Speaker {u['speaker'] + 1}"
                       if diarize and "speaker" in u else "")
                segments.append(STTSegment(
                    start_s=u["start"], end_s=u["end"],
                    text=u["transcript"].strip(), language=detected,
                    speaker=spk, confidence=u.get("confidence", 1.0)))
        else:
            words = [Word(w["word"], w["start"], w["end"],
                          w.get("confidence", 1.0))
                     for w in alt.get("words", [])]
            segments = [STTSegment(
                start_s=words[0].start_s if words else 0.0,
                end_s=words[-1].end_s if words else 0.0,
                text=alt.get("transcript", "").strip(),
                language=detected, words=words,
                confidence=alt.get("confidence", 1.0))]
        dur = (data.get("metadata") or {}).get("duration", 0.0)
        if progress:
            progress(100, "Done")
        return STTResult(segments=segments,
                         languages=[detected] if detected else [],
                         duration_s=dur, provider=self.key, model=model)
