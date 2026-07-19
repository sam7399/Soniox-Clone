"""Runtime provider registry with privacy-mode enforcement and fallback."""
from __future__ import annotations

import logging
from typing import TypeVar

from app.config import get_config_manager
from app.providers.base import (LLMProvider, ProviderError, STTProvider,
                                TranslationProvider, TTSProvider)

log = logging.getLogger(__name__)
T = TypeVar("T")

_stt: dict[str, STTProvider] = {}
_translate: dict[str, TranslationProvider] = {}
_tts: dict[str, TTSProvider] = {}
_llm: dict[str, LLMProvider] = {}


def register_stt(p: STTProvider) -> None: _stt[p.key] = p
def register_translate(p: TranslationProvider) -> None: _translate[p.key] = p
def register_tts(p: TTSProvider) -> None: _tts[p.key] = p
def register_llm(p: LLMProvider) -> None: _llm[p.key] = p


def _check_privacy(provider) -> None:
    cfg = get_config_manager().config
    if cfg.privacy_mode and not provider.is_local:
        raise ProviderError(
            f"Privacy mode blocks cloud provider {provider.key}",
            "Privacy Mode is on: only local providers may be used. "
            "Turn off Privacy Mode in Settings > Security to use cloud "
            "services.")


def _get(table: dict[str, T], key: str, kind: str) -> T:
    if key not in table:
        raise ProviderError(
            f"Unknown {kind} provider '{key}'",
            f"The configured {kind} provider is not installed. "
            "Choose another one in Settings.")
    p = table[key]
    _check_privacy(p)
    return p


def get_stt(key: str | None = None) -> STTProvider:
    cfg = get_config_manager().config
    return _get(_stt, key or cfg.stt_provider, "transcription")


def get_stt_with_fallback(key: str | None = None) -> list[STTProvider]:
    """Primary provider followed by the configured fallback, if any."""
    cfg = get_config_manager().config
    chain = [get_stt(key)]
    fb = cfg.stt_fallback_provider
    if fb and fb != chain[0].key and fb in _stt:
        try:
            chain.append(get_stt(fb))
        except ProviderError:
            pass
    return chain


def get_translate(key: str | None = None) -> TranslationProvider:
    cfg = get_config_manager().config
    return _get(_translate, key or cfg.translate_provider, "translation")


def get_tts(key: str | None = None) -> TTSProvider:
    cfg = get_config_manager().config
    return _get(_tts, key or cfg.tts_provider, "text-to-speech")


def get_llm(key: str | None = None) -> LLMProvider:
    cfg = get_config_manager().config
    return _get(_llm, key or cfg.llm_provider, "AI analysis")


def all_stt() -> dict[str, STTProvider]: return dict(_stt)
def all_translate() -> dict[str, TranslationProvider]: return dict(_translate)
def all_tts() -> dict[str, TTSProvider]: return dict(_tts)
def all_llm() -> dict[str, LLMProvider]: return dict(_llm)


def register_builtin_providers() -> None:
    """Import and register every bundled adapter. Safe to call twice."""
    from app.providers.stt.whisper_local import WhisperLocalSTT
    from app.providers.stt.openai_stt import OpenAISTT
    from app.providers.stt.deepgram_stt import DeepgramSTT
    from app.providers.stt.soniox_stt import SonioxSTT
    from app.providers.translate.openai_translate import OpenAITranslate
    from app.providers.translate.local_translate import PassthroughTranslate
    from app.providers.tts.openai_tts import OpenAITTS
    from app.providers.tts.local_tts import LocalTTS
    from app.providers.llm.openai_llm import OpenAILLM
    from app.providers.llm.ollama_llm import OllamaLLM

    for p in (WhisperLocalSTT(), OpenAISTT(), DeepgramSTT(), SonioxSTT()):
        register_stt(p)
    for t in (OpenAITranslate(), PassthroughTranslate()):
        register_translate(t)
    for t in (OpenAITTS(), LocalTTS()):
        register_tts(t)
    for l in (OpenAILLM(), OllamaLLM()):
        register_llm(l)
    log.info("Registered providers: stt=%s translate=%s tts=%s llm=%s",
             list(_stt), list(_translate), list(_tts), list(_llm))
