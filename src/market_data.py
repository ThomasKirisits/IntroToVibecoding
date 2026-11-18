"""Minute-start SPY bars and validation against the regular US equity session."""

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
MINUTE = timedelta(minutes=1)
FIELDS = ("timestamp", "open", "high", "low", "close", "volume", "vwap")


@dataclass(frozen=True, slots=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float


@dataclass(frozen=True, slots=True)
class SessionGap:
    date: date
    missing_minutes: tuple[datetime, ...]
    missing_open: bool
    observed_close: float | None

    @property
    def excluded(self) -> bool:
        return self.missing_open or self.observed_close is None


def session_hours(start: date, end: date) -> dict[date, tuple[datetime, datetime]]:
    """Return regular-session opens and closes in New York time for inclusive dates."""
    import exchange_calendars

    if end < start:
        raise ValueError("End date must be on or after start date")
    calendar = exchange_calendars.get_calendar(
        "XNYS", start=start - timedelta(days=7), end=end + timedelta(days=7)
    )
    return {
        session.date(): (
            calendar.session_open(session).to_pydatetime().astimezone(NY),
            calendar.session_close(session).to_pydatetime().astimezone(NY),
        )
        for session in calendar.sessions_in_range(start, end)
    }


def read_sessions(
    path: Path, start: date, end: date, *, gaps: list[SessionGap] | None = None
) -> Iterator[list[Bar] | SessionGap]:
    """Yield observed bars, optionally auditing gaps and flagging missing session endpoints.

    By default a missing minute fails validation. When given an audit list, keep
    sessions with both endpoints and yield a gap record for excluded sessions.
    """
    hours = session_hours(start, end)

    def regular_bars() -> Iterator[Bar]:
        previous = None
        with path.open(newline="") as source:
            reader = csv.DictReader(source)
            if not set(FIELDS[:-1]).issubset(reader.fieldnames or ()):
                raise ValueError("CSV requires timestamp, open, high, low, close and volume")
            for line, row in enumerate(reader, 2):
                try:
                    stamp = datetime.fromisoformat(row["timestamp"])
                    if stamp.utcoffset() is None or stamp.second or stamp.microsecond:
                        raise ValueError("Expected an offset-aware minute-start timestamp")
                    stamp = stamp.astimezone(NY)
                    if previous is not None and stamp <= previous:
                        raise ValueError("Expected strictly increasing timestamps")
                    previous = stamp
                    day = stamp.date()
                    if not start <= day <= end or day not in hours:
                        continue
                    opening, closing = hours[day]
                    if not opening <= stamp < closing:
                        continue
                    o, h, low, c, v = (float(row[key]) for key in FIELDS[1:-1])
                    vw = float(row["vwap"]) if row.get("vwap") else (h + low + c) / 3
                    if not all(map(isfinite, (o, h, low, c, v, vw))):
                        raise ValueError("Expected finite OHLCV and VWAP")
                    # Alpaca's VWAP and OHLC can use different trade eligibility rules.
                    if not 0 < low <= min(o, c) <= max(o, c) <= h or v < 0 or vw <= 0:
                        raise ValueError("Invalid OHLC, volume or VWAP")
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"{path}, line {line}: {exc}") from exc
                yield Bar(stamp, o, h, low, c, v, vw)

    with_regular = regular_bars()
    try:
        current = next(with_regular, None)
        for opening, closing in hours.values():
            session = []
            missing = []
            expected = opening
            while expected < closing:
                if current is None or current.timestamp != expected:
                    if gaps is None:
                        raise ValueError(f"Missing regular-session bar at {expected.isoformat()}")
                    missing.append(expected)
                else:
                    session.append(current)
                    current = next(with_regular, None)
                expected += MINUTE
            if missing:
                observed_close = (
                    session[-1].close if session and session[-1].timestamp == closing - MINUTE else None
                )
                gap = SessionGap(opening.date(), tuple(missing), missing[0] == opening, observed_close)
                gaps.append(gap)
                if gap.excluded:
                    yield gap
                    continue
            yield session
    finally:
        with_regular.close()
