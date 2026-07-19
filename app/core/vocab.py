"""Custom vocabulary correction applied after transcription.

Each VocabularyTerm may list wrong spellings ("replaces", comma
separated); occurrences are replaced with the canonical term using
word-boundary matching. Case-insensitive unless the term is flagged
case_sensitive.
"""
from __future__ import annotations

import re

from sqlalchemy import select

from app.db.database import db_session
from app.db.models import VocabularyTerm


def load_terms() -> list[VocabularyTerm]:
    with db_session() as s:
        return list(s.scalars(select(VocabularyTerm)
                              .where(VocabularyTerm.enabled)).all())


def apply_corrections(text: str,
                      terms: list[VocabularyTerm] | None = None) -> str:
    if terms is None:
        terms = load_terms()
    for term in terms:
        wrongs = [w.strip() for w in (term.replaces or "").split(",")
                  if w.strip()]
        for wrong in wrongs:
            flags = 0 if term.case_sensitive else re.IGNORECASE
            pattern = r"\b" + re.escape(wrong) + r"\b"
            text = re.sub(pattern, term.term, text, flags=flags)
    return text


def do_not_translate_terms(
        terms: list[VocabularyTerm] | None = None) -> list[str]:
    if terms is None:
        terms = load_terms()
    return [t.term for t in terms if t.do_not_translate]


def import_csv(path: str) -> int:
    """Import terms from CSV with columns: term,category,replaces,
    case_sensitive,do_not_translate. Returns number imported."""
    import csv
    count = 0
    with open(path, newline="", encoding="utf-8-sig") as f, \
            db_session() as s:
        for row in csv.DictReader(f):
            term = (row.get("term") or "").strip()
            if not term:
                continue
            existing = s.scalars(select(VocabularyTerm).where(
                VocabularyTerm.term == term,
                VocabularyTerm.category == (row.get("category")
                                            or "general").strip(),
            )).first()
            if existing is None:
                existing = VocabularyTerm(term=term)
                s.add(existing)
            existing.category = (row.get("category") or "general").strip()
            existing.replaces = (row.get("replaces") or "").strip()
            existing.case_sensitive = str(
                row.get("case_sensitive", "")).lower() in ("1", "true", "yes")
            existing.do_not_translate = str(
                row.get("do_not_translate", "")).lower() in ("1", "true",
                                                             "yes")
            count += 1
    return count


def export_csv(path: str) -> int:
    import csv
    terms = load_terms()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["term", "category", "replaces", "case_sensitive",
                    "do_not_translate"])
        for t in terms:
            w.writerow([t.term, t.category, t.replaces,
                        int(t.case_sensitive), int(t.do_not_translate)])
    return len(terms)
