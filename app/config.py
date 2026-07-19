"""Central configuration for GlobalVoice AI.

Settings live in a JSON file under the per-user application data folder
(%APPDATA%/GlobalVoiceAI on Windows, ~/.globalvoiceai elsewhere).
A portable install is detected by a `portable.flag` file next to the
executable, in which case everything is stored under ./data.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

APP_NAME = "GlobalVoice AI"
APP_ID = "GlobalVoiceAI"
APP_VERSION = "1.0.0"
TAGLINE = "Understand Every Voice. In Every Language."


def _exe_dir() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller bundle
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def is_portable() -> bool:
    return (_exe_dir() / "portable.flag").exists()


def app_data_dir() -> Path:
    if is_portable():
        d = _exe_dir() / "data"
    elif os.name == "nt":
        d = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_ID
    else:
        d = Path.home() / f".{APP_ID.lower()}"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class ProviderConfig:
    """Per-provider connection settings. API keys are stored separately
    in the encrypted credential store, never here."""
    name: str = ""
    base_url: str = ""
    model: str = ""
    region: str = ""
    language: str = "auto"
    timeout_s: int = 120
    retries: int = 2
    max_file_mb: int = 500
    enabled: bool = True


@dataclass
class AppConfig:
    # General
    app_name: str = APP_NAME
    ui_language: str = "en"
    theme: str = "dark"                      # dark | light | system
    date_format: str = "yyyy-MM-dd"
    time_format: str = "HH:mm:ss"
    default_save_folder: str = ""
    auto_save_interval_s: int = 30
    check_updates: bool = True

    # Audio
    input_device: str = ""                   # "" = system default
    sample_rate: int = 16000
    noise_reduction: bool = False
    vad_enabled: bool = True

    # Transcription
    stt_provider: str = "whisper_local"      # provider registry key
    stt_fallback_provider: str = ""
    stt_model: str = "small"
    stt_language: str = "auto"
    diarization: bool = False
    confidence_threshold: float = 0.55       # below this, words are flagged
    chunk_seconds: int = 300                 # long-file chunk size

    # Translation
    translate_provider: str = "openai_translate"
    translate_target: str = "en"
    preserve_names: bool = True

    # TTS
    tts_provider: str = "local_tts"
    tts_voice: str = ""
    tts_speed: float = 1.0
    tts_format: str = "wav"

    # AI analysis
    llm_provider: str = "openai_llm"
    llm_model: str = "gpt-4o-mini"
    summary_style: str = "detailed"
    max_output_tokens: int = 2000
    custom_instructions: str = ""

    # Storage
    db_path: str = ""                        # "" = default under app data
    attachments_dir: str = ""
    backup_dir: str = ""
    retention_days: int = 0                  # 0 = keep forever

    # Security / privacy
    privacy_mode: bool = False               # True = local-only, no cloud calls
    session_timeout_min: int = 0
    audit_logging: bool = True

    # Cost control
    monthly_budget_usd: float = 0.0          # 0 = no limit
    warn_at_percent: int = 80

    # Providers (connection settings only; keys are in credential store)
    providers: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Bookkeeping
    first_run_done: bool = False
    schema_version: int = 1


class ConfigManager:
    """Thread-safe load/save of AppConfig as JSON."""

    def __init__(self, path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self.path = path or (app_data_dir() / "config.json")
        self.config = self._load()

    def _load(self) -> AppConfig:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                known = {f for f in AppConfig.__dataclass_fields__}
                return AppConfig(**{k: v for k, v in raw.items() if k in known})
            except (json.JSONDecodeError, TypeError, ValueError):
                # Corrupt config: keep a copy, start fresh.
                try:
                    self.path.rename(self.path.with_suffix(".json.bak"))
                except OSError:
                    pass
        return AppConfig()

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(asdict(self.config), indent=2,
                                      ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)

    def get_provider(self, key: str) -> ProviderConfig:
        raw = self.config.providers.get(key, {})
        known = {f for f in ProviderConfig.__dataclass_fields__}
        return ProviderConfig(**{k: v for k, v in raw.items() if k in known})

    def set_provider(self, key: str, cfg: ProviderConfig) -> None:
        self.config.providers[key] = asdict(cfg)
        self.save()


_manager: ConfigManager | None = None


def get_config_manager() -> ConfigManager:
    global _manager
    if _manager is None:
        _manager = ConfigManager()
    return _manager
