import csv
import subprocess
import sys
import tempfile
import unittest
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from src.alpaca import fetch_rows, get_page
from src.backtest import (
    BUY_AND_HOLD, EFFICIENCY_FILTERED, STRATEGIES, Costs, decisions,
    directional_efficiency, metrics, run_backtest, simulate_day, volatility_leverage,
)
from src.market_data import Bar, NY, SessionGap, read_sessions
from src.reporting import equity_and_drawdown


def bars(prices: dict[int, tuple[float, float]]) -> list[Bar]:
    start = datetime(2024, 1, 2, 9, 30, tzinfo=NY)
    result = []
    for index in range(91):
        opening, close = prices.get(index, (100, 100))
        result.append(Bar(start + timedelta(minutes=index), opening, max(opening, close),
                          min(opening, close), close, 1, close))
    return result


class StrategyTest(unittest.TestCase):
    def test_bounds_use_prior_sessions_and_do_not_use_execution_bar(self):
        data = bars({29: (100, 102), 30: (110, 130)})
        output = decisions(data, {30: deque([0.01] * 14)}, 101)
        upper, lower, vwap = output[30]
        self.assertAlmostEqual(upper, 102.01)
        self.assertAlmostEqual(lower, 99)
        self.assertAlmostEqual(vwap, 100 + 2 / 30)
        self.assertNotIn(60, output)

    def test_missing_minutes_keep_decisions_on_the_clock_and_disable_efficiency(self):
        data = bars({29: (100, 104), 59: (100, 105), 89: (100, 106)})
        history = {slot: deque([0.01] * 14) for slot in (30, 60, 90)}
        missing_interior = data[:10] + data[11:]
        signals = decisions(missing_interior, history, 100)
        self.assertEqual([missing_interior[index].timestamp.strftime("%H:%M") for index in signals],
                         ["10:00", "10:30", "11:00"])
        self.assertEqual(directional_efficiency(missing_interior, 29), 0)
        self.assertNotEqual(directional_efficiency(missing_interior, 59), 0)

        for missing_index in (29, 30):
            unavailable = data[:missing_index] + data[missing_index + 1:]
            signals = decisions(unavailable, history, 100)
            self.assertEqual([unavailable[index].timestamp.strftime("%H:%M") for index in signals],
                             ["10:30", "11:00"])

    def test_reversal_costs_and_confirmation(self):
        data = bars({29: (100, 102), 30: (103, 100), 59: (100, 102), 60: (104, 100),
                     89: (100, 98), 90: (97, 96)})
        signals = dict.fromkeys((30, 60, 90), (101, 99, 100))
        fills = []
        baseline = simulate_day(data, signals, "Opposite band", 1000, Costs(0.1, 0.1), fills=fills)
        confirmed = simulate_day(data, signals, "Confirmed breakout", 1000, Costs(0.1, 0.1))
        self.assertEqual(baseline, (942, 40, 8))
        self.assertEqual(confirmed, (926, 20, 4))
        self.assertEqual([fill.shares for fill in fills], [10, -20, 10])
        self.assertEqual([fill.price for fill in fills], [103, 97, 96])
        self.assertEqual(fills[-1].timestamp, data[-1].timestamp + timedelta(minutes=1))

    def test_vwap_exit_uses_next_open_on_scheduled_check(self):
        data = bars({29: (100, 104), 30: (103, 103), 59: (103, 102), 60: (101, 101)})
        signals = {30: (101, 99, 103), 60: (101, 99, 103)}
        self.assertEqual(simulate_day(data, signals, "Band + VWAP", 1000, Costs(0, 0)),
                         (980, 20, 0))

    def test_flat_sharpe_is_undefined(self):
        self.assertEqual(metrics([0.0, 0.0]), (None, 0.0, 0.0))

    def test_efficiency_filters_entries_and_leaves_stops_active(self):
        smooth = {index: (100, 100 + (index + 1) / 10) for index in range(30)}
        choppy = {index: (100, 104 if index % 2 else 97) for index in range(30, 59)}
        finish = {59: (100, 98), 60: (98, 98)}
        signals = dict.fromkeys((30, 60), (101, 99, 100))
        data = bars(smooth | choppy | finish | {30: (103, 97)})
        self.assertAlmostEqual(directional_efficiency(data, 30), 1)
        self.assertEqual(simulate_day(data, signals, EFFICIENCY_FILTERED, 1000, Costs(0, 0)),
                         (950, 20, 0))

        noisy = bars({index: (100, 99 if index % 2 else 101) for index in range(29)}
                     | {29: (100, 103)})
        self.assertEqual(simulate_day(noisy, signals, EFFICIENCY_FILTERED, 1000, Costs(0, 0)),
                         (1000, 0, 0))
        self.assertAlmostEqual(
            directional_efficiency(bars({index: (100, 100 - index / 10) for index in range(30)}), 30),
            -1,
        )

    def test_leverage_uses_only_prior_daily_returns_and_is_capped(self):
        first_date = date(2024, 1, 1)
        sessions = []
        for offset in range(20):
            price = 100 + offset
            stamp = datetime.combine(first_date + timedelta(days=offset), datetime.min.time(), NY)
            sessions.append([Bar(stamp, price, price, price, price, 100, price)])
        windows = []

        def record_leverage(returns):
            windows.append(tuple(returns))
            return volatility_leverage(returns)

        with patch("src.backtest.volatility_leverage", side_effect=record_leverage):
            results = run_backtest(sessions, first_date + timedelta(days=17), Costs(0.01, 0.01))

        self.assertEqual(windows[0], tuple(price / (price - 1) - 1 for price in range(101, 115)))
        self.assertEqual(volatility_leverage(windows[0]), 4)
        self.assertLess(volatility_leverage([-0.04, 0.04] * 7), 1)
        benchmark = [row for row in results if row.strategy == BUY_AND_HOLD]
        self.assertEqual(benchmark[0].date, first_date + timedelta(days=15))
        self.assertEqual(benchmark[0].traded_shares, int(100_000 / 115.02))
        self.assertGreater(benchmark[0].cost, 0)
        self.assertEqual(benchmark[1].traded_shares, 0)
        self.assertAlmostEqual(benchmark[1].equity - benchmark[0].equity,
                               benchmark[0].traded_shares)

    def test_drawdown_includes_split_starting_equity(self):
        equity, drawdown = equity_and_drawdown([-0.10, 0.20, -0.25])
        self.assertAlmostEqual(equity[-1], 0.81)
        self.assertAlmostEqual(drawdown[0], -0.10)
        self.assertEqual(drawdown[1], 0)
        self.assertAlmostEqual(drawdown[-1], -0.25)

    def test_intraday_strategies_stay_flat_after_a_missing_prior_close(self):
        start = date(2024, 1, 1)
        sessions = []
        for offset in range(20):
            day = start + timedelta(days=offset)
            stamp = datetime(day.year, day.month, day.day, 9, 30, tzinfo=NY)
            if offset == 16:
                sessions.append(SessionGap(day, (stamp,), False, None))
            else:
                price = 100 + offset
                sessions.append([Bar(stamp, price, price, price, price, 100, price)])

        with patch("src.backtest.decisions", return_value={}) as compute:
            results = run_backtest(sessions, start + timedelta(days=18), Costs())

        signal_days = [call.args[0][0].timestamp.date() for call in compute.call_args_list]
        self.assertEqual(signal_days, [start + timedelta(days=offset) for offset in (15, 18, 19)])
        self.assertFalse(any(row.date == start + timedelta(days=16) for row in results))
        after_gap = [row for row in results if row.date == start + timedelta(days=17)]
        self.assertEqual(len(after_gap), len(STRATEGIES))
        self.assertTrue(all(row.net_return == 0 for row in after_gap if row.strategy != BUY_AND_HOLD))


