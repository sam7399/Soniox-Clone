"""Live transcription page.

Records from the microphone with a visible red indicator, shows the
input level, and (when the local Whisper engine is available) runs
rolling near-live transcription over ~6 second windows. When recording
stops, the full recording is queued for a proper full-quality pass and
saved as a session.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QVBoxLayout, QWidget)

from app.config import get_config_manager
from app.core.jobs import get_queue
from app.core.pipeline import create_session_for_file, PipelineError
from app.ui.util import Task, human_error
from app.workers.recorder import Recorder, RecorderError, \
    list_input_devices

log = logging.getLogger(__name__)


class LivePage(QWidget):
    _live_text = Signal(str)
    _level = Signal(float)

    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self.recorder: Recorder | None = None
        self._pool = QThreadPool.globalInstance()
        self._stt_busy = False

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        h1 = QLabel("Live Transcription")
        h1.setProperty("h1", True)
        v.addWidget(h1)

        row = QHBoxLayout()
        row.addWidget(QLabel("Microphone:"))
        self.device_box = QComboBox()
        self._reload_devices()
        row.addWidget(self.device_box, 1)
        reload_btn = QPushButton("↻")
        reload_btn.setFixedWidth(36)
        reload_btn.setToolTip("Re-scan microphones")
        reload_btn.clicked.connect(self._reload_devices)
        row.addWidget(reload_btn)
        v.addLayout(row)

        ctl = QHBoxLayout()
        self.start_btn = QPushButton("● Start recording")
        self.start_btn.setProperty("primary", True)
        self.start_btn.clicked.connect(self.start_recording)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.stop_btn = QPushButton("■ Stop && save")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_recording)
        ctl.addWidget(self.start_btn)
        ctl.addWidget(self.pause_btn)
        ctl.addWidget(self.stop_btn)
        ctl.addStretch(1)
        self.rec_label = QLabel("")
        self.rec_label.setProperty("recording", True)
        ctl.addWidget(self.rec_label)
        v.addLayout(ctl)

        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setTextVisible(False)
        self.level_bar.setFixedHeight(8)
        v.addWidget(self.level_bar)

        hint = QLabel("Live preview uses the local offline engine and is "
                      "approximate; the final transcript is produced at "
                      "full quality when you press Stop.")
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        v.addWidget(hint)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlaceholderText(
            "Press Start recording. A red indicator is always shown "
            "while the microphone is active.")
        v.addWidget(self.text, 1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_elapsed)
        self._live_text.connect(self._append_text)
        self._level.connect(lambda x: self.level_bar.setValue(
            min(int(x * 100), 100)))

    # -- devices ------------------------------------------------------
    def _reload_devices(self) -> None:
        self.device_box.clear()
        self.device_box.addItem("System default", None)
        try:
            for idx, name in list_input_devices():
                self.device_box.addItem(name, idx)
        except RecorderError as e:
            self.device_box.addItem("No microphone found", None)
            log.warning("device scan: %s", e)

    # -- record control -----------------------------------------------
    def start_recording(self) -> None:
        cfg = get_config_manager().config
        use_live_preview = (cfg.stt_provider == "whisper_local"
                            or cfg.privacy_mode)
        self.recorder = Recorder(
            on_level=self._level.emit,
            on_window=self._on_window if use_live_preview else None)
        try:
            self.recorder.start(self.device_box.currentData())
        except RecorderError as e:
            QMessageBox.warning(self, "Microphone", e.user_message)
            self.recorder = None
            return
        self.text.clear()
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self._timer.start(500)

    def _toggle_pause(self) -> None:
        if self.recorder is None:
            return
        if self.recorder.is_paused:
            self.recorder.resume()
            self.pause_btn.setText("Pause")
        else:
            self.recorder.pause()
            self.pause_btn.setText("Resume")

    def stop_recording(self) -> None:
        if self.recorder is None:
            return
        path = self.recorder.stop()
        self.recorder = None
        self._timer.stop()
        self.rec_label.setText("")
        self.level_bar.setValue(0)
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("Pause")
        self.stop_btn.setEnabled(False)
        if path is None:
            QMessageBox.information(self, "Recording",
                                    "No audio was captured.")
            return
        try:
            sid = create_session_for_file(Path(path),
                                          name=f"Live {path.stem}")
        except PipelineError as e:
            QMessageBox.warning(self, "Recording", e.user_message)
            return
        get_queue().enqueue_transcription(sid)
        QMessageBox.information(
            self, "Recording saved",
            "The recording was saved and queued for full-quality "
            "transcription. Track progress in Upload & Queue; the "
            "finished transcript appears under Sessions.")

    def _update_elapsed(self) -> None:
        if self.recorder is not None and self.recorder.is_recording:
            e = int(self.recorder.elapsed_s)
            state = "⏸ PAUSED" if self.recorder.is_paused else "● REC"
            self.rec_label.setText(f"{state}  {e // 60:02d}:{e % 60:02d}")

    # -- rolling live preview -----------------------------------------
    def _on_window(self, wav_path: Path) -> None:
        if self._stt_busy:
            wav_path.unlink(missing_ok=True)
            return
        self._stt_busy = True

        def work() -> str:
            try:
                from app.providers.registry import get_stt
                result = get_stt("whisper_local").transcribe_file(
                    wav_path, language=get_config_manager()
                    .config.stt_language)
                return " ".join(s.text for s in result.segments).strip()
            finally:
                wav_path.unlink(missing_ok=True)

        def done(text_or_err) -> None:
            self._stt_busy = False
            if isinstance(text_or_err, str) and text_or_err:
                self._live_text.emit(text_or_err)

        self._pool.start(Task(work, done))

    def _append_text(self, text: str) -> None:
        self.text.appendPlainText(text)

    def on_show(self, **_) -> None:
        pass
