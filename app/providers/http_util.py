"""Shared HTTP plumbing for cloud adapters: retries, backoff and
mapping of HTTP failures to user-friendly ProviderError subclasses."""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

from app.providers.base import (AuthError, NetworkError, ProviderError,
                                QuotaError, RateLimitError)
from app.security.credentials import CredentialStore

log = logging.getLogger(__name__)
_store = CredentialStore()


def get_api_key(provider_key: str) -> str:
    key = _store.get_key(provider_key)
    if not key:
        raise AuthError(f"No API key stored for {provider_key}")
    return key


def request_json(method: str, url: str, *, headers: dict[str, str],
                 json_body: Any | None = None, data: bytes | None = None,
                 files: Any | None = None, timeout_s: int = 120,
                 retries: int = 2) -> dict:
    """HTTP request returning parsed JSON, with retry on transient errors."""
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.request(method, url, headers=headers,
                                    json=json_body, data=data, files=files,
                                    timeout=timeout_s)
        except requests.exceptions.RequestException as e:
            last_err = NetworkError(str(e))
            time.sleep(min(2 ** attempt, 8))
            continue

        if resp.status_code in (200, 201):
            try:
                return resp.json()
            except ValueError as e:
                raise ProviderError(f"Non-JSON response from {url}") from e
        if resp.status_code in (401, 403):
            raise AuthError(f"HTTP {resp.status_code} from {url}")
        if resp.status_code == 402 or "quota" in resp.text.lower()[:500]:
            raise QuotaError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        if resp.status_code == 429:
            last_err = RateLimitError(resp.text[:200])
            retry_after = resp.headers.get("Retry-After")
            time.sleep(float(retry_after) if retry_after else
                       min(2 ** (attempt + 1), 15))
            continue
        if resp.status_code >= 500:
            last_err = ProviderError(
                f"HTTP {resp.status_code}: {resp.text[:200]}",
                "The provider is having a temporary problem. "
                "Please try again shortly.", retryable=True)
            time.sleep(min(2 ** attempt, 8))
            continue
        raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    assert last_err is not None
    raise last_err


def get_binary(url: str, *, headers: dict[str, str], json_body: Any = None,
               timeout_s: int = 120) -> bytes:
    try:
        resp = requests.post(url, headers=headers, json=json_body,
                             timeout=timeout_s)
    except requests.exceptions.RequestException as e:
        raise NetworkError(str(e)) from e
    if resp.status_code in (401, 403):
        raise AuthError(f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.content