class AlpacaTest(unittest.TestCase):
    @patch("src.alpaca.time.sleep")
    @patch("src.alpaca.urlopen")
    def test_rate_limit_retry_and_auth_failure(self, urlopen, sleep):
        url = "https://data.alpaca.markets/v2/stocks/bars"
        urlopen.side_effect = [HTTPError(url, 429, "", {"Retry-After": "3"}, None),
                               HTTPError(url, 401, "", {}, None)]
        with self.assertRaisesRegex(ValueError, "HTTP 401"):
            get_page(Request(url))
        sleep.assert_called_once_with(3)
        self.assertEqual(urlopen.call_count, 2)

    @patch("src.alpaca.get_page")
    def test_pagination_and_fixed_sip_parameters(self, page):
        row = {"t": "2024-01-02T14:30:00Z", "o": 100, "h": 101,
               "l": 99, "c": 100, "v": 10, "vw": 100}
        page.side_effect = [
            {"bars": {"SPY": [row]}, "next_page_token": "more"},
            {"bars": {"SPY": [{**row, "t": "2024-01-02T14:31:00Z"}]}, "next_page_token": None},
        ]
        self.assertEqual(len(list(fetch_rows(date(2024, 1, 2), date(2024, 1, 2), "key", "secret"))), 2)
        uri = page.call_args.args[0].full_url
        self.assertIn("feed=sip", uri)
        self.assertIn("page_token=more", uri)
        self.assertNotIn("secret", uri)

    @patch("src.alpaca.get_page", return_value={"bars": {}, "next_page_token": "loop"})
    def test_rejects_repeated_page_token(self, _page):
        with self.assertRaisesRegex(ValueError, "repeated"):
            list(fetch_rows(date(2024, 1, 2), date(2024, 1, 2), "key", "secret"))


