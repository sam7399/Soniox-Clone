"""Provider abstraction layer.

Every AI capability (speech-to-text, translation, text-to-speech,
LLM analysis) is an interface. Concrete adapters live in subpackages and
register themselves in the registry. The app never talks to a vendor SDK
directly - only through these interfaces - so providers can be swapped,
chained (fallback), or disabled (privacy mode) at runtime.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator


class ProviderError(Exception):
    """Base error. `user_message` is safe to show to non-technical users."""

    def __init__(self, message: str, user_message: str | None = None,
                 retryable: bool = False) -> None:
        super().__init__(message)
        self.user_message = user_message or (
            "The AI service could not complete this task. "
            "Check the provider settings and try again.")
        self.retryable = retryable


class AuthError(ProviderError):
    def __init__(self, message: str = "Invalid API key") -> None:
        super().__init__(message, "The API key for this provider was "
                         "rejected. Open Settings and check the key.")


class QuotaError(ProviderError):
    def __init__(self, message: str = "Quota exceeded") -> None:
        super().__init__(message, "The provider reports your usage quota "
                         "is exhausted. Check billing, or switch to the "
                         "local offline model.", retryable=False)


class RateLimitError(ProviderError):
    def __init__(self, message: str = "Rate limited") -> None:
        super().__init__(message, "The provider is rate-limiting requests. "
                         "The app will retry automatically.", retryable=True)


class NetworkError(ProviderError):
    def __init__(self, message: str = "Network unavailable") -> None:
        super().__init__(message, "Could not reach the provider. Check your "
                         "internet connection, or switch to offline mode.",
                         retryable=True)


# ------------------------------------------------------------------ STT

@dataclass
class Word:
    text: str
    start_s: float
    end_s: float
    confidence: float = 1.0


@dataclass
class STTSegment:
    start_s: float
    end_s: float
    text: str
    language: str = ""
    speaker: str = ""          # "Speaker 1" etc. when diarization available
    confidence: float = 1.0
    words: list[Word] = field(default_factory=list)
    is_final: bool = True      # False = streaming partial, will be revised


@dataclass
class STTResult:
    segments: list[STTSegment]
    languages: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    provider: str = ""
    model: str = ""


ProgressFn = Callable[[float, str], None]   # (percent 0..100, stage text)


class STTProvider(abc.ABC):
    key: str = ""
    display_name: str = ""
    is_local: bool = False
    supports_diarization: bool = False
    supports_streaming: bool = False

    @abc.abstractmethod
    def transcribe_file(self, audio_path: Path, language: str = "auto",
                        diarize: bool = False,
                        progress: ProgressFn | None = None) -> STTResult: ...

    def transcribe_stream(self, pcm_chunks: Iterator[bytes],
                          sample_rate: int, language: str = "auto",
                          ) -> Iterator[STTSegment]:
        raise NotImplementedError(
            f"{self.display_name} does not support streaming")

    def check_available(self) -> tuple[bool, str]:
        """Return (ok, human readable status)."""
        return True, "ready"


# ------------------------------------------------------------ Translation

class TranslationProvider(abc.ABC):
    key: str = ""
    display_name: str = ""
    is_local: bool = False

    @abc.abstractmethod
    def translate_segments(self, texts: list[str], target_lang: str,
                           source_lang: str = "auto",
                           glossary: dict[str, str] | None = None,
                           do_not_translate: list[str] | None = None,
                           ) -> list[str]: ...


# ------------------------------------------------------------------ TTS

@dataclass
class TTSVoice:
    id: str
    name: str
    language: str = ""
    gender: str = ""


class TTSProvider(abc.ABC):
    key: str = ""
    display_name: str = ""
    is_local: bool = False

    @abc.abstractmethod
    def list_voices(self) -> list[TTSVoice]: ...

    @abc.abstractmethod
    def synthesize(self, text: str, voice_id: str, out_path: Path,
                   speed: float = 1.0, fmt: str = "wav") -> Path: ...


# ------------------------------------------------------------------ LLM

class LLMProvider(abc.ABC):
    key: str = ""
    display_name: str = ""
    is_local: bool = False

    @abc.abstractmethod
    def complete(self, system: str, user: str,
                 max_tokens: int = 2000, json_mode: bool = False) -> str: ...
