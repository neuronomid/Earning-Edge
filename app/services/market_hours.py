from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

NEW_YORK_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class MarketSession:
    session_date: date
    open_at: datetime
    close_at: datetime


def current_market_session(now: datetime | None = None) -> MarketSession | None:
    now_et = _to_new_york(now)
    start = now_et.date() - timedelta(days=1)
    end = now_et.date() + timedelta(days=1)
    for session in _sessions(start, end):
        if session.open_at <= now_et < session.close_at:
            return session
    return None


def is_market_open(now: datetime | None = None) -> bool:
    return current_market_session(now) is not None


def next_market_open(after: datetime | None = None) -> datetime:
    after_et = _to_new_york(after)
    for days in (10, 30, 90):
        for session in _sessions(after_et.date(), after_et.date() + timedelta(days=days)):
            if session.open_at > after_et:
                return session.open_at
    raise RuntimeError("No NYSE market open found in the next 90 days.")


def market_sessions_between(start: date, end: date) -> tuple[MarketSession, ...]:
    if end < start:
        return ()
    return _sessions(start, end)


def _to_new_york(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(NEW_YORK_TZ)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(NEW_YORK_TZ)


def _sessions(start: date, end: date) -> tuple[MarketSession, ...]:
    return _cached_sessions(start.isoformat(), end.isoformat())


@lru_cache(maxsize=128)
def _cached_sessions(start_iso: str, end_iso: str) -> tuple[MarketSession, ...]:
    calendar = mcal.get_calendar("NYSE")
    schedule = calendar.schedule(start_date=start_iso, end_date=end_iso)
    sessions: list[MarketSession] = []
    for session_index, row in schedule.iterrows():
        open_at = row["market_open"].to_pydatetime().astimezone(NEW_YORK_TZ)
        close_at = row["market_close"].to_pydatetime().astimezone(NEW_YORK_TZ)
        session_date = session_index.date()
        sessions.append(
            MarketSession(
                session_date=session_date,
                open_at=open_at,
                close_at=close_at,
            )
        )
    return tuple(sessions)
