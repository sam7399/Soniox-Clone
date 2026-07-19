"""Settings page: general, transcription, providers/API keys, privacy.
API keys go straight into the encrypted credential store and are shown
only in redacted form."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox,
                               QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget)

from app.config import get_config_manager
from app.providers import registry
from app.security.credentials import CredentialStore, redact

KEYED_PROVIDERS = [
    ("openai_stt", "OpenAI (Whisper STT)"),
    ("deepgram_stt", "Deepgram"),
    ("soniox_stt", "Soniox"),
    ("openai_translate", "OpenAI (Translation)"),
    ("openai_tts", "OpenAI (TTS)"),
    ("openai_llm", "OpenAI / compatible (Summaries)"),
]


class SettingsPage(QWidget):
    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self.store = CredentialStore()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        h1 = QLabel("Settings")
        h1.setProperty("h1", True)
        outer.addWidget(h1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;}")
        inner = QWidget()
        v = QVBoxLayout(inner)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        cfg = get_config_manager().config

        # Transcription -----------------------------------------------
        g1 = QGroupBox("Transcription")
        f1 = QFormLayout(g1)
        self.stt_box = QComboBox()
        for key, p in registry.all_stt().items():
            self.stt_box.addItem(p.display_name, key)
        _set_by_data(self.stt_box, cfg.stt_provider)
        f1.addRow("Default provider:", self.stt_box)
        self.fb_box = QComboBox()
        self.fb_box.addItem("(none)", "")
        for key, p in registry.all_stt().items():
            self.fb_box.addItem(p.display_name, key)
        _set_by_data(self.fb_box, cfg.stt_fallback_provider)
        f1.addRow("Fallback provider:", self.fb_box)
        self.model_box = QComboBox()
        for m in ("tiny", "base", "small", "medium", "large-v3"):
            self.model_box.addItem(m)
        self.model_box.setCurrentText(cfg.stt_model)
        f1.addRow("Local model size:", self.model_box)
        self.lang_edit = QLineEdit(cfg.stt_language)
        self.lang_edit.setPlaceholderText(
            "auto  (or a code like en, hi, gu)")
        f1.addRow("Language:", self.lang_edit)
        self.diar_chk = QCheckBox("Enable speaker diarization "
                                  "(cloud providers that support it)")
        self.diar_chk.setChecked(cfg.diarization)
        f1.addRow("", self.diar_chk)
        v.addWidget(g1)

        # Privacy / cost ----------------------------------------------
        g2 = QGroupBox("Privacy & Cost")
        f2 = QFormLayout(g2)
        self.privacy_chk = QCheckBox(
            "Privacy Mode — local processing only, no cloud calls")
        self.privacy_chk.setChecked(cfg.privacy_mode)
        f2.addRow("", self.privacy_chk)
        self.budget_spin = QDoubleSpinBox()
        self.budget_spin.setRange(0, 100000)
        self.budget_spin.setPrefix("$")
        self.budget_spin.setValue(cfg.monthly_budget_usd)
        self.budget_spin.setToolTip("0 = no limit")
        f2.addRow("Monthly cloud budget:", self.budget_spin)
        self.warn_spin = QSpinBox()
        self.warn_spin.setRange(10, 100)
        self.warn_spin.setSuffix("%")
        self.warn_spin.setValue(cfg.warn_at_percent)
        f2.addRow("Warn at:", self.warn_spin)
        self.noise_chk = QCheckBox("Apply gentle noise reduction before "
                                   "transcription")
        self.noise_chk.setChecked(cfg.noise_reduction)
        f2.addRow("", self.noise_chk)
        v.addWidget(g2)

        # API keys -----------------------------------------------------
        g3 = QGroupBox("Provider API keys (stored encrypted, never in "
                       "plain text)")
        f3 = QFormLayout(g3)
        self._key_rows: dict[str, tuple[QLineEdit, QLabel]] = {}
        for pkey, label in KEYED_PROVIDERS:
            row = QHBoxLayout()
            edit = QLineEdit()
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setPlaceholderText("paste new key…")
            status = QLabel(redact(self.store.get_key(pkey)))
            status.setProperty("muted", True)
            save = QPushButton("Save")
            save.clicked.connect(
                lambda _=False, k=pkey: self._save_key(k))
            clear = QPushButton("Remove")
            clear.clicked.connect(
                lambda _=False, k=pkey: self._clear_key(k))
            row.addWidget(edit, 1)
            row.addWidget(status)
            row.addWidget(save)
            row.addWidget(clear)
            wrap = QWidget()
            wrap.setLayout(row)
            f3.addRow(label + ":", wrap)
            self._key_rows[pkey] = (edit, status)
        v.addWidget(g3)

        # LLM ----------------------------------------------------------
        g4 = QGroupBox("AI analysis")
        f4 = QFormLayout(g4)
        self.llm_box = QComboBox()
        for key, p in registry.all_llm().items():
            self.llm_box.addItem(p.display_name, key)
        _set_by_data(self.llm_box, cfg.llm_provider)
        f4.addRow("Provider:", self.llm_box)
        self.llm_model = QLineEdit(cfg.llm_model)
        f4.addRow("Model:", self.llm_model)
        self.custom_instr = QLineEdit(cfg.custom_instructions)
        self.custom_instr.setPlaceholderText(
            "Optional extra instructions for summaries")
        f4.addRow("Custom instructions:", self.custom_instr)
        v.addWidget(g4)

        v.addStretch(1)
        save_btn = QPushButton("Save settings")
        save_btn.setProperty("primary", True)
        save_btn.clicked.connect(self._save)
        outer.addWidget(save_btn)

    def _save_key(self, provider: str) -> None:
        edit, status = self._key_rows[provider]
        key = edit.text().strip()
        if not key:
            return
        self.store.set_key(provider, key)
        edit.clear()
        status.setText(redact(key))
        QMessageBox.information(self, "API key",
                                "Key saved to the encrypted store.")

    def _clear_key(self, provider: str) -> None:
        self.store.delete_key(provider)
        self._key_rows[provider][1].setText("(not set)")

    def _save(self) -> None:
        mgr = get_config_manager()
        cfg = mgr.config
        cfg.stt_provider = self.stt_box.currentData()
        cfg.stt_fallback_provider = self.fb_box.currentData()
        cfg.stt_model = self.model_box.currentText()
        cfg.stt_language = self.lang_edit.text().strip() or "auto"
        cfg.diarization = self.diar_chk.isChecked()
        cfg.privacy_mode = self.privacy_chk.isChecked()
        cfg.monthly_budget_usd = self.budget_spin.value()
        cfg.warn_at_percent = self.warn_spin.value()
        cfg.noise_reduction = self.noise_chk.isChecked()
        cfg.llm_provider = self.llm_box.currentData()
        cfg.llm_model = self.llm_model.text().strip()
        cfg.custom_instructions = self.custom_instr.text().strip()
        mgr.save()
        QMessageBox.information(self, "Settings", "Settings saved.")

    def on_show(self, **_) -> None:
        pass


def _set_by_data(box: QComboBox, data: str) -> None:
    for i in range(box.count()):
        if box.itemData(i) == data:
            box.setCurrentIndex(i)
            return
