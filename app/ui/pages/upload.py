"""Upload page: drag-and-drop / browse file import plus the processing
queue with progress, retry and cancel."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel,
                               QMessageBox, QProgressBar, QPushButton,
                               QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)
from sqlalchemy import select

from app.core.audio import SUPPORTED_EXTS
from app.core.jobs import get_queue
from app.core.pipeline import PipelineError, create_session_for_file
from app.db.database import db_session
from app.db.models import ProcessingJob, Session

log = logging.getLogger(__name__)


class UploadPage(QWidget):
    _job_event = Signal(int, str, float, str)

    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self.setAcceptDrops(True)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        h1 = QLabel("Upload & Queue")
        h1.setProperty("h1", True)
        v.addWidget(h1)

        drop = QLabel("Drop audio or video files here, or use Browse.\n"
                      "Supported: MP3, WAV, M4A, FLAC, OGG, MP4, MOV, "
                      "MKV, AVI, WEBM and more.")
        drop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop.setStyleSheet("QLabel{border:2px dashed #3a4150;"
                           "border-radius:10px;padding:34px;"
                           "color:#8a919b;}")
        v.addWidget(drop)

        row = QHBoxLayout()
        browse = QPushButton("Browse files…")
        browse.setProperty("primary", True)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        row.addStretch(1)
        v.addLayout(row)

        h2 = QLabel("Processing queue")
        h2.setProperty("h2", True)
        v.addWidget(h2)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Job", "Session", "Status", "Progress", "Actions"])
        self.table.setColumnWidth(1, 380)
        self.table.setColumnWidth(3, 220)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        v.addWidget(self.table, 1)

        self._job_event.connect(self._on_job_event)
        get_queue().add_listener(
            lambda *a: self._job_event.emit(*a))

    # -- import -------------------------------------------------------
    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:  # noqa: N802
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls()]
        self._import(paths)

    def _browse(self) -> None:
        exts = " ".join(f"*{x}" for x in sorted(SUPPORTED_EXTS))
        files, _ = QFileDialog.getOpenFileNames(
            self, "Choose audio or video files", "",
            f"Media files ({exts});;All files (*)")
        self._import([Path(f) for f in files])

    def _import(self, paths: list[Path]) -> None:
        errors = []
        queued = 0
        for p in paths:
            if p.is_dir():
                paths.extend(x for x in p.iterdir()
                             if x.suffix.lower() in SUPPORTED_EXTS)
                continue
            try:
                sid = create_session_for_file(p)
                get_queue().enqueue_transcription(sid)
                queued += 1
            except PipelineError as e:
                errors.append(f"{p.name}: {e.user_message}")
        if queued:
            self.refresh()
        if errors:
            QMessageBox.warning(self, "Some files were skipped",
                                "\n\n".join(errors[:8]))

    # -- queue table --------------------------------------------------
    def on_show(self, **_) -> None:
        self.refresh()

    def refresh(self) -> None:
        with db_session() as s:
            jobs = s.scalars(select(ProcessingJob)
                             .order_by(ProcessingJob.id.desc())
                             .limit(50)).all()
            rows = []
            for j in jobs:
                name = ""
                if j.session_id:
                    sess = s.get(Session, j.session_id)
                    name = sess.name if sess else ""
                rows.append((j.id, name, j.status.value, j.progress,
                             j.stage or j.error))
        self.table.setRowCount(0)
        self._row_by_job: dict[int, int] = {}
        for jid, name, status, progress, stage in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self._row_by_job[jid] = r
            self.table.setItem(r, 0, QTableWidgetItem(f"#{jid}"))
            self.table.setItem(r, 1, QTableWidgetItem(name))
            self.table.setItem(r, 2, QTableWidgetItem(status))
            bar = QProgressBar()
            bar.setValue(int(progress))
            self.table.setCellWidget(r, 3, bar)
            self.table.setItem(r, 4, QTableWidgetItem(stage[:80]))
            actions = QWidget()
            hl = QHBoxLayout(actions)
            hl.setContentsMargins(2, 0, 2, 0)
            if status in ("failed", "cancelled"):
                b = QPushButton("Retry")
                b.clicked.connect(lambda _=False, x=jid:
                                  (get_queue().retry(x), self.refresh()))
                hl.addWidget(b)
            if status in ("pending", "running"):
                b = QPushButton("Cancel")
                b.clicked.connect(lambda _=False, x=jid:
                                  (get_queue().cancel(x), self.refresh()))
                hl.addWidget(b)
            hl.addStretch(1)
            self.table.setCellWidget(r, 4, actions) if status in (
                "pending", "running", "failed", "cancelled") else None

    def _on_job_event(self, job_id: int, status: str, progress: float,
                      stage: str) -> None:
        r = getattr(self, "_row_by_job", {}).get(job_id)
        if r is None or r >= self.table.rowCount():
            self.refresh()
            return
        self.table.setItem(r, 2, QTableWidgetItem(status))
        bar = self.table.cellWidget(r, 3)
        if isinstance(bar, QProgressBar):
            bar.setValue(int(progress))
        if status in ("completed", "failed", "cancelled"):
            self.refresh()
