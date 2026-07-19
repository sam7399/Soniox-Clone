"""Higher-level services: translation of a session and meeting-style
summarization. Both persist results and record costs."""
from __future__ import annotations

import json
import logging

from sqlalchemy import select

from app.config import get_config_manager
from app.core import costs, vocab
from app.db.database import db_session
from app.db.models import Session, Summary, Translation
from app.providers import registry
from app.providers.base import ProviderError

log = logging.getLogger(__name__)


def translate_session(session_id: int, target_lang: str,
                      provider_key: str | None = None) -> int:
    """Translate all segments; stores a Translation row. Returns its id.
    The original transcript is never modified."""
    with db_session() as s:
        sess = s.get(Session, session_id)
        if sess is None:
            raise ValueError("session not found")
        seg_rows = [(seg.idx, seg.start_s, seg.end_s,
                     seg.speaker.display_name or seg.speaker.label
                     if seg.speaker else "", seg.text)
                    for seg in sess.segments]
    if not seg_rows:
        raise ProviderError("empty transcript",
                            "There is no transcript to translate yet.")

    provider = registry.get_translate(provider_key)
    dnt = vocab.do_not_translate_terms()
    texts = [r[4] for r in seg_rows]
    translated = provider.translate_segments(texts, target_lang,
                                             do_not_translate=dnt)
    payload = [{"idx": r[0], "start_s": r[1], "end_s": r[2],
                "speaker": r[3], "text": t}
               for r, t in zip(seg_rows, translated)]

    with db_session() as s:
        existing = s.scalars(select(Translation).where(
            Translation.session_id == session_id,
            Translation.target_language == target_lang)).first()
        if existing is None:
            existing = Translation(session_id=session_id,
                                   target_language=target_lang)
            s.add(existing)
        existing.provider = provider.key
        existing.segments_json = payload
        s.flush()
        tid = existing.id

    approx_tokens = sum(len(t.split()) for t in texts) * 3
    cost = costs.estimate_llm_cost(provider.key, approx_tokens)
    costs.record_cost(provider.key, "translate", approx_tokens, "tokens",
                      cost, session_id)
    return tid


MEETING_SCHEMA = {
    "executive_summary": "2-4 sentence executive summary",
    "detailed_summary": "1-3 paragraphs",
    "topics": ["list of discussion topics"],
    "decisions": ["key decisions made"],
    "action_items": [{"task": "", "owner": "", "due": "", "priority": ""}],
    "questions_open": ["unanswered questions"],
    "risks": ["risks or blockers mentioned"],
    "quotes": ["up to 3 important quotations"],
    "sentiment": "overall sentiment: positive/neutral/negative + 1 line",
    "next_steps": ["recommended follow-ups"],
}


def summarize_session(session_id: int, kind: str = "meeting",
                      provider_key: str | None = None) -> int:
    """Generate a structured meeting summary. Returns Summary row id."""
    cfg = get_config_manager().config
    with db_session() as s:
        sess = s.get(Session, session_id)
        if sess is None:
            raise ValueError("session not found")
        lines = []
        for seg in sess.segments:
            spk = (seg.speaker.display_name or seg.speaker.label
                   if seg.speaker else "")
            prefix = f"[{_fmt_ts(seg.start_s)}] "
            prefix += f"{spk}: " if spk else ""
            lines.append(prefix + seg.text)
        transcript_text = "\n".join(lines)
        duration = sess.duration_s
    if not transcript_text.strip():
        raise ProviderError("empty transcript",
                            "There is no transcript to summarize yet.")

    provider = registry.get_llm(provider_key)
    system = (
        "You are a professional meeting analyst. Analyze the transcript "
        "and return ONLY a JSON object with exactly these keys: "
        + json.dumps(MEETING_SCHEMA, ensure_ascii=False)
        + f" Meeting type: {kind}. "
        "Base every statement strictly on the transcript; do not invent "
        "facts. If information for a key is absent, use an empty list or "
        "empty string. Respond in the transcript's main language unless "
        "it is mixed, then use English. "
        + (cfg.custom_instructions or ""))
    # Trim very long transcripts to a safe size, keeping start and end.
    max_chars = 48000
    if len(transcript_text) > max_chars:
        half = max_chars // 2
        transcript_text = (transcript_text[:half]
                           + "\n[... middle omitted ...]\n"
                           + transcript_text[-half:])
    raw = provider.complete(system, transcript_text,
                            max_tokens=cfg.max_output_tokens,
                            json_mode=True)
    try:
        content = json.loads(raw)
    except json.JSONDecodeError:
        content = {"detailed_summary": raw}

    with db_session() as s:
        summ = Summary(session_id=session_id, kind=kind,
                       provider=provider.key, content_json=content,
                       is_ai_generated=True)
        s.add(summ)
        s.flush()
        sid = summ.id
    approx_tokens = len(transcript_text) // 3 + cfg.max_output_tokens
    cost = costs.estimate_llm_cost(provider.key, approx_tokens)
    costs.record_cost(provider.key, "summarize", approx_tokens, "tokens",
                      cost, session_id)
    log.info("Summary %s created for session %s (%.0fs audio)", sid,
             session_id, duration)
    return sid


def _fmt_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
