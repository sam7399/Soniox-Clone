"""Local LLM adapter for Ollama (http://localhost:11434 by default).
Fully offline; used for summaries and analysis in Privacy Mode."""
from __future__ import annotations

import requests

from app.config import get_config_manager
from app.providers.base import LLMProvider, NetworkError, ProviderError


class OllamaLLM(LLMProvider):
    key = "ollama_llm"
    display_name = "Ollama (local)"
    is_local = True

    def complete(self, system: str, user: str,
                 max_tokens: int = 2000, json_mode: bool = False) -> str:
        pcfg = get_config_manager().get_provider(self.key)
        base = (pcfg.base_url or "http://localhost:11434").rstrip("/")
        model = pcfg.model or "llama3.1"
        payload: dict = {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        if json_mode:
            payload["format"] = "json"
        try:
            resp = requests.post(f"{base}/api/chat", json=payload,
                                 timeout=max(pcfg.timeout_s, 300))
        except requests.exceptions.RequestException as e:
            raise NetworkError(
                "Ollama not reachable") from e
        if resp.status_code == 404:
            raise ProviderError(
                f"Ollama model {model} not found",
                f"The local model '{model}' is not installed. Run "
                f"'ollama pull {model}' or pick another model in Settings.")
        if resp.status_code != 200:
            raise ProviderError(f"Ollama HTTP {resp.status_code}: "
                                f"{resp.text[:200]}")
        try:
            return resp.json()["message"]["content"]
        except (KeyError, ValueError) as e:
            raise ProviderError("Malformed Ollama response") from e
