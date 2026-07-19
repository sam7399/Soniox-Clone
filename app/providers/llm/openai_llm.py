"""LLM adapter for OpenAI-compatible chat-completions endpoints.

Because `base_url` is configurable, this same adapter also works with
Azure OpenAI (compatible mode), OpenRouter, Groq, LM Studio, or any
other OpenAI-compatible server.
"""
from __future__ import annotations

from app.config import get_config_manager
from app.providers.base import LLMProvider, ProviderError
from app.providers.http_util import get_api_key, request_json


class OpenAILLM(LLMProvider):
    key = "openai_llm"
    display_name = "OpenAI / compatible (cloud)"
    is_local = False

    def complete(self, system: str, user: str,
                 max_tokens: int = 2000, json_mode: bool = False) -> str:
        cfg = get_config_manager()
        pcfg = cfg.get_provider(self.key)
        base = pcfg.base_url or "https://api.openai.com/v1"
        model = pcfg.model or cfg.config.llm_model or "gpt-4o-mini"
        payload: dict = {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = request_json(
            "POST", f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {get_api_key(self.key)}",
                     "Content-Type": "application/json"},
            json_body=payload, timeout_s=pcfg.timeout_s,
            retries=pcfg.retries)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise ProviderError("Malformed LLM response") from e
