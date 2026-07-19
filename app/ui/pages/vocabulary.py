"""Custom vocabulary manager: add/edit terms, CSV import/export."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)
from sqlalchemy import select

from app.core import vocab
from app.db.database import db_session
from app.db.models import VocabularyTerm


class VocabularyPage(QWidget):
    def __init__(self, main) -> None:
        super().__init__()
        self.main = main
        self._ids: list[int] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        h1 = QLabel("Custom Vocabulary")
        h1.setProperty("h1", True)
        v.addWidget(h1)
        hint = QLabel("Terms are used to correct transcripts (wrong "
                      "spellings → preferred spelling) and can be "
                      "protected from translation.")
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        v.addWidget(hint)

        form = QHBoxLayout()
        self.in_term = QLineEdit()
        self.in_term.setPlaceholderText("Correct term (e.g. Soniox)")
        self.in_cat = QLineEdit()
        self.in_cat.setPlaceholderText("Category")
        self.in_cat.setFixedWidth(130)
        self.in_wrong = QLineEdit()
        self.in_wrong.setPlaceholderText(
            "Wrong spellings, comma separated (e.g. sonyox, sonix)")
        self.chk_dnt = QCheckBox("Do not translate")
        add = QPushButton("Add / update")
        add.setProperty("primary", True)
        add.clicked.connect(self._add)
        form.addWidget(self.in_term, 1)
        form.addWidget(self.in_cat)
        form.addWidget(self.in_wrong, 1)
        form.addWidget(self.chk_dnt)
        form.addWidget(add)
        v.addLayout(form)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Term", "Category", "Replaces", "No-translate", "Enabled"])
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(2, 340)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        v.addWidget(self.table, 1)

        row = QHBoxLayout()
        imp = QPushButton("Import CSV…")
        imp.clicked.connect(self._import)
        exp = QPushButton("Export CSV…")
        exp.clicked.connect(self._export)
        rm = QPushButton("Delete selected")
        rm.setProperty("danger", True)
        rm.clicked.connect(self._delete)
        row.addWidget(imp)
        row.addWidget(exp)
        row.addWidget(rm)
        row.addStretch(1)
        v.addLayout(row)

    def on_show(self, **_) -> None:
        self.refresh()

    def refresh(self) -> None:
        with db_session() as s:
            terms = s.scalars(select(VocabularyTerm)
                              .order_by(VocabularyTerm.term)).all()
            rows = [(t.id, t.term, t.category, t.replaces,
                     "yes" if t.do_not_translate else "",
                     "yes" if t.enabled else "no") for t in terms]
        self.table.setRowCount(0)
        self._ids = []
        for tid, *cols in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self._ids.append(tid)
            for c, val in enumerate(cols):
                self.table.setItem(r, c, QTableWidgetItem(str(val)))

    def _add(self) -> None:
        term = self.in_term.text().strip()
        if not term:
            return
        cat = self.in_cat.text().strip() or "general"
        with db_session() as s:
            existing = s.scalars(select(VocabularyTerm).where(
                VocabularyTerm.term == term,
                VocabularyTerm.category == cat)).first()
            if existing is None:
                existing = VocabularyTerm(term=term, category=cat)
                s.add(existing)
            existing.replaces = self.in_wrong.text().strip()
            existing.do_not_translate = self.chk_dnt.isChecked()
        self.in_term.clear()
        self.in_wrong.clear()
        self.refresh()

    def _delete(self) -> None:
        r = self.table.currentRow()
        if r < 0 or r >= len(self._ids):
            return
        with db_session() as s:
            t = s.get(VocabularyTerm, self._ids[r])
            if t is not None:
                s.delete(t)
        self.refresh()

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import vocabulary",
                                              "", "CSV (*.csv)")
        if not path:
            return
        try:
            n = vocab.import_csv(path)
            QMessageBox.information(self, "Import",
                                    f"Imported {n} term(s).")
        except Exception:
            QMessageBox.warning(
                self, "Import",
                "The CSV could not be read. Expected columns: term, "
                "category, replaces, case_sensitive, do_not_translate.")
        self.refresh()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export vocabulary",
                                              "vocabulary.csv",
                                              "CSV (*.csv)")
        if not path:
            return
        n = vocab.export_csv(path)
        QMessageBox.information(self, "Export",
                                f"Exported {n} term(s) to:\n{path}")
