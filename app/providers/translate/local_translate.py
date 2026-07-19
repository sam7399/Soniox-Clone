"""Local translation placeholder provider.

v1 ships without a bundled offline translation model (they are large).
This provider exists so Privacy Mode has a registered local option: it
returns the original text unchanged and reports clearly that no local
translation model is installed. A future version can wire in Argos
Translate or an Ollama model here.
"""
from __future__ import annotations

from app.providers.base import ProviderError, TranslationProvider


class PassthroughTranslate(TranslationProvider):
    key = "local_translate"
    display_name = "Local translation (not installed)"
    is_local = True

    def translate_segments(self, texts, target_lang, source_lang="auto",
                           glossary=None, do_not_translate=None):
        raise ProviderError(
            "No local translation model installed",
            "Offline translation is not installed in this version. "
            "Turn off Privacy Mode to use a cloud translator, or keep "
            "the transcript in its original language.")
