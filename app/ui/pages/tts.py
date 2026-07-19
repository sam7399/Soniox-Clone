"""Text-to-speech page. All generated audio is clearly labelled as
AI-generated."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog,
                               QHBoxLayout, QLabel, QMessageBox,
                               QPlainTextEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)
from sqlalchemy import select

from app.config import get_config_manager
from app.db.database import db_session
from app.db.models import TTSGeneration
from app.providers import registry
from app.ui.util import Task, human_error

log = logging.getLogger(__name__)


class TTSPage(QWidget):
    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self._pool = QThreadPool.globalInstance()
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        h1 = QLabel("Text-to-Speech")
        h1.setProperty("h1", True)
        v.addWidget(h1)
        note = QLabel("Generated audio is synthetic (AI-generated) and "
                      "must not be presented as a human voice.")
        note.setProperty("muted", True)
        v.addWidget(note)

        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Enter or paste text to speak…")
        v.addWidget(self.text, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel("Provider:"))
        self.provider_box = QComboBox()
        for key, p in registry.all_tts().items():
            self.provider_box.addItem(p.display_name, key)
        self.provider_box.currentIndexChanged.connect(self._load_voices)
        row.addWidget(self.provider_box)
        row.addWidget(QLabel("Voice:"))
        self.voice_box = QComboBox()
        row.addWidget(self.voice_box, 1)
        row.addWidget(QLabel("Speed:"))
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.5, 2.0)
        self.speed.setSingleStep(0.1)
        self.speed.setValue(1.0)
        row.addWidget(self.speed)
        self.gen_btn = QPushButton("Generate audio")
        self.gen_btn.setProperty("primary", True)
        self.gen_btn.clicked.connect(self._generate)
        row.addWidget(self.gen_btn)
        v.addLayout(row)

        h2 = QLabel("History")
        h2.setProperty("h2", True)
        v.addWidget(h2)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Date", "Provider/Voice", "Text", "File"])
        self.table.setColumnWidth(2, 420)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        v.addWidget(self.table, 1)
        self._load_voices()

    def _load_voices(self) -> None:
        self.voice_box.clear()
        key = self.provider_box.currentData()
        if not key:
            return

        def work():
            return registry.get_tts(key).list_voices()

        def done(result) -> None:
            if isinstance(result, Exception):
                self.voice_box.addItem("(default)", "")
                return
            if not result:
                self.voice_box.addItem("(default)", "")
            for voice in result:
                label = voice.name + (f" [{voice.language}]"
                                      if voice.language else "")
                self.voice_box.addItem(label, voice.id)
        self._pool.start(Task(work, done))

    def _generate(self) -> None:
        content = self.text.toPlainText().strip()
        if not content:
            QMessageBox.information(self, "Text-to-Speech",
                                    "Please enter some text first.")
            return
        key = self.provider_box.currentData()
        voice = self.voice_box.currentData() or ""
        speed = self.speed.value()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save audio as", f"speech_{int(time.time())}.wav",
            "Audio (*.wav *.mp3)")
        if not path:
            return
        self.gen_btn.setEnabled(False)
        self.gen_btn.setText("Generating…")

        def work():
            provider = registry.get_tts(key)
            out = provider.synthesize(content, voice, Path(path),
                                      speed=speed,
                                      fmt=Path(path).suffix.lstrip("."))
            with db_session() as s:
                s.add(TTSGeneration(
                    text_preview=content[:290], provider=key,
                    voice=str(voice)[:78], output_path=str(out)))
            return out

        def done(result) -> None:
            self.gen_btn.setEnabled(True)
            self.gen_btn.setText("Generate audio")
            if isinstance(result, Exception):
                QMessageBox.warning(self, "Text-to-Speech",
                                    human_error(result))
            else:
                QMessageBox.information(self, "Text-to-Speech",
                                        f"AI-generated audio saved to:\n"
                                        f"{result}")
                self.on_show()
        self._pool.start(Task(work, done))

    def on_show(self, **_) -> None:
        with db_session() as s:
            gens = s.scalars(select(TTSGeneration)
                             .order_by(TTSGeneration.id.desc())
                             .limit(50)).all()
            rows = [(g.created_at.strftime("%Y-%m-%d %H:%M"),
                     f"{g.provider}/{g.voice}", g.text_preview,
                     g.output_path) for g in gens]
        self.table.setRowCount(0)
        for cols in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, val in enumerate(cols):
                self.table.setItem(r, c, QTableWidgetItem(str(val)))
