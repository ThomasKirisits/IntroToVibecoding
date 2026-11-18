"""Causal, share-based intraday SPY momentum simulations."""

from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from math import expm1, floor, log1p, sqrt
from statistics import mean, stdev

from src.market_data import Bar, MINUTE, SessionGap

LOOKBACK = 14
TRADING_DAYS = 252
SIGNAL_INTERVAL = 30 * MINUTE
INITIAL_EQUITY = 100_000.0
TARGET_DAILY_VOLATILITY = 0.02
MAX_LEVERAGE = 4.0
VOLATILITY_TARGETED = "Volatility-targeted VWAP"
EFFICIENCY_FILTERED = "Efficient breakout"
MIN_DIRECTIONAL_EFFICIENCY = 0.35
BUY_AND_HOLD = "SPY buy & hold"
INTRADAY_STRATEGIES = (
    "Opposite band", "Band + VWAP", VOLATILITY_TARGETED, "Confirmed breakout",
    EFFICIENCY_FILTERED,
)
STRATEGIES = (*INTRADAY_STRATEGIES, BUY_AND_HOLD)


@dataclass(frozen=True)
class Costs:
    commission: float = 0.0035
    slippage: float = 0.01


@dataclass(frozen=True)
class DailyResult:
    date: date
    strategy: str
    split: str
    equity: float
    net_return: float
    traded_shares: int
    cost: float


@dataclass(frozen=True)
class Fill:
    timestamp: datetime
    price: float
    shares: int


def noise_bounds(opening: float, previous_close: float, noise: float) -> tuple[float, float]:
    """Return the upper and lower boundaries around the opening gap."""
    return max(opening, previous_close) * (1 + noise), min(opening, previous_close) * (1 - noise)


def decisions(
    bars: list[Bar], history: dict[int, deque[float]], previous_close: float
) -> dict[int, tuple[float, float, float]]:
    """Map execution bar indices to the bounds and VWAP known at that bar's open."""
    opening = bars[0].open
    volume = weighted_price = 0.0
    result = {}
    for index, (bar, execution) in enumerate(zip(bars, bars[1:]), 1):
        volume += bar.volume
        weighted_price += bar.volume * bar.vwap
        if (execution.timestamp.minute % 30 == 0
                and execution.timestamp - bar.timestamp == MINUTE and volume > 0):
            slot = (execution.timestamp - bars[0].timestamp) // MINUTE
            moves = history.get(slot, ())
            if len(moves) == LOOKBACK:
                noise = mean(moves)
                result[index] = (*noise_bounds(opening, previous_close, noise), weighted_price / volume)
    return result


def simulate_day(
    bars: list[Bar],
    signals: dict[int, tuple[float, float, float]],
    strategy: str,
    equity: float,
    costs: Costs,
    *,
    leverage: float = 1.0,
    fills: list[Fill] | None = None,
) -> tuple[float, int, float]:
    """Return end equity, turnover in shares and total modeled execution costs."""
    shares = floor(equity * leverage / bars[0].open)
    position = turnover = prior_breakout = 0
    prior_decision = None
    cash = equity
    for index, (upper, lower, vwap) in signals.items():
        close = bars[index - 1].close
        breakout = 1 if close > upper else -1 if close < lower else 0
        decision_time = bars[index].timestamp
        entry = breakout
        if strategy == "Confirmed breakout" and (
            breakout != prior_breakout or prior_decision is None
            or decision_time - prior_decision != SIGNAL_INTERVAL
        ):
            entry = 0
        if (strategy == EFFICIENCY_FILTERED and breakout
                and breakout * directional_efficiency(bars, index) < MIN_DIRECTIONAL_EFFICIENCY):
            entry = 0
        prior_breakout, prior_decision = breakout, decision_time

        stop_long, stop_short = lower, upper
        if strategy != "Opposite band":
            stop_long, stop_short = max(upper, vwap), min(lower, vwap)
        target = position
        if position == 0 or position > 0 and close < stop_long or position < 0 and close > stop_short:
            # A stop can go flat or reverse. It cannot reopen the same side immediately.
            target = entry * shares if entry * position <= 0 else 0
        change = target - position
        cash -= change * bars[index].open
        turnover += abs(change)
        if fills is not None and change:
            fills.append(Fill(decision_time, bars[index].open, change))
        position = target
    cash += position * bars[-1].close
    turnover += abs(position)
    if fills is not None and position:
        fills.append(Fill(bars[-1].timestamp + MINUTE, bars[-1].close, -position))
    cost = turnover * (costs.commission + costs.slippage)
    return cash - cost, turnover, cost