class WorkflowTest(unittest.TestCase):
    def test_cli_with_early_close_and_missing_data(self):
        import exchange_calendars

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.csv"
            output = Path(directory) / "report"
            start, end = date(2024, 11, 4), date(2024, 12, 6)
            calendar = exchange_calendars.get_calendar("XNYS")
            with path.open("w", newline="") as target:
                writer = csv.writer(target)
                writer.writerow(("timestamp", "open", "high", "low", "close", "volume"))
                for day_index, session in enumerate(calendar.sessions_in_range(start, end)):
                    stamp = calendar.session_open(session).to_pydatetime()
                    closing = calendar.session_close(session)
                    while stamp < closing:
                        price = 100 + (0.01 + day_index / 500) * stamp.minute
                        writer.writerow((stamp.isoformat(), price, price, price, price, 10))
                        stamp += timedelta(minutes=1)
            sessions = list(read_sessions(path, start, end))
            self.assertIn(210, [len(session) for session in sessions])
            self.assertIn(390, [len(session) for session in sessions])
            process = subprocess.run(
                [sys.executable, "-m", "src", "backtest", "--input", str(path),
                 "--start", str(start), "--end", str(end), "--test-start", "2024-12-02",
                 "--output", str(output)], capture_output=True, text=True,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertGreater((output / "comparison.png").stat().st_size, 0)
            self.assertGreater((output / "equity.png").stat().st_size, 0)
            with (output / "metrics.csv").open() as source:
                rows = list(csv.DictReader(source))
                self.assertEqual({(row["split"], row["strategy"]) for row in rows},
                                 {(split, name) for split in ("train", "test") for name in STRATEGIES})
            lines = path.read_text().splitlines(keepends=True)
            path.write_text("".join(lines[:1] + lines[2:]))
            with self.assertRaisesRegex(ValueError, "Missing regular-session bar"):
                list(read_sessions(path, start, end))
            audit = []
            sparse = list(read_sessions(path, start, end, gaps=audit))
            self.assertEqual(len(audit), 1)
            self.assertEqual(sparse[0], audit[0])
            self.assertTrue(audit[0].excluded)
            self.assertIsNotNone(audit[0].observed_close)
