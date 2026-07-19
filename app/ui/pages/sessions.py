"""Sessions page: searchable list of all sessions with open/delete."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)
from sqlalchemy import or_, select

from app.db.database import db_session
from app.db.models import Session


class SessionsPage(QWidget):
    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self._ids: list[int] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        head = QHBoxLayout()
        h1 = QLabel("Sessions")
        h1.setProperty("h1", True)
        head.addWidget(h1)
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name or transcript…")
        self.search.setFixedWidth(320)
        self.search.returnPressed.connect(self.refresh)
        head.addWidget(self.search)
        btn = QPushButton("Search")
        btn.clicked.connect(self.refresh)
        head.addWidget(btn)
        v.addLayout(head)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Date", "Duration", "Languages", "Provider",
             "Status"])
        self.table.setColumnWidth(0, 380)
        self.table.setColumnWidth(1, 150)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.table.doubleClicked.connect(self._open)
        v.addWidget(self.table, 1)

        row = QHBoxLayout()
        open_btn = QPushButton("Open editor")
        open_btn.setProperty("primary", True)
        open_btn.clicked.connect(self._open)
        del_btn = QPushButton("Delete")
        del_btn.setProperty("danger", True)
        del_btn.clicked.connect(self._delete)
        row.addWidget(open_btn)
        row.addWidget(del_btn)
        row.addStretch(1)
        v.addLayout(row)

    def on_show(self, **_) -> None:
        self.refresh()

    def refresh(self) -> None:
        term = self.search.text().strip()
        with db_session() as s:
            q = select(Session).where(Session.is_deleted.is_(False))
            if term:
                like = f"%{term}%"
                q = q.where(or_(Session.name.ilike(like),
                                Session.notes.ilike(like)))
            sessions = s.scalars(q.order_by(Session.id.desc())
                                 .limit(300)).all()
            rows = [(x.id, x.name,
                     x.created_at.strftime("%Y-%m-%d %H:%M"),
                     _dur(x.duration_s), x.language, x.provider,
                     x.status.value) for x in sessions]
        self.table.setRowCount(0)
        self._ids = []
        for sid, *cols in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self._ids.append(sid)
            for c, val in enumerate(cols):
                self.table.setItem(r, c, QTableWidgetItem(str(val)))

    def _selected(self) -> int | None:
        r = self.table.currentRow()
        return self._ids[r] if 0 <= r < len(self._ids) else None

    def _open(self) -> None:
        sid = self._selected()
        if sid is not None:
            self.main.open_session(sid)

    def _delete(self) -> None:
        sid = self._selected()
        if sid is None:
            return
        if QMessageBox.question(
                self, "Delete session",
                "Delete this session and its transcript? The original "
                "audio/video file on disk is NOT deleted.") != \
                QMessageBox.StandardButton.Yes:
            return
        with db_session() as s:
            sess = s.get(Session, sid)
            if sess is not None:
                sess.is_deleted = True
        self.refresh()


def _dur(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}"
