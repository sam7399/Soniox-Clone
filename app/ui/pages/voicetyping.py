"""Voice Typing: dictate into any Windows application.

Speech is transcribed in rolling windows (local engine) or via a
streaming cloud provider, and the recognized text is typed into
whichever window currently has keyboard focus, like Soniox Voice
Typing. A visible ON indicator is always shown while the microphone is
active, and dictation stops the moment the user presses Stop or the
global hotkey (Ctrl+Alt+D).
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)

from app.config import get_config_manager
from app.ui.util import Task, human_error
from app.workers.recorder import Recorder, RecorderError, \
    list_input_devices

log = logging.getLogger(__name__)

HOTKEY = "ctrl+alt+d"


def _type_text(text: str) -> None:
    """Type text into the focused window (Windows)."""
    import keyboard
    keyboard.write(text, delay=0)


class VoiceTypingPage(QWidget):
    _typed = Signal(str)
    _toggle_signal = Signal()

    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self.recorder: Recorder | None = None
        self._pool = QThreadPool.globalInstance()
        self._busy = False
        self._hotkey_ok = False

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        h1 = QLabel("Voice Typing")
        h1.setProperty("h1", True)
        v.addWidget(h1)
        hint = QLabel(
            "Click Start (or press Ctrl+Alt+D anywhere), then place the "
            "cursor in any application — Word, email, browser, chat — "
            "and speak. Recognized text is typed where the cursor is. "
            "Punctuation is automatic; accuracy depends on the selected "
            "transcription provider.")
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        v.addWidget(hint)

        row = QHBoxLayout()
        row.addWidget(QLabel("Microphone:"))
        self.device_box = QComboBox()
        try:
            self.device_box.addItem("System default", None)
            for idx, name in list_input_devices():
                self.device_box.addItem(name, idx)
        except RecorderError:
            self.device_box.addItem("No microphone found", None)
        row.addWidget(self.device_box, 1)
        self.toggle_btn = QPushButton("● Start voice typing")
        self.toggle_btn.setProperty("primary", True)
        self.toggle_btn.clicked.connect(self.toggle)
        row.addWidget(self.toggle_btn)
        self.state_lbl = QLabel("")
        self.state_lbl.setProperty("recording", True)
        row.addWidget(self.state_lbl)
        v.addLayout(row)

        v.addWidget(QLabel("Recently typed:"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        v.addWidget(self.log_view, 1)

        self._typed.connect(self.log_view.appendPlainText)
        self._toggle_signal.connect(self.toggle)
        self._register_hotkey()

    def _register_hotkey(self) -> None:
        try:
            import keyboard
            keyboard.add_hotkey(HOTKEY, self._toggle_signal.emit)
            self._hotkey_ok = True
        except Exception as e:
            # Non-fatal: hotkey needs OS support/permissions.
            log.warning("Global hotkey unavailable: %s", e)

    # -- control ------------------------------------------------------
    def toggle(self) -> None:
        if self.recorder is None:
            self._start()
        else:
            self._stop()

    def _start(self) -> None:
        self.recorder = Recorder(on_window=self._on_window, window_s=4.0)
        try:
            self.recorder.start(self.device_box.currentData())
        except RecorderError as e:
            QMessageBox.warning(self, "Voice Typing", e.user_message)
            self.recorder = None
            return
        self.toggle_btn.setText("■ Stop voice typing")
        self.state_lbl.setText("● DICTATING")

    def _stop(self) -> None:
        if self.recorder is not None:
            self.recorder.stop()
            self.recorder = None
        self.toggle_btn.setText("● Start voice typing")
        self.state_lbl.setText("")

    # -- recognition --------------------------------------------------
    def _on_window(self, wav_path: Path) -> None:
        if self._busy:
            wav_path.unlink(missing_ok=True)
            return
        self._busy = True

        def work() -> str:
            try:
                from app.providers.registry import get_stt
                cfg = get_config_manager().config
                result = get_stt().transcribe_file(
                    wav_path, language=cfg.stt_language)
                return " ".join(s.text for s in result.segments).strip()
            finally:
                wav_path.unlink(missing_ok=True)

        def done(result) -> None:
            self._busy = False
            if isinstance(result, Exception):
                log.warning("voice typing window failed: %s", result)
                return
            if result:
                try:
                    _type_text(result + " ")
                    self._typed.emit(result)
                except Exception as e:
                    log.error("typing failed: %s", e)
                    self._typed.emit(f"(could not type: {result})")

        self._pool.start(Task(work, done))

    def on_show(self, **_) -> None:
        if not self._hotkey_ok:
            self._register_hotkey()
