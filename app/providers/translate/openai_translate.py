"""Translation via OpenAI chat completions, with glossary and
do-not-translate support. Segment boundaries are preserved 1:1 by using
a numbered JSON protocol rather than free text."""
from __future__ import annotations

import json

from app.config import get_config_manager
from app.providers.base import ProviderError, TranslationProvider
from app.providers.http_util import get_api_key, request_json

_BATCH = 40  # segments per request


class OpenAITranslate(TranslationProvider):
    key = "openai_translate"
    display_name = "OpenAI Translation (cloud)"
    is_local = False

    def translate_segments(self, texts: list[str], target_lang: str,
                           source_lang: str = "auto",
                           glossary: dict[str, str] | None = None,
                           do_not_translate: list[str] | None = None,
                           ) -> list[str]:
        if not texts:
            return []
        out: list[str] = []
        for i in range(0, len(texts), _BATCH):
            out.extend(self._translate_batch(
                texts[i:i + _BATCH], target_lang, source_lang,
                glossary or {}, do_not_translate or []))
        return out

    def _translate_batch(self, texts: list[str], target: str, source: str,
                         glossary: dict[str, str],
                         dnt: list[str]) -> list[str]:
        pcfg = get_config_manager().get_provider(self.key)
        base = pcfg.base_url or "https://api.openai.com/v1"
        model = pcfg.model or "gpt-4o-mini"

        rules = [f"Translate each numbered segment into {target}.",
                 "Return ONLY a JSON object: "
                 '{"segments": ["...", "..."]} with exactly '
                 f"{len(texts)} entries, same order.",
                 "Keep numbers, dates and proper names accurate."]
        if source not in ("", "auto"):
            rules.append(f"The source language is {source}.")
        if dnt:
            rules.append("Never translate these terms, keep them exactly "
                         "as written: " + ", ".join(dnt))
        if glossary:
            rules.append("Use this glossary (source=target): " +
                         "; ".join(f"{k}={v}" for k, v in glossary.items()))

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": " ".join(rules)},
                {"role": "user", "content": json.dumps(
                    {"segments": texts}, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        data = request_json(
            "POST", f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {get_api_key(self.key)}",
                     "Content-Type": "application/json"},
            json_body=payload, timeout_s=pcfg.timeout_s,
            retries=pcfg.retries)
        try:
            content = data["choices"][0]["message"]["content"]
            result = json.loads(content)["segments"]
        except (KeyError, IndexError, json.JSONDecodeError, TypeError) as e:
            raise ProviderError("Malformed translation response") from e
        if len(result) != len(texts):
            # Length mismatch: pad/trim so timestamps stay aligned.
            result = (result + [""] * len(texts))[:len(texts)]
        return [str(x) for x in result]