def directional_efficiency(bars: list[Bar], index: int) -> float:
    """Measure signed progress divided by price travel over 30 completed minutes."""
    start = index - 30
    if start < 0 or bars[index].timestamp - bars[start].timestamp != SIGNAL_INTERVAL:
        return 0.0
    if start and bars[start].timestamp - bars[start - 1].timestamp != MINUTE:
        return 0.0
    anchor = bars[start - 1].close if start else bars[0].open
    closes = [anchor, *(bar.close for bar in bars[start:index])]
    distance = sum(abs(current - previous) for previous, current in zip(closes, closes[1:]))
    return (closes[-1] - anchor) / distance if distance else 0.0


def volatility_leverage(prior_returns: Iterable[float]) -> float:
    """Use the paper's daily volatility target and leverage cap."""
    realized = stdev(prior_returns)
    return min(MAX_LEVERAGE, TARGET_DAILY_VOLATILITY / realized) if realized else MAX_LEVERAGE


def run_backtest(
    sessions: Iterable[list[Bar] | SessionGap], test_start: date, costs: Costs
) -> list[DailyResult]:
    """Warm up with past sessions and carry causal history and equity across the split."""
    history: dict[int, deque[float]] = defaultdict(lambda: deque(maxlen=LOOKBACK))
    prior_returns: deque[float] = deque(maxlen=LOOKBACK)
    previous_close = None
    equity = dict.fromkeys(STRATEGIES, INITIAL_EQUITY)
    benchmark_shares = None
    benchmark_cash = INITIAL_EQUITY
    results = []
    for bars in sessions:
        if isinstance(bars, SessionGap):
            if previous_close is not None and bars.observed_close is not None:
                prior_returns.append(bars.observed_close / previous_close - 1)
            previous_close = bars.observed_close
            continue
        day = bars[0].timestamp.date()
        closing = bars[-1].close
        if len(prior_returns) == LOOKBACK:
            signals = {} if previous_close is None else decisions(bars, history, previous_close)
            split = "test" if day >= test_start else "train"
            leverage = volatility_leverage(prior_returns)
            for name in INTRADAY_STRATEGIES:
                start_equity = equity[name]
                end_equity, shares, cost = simulate_day(
                    bars, signals, name, start_equity, costs,
                    leverage=leverage if name == VOLATILITY_TARGETED else 1.0,
                )
                if end_equity <= 0:
                    raise ValueError(f"{name} exhausted equity on {day}")
                equity[name] = end_equity
                results.append(DailyResult(day, name, split, end_equity,
                                           end_equity / start_equity - 1, shares, cost))

            traded = 0
            benchmark_cost = 0.0
            if benchmark_shares is None:
                cost_per_share = costs.commission + costs.slippage
                benchmark_shares = floor(benchmark_cash / (bars[0].open + cost_per_share))
                traded = benchmark_shares
                benchmark_cost = traded * cost_per_share
                benchmark_cash -= traded * bars[0].open + benchmark_cost
            end_equity = benchmark_cash + benchmark_shares * closing
            results.append(DailyResult(day, BUY_AND_HOLD, split, end_equity,
                                       end_equity / equity[BUY_AND_HOLD] - 1, traded, benchmark_cost))
            equity[BUY_AND_HOLD] = end_equity
        for bar in bars[:-1]:
            if bar.timestamp.minute in (29, 59):
                slot = (bar.timestamp - bars[0].timestamp) // MINUTE + 1
                history[slot].append(abs(bar.close / bars[0].open - 1))
        if previous_close is not None:
            prior_returns.append(closing / previous_close - 1)
        previous_close = closing
    for split in ("train", "test"):
        if sum(row.split == split for row in results) < 2 * len(STRATEGIES):
            raise ValueError(f"{split} requires at least two sessions after warm-up")
    return results


def metrics(returns: list[float]) -> tuple[float | None, float, float]:
    """Return zero-rate Sharpe, annualized compounded return and annualized sample volatility."""
    daily_vol = stdev(returns)
    sharpe = sqrt(TRADING_DAYS) * mean(returns) / daily_vol if daily_vol else None
    return (
        sharpe,
        expm1(TRADING_DAYS * mean(map(log1p, returns))),
        sqrt(TRADING_DAYS) * daily_vol,
    )
