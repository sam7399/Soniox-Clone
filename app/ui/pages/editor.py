"""Transcript editor: editable segments with speakers and timestamps,
synchronized audio playback, translation tab, AI summary tab and
export. The original AI transcript is kept immutable; edits go to the
`text` column and can be reverted per segment."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QMessageBox,
                               QPlainTextEdit, QPushButton, QSlider,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)
from sqlalchemy import select

from app.core import services
from app.core.exporters import ExportOptions, export_session
from app.db.database import db_session
from app.db.models import Session, Speaker, TranscriptSegment
from app.providers.base import ProviderError
from app.ui.util import Task, human_error

log = logging.getLogger(__name__)

LANGS = [("en", "English"), ("hi", "Hindi"), ("mr", "Marathi"),
         ("gu", "Gujarati"), ("ta", "Tamil"), ("te", "Telugu"),
         ("kn", "Kannada"), ("ml", "Malayalam"), ("bn", "Bengali"),
         ("pa", "Punjabi"), ("ur", "Urdu"), ("ar", "Arabic"),
         ("fr", "French"), ("de", "German"), ("es", "Spanish"),
         ("pt", "Portuguese"), ("zh", "Chinese"), ("ja", "Japanese"),
         ("ko", "Korean"), ("ru", "Russian")]


class EditorPage(QWidget):
    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self.session_id: int | None = None
        self._seg_ids: list[int] = []
        self._pool = QThreadPool.globalInstance()

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        head = QHBoxLayout()
        self.title = QLabel("Transcript editor")
        self.title.setProperty("h1", True)
        head.addWidget(self.title)
        head.addStretch(1)
        back = QPushButton("← Sessions")
        back.clicked.connect(lambda: self.main.navigate("sessions"))
        head.addWidget(back)
        v.addLayout(head)

        # Playback bar -------------------------------------------------
        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        bar = QHBoxLayout()
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(40)
        self.play_btn.clicked.connect(self._toggle_play)
        bar.addWidget(self.play_btn)
        self.pos_slider = QSlider(Qt.Orientation.Horizontal)
        self.pos_slider.sliderMoved.connect(
            lambda ms: self.player.setPosition(ms))
        bar.addWidget(self.pos_slider, 1)
        self.pos_label = QLabel("0:00 / 0:00")
        bar.addWidget(self.pos_label)
        self.speed_box = QComboBox()
        for s in ("0.75x", "1.0x", "1.25x", "1.5x", "2.0x"):
            self.speed_box.addItem(s)
        self.speed_box.setCurrentIndex(1)
        self.speed_box.currentTextChanged.connect(
            lambda t: self.player.setPlaybackRate(float(t[:-1])))
        bar.addWidget(self.speed_box)
        v.addLayout(bar)
        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(
            lambda d: self.pos_slider.setRange(0, d))

        # Tabs ---------------------------------------------------------
        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)

        # Transcript tab
        t1 = QWidget()
        tv = QVBoxLayout(t1)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Time", "Speaker", "Lang", "Text (double-click to edit)"])
        self.table.setColumnWidth(0, 90)
        self.table.setColumnWidth(1, 140)
        self.table.setColumnWidth(2, 50)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setWordWrap(True)
        self.table.cellChanged.connect(self._on_cell_changed)
        self.table.cellClicked.connect(self._on_cell_clicked)
        tv.addWidget(self.table, 1)
        row = QHBoxLayout()
        save_btn = QPushButton("Save edits")
        save_btn.setProperty("primary", True)
        save_btn.clicked.connect(self._save_edits)
        revert_btn = QPushButton("Revert row to AI original")
        revert_btn.clicked.connect(self._revert_row)
        rename_btn = QPushButton("Rename speaker…")
        rename_btn.clicked.connect(self._rename_speaker)
        row.addWidget(save_btn)
        row.addWidget(revert_btn)
        row.addWidget(rename_btn)
        row.addStretch(1)
        tv.addLayout(row)
        self.tabs.addTab(t1, "Transcript")

        # Translation tab
        t2 = QWidget()
        tv2 = QVBoxLayout(t2)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Target language:"))
        self.lang_box = QComboBox()
        for code, name in LANGS:
            self.lang_box.addItem(f"{name} ({code})", code)
        row2.addWidget(self.lang_box)
        self.translate_btn = QPushButton("Translate transcript")
        self.translate_btn.setProperty("primary", True)
        self.translate_btn.clicked.connect(self._translate)
        row2.addWidget(self.translate_btn)
        row2.addStretch(1)
        tv2.addLayout(row2)
        self.translation_view = QPlainTextEdit()
        self.translation_view.setReadOnly(True)
        self.translation_view.setPlaceholderText(
            "No translation yet. Choose a language and press Translate. "
            "The original transcript is never modified.")
        tv2.addWidget(self.translation_view, 1)
        self.tabs.addTab(t2, "Translation")

        # Summary tab
        t3 = QWidget()
        tv3 = QVBoxLayout(t3)
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Template:"))
        self.kind_box = QComboBox()
        for k in ("meeting", "client meeting", "sales call", "interview",
                  "training", "customer support call", "general"):
            self.kind_box.addItem(k)
        row3.addWidget(self.kind_box)
        self.summarize_btn = QPushButton("Generate summary")
        self.summarize_btn.setProperty("primary", True)
        self.summarize_btn.clicked.connect(self._summarize)
        row3.addWidget(self.summarize_btn)
        note = QLabel("Output is AI-generated — review before sharing.")
        note.setProperty("muted", True)
        row3.addWidget(note)
        row3.addStretch(1)
        tv3.addLayout(row3)
        self.summary_view = QPlainTextEdit()
        self.summary_view.setPlaceholderText(
            "No summary yet. The generated report is editable here.")
        tv3.addWidget(self.summary_view, 1)
        self.tabs.addTab(t3, "AI Summary")

        # Export bar ---------------------------------------------------
        exp = QHBoxLayout()
        exp.addWidget(QLabel("Export:"))
        for fmt in ("docx", "pdf", "xlsx", "txt", "srt", "vtt", "json",
                    "html", "md"):
            b = QPushButton(fmt.upper())
            b.setFixedWidth(64)
            b.clicked.connect(lambda _=False, f=fmt: self._export(f))
            exp.addWidget(b)
        exp.addStretch(1)
        v.addLayout(exp)

    # -- load ---------------------------------------------------------
    def on_show(self, session_id: int | None = None, **_) -> None:
        if session_id is not None:
            self.session_id = session_id
        self._load()

    def _load(self) -> None:
        if self.session_id is None:
            return
        self._loading = True
        with db_session() as s:
            sess = s.get(Session, self.session_id)
            if sess is None:
                return
            self.title.setText(sess.name)
            audio = sess.audio_path or sess.source_path
            segs = [(seg.id, seg.start_s,
                     (seg.speaker.display_name or seg.speaker.label)
                     if seg.speaker else "", seg.language, seg.text,
                     seg.confidence)
                    for seg in sess.segments]
            translations = {t.target_language: t.segments_json
                            for t in sess.translations}
            summary = (sess.summaries[-1].content_json
                       if sess.summaries else {})
        if audio and Path(audio).exists():
            self.player.setSource(QUrl.fromLocalFile(audio))
        self.table.setRowCount(0)
        self._seg_ids = []
        for seg_id, start, speaker, lang, text, conf in segs:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self._seg_ids.append(seg_id)
            for c, val in ((0, _ts(start)), (1, speaker), (2, lang)):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, c, item)
            text_item = QTableWidgetItem(text)
            if conf < 0.55:
                text_item.setForeground(Qt.GlobalColor.yellow)
                text_item.setToolTip("Low confidence — please verify")
            self.table.setItem(r, 3, text_item)
        self.table.resizeRowsToContents()
        # Translation view
        self.translation_view.clear()
        for lang, payload in translations.items():
            self.translation_view.appendPlainText(f"=== {lang} ===")
            for seg in payload:
                spk = f"{seg['speaker']}: " if seg.get("speaker") else ""
                self.translation_view.appendPlainText(
                    f"[{_ts(seg['start_s'])}] {spk}{seg['text']}")
            self.translation_view.appendPlainText("")
        # Summary view
        from app.core.exporters import _summary_text
        self.summary_view.setPlainText(
            _summary_text(summary) if summary else "")
        self._loading = False

    # -- edits --------------------------------------------------------
    def _on_cell_changed(self, row: int, col: int) -> None:
        if col != 3 or getattr(self, "_loading", False):
            return
        item = self.table.item(row, 3)
        if item is not None:
            item.setData(Qt.ItemDataRole.UserRole, "dirty")

    def _save_edits(self) -> None:
        if self.session_id is None:
            return
        changed = 0
        with db_session() as s:
            for r, seg_id in enumerate(self._seg_ids):
                item = self.table.item(r, 3)
                if item is None or \
                        item.data(Qt.ItemDataRole.UserRole) != "dirty":
                    continue
                seg = s.get(TranscriptSegment, seg_id)
                if seg is not None and seg.text != item.text():
                    seg.text = item.text()
                    changed += 1
                item.setData(Qt.ItemDataRole.UserRole, None)
        if changed:
            QMessageBox.information(self, "Saved",
                                    f"Saved {changed} edited segment(s). "
                                    "The AI original is kept and can be "
                                    "restored per row.")

    def _revert_row(self) -> None:
        r = self.table.currentRow()
        if r < 0 or r >= len(self._seg_ids):
            return
        with db_session() as s:
            seg = s.get(TranscriptSegment, self._seg_ids[r])
            if seg is not None:
                seg.text = seg.original_text
        self._load()

    def _rename_speaker(self) -> None:
        if self.session_id is None:
            return
        with db_session() as s:
            speakers = s.scalars(select(Speaker).where(
                Speaker.session_id == self.session_id)).all()
            options = [f"{sp.label} → {sp.display_name or '(unnamed)'}"
                       for sp in speakers]
            ids = [sp.id for sp in speakers]
        if not options:
            QMessageBox.information(
                self, "Speakers",
                "No speakers were detected in this session. Speaker "
                "diarization requires a provider that supports it "
                "(e.g. Deepgram or Soniox) and must be enabled in "
                "Settings.")
            return
        choice, ok = QInputDialog.getItem(self, "Rename speaker",
                                          "Speaker:", options, 0, False)
        if not ok:
            return
        idx = options.index(choice)
        name, ok = QInputDialog.getText(self, "Rename speaker",
                                        "New name:")
        if not ok or not name.strip():
            return
        with db_session() as s:
            sp = s.get(Speaker, ids[idx])
            if sp is not None:
                sp.display_name = name.strip()
        self._load()

    # -- playback -----------------------------------------------------
    def _toggle_play(self) -> None:
        if self.player.playbackState() == \
                QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.play_btn.setText("▶")
        else:
            self.player.play()
            self.play_btn.setText("⏸")

    def _on_pos(self, ms: int) -> None:
        if not self.pos_slider.isSliderDown():
            self.pos_slider.setValue(ms)
        total = self.player.duration() // 1000
        cur = ms // 1000
        self.pos_label.setText(
            f"{cur // 60}:{cur % 60:02d} / {total // 60}:"
            f"{total % 60:02d}")

    def _on_cell_clicked(self, row: int, col: int) -> None:
        if col == 0 and 0 <= row < len(self._seg_ids):
            with db_session() as s:
                seg = s.get(TranscriptSegment, self._seg_ids[row])
                if seg is not None:
                    self.player.setPosition(int(seg.start_s * 1000))

    # -- AI actions ---------------------------------------------------
    def _translate(self) -> None:
        if self.session_id is None:
            return
        target = self.lang_box.currentData()
        self.translate_btn.setEnabled(False)
        self.translate_btn.setText("Translating…")
        sid = self.session_id

        def done(result) -> None:
            self.translate_btn.setEnabled(True)
            self.translate_btn.setText("Translate transcript")
            if isinstance(result, Exception):
                QMessageBox.warning(self, "Translation",
                                    human_error(result))
            else:
                self._load()
                self.tabs.setCurrentIndex(1)
        self._pool.start(Task(
            lambda: services.translate_session(sid, target), done))

    def _summarize(self) -> None:
        if self.session_id is None:
            return
        kind = self.kind_box.currentText()
        self.summarize_btn.setEnabled(False)
        self.summarize_btn.setText("Generating…")
        sid = self.session_id

        def done(result) -> None:
            self.summarize_btn.setEnabled(True)
            self.summarize_btn.setText("Generate summary")
            if isinstance(result, Exception):
                QMessageBox.warning(self, "Summary", human_error(result))
            else:
                self._load()
                self.tabs.setCurrentIndex(2)
        self._pool.start(Task(
            lambda: services.summarize_session(sid, kind), done))

    # -- export -------------------------------------------------------
    def _export(self, fmt: str) -> None:
        if self.session_id is None:
            return
        with db_session() as s:
            sess = s.get(Session, self.session_id)
            default_name = (sess.name if sess else "transcript")
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export {fmt.upper()}", f"{default_name}.{fmt}",
            f"{fmt.upper()} (*.{fmt})")
        if not path:
            return
        opts = ExportOptions(include_summary=True)
        try:
            out = export_session(self.session_id, fmt, Path(path), opts)
            QMessageBox.information(self, "Export complete",
                                    f"Saved to:\n{out}")
        except Exception as e:
            log.exception("export failed")
            QMessageBox.warning(self, "Export failed", human_error(e))


def _ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
