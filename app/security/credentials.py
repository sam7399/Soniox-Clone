"""Encrypted API-key storage.

Primary backend: OS keyring (Windows Credential Manager on Windows).
Fallback: Fernet-encrypted file under the app data folder, with the key
material itself stored in the keyring when available. Keys are never
written to config files or logs in plain text.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path

from app.config import APP_ID, app_data_dir

log = logging.getLogger(__name__)

_SERVICE = APP_ID


def _keyring():
    try:
        import keyring
        # Force failure early if no usable backend.
        keyring.get_keyring()
        return keyring
    except Exception:  # pragma: no cover - environment dependent
        return None


class CredentialStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self._dir = data_dir or app_data_dir()
        self._kr = _keyring()

    # -- public API ---------------------------------------------------
    def set_key(self, provider: str, api_key: str) -> None:
        if self._kr is not None:
            try:
                self._kr.set_password(_SERVICE, provider, api_key)
                return
            except Exception:
                log.warning("Keyring unavailable, using encrypted file store")
        self._file_set(provider, api_key)

    def get_key(self, provider: str) -> str | None:
        if self._kr is not None:
            try:
                v = self._kr.get_password(_SERVICE, provider)
                if v is not None:
                    return v
            except Exception:
                pass
        return self._file_get(provider)

    def delete_key(self, provider: str) -> None:
        if self._kr is not None:
            try:
                self._kr.delete_password(_SERVICE, provider)
            except Exception:
                pass
        data = self._file_load()
        if provider in data:
            del data[provider]
            self._file_save(data)

    def has_key(self, provider: str) -> bool:
        return bool(self.get_key(provider))

    # -- encrypted-file fallback --------------------------------------
    def _fernet(self):
        from cryptography.fernet import Fernet
        key_path = self._dir / ".credkey"
        if key_path.exists():
            key = key_path.read_bytes()
        else:
            key = Fernet.generate_key()
            key_path.write_bytes(key)
            if os.name != "nt":
                os.chmod(key_path, 0o600)
        return Fernet(key)

    def _cred_file(self) -> Path:
        return self._dir / "credentials.enc"

    def _file_load(self) -> dict[str, str]:
        p = self._cred_file()
        if not p.exists():
            return {}
        try:
            raw = self._fernet().decrypt(p.read_bytes())
            return json.loads(raw.decode("utf-8"))
        except Exception:
            log.error("Credential file unreadable; treating as empty")
            return {}

    def _file_save(self, data: dict[str, str]) -> None:
        blob = self._fernet().encrypt(json.dumps(data).encode("utf-8"))
        p = self._cred_file()
        p.write_bytes(blob)
        if os.name != "nt":
            os.chmod(p, 0o600)

    def _file_set(self, provider: str, api_key: str) -> None:
        data = self._file_load()
        data[provider] = api_key
        self._file_save(data)

    def _file_get(self, provider: str) -> str | None:
        return self._file_load().get(provider)


def redact(value: str | None) -> str:
    """Safe representation for logs/UI: never the real key."""
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "****"
    return value[:4] + "…" + value[-2:]
