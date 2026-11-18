"""Seeded synthetic bars for exercising the notebook without vendor data."""

from collections.abc import Iterator
from datetime import date
from math import exp
from random import Random

from src.market_data import Bar, MINUTE, session_hours


def synthetic_sessions(start: date, end: date, *, seed: int) -> Iterator[list[Bar]]:
    """Generate minute bars with overnight gaps and changing intraday drift."""
    rng = Random(seed)
    price = 450.0
    for opening, closing in session_hours(start, end).values():
        price *= exp(rng.gauss(0, 0.003))
        drift = rng.gauss(0, 0.000055)
        afternoon_drift = rng.gauss(0, 0.000055)
        bars = []
        timestamp = opening
        while timestamp < closing:
            current_drift = drift if len(bars) < 180 else afternoon_drift
            close = price * exp(rng.gauss(current_drift, 0.00028))
            high = max(price, close)
            low = min(price, close)
            volume = rng.randint(1000, 5000)
            bars.append(Bar(timestamp, price, high, low, close, volume, (price + close) / 2))
            price = close
            timestamp += MINUTE
        yield bars
