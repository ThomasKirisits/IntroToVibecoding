"""Download paginated historical SPY SIP minute bars from Alpaca."""

import csv
import json
import os
import time
from collections.abc import Iterator
from datetime import date, datetime, time as clock, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.market_data import FIELDS, NY

ENDPOINT = "https://data.alpaca.markets/v2/stocks/bars"


def get_page(request: Request) -> dict:
    """Fetch a JSON page, retrying only recoverable GET failures."""
    for attempt in range(4):
        delay = 2 ** attempt
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object")
            return payload
        except HTTPError as exc:
            status = exc.code
            retry_after = exc.headers.get("Retry-After")
            exc.close()
            if status not in (429, 500, 502, 503, 504) or attempt == 3:
                raise ValueError(f"Alpaca returned HTTP {status}. Check credentials and SIP access.") from None
            if retry_after:
                try:
                    wait = (int(retry_after) if retry_after.isdigit() else
                            (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
                except (ValueError, TypeError):
                    wait = delay
                delay = max(delay, wait)
                if delay > 120:
                    raise ValueError("Alpaca requested a retry delay over two minutes") from None
        except (URLError, TimeoutError):
            if attempt == 3:
                raise ValueError("Could not reach Alpaca after four attempts") from None
        time.sleep(delay)
    raise RuntimeError("Retry loop ended unexpectedly")


def fetch_rows(start: date, end: date, key: str, secret: str) -> Iterator[list]:
    """Yield CSV rows for inclusive New York dates using split-adjusted SIP bars."""
    start_time = datetime.combine(start, clock.min, NY)
    end_time = datetime.combine(end + timedelta(days=1), clock.min, NY)
    if end < start or end_time > datetime.now(NY) - timedelta(minutes=15):
        raise ValueError("Choose an ordered range of completed historical New York dates")
    params = {
        "symbols": "SPY", "timeframe": "1Min", "feed": "sip",
        "adjustment": "split", "limit": 10000, "sort": "asc",
        "start": start_time.isoformat(), "end": end_time.isoformat(),
    }
    seen = set()
    previous = None
    while True:
        request = Request(f"{ENDPOINT}?{urlencode(params)}")
        request.add_unredirected_header("APCA-API-KEY-ID", key)
        request.add_unredirected_header("APCA-API-SECRET-KEY", secret)
        page = get_page(request)
        bars = page.get("bars")
        token = page.get("next_page_token")
        if not isinstance(bars, dict) or not isinstance(bars.get("SPY", []), list):
            raise ValueError("Invalid Alpaca bars payload")
        for bar in bars.get("SPY", []):
            try:
                stamp = datetime.fromisoformat(bar["t"])
                if stamp.utcoffset() is None or (previous is not None and stamp <= previous):
                    raise ValueError("Expected increasing offset-aware timestamps")
                values = [float(bar[field]) for field in ("o", "h", "l", "c", "v", "vw")]
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Invalid Alpaca SPY minute bar") from exc
            previous = stamp
            if start_time <= stamp < end_time:
                yield [stamp.isoformat(), *values]
        if token is None:
            return
        if not isinstance(token, str) or not token or token in seen:
            raise ValueError("Invalid or repeated Alpaca pagination token")
        seen.add(token)
        params["page_token"] = token


def download(start: date, end: date, path: Path) -> int:
    """Write a completed download atomically and return the number of bars."""
    key = os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise ValueError("Set APCA_API_KEY_ID and APCA_API_SECRET_KEY in the environment")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = NamedTemporaryFile(mode="w", newline="", dir=path.parent, delete=False)
    temp_path = Path(temporary.name)
    try:
        with temporary:
            writer = csv.writer(temporary)
            writer.writerow(FIELDS)
            count = 0
            for row in fetch_rows(start, end, key, secret):
                writer.writerow(row)
                count += 1
        if not count:
            raise ValueError("Alpaca returned no SPY minute bars")
        # Link atomically and preserve an existing dataset if the path is already in use.
        os.link(temp_path, path)
        return count
    finally:
        temp_path.unlink(missing_ok=True)
