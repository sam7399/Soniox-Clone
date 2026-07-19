"""Dashboard page: usage statistics and recent sessions."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)
from sqlalchemy import func, select

from app.config import get_config_manager
from app.core.costs import budget_state
from app.db.database import db_session
from app.db.models import JobStatus, ProcessingJob, Session, SessionStatus


def _card(title: str, value_label: QLabel) -> QFrame:
    f = QFrame()
    f.setStyleSheet("QFrame{background:#232830;border-radius:10px;}")
    v = QVBoxLayout(f)
    t = QLabel(title)
    t.setProperty("muted", True)
    value_label.setStyleSheet("font-size:26px;font-weight:700;")
    v.addWidget(value_label)
    v.addWidget(t)
    return f


class DashboardPage(QWidget):
    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        head = QHBoxLayout()
        h1 = QLabel("Dashboard")
        h1.setProperty("h1", True)
        head.addWidget(h1)
        head.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.on_show)
        head.addWidget(refresh)
        v.addLayout(head)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.lbl_sessions = QLabel("0")
        self.lbl_hours = QLabel("0.0")
        self.lbl_langs = QLabel("–")
        self.lbl_failed = QLabel("0")
        self.lbl_cost = QLabel("$0.00")
        for i, (title, lbl) in enumerate([
                ("Total sessions", self.lbl_sessions),
                ("Transcribed hours", self.lbl_hours),
                ("Languages detected", self.lbl_langs),
                ("Failed jobs", self.lbl_failed),
                ("Cost this month (est.)", self.lbl_cost)]):
            grid.addWidget(_card(title, lbl), 0, i)
        v.addLayout(grid)

        h2 = QLabel("Recent sessions")
        h2.setProperty("h2", True)
        v.addWidget(h2)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Date", "Duration", "Languages", "Status"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 380)
        self.table.setColumnWidth(1, 150)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.table.doubleClicked.connect(self._open_selected)
        v.addWidget(self.table, 1)

    def on_show(self, **_) -> None:
        cfg = get_config_manager().config
        with db_session() as s:
            total = s.scalar(select(func.count(Session.id)).where(
                Session.is_deleted.is_(False))) or 0
            hours = (s.scalar(select(func.coalesce(func.sum(
                Session.duration_s), 0.0)).where(
                Session.is_deleted.is_(False))) or 0.0) / 3600.0
            failed = s.scalar(select(func.count(ProcessingJob.id)).where(
                ProcessingJob.status == JobStatus.FAILED)) or 0
            langs: set[str] = set()
            for (lang,) in s.execute(select(Session.language)):
                langs.update(x for x in (lang or "").split(",") if x)
            recent = s.scalars(select(Session)
                               .where(Session.is_deleted.is_(False))
                               .order_by(Session.id.desc())
                               .limit(15)).all()
            rows = [(x.id, x.name,
                     x.created_at.strftime("%Y-%m-%d %H:%M"),
                     _dur(x.duration_s), x.language,
                     x.status.value) for x in recent]
        self.lbl_sessions.setText(str(total))
        self.lbl_hours.setText(f"{hours:.1f}")
        self.lbl_langs.setText(str(len(langs)) if langs else "–")
        self.lbl_failed.setText(str(failed))
        state, spent = budget_state(cfg.monthly_budget_usd,
                                    cfg.warn_at_percent)
        self.lbl_cost.setText(f"${spent:.2f}")
        self.lbl_cost.setStyleSheet(
            "font-size:26px;font-weight:700;color:%s;" % (
                "#ff5555" if state == "over" else
                "#ffb84f" if state == "warn" else "#e8eaed"))

        self.table.setRowCount(0)
        self._ids = []
        for sid, *cols in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self._ids.append(sid)
            for c, val in enumerate(cols):
                item = QTableWidgetItem(str(val))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, c, item)

    def _open_selected(self) -> None:
        r = self.table.currentRow()
        if 0 <= r < len(self._ids):
            self.main.open_session(self._ids[r])


def _dur(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}"
