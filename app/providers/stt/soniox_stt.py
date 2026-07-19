"""Soniox async file-transcription adapter (REST).

Flow: upload file -> create transcription -> poll status -> fetch
transcript tokens. Soniox returns token-level language and speaker
fields, which makes it well suited to mixed-language (e.g. Hinglish)
audio. Requires a licensed Soniox API key.
"""
from __future__ import annotations

import time
from pathlib import Path

from app.config import get_config_manager
from app.providers.base import (ProgressFn, ProviderError, STTProvider,
                                STTResult, STTSegment, Word)
from app.providers.http_util import get_api_key, request_json


class SonioxSTT(STTProvider):
    key = "soniox_stt"
    display_name = "Soniox (cloud)"
    is_local = False
    supports_diarization = True
    supports_streaming = True

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
        base = (pcfg.base_url or "https://api.soniox.com").rstrip("/")
        model = pcfg.model or "stt-async-preview"
        headers = {"Authorization": f"Bearer {get_api_key(self.key)}"}

        # 1. Upload
        if progress:
            progress(5, "Uploading to Soniox")
        with open(audio_path, "rb") as f:
            up = request_json("POST", f"{base}/v1/files", headers=headers,
                              files={"file": (audio_path.name, f)},
                              timeout_s=pcfg.timeout_s, retries=pcfg.retries)
        file_id = up.get("id")
        if not file_id:
            raise ProviderError(f"Soniox upload response missing id: {up}")

        # 2. Create transcription
        body: dict = {"file_id": file_id, "model": model}
        if diarize:
            body["enable_speaker_diarization"] = True
        body["enable_language_identification"] = True
        if language not in ("", "auto"):
            body["language_hints"] = [language]
        tr = request_json("POST", f"{base}/v1/transcriptions",
                          headers=headers, json_body=body,
                          timeout_s=pcfg.timeout_s, retries=pcfg.retries)
        tr_id = tr.get("id")
        if not tr_id:
            raise ProviderError(f"Soniox create response missing id: {tr}")

        # 3. Poll
        deadline = time.monotonic() + max(pcfg.timeout_s, 600)
        while True:
            st = request_json("GET", f"{base}/v1/transcriptions/{tr_id}",
                              headers=headers, timeout_s=30, retries=1)
            status = st.get("status", "")
            if status == "completed":
                break
            if status == "error":
                raise ProviderError(
                    f"Soniox transcription failed: {st.get('error_message')}",
                    "Soniox could not process this file.")
            if time.monotonic() > deadline:
                raise ProviderError("Soniox transcription timed out",
                                    "The provider took too long. Try again "
                                    "or use another provider.",
                                    retryable=True)
            if progress:
                progress(min(20 + 60 * 0.5, 80), "Waiting for Soniox")
            time.sleep(2)

        # 4. Fetch tokens
        data = request_json("GET",
                            f"{base}/v1/transcriptions/{tr_id}/transcript",
                            headers=headers, timeout_s=60, retries=1)
        tokens = data.get("tokens", [])
        segments = self._tokens_to_segments(tokens)
        langs: list[str] = []
        for s in segments:
            if s.language and s.language not in langs:
                langs.append(s.language)
        dur = segments[-1].end_s if segments else 0.0
        if progress:
            progress(100, "Done")
        return STTResult(segments=segments, languages=langs,
                         duration_s=dur, provider=self.key, model=model)

    # -- real-time streaming ------------------------------------------
    def transcribe_stream(self, pcm_chunks, sample_rate: int,
                          language: str = "auto"):
        """Stream 16-bit mono PCM to the Soniox realtime endpoint.

        Yields STTSegment objects: is_final=False partials (rolling
        hypothesis, replace previous partial) and is_final=True
        segments (append). Ends when pcm_chunks is exhausted.
        """
        import json as _json
        import threading as _threading

        try:
            import websocket  # websocket-client
        except ImportError as e:
            raise ProviderError(
                "websocket-client not installed",
                "Streaming support is missing from this build. "
                "Reinstall the application.") from e

        pcfg = get_config_manager().get_provider(self.key)
        url = (pcfg.base_url
               if pcfg.base_url.startswith("ws")
               else "wss://stt-rt.soniox.com/transcribe-websocket")
        start_msg: dict = {
            "api_key": get_api_key(self.key),
            "model": (pcfg.model if "rt" in pcfg.model
                      else "stt-rt-preview"),
            "audio_format": "pcm_s16le",
            "sample_rate": sample_rate,
            "num_channels": 1,
            "enable_language_identification": True,
            "enable_speaker_diarization": True,
        }
        if language not in ("", "auto"):
            start_msg["language_hints"] = [language]

        try:
            ws = websocket.create_connection(url, timeout=15)
        except Exception as e:
            raise ProviderError(
                f"Soniox realtime connect failed: {e}",
                "Could not connect to the Soniox realtime service. "
                "Check your internet connection and API key.",
                retryable=True) from e
        ws.send(_json.dumps(start_msg))

        send_err: list[Exception] = []

        def _sender() -> None:
            try:
                for chunk in pcm_chunks:
                    ws.send_binary(chunk)
                ws.send("")          # empty message = end of audio
            except Exception as e:   # surfaced via queue drain below
                send_err.append(e)

        t = _threading.Thread(target=_sender, daemon=True,
                              name="soniox-stream-send")
        t.start()

        try:
            while True:
                raw = ws.recv()
                if not raw:
                    break
                msg = _json.loads(raw)
                if msg.get("error_code"):
                    raise ProviderError(
                        f"Soniox realtime error {msg['error_code']}: "
                        f"{msg.get('error_message')}",
                        "The Soniox realtime service reported an "
                        "error. Check your API key and plan.")
                tokens = msg.get("tokens", [])
                finals = [tk for tk in tokens if tk.get("is_final")]
                partials = [tk for tk in tokens
                            if not tk.get("is_final")]
                for seg in self._tokens_to_segments(finals):
                    seg.is_final = True
                    yield seg
                if partials:
                    text = "".join(tk.get("text", "")
                                   for tk in partials).strip()
                    if text:
                        yield STTSegment(
                            start_s=partials[0].get("start_ms", 0)
                            / 1000.0,
                            end_s=partials[-1].get("end_ms", 0) / 1000.0,
                            text=text,
                            language=partials[-1].get("language", ""),
                            is_final=False)
                if msg.get("finished"):
                    break
        finally:
            try:
                ws.close()
            except Exception:
                pass
        if send_err:
            raise ProviderError(f"stream send failed: {send_err[0]}",
                                "The audio stream was interrupted.",
                                retryable=True)

    @staticmethod
    def _tokens_to_segments(tokens: list[dict]) -> list[STTSegment]:
        """Group word tokens into segments on speaker or language change,
        or on gaps longer than one second."""
        segments: list[STTSegment] = []
        cur_words: list[Word] = []
        cur_speaker = cur_lang = ""

        def flush() -> None:
            nonlocal cur_words
            if not cur_words:
                return
            text = "".join(w.text for w in cur_words).strip()
            conf = sum(w.confidence for w in cur_words) / len(cur_words)
            spk = f"Speaker {cur_speaker}" if cur_speaker else ""
            segments.append(STTSegment(
                start_s=cur_words[0].start_s, end_s=cur_words[-1].end_s,
                text=text, language=cur_lang, speaker=spk,
                confidence=conf, words=list(cur_words)))
            cur_words = []

        for t in tokens:
            text = t.get("text", "")
            start = t.get("start_ms", 0) / 1000.0
            end = t.get("end_ms", t.get("start_ms", 0)
                        + t.get("duration_ms", 0)) / 1000.0
            spk = str(t.get("speaker", "") or "")
            lang = t.get("language", "") or ""
            gap = (cur_words and start - cur_words[-1].end_s > 1.0)
            if cur_words and (spk != cur_speaker or lang != cur_lang or gap):
                flush()
            cur_speaker, cur_lang = spk, lang
            cur_words.append(Word(text, start, end,
                                  t.get("confidence", 1.0)))
        flush()
        return segments
