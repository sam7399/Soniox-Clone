"""Cost estimation and recording.

Prices are estimates and editable in this table; providers change
pricing, so figures shown to the user are always labelled as estimates.
Local providers cost $0.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from app.db.database import db_session
from app.db.models import CostRecord

# USD per audio minute (STT) / per 1M tokens (LLM) / per 1M chars (TTS)
STT_PER_MINUTE = {
    "openai_stt": 0.006,
    "deepgram_stt": 0.0043,
    "soniox_stt": 0.0017,
    "whisper_local": 0.0,
}
LLM_PER_MTOK = {"openai_llm": 0.60, "ollama_llm": 0.0}
TTS_PER_MCHAR = {"openai_tts": 12.0, "local_tts": 0.0}


def estimate_stt_cost(provider_key: str, duration_s: float) -> float:
    rate = STT_PER_MINUTE.get(provider_key, 0.006)
    return round(rate * duration_s / 60.0, 4)


def estimate_llm_cost(provider_key: str, approx_tokens: int) -> float:
    rate = LLM_PER_MTOK.get(provider_key, 1.0)
    return round(rate * approx_tokens / 1_000_000, 4)


def estimate_tts_cost(provider_key: str, char_count: int) -> float:
    rate = TTS_PER_MCHAR.get(provider_key, 15.0)
    return round(rate * char_count / 1_000_000, 4)


def record_cost(provider: str, operation: str, units: float,
                unit_type: str, cost_usd: float,
                session_id: int | None = None) -> None:
    with db_session() as s:
        s.add(CostRecord(session_id=session_id, provider=provider,
                         operation=operation, units=units,
                         unit_type=unit_type, cost_usd=cost_usd))


def month_to_date_cost() -> float:
    now = dt.datetime.now(dt.timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0,
                              microsecond=0)
    with db_session() as s:
        total = s.scalar(select(func.coalesce(func.sum(
            CostRecord.cost_usd), 0.0)).where(
            CostRecord.created_at >= month_start.replace(tzinfo=None)))
    return float(total or 0.0)


def budget_state(monthly_budget: float, warn_percent: int
                 ) -> tuple[str, float]:
    """Return ('ok'|'warn'|'over', month_to_date)."""
    spent = month_to_date_cost()
    if monthly_budget <= 0:
        return "ok", spent
    if spent >= monthly_budget:
        return "over", spent
    if spent >= monthly_budget * warn_percent / 100.0:
        return "warn", spent
    return "ok", spent
