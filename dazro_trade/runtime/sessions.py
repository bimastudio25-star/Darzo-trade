from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ROME_TZ = ZoneInfo("Europe/Rome")
UTC_TZ = ZoneInfo("UTC")


@dataclass(frozen=True)
class TradingSession:
    name: str
    timezone_name: str
    start: time
    end: time
    enabled: bool = True
    peak_start: time | None = None
    peak_end: time | None = None

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    def bounds_for(self, now_utc: datetime) -> tuple[datetime, datetime]:
        local_now = now_utc.astimezone(self.tz)
        start_local = datetime.combine(local_now.date(), self.start, tzinfo=self.tz)
        end_local = datetime.combine(local_now.date(), self.end, tzinfo=self.tz)
        if end_local <= start_local:
            end_local += timedelta(days=1)
            if local_now < start_local:
                start_local -= timedelta(days=1)
                end_local -= timedelta(days=1)
        return start_local, end_local

    def is_active(self, now_utc: datetime) -> bool:
        if not self.enabled:
            return False
        start_local, end_local = self.bounds_for(now_utc)
        local_now = now_utc.astimezone(self.tz)
        return start_local <= local_now <= end_local

    def next_open(self, now_utc: datetime) -> datetime:
        local_now = now_utc.astimezone(self.tz)
        candidate = datetime.combine(local_now.date(), self.start, tzinfo=self.tz)
        if candidate <= local_now:
            candidate += timedelta(days=1)
        return candidate.astimezone(UTC_TZ)


DEFAULT_SESSIONS = [
    TradingSession("Sydney", "Australia/Sydney", time(7, 0), time(16, 0), enabled=True),
    TradingSession("Tokyo", "Asia/Tokyo", time(9, 0), time(18, 0), enabled=True),
    TradingSession("London", "Europe/London", time(8, 0), time(17, 0), enabled=True, peak_start=time(8, 0), peak_end=time(11, 0)),
    TradingSession("New York", "America/New_York", time(8, 0), time(17, 0), enabled=True, peak_start=time(8, 0), peak_end=time(11, 0)),
]


def ensure_utc(dt: datetime | None = None) -> datetime:
    current = dt or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=UTC_TZ)
    return current.astimezone(UTC_TZ)


def active_sessions(now_utc: datetime | None = None, sessions: list[TradingSession] | None = None) -> list[TradingSession]:
    now = ensure_utc(now_utc)
    return [session for session in (sessions or DEFAULT_SESSIONS) if session.is_active(now)]


def current_session_name(now_utc: datetime | None = None, sessions: list[TradingSession] | None = None) -> str:
    active = active_sessions(now_utc, sessions)
    if not active:
        return "fuori sessione"
    names = [session.name for session in active]
    if "London" in names and "New York" in names:
        return "London/New York overlap"
    return " + ".join(names)


def next_session(now_utc: datetime | None = None, sessions: list[TradingSession] | None = None) -> dict:
    now = ensure_utc(now_utc)
    candidates = []
    for session in sessions or DEFAULT_SESSIONS:
        if not session.enabled:
            continue
        open_utc = session.next_open(now)
        candidates.append((open_utc, session))
    open_utc, session = min(candidates, key=lambda item: item[0])
    return {
        "name": session.name,
        "start_utc": open_utc,
        "start_local": open_utc.astimezone(session.tz),
        "start_italy": open_utc.astimezone(ROME_TZ),
        "minutes_left": int((open_utc - now).total_seconds() // 60),
        "timezone": session.timezone_name,
    }


def format_session_summary(now_utc: datetime | None = None) -> str:
    now = ensure_utc(now_utc)
    next_info = next_session(now)
    return "\n".join(
        [
            f"Ora UTC: {now:%Y-%m-%d %H:%M} UTC",
            f"Ora Italia: {now.astimezone(ROME_TZ):%Y-%m-%d %H:%M} Europe/Rome",
            f"Ora London: {now.astimezone(ZoneInfo('Europe/London')):%Y-%m-%d %H:%M} Europe/London",
            f"Sessione attuale: {current_session_name(now)}",
            "Prossima sessione:",
            f"- {next_info['name']} locale: {next_info['start_local']:%Y-%m-%d %H:%M} {next_info['timezone']}",
            f"- UTC: {next_info['start_utc']:%Y-%m-%d %H:%M} UTC",
            f"- Italia: {next_info['start_italy']:%Y-%m-%d %H:%M} Europe/Rome",
            f"- Tempo mancante: {next_info['minutes_left']} minuti",
        ]
    )


__all__ = [
    "DEFAULT_SESSIONS",
    "ROME_TZ",
    "TradingSession",
    "active_sessions",
    "current_session_name",
    "format_session_summary",
    "next_session",
]
